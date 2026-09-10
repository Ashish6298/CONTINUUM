"""
Project Continuum - Conversational Intent, Claim & Execution Analyzer
=====================================================================
Analyzes conversation transcripts to extract requirements, unverified
agent claims, architectural decisions, assumptions, unresolved questions,
file references, and tactical execution state.
"""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from core.enums import Status
from core.state_models import (
    AgentClaim,
    ArchitecturalDecision,
    NextActionRecommendation,
    Requirement,
    TacticalTask,
    UnresolvedQuestion,
)
from extractors.conversation.models import ConversationTranscript, ConversationTurn, TurnRole


@dataclass
class TranscriptAnalysisResult:
    """Structured insights extracted from a conversation transcript."""
    requirements: List[Requirement] = field(default_factory=list)
    agent_claims: List[AgentClaim] = field(default_factory=list)
    decisions: List[ArchitecturalDecision] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    unresolved_questions: List[UnresolvedQuestion] = field(default_factory=list)
    tactical_tasks: List[TacticalTask] = field(default_factory=list)
    referenced_files: List[str] = field(default_factory=list)
    next_action: Optional[NextActionRecommendation] = None


class TranscriptAnalyzer:
    """
    Parses conversational dialogue turns and extracts semantic intent, claims,
    and execution state using pattern matching and ontological heuristics.
    """

    # Requirements keywords (user intent)
    REQUIREMENT_PATTERNS = [
        re.compile(r"(?:we need to|please|i want to|implement|create|build|add support for|must have|requirement:?)\s+([^.\n]+)", re.IGNORECASE),
        re.compile(r"(?:feature request:?|goal:?)\s+([^.\n]+)", re.IGNORECASE)
    ]

    # Completion / Progress claims (assistant statements)
    CLAIM_PATTERNS = [
        re.compile(r"(?:i have|i've|we have|we've)\s+(?:completed|implemented|finished|created|fixed|verified|tested|added)\s+([^.\n]+)", re.IGNORECASE),
        re.compile(r"(?:is now|are now)\s+(?:complete|working|passing all tests|implemented|ready)\b([^.\n]*)", re.IGNORECASE),
        re.compile(r"(?:tests are passing|all tests pass|build succeeded)", re.IGNORECASE)
    ]

    # Architectural decisions
    DECISION_PATTERNS = [
        re.compile(r"(?:decided to|let's use|we will use|architectural decision:?|decision:?|chosen approach:?)\s+([^.\n]+)", re.IGNORECASE),
        re.compile(r"(?:instead of\s+[\w\s]+,\s*we(?:'ll| will)\s+use\s+([^.\n]+))", re.IGNORECASE)
    ]

    # Questions & dilemmas
    QUESTION_PATTERNS = [
        re.compile(r"^(?:.*?\s+)?([^.!\n]+\?)", re.MULTILINE),
    ]

    # File path detector
    FILE_PATH_PATTERN = re.compile(
        r"""(?:[\w\-_\/.]+\.(?:py|js|ts|tsx|jsx|json|toml|yaml|yml|rs|go|md|txt|sql|html|css|dart|c|cpp|h))""",
        re.IGNORECASE
    )

    # Next action patterns
    NEXT_ACTION_PATTERNS = [
        re.compile(r"(?:next steps?:?|next action:?|next,?\s+(?:we should|let's|i will))\s+([^.\n]+)", re.IGNORECASE),
        re.compile(r"(?:now we can proceed to|moving on to)\s+([^.\n]+)", re.IGNORECASE)
    ]

    @classmethod
    def analyze(cls, transcript: ConversationTranscript) -> TranscriptAnalysisResult:
        result = TranscriptAnalysisResult()
        req_id_counter = 1
        claim_id_counter = 1
        dec_id_counter = 1
        q_id_counter = 1
        task_id_counter = 1

        all_file_refs: Set[str] = set()

        for turn in transcript.turns:
            content = turn.content.strip()
            if not content:
                continue

            # Detect file references across all turns
            for match in cls.FILE_PATH_PATTERN.finditer(content):
                path_match = match.group(0).strip("`'\"(),")
                if "/" in path_match or "." in path_match:
                    all_file_refs.add(path_match)

            # 1. Analyze User Turns (Requirements & Assumptions)
            if turn.role == TurnRole.USER:
                for pat in cls.REQUIREMENT_PATTERNS:
                    for match in pat.finditer(content):
                        title = match.group(1).strip()
                        if len(title) > 5 and not any(r.title.lower() == title.lower() for r in result.requirements):
                            result.requirements.append(Requirement(
                                id=f"req_{req_id_counter:03d}",
                                title=title,
                                description=f"Extracted from User turn #{turn.turn_index}: '{match.group(0).strip()}'",
                                source_turn=turn.turn_index,
                                status=Status.PENDING
                            ))
                            req_id_counter += 1

                # Check for explicit assumptions
                if "assuming" in content.lower() or "assumption" in content.lower():
                    result.assumptions.append(f"User turn #{turn.turn_index}: {content[:120]}")

            # 2. Analyze Assistant Turns (Claims, Decisions, Questions, Tasks)
            elif turn.role == TurnRole.ASSISTANT:
                # Claims
                for pat in cls.CLAIM_PATTERNS:
                    for match in pat.finditer(content):
                        claim_text = match.group(0).strip()
                        if len(claim_text) > 8:
                            result.agent_claims.append(AgentClaim(
                                id=f"claim_{claim_id_counter:03d}",
                                claim_text=claim_text,
                                target_component=cls._extract_target_component(claim_text),
                                claimed_status=Status.VERIFIED,
                                source_agent=turn.author_model or "assistant",
                                turn_id=turn.turn_index
                            ))
                            claim_id_counter += 1

                # Architectural Decisions
                for pat in cls.DECISION_PATTERNS:
                    for match in pat.finditer(content):
                        dec_title = match.group(1).strip()
                        if len(dec_title) > 5:
                            result.decisions.append(ArchitecturalDecision(
                                id=f"arch_{dec_id_counter:03d}",
                                title=dec_title,
                                rationale=f"Agreed in Assistant turn #{turn.turn_index}",
                                recorded_at=turn.timestamp
                            ))
                            dec_id_counter += 1

                # Unresolved Questions (Assistant asking user)
                if "?" in content:
                    for match in cls.QUESTION_PATTERNS:
                        for q_match in match.finditer(content):
                            q_text = q_match.group(0).strip()
                            if len(q_text) > 10 and not any(q.question == q_text for q in result.unresolved_questions):
                                result.unresolved_questions.append(UnresolvedQuestion(
                                    id=f"q_{q_id_counter:03d}",
                                    question=q_text,
                                    context=f"Asked by assistant at turn #{turn.turn_index}",
                                    blocking=True
                                ))
                                q_id_counter += 1

                # Tactical Tasks (In-flight work)
                if "task" in content.lower() or "working on" in content.lower() or "currently" in content.lower():
                    result.tactical_tasks.append(TacticalTask(
                        id=f"task_{task_id_counter:03d}",
                        title=f"Turn #{turn.turn_index} action item",
                        notes=content[:200],
                        status=Status.IN_PROGRESS
                    ))
                    task_id_counter += 1

                # Next Action
                for pat in cls.NEXT_ACTION_PATTERNS:
                    match = pat.search(content)
                    if match:
                        action_desc = match.group(1).strip()
                        result.next_action = NextActionRecommendation(
                            action_type="CONTINUE_EXECUTION",
                            target_uri="workspace",
                            description=action_desc
                        )

        result.referenced_files = sorted(list(all_file_refs))
        return result

    @staticmethod
    def _extract_target_component(claim_text: str) -> Optional[str]:
        """Heuristically extracts symbol or component name from claim text."""
        words = re.findall(r"[A-Z][a-zA-Z0-9]+|\b[\w\-_\/.]+\.\w+\b", claim_text)
        return words[0] if words else None
