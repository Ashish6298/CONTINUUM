"""
Project Continuum - Conversation & Agent State Evidence Extractor
=================================================================
Milestone 2 - Phase 5: Conversation & Agent State Ingestion.
Ingests conversational transcripts (JSON, markdown, or plain-text), extracts
requirements, unverified claims, architectural decisions, and tactical agent
state, generating Level 5 canonical evidence without contaminating ProjectState.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from core.enums import EvidenceType, EvidenceLevel, Status
from core.evidence import Evidence
from core.state_models import (
    AgentExecutionState,
    CanonicalProjectState,
    ConversationalState,
)
from extractors.base import BaseEvidenceExtractor
from extractors.conversation.analyzers import TranscriptAnalysisResult, TranscriptAnalyzer
from extractors.conversation.models import ConversationTranscript, TurnRole


class ConversationEvidenceExtractor(BaseEvidenceExtractor):
    """
    Extractor responsible for Phase 5: Ingesting conversation transcripts
    and recording conversational intent and agent execution states.
    """

    @property
    def extractor_name(self) -> str:
        return "ConversationEvidenceExtractor"

    @property
    def supported_evidence_types(self) -> List[EvidenceType]:
        return [
            EvidenceType.CONVERSATION_ASSERTION,
            EvidenceType.USER_REQUIREMENT,
            EvidenceType.AGENT_CLAIM,
        ]

    def can_extract(self, target_path_or_input: str) -> bool:
        # Can extract from a file (.json, .txt, .md) or from raw text string
        if isinstance(target_path_or_input, str):
            if Path(target_path_or_input).exists():
                return True
            # Or raw conversational text
            return "user:" in target_path_or_input.lower() or "assistant:" in target_path_or_input.lower() or "{" in target_path_or_input
        return False

    def load_transcript(self, source: Union[str, Path, Dict[str, Any]]) -> ConversationTranscript:
        """Loads a transcript from a file, raw string, or dictionary."""
        if isinstance(source, dict):
            return ConversationTranscript.from_dict(source)

        if isinstance(source, (str, Path)):
            path = Path(source)
            if path.exists() and path.is_file():
                content = path.read_text(encoding="utf-8", errors="replace")
                if path.suffix.lower() == ".json":
                    return ConversationTranscript.from_json(content)
                else:
                    return ConversationTranscript.from_plain_text(content)
            elif isinstance(source, str):
                # Check if JSON string
                if source.strip().startswith("{") or source.strip().startswith("["):
                    try:
                        return ConversationTranscript.from_json(source)
                    except Exception:
                        pass
                return ConversationTranscript.from_plain_text(source)

        return ConversationTranscript()

    def extract(self, target_path_or_input: str, context: Optional[Dict[str, Any]] = None) -> List[Evidence]:
        transcript = self.load_transcript(target_path_or_input)
        analysis: TranscriptAnalysisResult = TranscriptAnalyzer.analyze(transcript)

        evidence_list: List[Evidence] = []
        source_label = str(target_path_or_input) if isinstance(target_path_or_input, (str, Path)) else "raw_transcript"

        # 1. User Requirements Evidence
        for req in analysis.requirements:
            ev = self.create_evidence(
                evidence_type=EvidenceType.USER_REQUIREMENT,
                summary=f"User Requirement #{req.id}: {req.title}",
                raw_payload={"requirement": req.to_dict(), "session_id": transcript.session_id},
                source_uri=source_label,
                locator=f"turn:{req.source_turn}"
            )
            req.evidence_id = ev.id
            evidence_list.append(ev)

        # 2. Agent Claims Evidence
        for claim in analysis.agent_claims:
            ev = self.create_evidence(
                evidence_type=EvidenceType.AGENT_CLAIM,
                summary=f"Agent Claim #{claim.id} by {claim.source_agent}: '{claim.claim_text}'",
                raw_payload={"claim": claim.to_dict(), "session_id": transcript.session_id},
                source_uri=source_label,
                locator=f"turn:{claim.turn_id}"
            )
            claim.evidence_id = ev.id
            evidence_list.append(ev)

        # 3. Overall Conversational State Evidence
        evidence_list.append(self.create_evidence(
            evidence_type=EvidenceType.CONVERSATION_ASSERTION,
            summary=(
                f"Ingested transcript with {len(transcript.turns)} turns: "
                f"{len(analysis.requirements)} requirements, {len(analysis.agent_claims)} agent claims, "
                f"{len(analysis.decisions)} decisions, {len(analysis.unresolved_questions)} unresolved Qs"
            ),
            raw_payload={
                "session_id": transcript.session_id,
                "platform": transcript.platform,
                "model_name": transcript.model_name,
                "referenced_files": analysis.referenced_files,
                "decisions": [d.to_dict() for d in analysis.decisions],
                "assumptions": analysis.assumptions,
                "unresolved_questions": [q.to_dict() for q in analysis.unresolved_questions]
            },
            source_uri=source_label,
            locator="session:transcript"
        ))

        return evidence_list

    def ingest_transcript(
        self,
        transcript_source: Union[str, Path, Dict[str, Any]],
        canonical_state: CanonicalProjectState
    ) -> Tuple[ConversationalState, AgentExecutionState]:
        """
        Populates CanonicalProjectState.conversational_state and agent_execution_state
        while STRICTLY ensuring that ProjectState remains completely unchanged.
        """
        transcript = self.load_transcript(transcript_source)
        analysis = TranscriptAnalyzer.analyze(transcript)
        evidence_list = self.extract(transcript_source if isinstance(transcript_source, str) else str(transcript.session_id))

        # Register evidence
        for ev in evidence_list:
            canonical_state.add_evidence(ev)

        # Update ConversationalState
        cs = canonical_state.conversational_state
        cs.session_id = transcript.session_id
        cs.user_requirements.extend(analysis.requirements)
        cs.agent_claims.extend(analysis.agent_claims)
        cs.architectural_decisions.extend(analysis.decisions)
        cs.assumptions.extend(analysis.assumptions)
        cs.unresolved_questions.extend(analysis.unresolved_questions)
        cs.transcript_provenance.append(f"session:{transcript.session_id} ({len(transcript.turns)} turns)")

        # Update AgentExecutionState
        aes = canonical_state.agent_execution_state
        aes.agent_id = transcript.model_name or "assistant_session"
        aes.model_name = transcript.model_name or "unknown"
        aes.active_tasks.extend(analysis.tactical_tasks)
        aes.modified_files_in_flight.extend(analysis.referenced_files)
        if analysis.next_action:
            aes.next_action = analysis.next_action

        return cs, aes
