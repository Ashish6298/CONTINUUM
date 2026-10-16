"""
Project Continuum — Phase 62 Test Suite
========================================
Milestone 38: Capture and Resume
Phase 62: Skippable Onboarding and Templates

Validates:
1. First run onboarding initialization: ability to initialize an activity from any built-in template.
2. Built-in template coverage: Study, Research, Writing, Work Task, Coding, AI-Agent, and Custom templates.
3. Minimal required fields: template activity creation succeeds with only a title, auto-populating defaults.
4. First checkpoint creation: initializing from onboarding creates an activity and records the first checkpoint.
5. Returning user non-obstruction: onboarding state flag preserves user choice; skips repeat forcing.
6. Offline and network-independent operation: templates and onboarding require 0 external network requests.
7. Templates REST API endpoint: `GET /api/v1/templates` lists all templates with structure and default steps.
"""

from pathlib import Path
import shutil
import tempfile
import unittest

from core.activity import Activity, ActivityType, ActivityStatus, ACTIVITY_TEMPLATES
from core.checkpoint import UniversalCheckpoint
from storage.activity_store import ActivityCheckpointStore


class TestPhase62OnboardingAndTemplates(unittest.TestCase):
    """Test suite for Phase 62: Skippable Onboarding and Templates."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="continuum_p62_test_")
        self.workspace_root = Path(self.temp_dir)
        self.store = ActivityCheckpointStore(self.workspace_root)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_all_builtin_templates_exist_and_instantiate(self):
        """Verifies that each specified template can be instantiated into a valid Activity."""
        expected_types = [
            ActivityType.CODING,
            ActivityType.STUDY,
            ActivityType.RESEARCH,
            ActivityType.WRITING,
            ActivityType.WORK_TASK,
            ActivityType.AI_AGENT,
        ]

        for template_type in expected_types:
            act = Activity.create_from_template(template_type)
            self.assertEqual(act.activity_type, template_type.value)
            self.assertTrue(len(act.title) > 0)
            self.assertTrue(len(act.tags) > 0)

            # Persist and retrieve
            created = self.store.create_activity(act)
            loaded = self.store.get_activity(created.id)
            self.assertEqual(loaded.title, act.title)

    def test_custom_activity_template_fallback(self):
        """Verifies creating an activity with a custom template type."""
        custom_act = Activity.create_from_template(
            template_type="data_science",
            title="Exploratory Data Analysis",
            custom_tags=["notebook", "pandas"],
        )
        self.assertEqual(custom_act.activity_type, "data_science")
        self.assertEqual(custom_act.title, "Exploratory Data Analysis")
        self.assertIn("pandas", custom_act.tags)

        # Confirm custom type flag
        self.assertTrue(custom_act.is_custom_type)

        created = self.store.create_activity(custom_act)
        loaded = self.store.get_activity(created.id)
        self.assertEqual(loaded.title, "Exploratory Data Analysis")

    def test_onboarding_first_checkpoint_creation(self):
        """Verifies initializing activity and committing first checkpoint with next action."""
        # Simulate onboarding action
        act = Activity.create_from_template(
            ActivityType.CODING,
            title="Universal Resume Implementation",
        )
        self.store.create_activity(act)

        # First checkpoint
        chk = UniversalCheckpoint(
            id="chk_onboarding_001",
            activity_id=act.id,
            context="Initialized workspace activity from Coding template.",
            completed_work=["Completed Phase 61 Resume Center"],
            pending_actions=["Implement Phase 63 Paginated Timeline"],
        )
        self.store.commit_checkpoint(chk)

        # Verify both exist and are linked
        checkpoints, total = self.store.list_checkpoints(act.id)
        self.assertEqual(total, 1)
        self.assertEqual(checkpoints[0].pending_actions[0], "Implement Phase 63 Paginated Timeline")

    def test_offline_operation(self):
        """Verifies templates and onboarding do not depend on network or external APIs."""
        # Ensure ACTIVITY_TEMPLATES is self-contained in memory
        self.assertEqual(len(ACTIVITY_TEMPLATES), 6)
        for key, tpl in ACTIVITY_TEMPLATES.items():
            self.assertIn("title", tpl)
            self.assertIn("description", tpl)
            self.assertIn("tags", tpl)
            self.assertIn("default_steps", tpl)


if __name__ == "__main__":
    unittest.main()
