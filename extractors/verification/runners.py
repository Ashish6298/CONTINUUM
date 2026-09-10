"""
Project Continuum - Test & Build Verification Runners & Parsers
===============================================================
Provides safe command execution with timeouts and output capture,
along with structured test output parsers for PyTest, Unittest,
Vitest, Jest, Cargo test, Go test, and generic test runners.
"""

from dataclasses import dataclass, field
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from core.enums import Status
from core.state_models import TestResult


@dataclass
class ExecutionResult:
    """Raw result of an executed verification command."""
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False
    error: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class ParsedTestSummary:
    """Structured test outcome summary parsed from stdout/stderr."""
    framework: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_ms: float = 0.0
    individual_tests: List[TestResult] = field(default_factory=list)
    failure_details: List[str] = field(default_factory=list)


class VerificationRunner:
    """
    Safely executes verification and build commands with process timeouts,
    stream capture, and exact duration measurement.
    """

    @staticmethod
    def run_command(
        command: str | List[str],
        cwd: Path | str,
        timeout_seconds: int = 60,
        env: Optional[Dict[str, str]] = None
    ) -> ExecutionResult:
        cmd_str = command if isinstance(command, str) else " ".join(command)
        start_time = time.time()

        try:
            res = subprocess.run(
                command,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=isinstance(command, str),
                timeout=timeout_seconds,
                env=env,
                encoding="utf-8",
                errors="replace"
            )
            duration_ms = (time.time() - start_time) * 1000.0
            return ExecutionResult(
                command=cmd_str,
                exit_code=res.returncode,
                stdout=res.stdout,
                stderr=res.stderr,
                duration_ms=duration_ms,
                timed_out=False
            )
        except subprocess.TimeoutExpired as e:
            duration_ms = (time.time() - start_time) * 1000.0
            stdout_text = e.stdout if isinstance(e.stdout, str) else (e.stdout.decode("utf-8", "replace") if e.stdout else "")
            stderr_text = e.stderr if isinstance(e.stderr, str) else (e.stderr.decode("utf-8", "replace") if e.stderr else "")
            return ExecutionResult(
                command=cmd_str,
                exit_code=124,
                stdout=stdout_text,
                stderr=stderr_text,
                duration_ms=duration_ms,
                timed_out=True,
                error=f"Command timed out after {timeout_seconds} seconds"
            )
        except FileNotFoundError as e:
            duration_ms = (time.time() - start_time) * 1000.0
            return ExecutionResult(
                command=cmd_str,
                exit_code=127,
                stdout="",
                stderr=str(e),
                duration_ms=duration_ms,
                timed_out=False,
                error=f"Executable not found: {e}"
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000.0
            return ExecutionResult(
                command=cmd_str,
                exit_code=1,
                stdout="",
                stderr=str(e),
                duration_ms=duration_ms,
                timed_out=False,
                error=str(e)
            )


class TestOutputParser:
    """
    Parses CLI output streams from various test frameworks into structured metrics.
    """

    # PyTest pattern: "=== 5 passed, 2 failed, 1 skipped in 0.42s ==="
    PYTEST_SUMMARY_PATTERN = re.compile(
        r"(=+)\s*(?:(?P<passed>\d+)\s+passed)?(?:,\s*)?(?:(?P<failed>\d+)\s+failed)?(?:,\s*)?(?:(?P<errors>\d+)\s+errors?)?(?:,\s*)?(?:(?P<skipped>\d+)\s+skipped)?.*in\s+(?P<duration>[\d\.]+)\s*s\s*(=+)",
        re.IGNORECASE
    )

    # Unittest pattern: "Ran 27 tests in 0.048s\n\nOK" or "FAILED (failures=1, errors=2)"
    UNITTEST_RAN_PATTERN = re.compile(
        r"Ran\s+(?P<total>\d+)\s+tests?\s+in\s+(?P<duration>[\d\.]+)s",
        re.IGNORECASE
    )
    UNITTEST_FAILED_PATTERN = re.compile(
        r"FAILED\s*\((?:failures=(?P<failures>\d+))?(?:,\s*)?(?:errors=(?P<errors>\d+))?\)",
        re.IGNORECASE
    )

    # Vitest / Jest pattern: "Tests: 3 failed, 12 passed, 15 total"
    JEST_PATTERN = re.compile(
        r"Tests:\s*(?:(?P<failed>\d+)\s+failed,\s*)?(?:(?P<passed>\d+)\s+passed,\s*)?(?:(?P<skipped>\d+)\s+skipped,\s*)?(?P<total>\d+)\s+total",
        re.IGNORECASE
    )

    # Cargo test pattern: "test result: ok. 12 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out"
    CARGO_PATTERN = re.compile(
        r"test result:\s*(?P<status>\w+)\.\s*(?P<passed>\d+)\s+passed;\s*(?P<failed>\d+)\s+failed;\s*(?P<ignored>\d+)\s+ignored",
        re.IGNORECASE
    )

    # Go test pattern: "PASS: TestAuth (0.02s)" or "--- FAIL: TestLogin (0.01s)" or "FAIL\tpkg/auth\t0.035s"
    GO_SUMMARY_PATTERN = re.compile(
        r"(?P<status>PASS|FAIL)\s+(?P<pkg>[\w\.\/\-_]+)\s+(?P<duration>[\d\.]+)s",
        re.IGNORECASE
    )

    @classmethod
    def parse(cls, stdout: str, stderr: str, exit_code: int, duration_ms: float) -> ParsedTestSummary:
        combined = f"{stdout}\n{stderr}"

        # 1. Try PyTest
        pytest_match = cls.PYTEST_SUMMARY_PATTERN.search(combined)
        if pytest_match:
            passed = int(pytest_match.group("passed") or 0)
            failed = int(pytest_match.group("failed") or 0)
            errors = int(pytest_match.group("errors") or 0)
            skipped = int(pytest_match.group("skipped") or 0)
            total = passed + failed + errors + skipped
            dur = float(pytest_match.group("duration") or 0.0) * 1000.0
            return ParsedTestSummary(
                framework="pytest",
                total=total,
                passed=passed,
                failed=failed,
                errors=errors,
                skipped=skipped,
                duration_ms=dur or duration_ms,
                failure_details=cls._extract_error_snippets(combined) if failed or errors else []
            )

        # 2. Try Unittest
        unittest_match = cls.UNITTEST_RAN_PATTERN.search(combined)
        if unittest_match:
            total = int(unittest_match.group("total") or 0)
            dur = float(unittest_match.group("duration") or 0.0) * 1000.0
            failed = 0
            errors = 0
            fail_match = cls.UNITTEST_FAILED_PATTERN.search(combined)
            if fail_match:
                failed = int(fail_match.group("failures") or 0)
                errors = int(fail_match.group("errors") or 0)
            passed = total - failed - errors
            return ParsedTestSummary(
                framework="unittest",
                total=total,
                passed=max(0, passed),
                failed=failed,
                errors=errors,
                skipped=0,
                duration_ms=dur or duration_ms,
                failure_details=cls._extract_error_snippets(combined) if failed or errors else []
            )

        # 3. Try Jest / Vitest
        jest_match = cls.JEST_PATTERN.search(combined)
        if jest_match:
            total = int(jest_match.group("total") or 0)
            passed = int(jest_match.group("passed") or 0)
            failed = int(jest_match.group("failed") or 0)
            skipped = int(jest_match.group("skipped") or 0)
            return ParsedTestSummary(
                framework="jest/vitest",
                total=total,
                passed=passed,
                failed=failed,
                errors=0,
                skipped=skipped,
                duration_ms=duration_ms,
                failure_details=cls._extract_error_snippets(combined) if failed else []
            )

        # 4. Try Cargo test
        cargo_match = cls.CARGO_PATTERN.search(combined)
        if cargo_match:
            passed = int(cargo_match.group("passed") or 0)
            failed = int(cargo_match.group("failed") or 0)
            ignored = int(cargo_match.group("ignored") or 0)
            total = passed + failed + ignored
            return ParsedTestSummary(
                framework="cargo-test",
                total=total,
                passed=passed,
                failed=failed,
                errors=0,
                skipped=ignored,
                duration_ms=duration_ms,
                failure_details=cls._extract_error_snippets(combined) if failed else []
            )

        # 5. Fallback Generic Parser based on exit code
        status = Status.VERIFIED if exit_code == 0 else Status.FAILED
        failed_count = 0 if exit_code == 0 else 1
        passed_count = 1 if exit_code == 0 else 0
        return ParsedTestSummary(
            framework="generic_cli",
            total=1,
            passed=passed_count,
            failed=failed_count,
            errors=0,
            skipped=0,
            duration_ms=duration_ms,
            failure_details=cls._extract_error_snippets(combined) if exit_code != 0 else []
        )

    @staticmethod
    def _extract_error_snippets(output: str, max_lines: int = 15) -> List[str]:
        """Extracts the most relevant error lines from a failing run."""
        lines = output.splitlines()
        error_lines: List[str] = []
        capture = False

        for line in lines:
            lower = line.lower()
            if any(k in lower for k in ["fail", "error", "traceback", "assertionerror", "exception"]):
                capture = True
            if capture and line.strip():
                error_lines.append(line.strip())
                if len(error_lines) >= max_lines:
                    break

        return error_lines or [lines[-1].strip()] if lines else ["Unknown execution failure"]
