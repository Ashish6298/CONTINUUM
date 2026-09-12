"""
Tests for Phase 4: Test, Build & Verification Evidence Collection
=================================================================
Validates:
1. Discovery of test/build configurations without unsolicited execution.
2. Explicit test execution (passing runs -> VERIFIED, exit_code 0).
3. Explicit test execution (failing runs -> FAILED, exit_code > 0, error capture).
4. Structured test output parsing for PyTest, Unittest, Jest, Cargo, and Generic runners.
5. Handling of unavailable test tools / non-existent executables.
6. Build log extraction and compiler error capture.
7. Generating Level 1 canonical evidence and populating ProjectState.test_results.
"""

import sys
import tempfile
import unittest
from pathlib import Path

from core.enums import EvidenceType, EvidenceLevel, Status
from core.state_models import CanonicalProjectState
from extractors.verification.runners import TestOutputParser, VerificationRunner
from extractors.verification_extractor import VerificationEvidenceExtractor


class TestVerificationExtractor(unittest.TestCase):

    def test_test_output_parsers(self):
        # 1. PyTest Output
        pytest_out = "======= 14 passed, 2 failed, 1 skipped in 1.25s ======="
        p_res = TestOutputParser.parse(pytest_out, "", 1, 1250.0)
        self.assertEqual(p_res.framework, "pytest")
        self.assertEqual(p_res.passed, 14)
        self.assertEqual(p_res.failed, 2)
        self.assertEqual(p_res.skipped, 1)
        self.assertEqual(p_res.total, 17)

        # 2. Unittest Output
        unittest_out = "Ran 21 tests in 0.025s\n\nOK"
        u_res = TestOutputParser.parse(unittest_out, "", 0, 25.0)
        self.assertEqual(u_res.framework, "unittest")
        self.assertEqual(u_res.total, 21)
        self.assertEqual(u_res.passed, 21)
        self.assertEqual(u_res.failed, 0)

        # 3. Jest Output
        jest_out = "Tests: 1 failed, 8 passed, 9 total\nSnapshots: 0 total\nTime: 2.1s"
        j_res = TestOutputParser.parse(jest_out, "", 1, 2100.0)
        self.assertEqual(j_res.framework, "jest/vitest")
        self.assertEqual(j_res.passed, 8)
        self.assertEqual(j_res.failed, 1)
        self.assertEqual(j_res.total, 9)

        # 4. Cargo test Output
        cargo_out = "test result: ok. 10 passed; 0 failed; 2 ignored; 0 measured; 0 filtered out"
        c_res = TestOutputParser.parse(cargo_out, "", 0, 300.0)
        self.assertEqual(c_res.framework, "cargo-test")
        self.assertEqual(c_res.passed, 10)
        self.assertEqual(c_res.failed, 0)
        self.assertEqual(c_res.skipped, 2)

    def test_discovery_does_not_execute_automatically(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text("[project]\nname='app'", encoding="utf-8")
            (root / "package.json").write_text('{"scripts": {"test": "echo test", "build": "echo build"}}', encoding="utf-8")

            extractor = VerificationEvidenceExtractor()
            configs = extractor.discover_verification_configs(root)

            self.assertTrue(len(configs) >= 2)
            frameworks = [c["framework"] for c in configs]
            self.assertIn("pytest", frameworks)
            self.assertIn("npm_test", frameworks)

            # Extract without explicit commands only returns discovery evidence
            ev_list = extractor.extract(str(root))
            self.assertEqual(len(ev_list), 1)
            self.assertIn("Discovered", ev_list[0].summary)

    def test_passing_and_failing_verification_execution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            extractor = VerificationEvidenceExtractor()

            # 1. Passing command (Python exit 0)
            py_exe = sys.executable
            cmd_pass = f'"{py_exe}" -c "import sys; sys.exit(0)"'
            _, _, ev_pass = extractor.run_verification(root, cmd_pass, suite_name="pass_suite")

            self.assertEqual(ev_pass.level, EvidenceLevel.LEVEL_1_RUNTIME_TEST)
            self.assertEqual(ev_pass.raw_payload["status"], Status.VERIFIED.value)
            self.assertEqual(ev_pass.raw_payload["exit_code"], 0)
            self.assertTrue(ev_pass.verify_integrity())

            # 2. Failing command (Python exit 1 with stderr)
            cmd_fail = f'"{py_exe}" -c "import sys; sys.stderr.write(\'AssertionError: token expired\\n\'); sys.exit(1)"'
            _, _, ev_fail = extractor.run_verification(root, cmd_fail, suite_name="fail_suite")

            self.assertEqual(ev_fail.level, EvidenceLevel.LEVEL_1_RUNTIME_TEST)
            self.assertEqual(ev_fail.raw_payload["status"], Status.FAILED.value)
            self.assertEqual(ev_fail.raw_payload["exit_code"], 1)
            self.assertIn("AssertionError", ev_fail.raw_payload["stderr_snippet"])
            self.assertTrue(ev_fail.verify_integrity())

            # 3. Build command failure
            cmd_build = f'"{py_exe}" -c "import sys; sys.stderr.write(\'SyntaxError: unexpected EOF\\n\'); sys.exit(2)"'
            _, _, ev_build = extractor.run_verification(root, cmd_build, suite_name="build_target", is_build=True)
            self.assertEqual(ev_build.type, EvidenceType.BUILD_LOG)
            self.assertEqual(ev_build.raw_payload["status"], Status.FAILED.value)

            # 4. Populate ProjectState
            state = CanonicalProjectState()
            extractor.populate_project_state(str(root), state, evidence_list=[ev_pass, ev_fail, ev_build])

            self.assertEqual(len(state.project_state.test_results), 2)
            self.assertEqual(state.project_state.test_results[0].status, Status.VERIFIED)
            self.assertEqual(state.project_state.test_results[1].status, Status.FAILED)
            self.assertEqual(state.project_state.build_status, Status.FAILED)

    def test_unavailable_executable_handling(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            extractor = VerificationEvidenceExtractor()

            cmd_missing = "non_existent_test_tool_xyz123 --all"
            res, _, ev = extractor.run_verification(root, cmd_missing, suite_name="missing_tool")

            self.assertEqual(ev.raw_payload["status"], Status.FAILED.value)
            self.assertNotEqual(res.exit_code, 0)
            self.assertTrue(ev.verify_integrity())


if __name__ == "__main__":
    unittest.main()
