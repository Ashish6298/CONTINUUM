"""
Project Continuum — Phase 60 Test Suite
========================================
Milestone 38: Capture and Resume
Phase 60: Deterministic Resume Briefs

Validates:
1. Deterministic repeat: identical Activity + Checkpoint produces byte-identical brief.
2. Sparse data handling: missing completed work, decisions, or blockers emit explicit labels without hallucinating.
3. Provenance and uncertainty labelling: non-user-confirmed checkpoints receive provenance notices in unresolved questions.
4. Comprehensive secret redaction: inline API tokens (sk-*, ghp_*, AKIA*) in context, decisions, or actions are redacted.
5. AI Disabled / Unavailable / Declined path: generator remains completely offline when consent is absent.
6. AI Consent verification: AI provider is invoked only when explicit consent is present and valid.
7. AI Failure fallback: any failure in AI provider safely falls back to local deterministic brief without data loss.
8. Markdown rendering: formats structured brief into clean, human-readable markdown.
"""

from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from core.activity import Activity, ActivityType, ActivityStatus
from core.checkpoint import UniversalCheckpoint, DecisionRecord, ProvenanceRecord
from core.enums import ProvenanceType
from core.resume_generator import (
    DeterministicResumeBriefGenerator,
    AiEnhancementConsent,
)


