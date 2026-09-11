"""
Project Continuum - Contradiction Detection Engine
==================================================
Milestone 3 - Phase 7: Automated Discrepancy Identification.
Detects mismatches between:
1. Conversational claims vs Missing physical AST/file implementations (HIGH).
2. Conversational claims vs Failing automated test results (HIGH).
3. Documentation references vs Missing code symbols/types (MEDIUM).
4. Manifest dependencies vs Missing lockfiles/imports (MEDIUM).
5. Conversational claims of clean state vs Dirty Git working trees (LOW/MEDIUM).
"""

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional, Set
import uuid

from core.enums import EvidenceLevel, EvidenceType, Status
from core.evidence import Evidence
from core.interfaces import IContradictionDetector
from core.state_models import (
    AgentClaim,
    AstSymbol,
    CanonicalProjectState,
    ContradictionRecord,
    ConversationalState,
    GitState,
    ProjectState,
    TestResult,
)
from contradictions.models import ContradictionSeverity, ContradictionType, DiscrepancyLedger


class ContradictionDetector(IContradictionDetector):
    """
    Identifies and records discrepancies across ProjectState, ConversationalState,
    and the global Evidence pool.
    """

    COMPLETION_PATTERNS = [
        re.compile(r"\b(completed?|implemented?|finished?|done|created|built|ready)\b", re.IGNORECASE),
        re.compile(r"\b(working|passes?|passed|passing|verified)\b", re.IGNORECASE),
        re.compile(r"\b(all tests (pass|passed|are passing))\b", re.IGNORECASE),
        re.compile(r"\b(100%|completely|fully implemented)\b", re.IGNORECASE),
    ]

    DOC_SYMBOL_PATTERN = re.compile(r"`([A-Za-z_][A-Za-z0-9_]{2,})`|\bclass\s+([A-Za-z_][A-Za-z0-9_]+)\b|\bdef\s+([A-Za-z_][A-Za-z0-9_]+)\b")

    def detect_contradictions(
        self,
        project_state: ProjectState,
        conversational_state: ConversationalState,
        evidence_pool: Dict[str, Evidence]
    ) -> List[ContradictionRecord]:
        """
        Analyzes all state dimensions and returns structured ContradictionRecord items.
        Implements IContradictionDetector Protocol.
        """
        contradictions: List[ContradictionRecord] = []

        # 1. Detect claims of completion vs missing implementation (AST / Files)
        claim_impl_contradictions = self._detect_claims_vs_missing_implementation(
            conversational_state.agent_claims,
            project_state.symbols,
            project_state.files,
            evidence_pool
        )
        contradictions.extend(claim_impl_contradictions)

        # 2. Detect claims of passing tests vs failing test results
        claim_test_contradictions = self._detect_claims_vs_failing_tests(
            conversational_state.agent_claims,
            project_state.test_results,
            evidence_pool
        )
        contradictions.extend(claim_test_contradictions)

        # 3. Detect documentation referencing non-existent code symbols
        doc_symbol_contradictions = self._detect_documentation_vs_missing_symbols(
            evidence_pool,
            project_state.symbols
        )
        contradictions.extend(doc_symbol_contradictions)

        # 4. Detect claims of clean repository vs dirty Git state
        git_contradictions = self._detect_stale_git_state(
            conversational_state.agent_claims,
            project_state.git_state,
            evidence_pool
        )
        contradictions.extend(git_contradictions)

        # 5. Detect misleading commit messages claiming non-existent implementations
        commit_contradictions = self._detect_misleading_commits(
            project_state.git_state,
            project_state.symbols,
            project_state.files
        )
        contradictions.extend(commit_contradictions)

        return contradictions

    def _detect_claims_vs_missing_implementation(
        self,
        claims: List[AgentClaim],
        symbols: List[AstSymbol],
        files: List[str],
        evidence_pool: Dict[str, Evidence]
    ) -> List[ContradictionRecord]:
        """
        Detects claims asserting a component, service, or function is complete/implemented
        when no matching AST symbol or file exists in the physical workspace.
        """
        records: List[ContradictionRecord] = []
        symbol_names = {s.name.lower() for s in symbols}
        file_names = {f.replace("\\", "/").lower() for f in files}

        # If claim is specifically about test pass/fail, avoid duplicate missing-impl contradiction
        test_assertion_pattern = re.compile(r"\b(tests? (pass|passed|passing)|all tests pass)\b", re.IGNORECASE)

        for claim in claims:
            target = claim.target_component or ""
            claim_text = claim.claim_text.strip()

            # If claim is strictly a test execution claim, let _detect_claims_vs_failing_tests handle it
            if test_assertion_pattern.search(claim_text) and not any(k in claim_text.lower() for k in ["implemented", "complete", "finished", "created", "built"]):
                continue

            is_completion_claim = (
                claim.claimed_status == Status.VERIFIED
                or any(p.search(claim_text) for p in self.COMPLETION_PATTERNS)
            )

            if not is_completion_claim:
                continue

            # Extract possible component identifiers from claim_text or target_component
            candidates = self._extract_identifier_candidates(target, claim_text)
            if not candidates:
                continue

            # Check if any candidate exists in AST symbols or file paths
            has_match = False
            for cand in candidates:
                cand_lower = cand.lower()
                if cand_lower in symbol_names or any(cand_lower in s for s in symbol_names):
                    has_match = True
                    break
                if any(cand_lower in f for f in file_names):
                    has_match = True
                    break

            if not has_match:
                record = ContradictionRecord(
                    id=f"contra_{uuid.uuid4().hex[:8]}",
                    severity=ContradictionSeverity.HIGH.value,
                    claim_id=claim.id,
                    claim_text=claim_text,
                    physical_evidence_id=None,
                    explanation=(
                        f"Agent claimed '{claim_text}' (target: '{target or candidates[0]}'), "
                        f"but no matching AST symbols ({', '.join(candidates[:3])}) or source files "
                        f"exist in the workspace."
                    ),
                    detected_at=datetime.now(timezone.utc).isoformat(),
                    resolved=False
                )
                records.append(record)

        return records

    def _detect_claims_vs_failing_tests(
        self,
        claims: List[AgentClaim],
        test_results: List[TestResult],
        evidence_pool: Dict[str, Evidence]
    ) -> List[ContradictionRecord]:
        """
        Detects claims asserting tests pass or features are verified when actual
        recorded test executions failed (exit code != 0).
        """
        records: List[ContradictionRecord] = []
        failing_tests = [t for t in test_results if t.status == Status.FAILED or t.exit_code != 0]

        # Also check evidence pool for Level 1 test runs
        failing_test_ev = [
            ev for ev in evidence_pool.values()
            if ev.type == EvidenceType.TEST_RUN and ev.raw_payload.get("exit_code", 0) != 0
        ]

        if not failing_tests and not failing_test_ev:
            return records

        test_pass_regex = re.compile(r"\b(tests? (pass|passed|passing|green|succeeded)|all tests|100% pass|verified)\b", re.IGNORECASE)

        for claim in claims:
            claim_text = claim.claim_text
            target = (claim.target_component or "").lower()

            claims_passing = (
                bool(test_pass_regex.search(claim_text))
                or claim.claimed_status == Status.VERIFIED
            )

            if not claims_passing:
                continue

            # Identify matching failing test
            matching_failing_test = None
            for ft in failing_tests:
                if not target or target in ft.name.lower() or target in ft.suite.lower() or "test" in claim_text.lower():
                    matching_failing_test = ft
                    break

            matching_ev = None
            for ev in failing_test_ev:
                if not target or target in ev.summary.lower() or target in str(ev.raw_payload).lower() or "test" in claim_text.lower():
                    matching_ev = ev
                    break

            if matching_failing_test or matching_ev:
                ev_id = matching_failing_test.evidence_id if matching_failing_test else (matching_ev.id if matching_ev else None)
                fail_detail = (
                    f"test '{matching_failing_test.name}' failed with exit code {matching_failing_test.exit_code}"
                    if matching_failing_test
                    else f"test suite '{matching_ev.summary}' failed (exit code {matching_ev.raw_payload.get('exit_code')})"
                )

                record = ContradictionRecord(
                    id=f"contra_{uuid.uuid4().hex[:8]}",
                    severity=ContradictionSeverity.HIGH.value,
                    claim_id=claim.id,
                    claim_text=claim_text,
                    physical_evidence_id=ev_id,
                    explanation=(
                        f"Agent claimed '{claim_text}', but physical verification recorded a failure: {fail_detail}."
                    ),
                    detected_at=datetime.now(timezone.utc).isoformat(),
                    resolved=False
                )
                records.append(record)

        return records

    def _detect_documentation_vs_missing_symbols(
        self,
        evidence_pool: Dict[str, Evidence],
        symbols: List[AstSymbol]
    ) -> List[ContradictionRecord]:
        """
        Detects documentation evidence (markdown, comments) referencing classes or functions
        that do not exist anywhere in the extracted AST symbol table.
        """
        records: List[ContradictionRecord] = []
        symbol_names = {s.name for s in symbols}
        doc_evidences = [
            ev for ev in evidence_pool.values()
            if ev.level == EvidenceLevel.LEVEL_4_DOCUMENTATION or ev.type == EvidenceType.DOCUMENTATION
        ]

        # Standard built-in names to ignore
        BUILTIN_IGNORE = {
            "str", "int", "float", "bool", "dict", "list", "set", "tuple", "None", "Optional",
            "Any", "List", "Dict", "Set", "Tuple", "Union", "Protocol", "Enum", "True", "False",
            "self", "cls", "return", "import", "from", "class", "def", "async", "await",
            "JSON", "HTTP", "REST", "API", "URL", "UUID", "SHA", "README", "TODO", "FIXME",
            "GET", "POST", "PUT", "DELETE", "UTF-8", "ASCII", "Linux", "Windows", "MacOS"
        }

        for ev in doc_evidences:
            content = str(ev.raw_payload.get("content", "")) or ev.summary
            referenced_identifiers: Set[str] = set()

            for match in self.DOC_SYMBOL_PATTERN.finditer(content):
                for group in match.groups():
                    if group and len(group) > 3 and group not in BUILTIN_IGNORE:
                        referenced_identifiers.add(group)

            missing_symbols = [
                ident for ident in referenced_identifiers
                if ident not in symbol_names and not any(ident.lower() == s.lower() for s in symbol_names)
            ]

            # Filter out likely non-code nouns (keep CamelCase and snake_case with underscores)
            suspicious_missing = [
                m for m in missing_symbols
                if ("_" in m or (m[0].isupper() and any(c.islower() for c in m[1:])))
            ]

            if suspicious_missing:
                record = ContradictionRecord(
                    id=f"contra_{uuid.uuid4().hex[:8]}",
                    severity=ContradictionSeverity.MEDIUM.value,
                    claim_id=None,
                    claim_text=f"Documentation in '{ev.summary}'",
                    physical_evidence_id=ev.id,
                    explanation=(
                        f"Documentation ({ev.summary}) references code symbol(s) '{', '.join(suspicious_missing[:3])}' "
                        f"which are absent from physical AST symbols."
                    ),
                    detected_at=datetime.now(timezone.utc).isoformat(),
                    resolved=False
                )
                records.append(record)

        return records

    def _detect_stale_git_state(
        self,
        claims: List[AgentClaim],
        git_state: GitState,
        evidence_pool: Dict[str, Evidence]
    ) -> List[ContradictionRecord]:
        """
        Detects claims asserting the workspace is committed, clean, or ready for release
        when Git state is dirty or has untracked / uncommitted changes.
        """
        records: List[ContradictionRecord] = []
        if not git_state.is_repo or not git_state.is_dirty:
            return records

        clean_claim_regex = re.compile(r"\b(committed|all changes committed|clean working tree|ready to ship|pushed)\b", re.IGNORECASE)

        for claim in claims:
            if clean_claim_regex.search(claim.claim_text):
                dirty_summary = f"{len(git_state.staged_files)} staged, {len(git_state.unstaged_files)} unstaged, {len(git_state.untracked_files)} untracked files"
                record = ContradictionRecord(
                    id=f"contra_{uuid.uuid4().hex[:8]}",
                    severity=ContradictionSeverity.MEDIUM.value,
                    claim_id=claim.id,
                    claim_text=claim.claim_text,
                    physical_evidence_id=git_state.evidence_ids[0] if git_state.evidence_ids else None,
                    explanation=(
                        f"Agent claimed '{claim.claim_text}', but physical Git repository is DIRTY ({dirty_summary})."
                    ),
                    detected_at=datetime.now(timezone.utc).isoformat(),
                    resolved=False
                )
                records.append(record)

        return records

    def _detect_misleading_commits(
        self,
        git_state: GitState,
        symbols: List[AstSymbol],
        files: List[str]
    ) -> List[ContradictionRecord]:
        """
        Detects commits with messages claiming to have added/implemented components
        that do not actually exist in the physical AST or file system.
        """
        records: List[ContradictionRecord] = []
        if not git_state.is_repo or not git_state.recent_commits:
            return records

        symbol_names = {s.name.lower() for s in symbols}
        file_names = {f.replace("\\", "/").lower() for f in files}

        for commit in git_state.recent_commits:
            msg = commit.get("message", "") or commit.get("summary", "")
            if not msg:
                continue

            candidates = self._extract_identifier_candidates("", msg)
            if not candidates:
                continue

            # Check if this commit claims creation/implementation of a specific component
            if any(p.search(msg) for p in self.COMPLETION_PATTERNS) or msg.lower().startswith(("feat:", "add ", "implement ")):
                for cand in candidates:
                    cand_lower = cand.lower()
                    if len(cand) < 4 or cand_lower in {"test", "tests", "code", "file", "feat", "docs", "fix"}:
                        continue
                    has_match = (
                        cand_lower in symbol_names
                        or any(cand_lower in s for s in symbol_names)
                        or any(cand_lower in f for f in file_names)
                    )
                    if not has_match:
                        records.append(ContradictionRecord(
                            id=f"contra_{uuid.uuid4().hex[:8]}",
                            severity=ContradictionSeverity.MEDIUM.value,
                            claim_id=None,
                            claim_text=f"Git commit '{commit.get('hash', 'head')[:7]}': {msg}",
                            physical_evidence_id=git_state.evidence_ids[0] if git_state.evidence_ids else None,
                            explanation=(
                                f"Git commit message '{msg}' implies implementation of '{cand}', "
                                f"but no matching AST symbol or source file exists in the repository."
                            ),
                            detected_at=datetime.now(timezone.utc).isoformat(),
                            resolved=False
                        ))

        return records

    def _extract_identifier_candidates(self, target: str, text: str) -> List[str]:
        """Extracts potential class, function, or module names from claim text."""
        candidates = []
        if target:
            candidates.append(target)

        # Look for words in quotes or CamelCase or snake_case
        quoted = re.findall(r"['\"`]([A-Za-z0-9_\-\.]+)['\"`]", text)
        candidates.extend(quoted)

        # Look for explicit CamelCase identifiers (e.g. KafkaEventStreamingProducer)
        camel_cases = re.findall(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b", text)
        candidates.extend(camel_cases)

        # Look for targets following feat:, add, implement, create
        verb_match = re.findall(r"\b(?:implement|add|create|feat:)\s+([A-Za-z0-9_]+)\b", text, re.IGNORECASE)
        candidates.extend(verb_match)

        # Look for tokens before keywords like "service", "handler", "manager", "parser", "client", "controller"
        comp_match = re.findall(r"\b([A-Za-z0-9_]+(?:\s+[A-Za-z0-9_]+)?\s+(?:service|handler|manager|parser|client|controller|engine|module|endpoint|function|producer|consumer))\b", text, re.IGNORECASE)
        for m in comp_match:
            cleaned = m.replace(" ", "_").lower()
            candidates.append(cleaned)
            candidates.append(m)

        # Strip duplicates while preserving order
        unique: List[str] = []
        for c in candidates:
            if c and c not in unique:
                unique.append(c)

        return unique

    def audit_canonical_state(self, canonical_state: CanonicalProjectState) -> DiscrepancyLedger:
        """
        Executes full contradiction audit on a CanonicalProjectState,
        populates its discrepancies ledger, and returns the DiscrepancyLedger.
        """
        detected = self.detect_contradictions(
            project_state=canonical_state.project_state,
            conversational_state=canonical_state.conversational_state,
            evidence_pool=canonical_state.evidence_pool
        )

        canonical_state.contradictions = detected
        return DiscrepancyLedger(records=detected)
