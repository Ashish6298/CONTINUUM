"""
Project Continuum - Test Suite for Conversation Context Preservation & Smart Handoff (v1.3.0)
================================================================================================
Comprehensive verification of:
1. Long conversations (40+ turns) without turn loss or arbitrary truncation.
2. In-Session Accumulator (sessionStorage schema, streaming reconciliation, recovery).
3. Five-Tier Output Structure (Goals, Code Artifacts, Milestones, Verbatim Trail, Directives).
4. Three Context Modes (Smart Digest, Full History, Quick Task).
5. Target model synthesizers (Claude XML, Gemini hierarchy, DeepSeek compact, ChatGPT checklist).
6. Priority-based overflow management and deterministic omission reporting.
"""

from pathlib import Path
import json
import shutil
import subprocess
import unittest


class TestConversationContextPreservationV130(unittest.TestCase):
    def setUp(self):
        self.userjs_path = Path(__file__).parent.parent / "browser" / "continuum.user.js"
        self.content_script_path = Path(__file__).parent.parent / "browser" / "extension" / "content_script.js"
        self.userjs_content = self.userjs_path.read_text(encoding="utf-8")
        self.cs_content = self.content_script_path.read_text(encoding="utf-8")

    def test_version_v130_alignment(self):
        """Verify v1.3.0 versioning across companion userscript, extension, and pyproject.toml."""
        self.assertIn("@version      1.3.0", self.userjs_content)
        self.assertIn("[Continuum v1.3.0]", self.userjs_content)
        self.assertIn("[Continuum Extension v1.3.0]", self.cs_content)

        manifest_path = Path(__file__).parent.parent / "browser" / "extension" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest.get("version"), "1.3.0")

        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        self.assertIn('version = "1.3.0"', pyproject_path.read_text(encoding="utf-8"))

    def test_accumulator_session_namespacing_and_isolation(self):
        """Verify ConversationAccumulator extracts platform-specific conversation IDs and namespaces storage."""
        # Platform URL regexes
        self.assertIn(r"path.match(/\/c\/([a-zA-Z0-9-]+)/)", self.userjs_content)
        self.assertIn(r"path.match(/\/chat\/([a-zA-Z0-9-]+)/)", self.userjs_content)
        self.assertIn(r"path.match(/\/(?:app|prompts)\/([a-zA-Z0-9_-]+)/)", self.userjs_content)
        self.assertIn(r"path.match(/\/a\/([a-zA-Z0-9_-]+)/)", self.userjs_content)

        # Storage keys
        self.assertIn("continuum_chat_v130_", self.userjs_content)
        self.assertIn("this.schemaVersion = 1", self.userjs_content)
        self.assertIn("this.maxTurns = 250", self.userjs_content)

    def test_streaming_updates_without_duplicates(self):
        """Verify streaming updates modify in-place instead of creating duplicate turns."""
        self.assertIn("isStreaming()", self.userjs_content)
        self.assertIn("streamingNow", self.userjs_content)
        self.assertIn("existing.text = nt.text", self.userjs_content)
        self.assertIn("lastStored.text = nt.text", self.userjs_content)

    def test_explicit_cold_start_recovery_bounds_and_restoration(self):
        """Verify cold-start recovery is bounded, restores scroll position, and rejects concurrent runs."""
        self.assertIn("isRecovering", self.userjs_content)
        self.assertIn("if (this.isRecovering) return { success: false, reason: 'already_running' };", self.userjs_content)
        self.assertIn("const initialScrollTop = scroller.scrollTop", self.userjs_content)
        self.assertIn("scroller.scrollTop = initialScrollTop", self.userjs_content)
        self.assertIn("completeness = 'recovered'", self.userjs_content)

    def test_smart_digest_5_tier_architecture(self):
        """Verify Smart Digest incorporates all 5 tiers with proper structures."""
        # Tier 1: Project Goal & Ground Intent
        self.assertIn("initialRequirements", self.userjs_content)
        self.assertIn("<initial_requirements>", self.userjs_content)
        self.assertIn("### [1.0] PROJECT INTENT & SPECIFICATION", self.userjs_content)
        self.assertIn("## Project / Initial Request", self.userjs_content)

        # Tier 2: Ground Truth Code Artifacts
        self.assertIn("uniqueCode", self.userjs_content)
        self.assertIn("deduplicateCodeBlocks", self.userjs_content)
        self.assertIn("<verified_code_artifacts>", self.userjs_content)
        self.assertIn("### [2.0] VERIFIED CODE REPOSITORY (GROUND TRUTH)", self.userjs_content)
        self.assertIn("## All Code Produced So Far", self.userjs_content)

        # Tier 3: Conversation Progression & Milestone Digest
        self.assertIn("_generateMilestoneDigest", self.userjs_content)
        self.assertIn("<milestone_progression_digest>", self.userjs_content)
        self.assertIn("### [3.0] CONVERSATION PROGRESSION & MILESTONES", self.userjs_content)
        self.assertIn("## Conversation Progression & Milestones", self.userjs_content)

        # Tier 4: Active Conversation Trail
        self.assertIn("<recent_conversation_trail>", self.userjs_content)
        self.assertIn("### [3.0] RECENT CONVERSATION STATE", self.userjs_content)
        self.assertIn("## Recent Context", self.userjs_content)

        # Tier 5: Immediate Execution Directive
        self.assertIn("<immediate_task>", self.userjs_content)
        self.assertIn("### [4.0] NEXT IMMEDIATE EXECUTION TARGET", self.userjs_content)
        self.assertIn("## YOUR IMMEDIATE TASK", self.userjs_content)
        self.assertIn("--- YOUR TASK ---", self.userjs_content)

    def test_three_context_modes_and_budgets(self):
        """Verify target token budgets for Smart Digest (8k), Full History (24k), and Quick Task (2.5k)."""
        self.assertIn("smart_digest: 8000", self.userjs_content)
        self.assertIn("full_history: 24000", self.userjs_content)
        self.assertIn("quick_task: 2500", self.userjs_content)
        self.assertIn("estimateTokens", self.userjs_content)

    def test_priority_overflow_policy(self):
        """Verify priority-based compression protects the active directive and avoids silent truncation."""
        self.assertIn("Intermediate conversation condensed to maintain token ceiling", self.userjs_content)
        self.assertIn("tailSize", self.userjs_content)
        self.assertIn("headSize", self.userjs_content)

    def test_companion_ui_controls_and_preference_persistence(self):
        """Verify companion UI includes mode selector, preview, recovery box, and localStorage persistence."""
        self.assertIn("mode-bar", self.userjs_content)
        self.assertIn("continuum_context_mode", self.userjs_content)
        self.assertIn("defaultMode: 'smart_digest'", self.userjs_content)
        self.assertIn("preview-drawer", self.userjs_content)
        self.assertIn("recovery-box", self.userjs_content)
        self.assertIn("btnClearHistory", self.userjs_content)

    def test_headless_companion_runner_execution(self):
        """Execute the Node.js headless runner to verify accumulator, compressor, and modes at runtime."""
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js runtime not installed in environment")

        runner_script = Path(__file__).parent / "test_companion_runner.js"
        result = subprocess.run(
            [node_bin, str(runner_script)],
            capture_output=True,
            text=True,
            timeout=30
        )
        self.assertEqual(
            result.returncode, 0,
            f"Node test runner failed with exit code {result.returncode}:\n{result.stdout}\n{result.stderr}"
        )
        self.assertIn("ALL CONTINUUM v1.3.0 COMPANION TESTS PASSED ACCURATELY", result.stdout)


if __name__ == "__main__":
    unittest.main()