class TestPhase60DeterministicResumeBriefs(unittest.TestCase):
    """Test suite for Phase 60: Deterministic Resume Briefs."""

    def setUp(self):
        self.generator = DeterministicResumeBriefGenerator()
        self.activity = Activity.create_blank(
            title="Refactor Storage Subsystem",
            activity_type=ActivityType.CODING,
            description="Migrate storage layer to SQLite index and atomic files",
        )
        self.checkpoint = UniversalCheckpoint(
            id="chk_test_brief_001",
            activity_id=self.activity.id,
            context="Completed persistence layer tests and verified schema constraints.",
            completed_work=[
                "Implemented ActivityCheckpointStore in Phase 56",
                "Created storage migration engine in Phase 57",
            ],
            pending_actions=[
                "Implement Phase 61 Resume Center UI",
                "Verify keyboard shortcuts and accessibility",
            ],
            decisions=[
                DecisionRecord(
                    id="dec_001",
                    decision="Use SQLite for secondary queries",
                    rationale="Faster lookups without external database server",
                    constraints=["Loopback only", "Embedded stdlib"],
                )
            ],
            blockers=["Pending upstream API token rotation"],
        )

    def test_deterministic_repeat(self):
        """Verifies that running generation repeatedly produces identical results."""
        brief1 = self.generator.generate_brief(self.activity, self.checkpoint)
        brief2 = self.generator.generate_brief(self.activity, self.checkpoint)

        self.assertEqual(brief1.purpose, brief2.purpose)
        self.assertEqual(brief1.last_completed_work, brief2.last_completed_work)
        self.assertEqual(brief1.key_decisions, brief2.key_decisions)
        self.assertEqual(brief1.blockers, brief2.blockers)
        self.assertEqual(brief1.unresolved_questions, brief2.unresolved_questions)
        self.assertEqual(brief1.next_actions, brief2.next_actions)
        self.assertEqual(brief1.is_ai_enhanced, False)

    def test_sparse_data_handling(self):
        """Verifies that empty/sparse records emit explicit markers and avoid hallucinating facts."""
        sparse_checkpoint = UniversalCheckpoint.create_minimal(
            activity_id=self.activity.id,
            context="",
        )

        brief = self.generator.generate_brief(self.activity, sparse_checkpoint)

        # Purpose falls back to activity description or title
        self.assertEqual(brief.purpose, self.activity.description)

        # Completed work has explicit empty indicator
        self.assertEqual(len(brief.last_completed_work), 1)
        self.assertIn("No specific completed work items logged", brief.last_completed_work[0])

        # Decisions have explicit empty indicator
        self.assertEqual(len(brief.key_decisions), 1)
        self.assertIn("No explicit architectural decisions recorded", brief.key_decisions[0])

        # Blockers has explicit none reported indicator
        self.assertEqual(len(brief.blockers), 1)
        self.assertIn("[None reported]", brief.blockers[0])

        # Next actions points back to activity title
        self.assertEqual(len(brief.next_actions), 1)
        self.assertIn(self.activity.title, brief.next_actions[0])

    def test_provenance_and_uncertainty_labelling(self):
        """Verifies that auto-captured/imported checkpoints receive provenance notices."""
        auto_chk = UniversalCheckpoint(
            id="chk_auto_001",
            activity_id=self.activity.id,
            context="Auto-captured state from browser tab",
            provenance=ProvenanceRecord(
                provenance_type=ProvenanceType.AUTO_CAPTURED,
                captured_by="web_extension",
            ),
        )

        brief = self.generator.generate_brief(self.activity, auto_chk)
        self.assertTrue(any("Provenance notice" in q for q in brief.unresolved_questions))
        self.assertTrue(any("auto_captured" in q for q in brief.unresolved_questions))

    def test_comprehensive_secret_redaction(self):
        """Verifies that secret tokens in context, completed work, and decisions are masked."""
        secret_chk = UniversalCheckpoint(
            id="chk_secret_001",
            activity_id=self.activity.id,
            context="Connecting to API with token sk-1234567890abcdef1234567890abcdef",
            completed_work=["Created GitHub client with token ghp_123456789012345678901234567890123456"],
            decisions=[
                DecisionRecord(
                    id="dec_sec",
                    decision="Store AWS key AKIA1234567890ABCDEF in environment",
                    rationale="Avoid hardcoding secrets",
                )
            ],
            blockers=["Blocked by secret key sk-ant-api03-abcdef1234567890abcdef1234567890abcdef12"],
        )

        brief = self.generator.generate_brief(self.activity, secret_chk)

        # Assert no secrets in output
        self.assertNotIn("sk-1234567890", brief.purpose)
        self.assertIn("<REDACTED_OPENAI_KEY>", brief.purpose)

        self.assertNotIn("ghp_1234567890", brief.last_completed_work[0])
        self.assertIn("<REDACTED_GITHUB_TOKEN>", brief.last_completed_work[0])

        self.assertNotIn("AKIA1234567890", brief.key_decisions[0])
        self.assertIn("<REDACTED_AWS_KEY>", brief.key_decisions[0])

        self.assertNotIn("sk-ant-api03", brief.blockers[0])
        self.assertIn("<REDACTED_ANTHROPIC_KEY>", brief.blockers[0])

    def test_ai_disabled_or_declined_path(self):
        """Verifies that when AI consent is False, AI callback is never executed."""
        mock_ai_callback = MagicMock(return_value={"purpose": "AI generated purpose"})
        generator = DeterministicResumeBriefGenerator(ai_provider_callback=mock_ai_callback)

        consent = AiEnhancementConsent(
            consent_granted=False,
            provider_name="test_ai",
            model_name="model-x",
        )

        brief = generator.generate_brief(self.activity, self.checkpoint, ai_consent=consent)

        self.assertFalse(brief.is_ai_enhanced)
        mock_ai_callback.assert_not_called()

    def test_ai_consent_configured_path(self):
        """Verifies that when explicit consent is granted, AI provider is invoked and brief marked AI-enhanced."""
        mock_ai_callback = MagicMock(
            return_value={
                "purpose": "Enhanced Purpose from LLM",
                "last_completed_work": ["AI summarized task A"],
                "next_actions": ["AI suggested next step B"],
            }
        )
        generator = DeterministicResumeBriefGenerator(ai_provider_callback=mock_ai_callback)

        consent = AiEnhancementConsent(
            consent_granted=True,
            provider_name="anthropic",
            model_name="claude-3-5-sonnet",
        )

        brief = generator.generate_brief(self.activity, self.checkpoint, ai_consent=consent)

        self.assertTrue(brief.is_ai_enhanced)
        self.assertIn("ai_enhanced", brief.generator_id)
        self.assertEqual(brief.purpose, "Enhanced Purpose from LLM")
        mock_ai_callback.assert_called_once()

    def test_ai_failure_safe_fallback(self):
        """Verifies that if AI provider fails or raises an error, local deterministic brief is returned."""
        mock_ai_callback = MagicMock(side_effect=RuntimeError("AI API connection timed out"))
        generator = DeterministicResumeBriefGenerator(ai_provider_callback=mock_ai_callback)

        consent = AiEnhancementConsent(
            consent_granted=True,
            provider_name="anthropic",
            model_name="claude-3-5-sonnet",
        )

        brief = generator.generate_brief(self.activity, self.checkpoint, ai_consent=consent)

        # Must fall back gracefully to deterministic brief
        self.assertFalse(brief.is_ai_enhanced)
        self.assertEqual(brief.generator_id, DeterministicResumeBriefGenerator.GENERATOR_ID)
        self.assertEqual(brief.purpose, self.checkpoint.context)

    def test_format_brief_as_markdown(self):
        """Verifies formatting brief into markdown document."""
        brief = self.generator.generate_brief(self.activity, self.checkpoint)
        md = DeterministicResumeBriefGenerator.format_brief_as_markdown(brief, activity_title=self.activity.title)

        self.assertIn("CONTINUITY RESUME BRIEF", md)
        self.assertIn(self.activity.title, md)
        self.assertIn("Purpose & Working Goal", md)
        self.assertIn("Last Completed Work", md)
        self.assertIn("Key Decisions & Constraints", md)
        self.assertIn("Next Concrete Actions", md)


if __name__ == "__main__":
    unittest.main()
