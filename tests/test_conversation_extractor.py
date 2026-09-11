"""
Tests for Phase 5: Conversation & Agent State Ingestion
======================================================
Validates:
1. Ingestion of structured JSON conversation transcripts.
2. Ingestion of plain-text / markdown conversation exports.
3. Extraction of user requirements, architectural decisions, and assumptions.
4. Extraction of unverified agent completion claims.
5. Extraction of unresolved questions & open dilemmas.
6. Extraction of active tactical tasks, file references, and next action recommendations.
7. Verification that conversational claims NEVER mutate physical ProjectState.
8. Generating Level 5 canonical evidence records with proper provenance.
"""

import json
from pathlib import Path
import tempfile
import unittest

from core.enums import EvidenceType, EvidenceLevel, Status
from core.state_models import CanonicalProjectState
from extractors.conversation.models import ConversationTranscript, TurnRole
from extractors.conversation.analyzers import TranscriptAnalyzer
from extractors.conversation_extractor import ConversationEvidenceExtractor


class TestConversationExtractor(unittest.TestCase):

    def test_transcript_parsing_from_plain_text(self):
        text = """
        User: We need to implement JWT token authentication for the REST API.
        Assistant: I decided to use the PyJWT library with RS256 algorithm.
        User: What about token revocation?
        Assistant: Should we store blacklisted tokens in Redis or Postgres? I have implemented the base JwtService in src/auth/jwt.py.
        """
        transcript = ConversationTranscript.from_plain_text(text)
        self.assertEqual(len(transcript.turns), 4)
        self.assertEqual(transcript.turns[0].role, TurnRole.USER)
        self.assertEqual(transcript.turns[1].role, TurnRole.ASSISTANT)

    def test_transcript_analyzer_extractions(self):
        transcript = ConversationTranscript(session_id="sess_jwt_001", model_name="claude-3-7-sonnet")
        transcript.add_turn(
            role=TurnRole.USER,
            content="Please implement rate limiting for auth endpoints in src/api/auth.py."
        )
        transcript.add_turn(
            role=TurnRole.ASSISTANT,
            content=(
                "Architectural decision: We will use Redis sliding window for rate limiting.\n"
                "I have implemented the RateLimiter class in src/api/auth.py and tests are passing.\n"
                "Should we enforce 100 requests per minute by default?\n"
                "Next action: Wire RateLimiter into FastAPI middleware."
            )
        )

        analysis = TranscriptAnalyzer.analyze(transcript)

        # 1. Requirements
        self.assertEqual(len(analysis.requirements), 1)
        self.assertIn("rate limiting", analysis.requirements[0].title.lower())

        # 2. Agent Claims
        self.assertTrue(len(analysis.agent_claims) >= 1)
        claim_texts = [c.claim_text for c in analysis.agent_claims]
        self.assertTrue(any("implemented" in c.lower() for c in claim_texts))

        # 3. Decisions
        self.assertEqual(len(analysis.decisions), 1)
        self.assertIn("Redis sliding window", analysis.decisions[0].title)

        # 4. Unresolved Questions
        self.assertEqual(len(analysis.unresolved_questions), 1)
        self.assertIn("requests per minute", analysis.unresolved_questions[0].question)

        # 5. Referenced Files
        self.assertIn("src/api/auth.py", analysis.referenced_files)

        # 6. Next action
        self.assertIsNotNone(analysis.next_action)
        self.assertIn("middleware", analysis.next_action.description.lower())

    def test_strict_isolation_claims_do_not_mutate_project_state(self):
        """
        Crucial verification: When an assistant claims 'I have finished all database migrations',
        it must ONLY populate ConversationalState and NEVER add fake files or test results into ProjectState.
        """
        json_transcript = json.dumps([
            {"role": "user", "content": "Complete user migration"},
            {"role": "assistant", "content": "I have implemented UserService and all database migrations are complete and verified in src/db/models.py."}
        ])

        extractor = ConversationEvidenceExtractor()
        canonical_state = CanonicalProjectState(project_id="test_isolation_proj")

        # Ingest transcript
        cs, aes = extractor.ingest_transcript(json_transcript, canonical_state)

        # Check conversational state has claim
        self.assertEqual(len(cs.agent_claims), 1)
        self.assertEqual(cs.agent_claims[0].claimed_status, Status.VERIFIED)

        # CHECK PROJECT STATE: Must remain completely empty and unmutated!
        self.assertEqual(len(canonical_state.project_state.files), 0)
        self.assertEqual(len(canonical_state.project_state.symbols), 0)
        self.assertEqual(len(canonical_state.project_state.test_results), 0)
        self.assertEqual(canonical_state.project_state.build_status, Status.UNKNOWN)

        # Check evidence records
        for ev in canonical_state.evidence_pool.values():
            self.assertTrue(ev.verify_integrity())
            self.assertEqual(ev.level, EvidenceLevel.LEVEL_5_CONVERSATION)

    def test_file_based_transcript_ingestion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript_file = Path(tmpdir) / "chat_export.json"
            transcript_file.write_text(json.dumps({
                "session_id": "session_file_test",
                "platform": "cursor",
                "model_name": "gpt-4o",
                "turns": [
                    {"turn_index": 1, "role": "user", "content": "Requirement: Add GraphQL schema"},
                    {"turn_index": 2, "role": "assistant", "content": "I have created the schema in schema.graphql. Working on resolvers."}
                ]
            }), encoding="utf-8")

            extractor = ConversationEvidenceExtractor()
            canonical_state = CanonicalProjectState()

            cs, aes = extractor.ingest_transcript(transcript_file, canonical_state)

            self.assertEqual(cs.session_id, "session_file_test")
            self.assertEqual(len(cs.user_requirements), 1)
            self.assertEqual(len(cs.agent_claims), 1)
            self.assertEqual(aes.agent_id, "gpt-4o")


if __name__ == "__main__":
    unittest.main()
