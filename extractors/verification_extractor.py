"""
Project Continuum - Test, Build & Verification Evidence Extractor
=================================================================
Milestone 2 - Phase 4: Test, Build & Verification Evidence Collection.
Discovers available test frameworks, explicitly executes configured verification
commands, records exit codes, durations, parsed outcomes, and registers
highest-priority Level 1 canonical Evidence.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.enums import EvidenceType, EvidenceLevel, Status
from core.evidence import Evidence
from core.state_models import (
    CanonicalProjectState,
    ManifestInfo,
    ProjectState,
    TestResult,
)
from extractors.base import BaseEvidenceExtractor
from extractors.verification.runners import (
    ExecutionResult,
    ParsedTestSummary,
    TestOutputParser,
    VerificationRunner,
)


class VerificationEvidenceExtractor(BaseEvidenceExtractor):
    """
    Extractor responsible for Phase 4: Verification, Test, and Build Evidence.
    Adheres strictly to the rule: Never run scripts automatically; only discover
    configurations or run when explicitly requested.
    """

    @property
    def extractor_name(self) -> str:
        return "VerificationEvidenceExtractor"

    @property
    def supported_evidence_types(self) -> List[EvidenceType]:
        return [
            EvidenceType.TEST_RUN,
            EvidenceType.BUILD_LOG,
            EvidenceType.RUNTIME_LOG,
        ]

    def can_extract(self, target_path_or_input: str) -> bool:
        path = Path(target_path_or_input)
        return path.exists()

    def discover_verification_configs(self, root_path: Path, manifests: Optional[List[ManifestInfo]] = None) -> List[Dict[str, Any]]:
        """
        Scans project directory and manifests for available test and build commands
        WITHOUT automatically executing any of them.
        """
        discovered: List[Dict[str, Any]] = []

        # 1. Check Python tools
        if (root_path / "pyproject.toml").exists() or (root_path / "pytest.ini").exists() or (root_path / "tests").exists():
            discovered.append({
                "framework": "pytest",
                "type": "test",
                "recommended_command": "pytest",
                "config_file": "pytest.ini" if (root_path / "pytest.ini").exists() else "pyproject.toml"
            })
            discovered.append({
                "framework": "unittest",
                "type": "test",
                "recommended_command": "py -m unittest discover",
                "config_file": None
            })

        # 2. Check JavaScript / TypeScript (package.json scripts)
        pkg_json = root_path / "package.json"
        if pkg_json.exists():
            try:
                import json
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                scripts = data.get("scripts", {})
                if "test" in scripts:
                    discovered.append({
                        "framework": "npm_test",
                        "type": "test",
                        "recommended_command": "npm test",
                        "script_body": scripts["test"]
                    })
                if "build" in scripts:
                    discovered.append({
                        "framework": "npm_build",
                        "type": "build",
                        "recommended_command": "npm run build",
                        "script_body": scripts["build"]
                    })
            except Exception:
                pass

        # 3. Check Rust
        if (root_path / "Cargo.toml").exists():
            discovered.append({
                "framework": "cargo_test",
                "type": "test",
                "recommended_command": "cargo test",
                "config_file": "Cargo.toml"
            })
            discovered.append({
                "framework": "cargo_build",
                "type": "build",
                "recommended_command": "cargo build",
                "config_file": "Cargo.toml"
            })

        # 4. Check Go
        if (root_path / "go.mod").exists():
            discovered.append({
                "framework": "go_test",
                "type": "test",
                "recommended_command": "go test ./...",
                "config_file": "go.mod"
            })
            discovered.append({
                "framework": "go_build",
                "type": "build",
                "recommended_command": "go build ./...",
                "config_file": "go.mod"
            })

        return discovered

    def run_verification(
        self,
        root_path: Path | str,
        command: str | List[str],
        suite_name: str = "default_suite",
        is_build: bool = False,
        timeout_seconds: int = 60
    ) -> Tuple[ExecutionResult, ParsedTestSummary, Evidence]:
        """
        Explicitly executes a verification command and produces Level 1 canonical Evidence.
        """
        root = Path(root_path).resolve()
        exec_result = VerificationRunner.run_command(command, cwd=root, timeout_seconds=timeout_seconds)

        parsed_summary = TestOutputParser.parse(
            stdout=exec_result.stdout,
            stderr=exec_result.stderr,
            exit_code=exec_result.exit_code,
            duration_ms=exec_result.duration_ms
        )

        status = Status.VERIFIED if exec_result.is_success else Status.FAILED
        evidence_type = EvidenceType.BUILD_LOG if is_build else EvidenceType.TEST_RUN

        summary_text = (
            f"{'Build' if is_build else 'Test'} suite '{suite_name}' {status.value} (exit code {exec_result.exit_code}) "
            f"in {exec_result.duration_ms:.2f}ms. "
            f"Results: {parsed_summary.passed} passed, {parsed_summary.failed} failed, {parsed_summary.errors} errors."
        )

        raw_payload = {
            "suite_name": suite_name,
            "is_build": is_build,
            "command": exec_result.command,
            "status": status.value,
            "exit_code": exec_result.exit_code,
            "duration_ms": exec_result.duration_ms,
            "timed_out": exec_result.timed_out,
            "error": exec_result.error,
            "summary": {
                "framework": parsed_summary.framework,
                "total": parsed_summary.total,
                "passed": parsed_summary.passed,
                "failed": parsed_summary.failed,
                "errors": parsed_summary.errors,
                "skipped": parsed_summary.skipped,
            },
            "failure_details": parsed_summary.failure_details,
            "stdout_snippet": exec_result.stdout[-1500:] if exec_result.stdout else "",
            "stderr_snippet": exec_result.stderr[-1500:] if exec_result.stderr else ""
        }

        evidence = self.create_evidence(
            evidence_type=evidence_type,
            summary=summary_text,
            raw_payload=raw_payload,
            source_uri=str(root),
            locator=f"{'build' if is_build else 'test'}:{suite_name}"
        )

        return exec_result, parsed_summary, evidence

    def extract(self, target_path_or_input: str, context: Optional[Dict[str, Any]] = None) -> List[Evidence]:
        """
        Standard extract method: If context contains 'explicit_commands', executes them.
        Otherwise, extracts discovery metadata only.
        """
        root_path = Path(target_path_or_input).resolve()
        evidence_list: List[Evidence] = []

        if context and "commands" in context:
            for cmd_info in context["commands"]:
                cmd = cmd_info.get("command")
                suite = cmd_info.get("suite", "verification")
                is_build = cmd_info.get("is_build", False)
                if cmd:
                    _, _, ev = self.run_verification(root_path, cmd, suite_name=suite, is_build=is_build)
                    evidence_list.append(ev)
        else:
            # Only record discovery of available configurations
            configs = self.discover_verification_configs(root_path)
            evidence_list.append(self.create_evidence(
                evidence_type=EvidenceType.TEST_RUN,
                summary=f"Discovered {len(configs)} available verification and build configurations (auto-execution disabled)",
                raw_payload={"discovered_configs": configs},
                source_uri=str(root_path),
                locator="verification:discovery"
            ))

        return evidence_list

    def populate_project_state(
        self,
        root_dir: str,
        canonical_state: CanonicalProjectState,
        evidence_list: Optional[List[Evidence]] = None
    ) -> ProjectState:
        """
        Registers verification evidence and updates ProjectState.test_results and build_status.
        """
        root_path = Path(root_dir).resolve()
        ev_list = evidence_list or self.extract(str(root_path))

        test_results: List[TestResult] = []
        build_status = canonical_state.project_state.build_status

        for ev in ev_list:
            canonical_state.add_evidence(ev)

            if ev.type == EvidenceType.TEST_RUN and "exit_code" in ev.raw_payload:
                suite = ev.raw_payload.get("suite_name", "test_suite")
                status = Status(ev.raw_payload.get("status", Status.FAILED.value))
                tr = TestResult(
                    test_id=f"tr_{ev.id}",
                    name=suite,
                    suite=suite,
                    status=status,
                    exit_code=ev.raw_payload.get("exit_code", 1),
                    duration_ms=ev.raw_payload.get("duration_ms", 0.0),
                    output_snippet=ev.raw_payload.get("stdout_snippet", ""),
                    error_message=ev.raw_payload.get("error") or "\n".join(ev.raw_payload.get("failure_details", [])),
                    evidence_id=ev.id
                )
                test_results.append(tr)
            elif ev.type == EvidenceType.BUILD_LOG and "exit_code" in ev.raw_payload:
                build_status = Status(ev.raw_payload.get("status", Status.FAILED.value))

        ps = canonical_state.project_state
        ps.test_results.extend(test_results)
        ps.build_status = build_status
        ps.evidence_ids.extend([ev.id for ev in ev_list])

        return ps
