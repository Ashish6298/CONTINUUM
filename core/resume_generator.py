"""
Project Continuum — Deterministic Resume Brief Generator (v1.4.0)
================================================================
Milestone 38: Capture and Resume
Phase 60: Deterministic Resume Briefs

Implements:
1. `DeterministicResumeBriefGenerator`:
   - Generates actionable continuity briefs locally and deterministically answering
     the 6 core continuity questions:
     1. Purpose: activity purpose & checkpoint directive context.
     2. Last completed work: authoritative completed tasks with provenance labelling.
     3. Key decisions & constraints: structured design decisions.
     4. Blockers: unresolved blockers or explicit '[None reported]' indicator.
     5. Unresolved issues: pending questions or uncertainties labeled explicitly.
     6. Next actions: concrete prioritized forward steps.
   - Ground truth invariant (I-06): Summaries are derived, never authoritative.
     Ground truth resides strictly in structured checkpoint records.
   - Zero-invention rule: Never hallucinates missing facts. If data is sparse, it
     emits explicit uncertainty/sparse indicators (e.g., '[Unspecified; proceed with activity goal]').
   - Comprehensive secret redaction (I-10): All output text is sanitized against DaemonSanitizer.
   - Optional AI Enhancement abstraction (I-09):
     * Strictly requires explicit user consent (`ai_consent_granted=True`).
     * Transparently discloses provider, model, and transmitted fields.
     * Safely falls back to local deterministic generator if AI is disabled,
       unavailable, unconfigured, or declined.
     * Zero external transfer without user consent.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.activity import Activity
from core.checkpoint import UniversalCheckpoint, ResumeBrief, DecisionRecord
from core.enums import ProvenanceType
from server.sanitizer import DaemonSanitizer


@dataclass
class AiEnhancementConsent:
    """Explicit disclosure and consent record for optional AI brief enhancement."""
    consent_granted: bool = False
    provider_name: str = "none"
    model_name: str = "none"
    disclosed_content_scope: List[str] = field(default_factory=list)
    consent_timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "consent_granted": self.consent_granted,
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "disclosed_content_scope": list(self.disclosed_content_scope),
            "consent_timestamp": self.consent_timestamp,
        }


class DeterministicResumeBriefGenerator:
    """
    Generator of derived Resume Briefs from authoritative activity and checkpoint data.
    """

    GENERATOR_ID = "continuum_deterministic_v1"

    def __init__(
        self,
        ai_provider_callback: Optional[Callable[[str, Dict[str, Any]], Optional[Dict[str, Any]]]] = None,
        workspace_root: Optional[Any] = None,
    ):
        """
        :param ai_provider_callback: Optional hook for AI enhancement. Receives (prompt, metadata)
                                     and returns structured enhancement dict.
        :param workspace_root: Optional workspace root path.
        """
        self.ai_provider_callback = ai_provider_callback
        self.workspace_root = workspace_root

    def _sanitize_string(self, text: str) -> str:
        """Redacts inline secrets, credentials, and custom denied terms via PrivacyManager."""
        if not text:
            return ""
        try:
            from core.privacy import PrivacyManager
            return PrivacyManager.get_instance().sanitize_text(text)
        except Exception:
            sanitized = text
            for pattern, replacement in DaemonSanitizer.INLINE_SECRET_PATTERNS:
                sanitized = pattern.sub(replacement, sanitized)
            return sanitized

    def _sanitize_list(self, items: List[str]) -> List[str]:
        """Redacts secrets from each item in a list."""
        return [self._sanitize_string(str(item).strip()) for item in items if str(item).strip()]

    def generate_brief(
        self,
        activity: Activity,
        checkpoint: UniversalCheckpoint,
        ai_consent: Optional[AiEnhancementConsent] = None,
    ) -> ResumeBrief:
        """
        Generates a ResumeBrief deterministically from authoritative Activity and Checkpoint entities.
        If AI enhancement is requested and consent is verified, attempts AI enhancement with safe fallback.
        """
        # 1. Purpose (Authoritative from Activity description / Checkpoint context)
        purpose_candidates = [
            checkpoint.context.strip(),
            activity.description.strip() if hasattr(activity, "description") else "",
            activity.title.strip(),
        ]
        chosen_purpose = next((p for p in purpose_candidates if p), f"Work session for activity: {activity.title}")
        sanitized_purpose = self._sanitize_string(chosen_purpose)

        # 2. Last Completed Work
        completed_work: List[str] = []
        if checkpoint.completed_work:
            for item in checkpoint.completed_work:
                clean = self._sanitize_string(str(item).strip())
                if clean:
                    completed_work.append(clean)
        else:
            # Explicit non-invention label for sparse state
            completed_work.append("[No specific completed work items logged in source checkpoint]")

        # 3. Key Decisions & Constraints
        key_decisions: List[str] = []
        if checkpoint.decisions:
            for d in checkpoint.decisions:
                decision_text = d.decision if isinstance(d, DecisionRecord) else str(d.get("decision", ""))
                rationale_text = d.rationale if isinstance(d, DecisionRecord) else str(d.get("rationale", ""))
                constraints = d.constraints if isinstance(d, DecisionRecord) else list(d.get("constraints", []))

                clean_dec = self._sanitize_string(decision_text.strip())
                clean_rat = self._sanitize_string(rationale_text.strip())
                clean_cons = self._sanitize_list(constraints)

                entry = clean_dec
                if clean_rat:
                    entry += f" (Rationale: {clean_rat})"
                if clean_cons:
                    entry += f" [Constraints: {', '.join(clean_cons)}]"
                if entry:
                    key_decisions.append(entry)
        else:
            key_decisions.append("[No explicit architectural decisions recorded]")

        # 4. Blockers
        blockers: List[str] = []
        if checkpoint.blockers:
            for b in checkpoint.blockers:
                clean_b = self._sanitize_string(str(b).strip())
                if clean_b:
                    blockers.append(clean_b)
        else:
            blockers.append("[None reported]")

        # 5. Unresolved Questions & Uncertainties
        unresolved_questions: List[str] = []
        if checkpoint.structured_state and isinstance(checkpoint.structured_state, dict):
            raw_unresolved = checkpoint.structured_state.get("unresolved_questions") or []
            if isinstance(raw_unresolved, list):
                for q in raw_unresolved:
                    clean_q = self._sanitize_string(str(q).strip())
                    if clean_q:
                        unresolved_questions.append(clean_q)

        # Label provenance uncertainty if not user-confirmed
        if checkpoint.provenance and checkpoint.provenance.provenance_type != ProvenanceType.USER_CONFIRMED:
            prov_type = (
                checkpoint.provenance.provenance_type.value
                if hasattr(checkpoint.provenance.provenance_type, "value")
                else str(checkpoint.provenance.provenance_type)
            )
            unresolved_questions.append(
                f"[Provenance notice: source checkpoint was {prov_type} by '{checkpoint.provenance.captured_by}'; verify assumptions before proceeding]"
            )

        if not unresolved_questions:
            unresolved_questions.append("[None reported]")

        # 6. Next Actions
        next_actions: List[str] = []
        if checkpoint.pending_actions:
            for a in checkpoint.pending_actions:
                clean_a = self._sanitize_string(str(a).strip())
                if clean_a:
                    next_actions.append(clean_a)
        else:
            # Fallback action without hallucination
            next_actions.append(f"Resume work on '{activity.title}' according to activity purpose.")

        # Construct deterministic baseline brief
        brief = ResumeBrief(
            purpose=sanitized_purpose,
            last_completed_work=completed_work,
            key_decisions=key_decisions,
            blockers=blockers,
            unresolved_questions=unresolved_questions,
            next_actions=next_actions,
            generated_at=datetime.now(timezone.utc).isoformat(),
            is_ai_enhanced=False,
            generator_id=self.GENERATOR_ID,
        )

        # 7. Optional AI Enhancement (strictly gated by explicit user consent & privacy configuration)
        ai_allowed_by_privacy = False
        try:
            from core.privacy import PrivacyManager
            ai_allowed_by_privacy = PrivacyManager.get_instance().config.ai_enhancement_allowed
        except Exception:
            ai_allowed_by_privacy = False

        if ai_allowed_by_privacy and ai_consent and ai_consent.consent_granted and self.ai_provider_callback:
            try:
                enhanced_brief = self._attempt_ai_enhancement(brief, activity, checkpoint, ai_consent)
                if enhanced_brief is not None:
                    return enhanced_brief
            except Exception:
                # Safe fallback to deterministic brief on any AI failure
                pass

        return brief

    def _attempt_ai_enhancement(
        self,
        baseline: ResumeBrief,
        activity: Activity,
        checkpoint: UniversalCheckpoint,
        ai_consent: AiEnhancementConsent,
    ) -> Optional[ResumeBrief]:
        """Executes optional AI enhancement only when explicit consent is present."""
        if not self.ai_provider_callback or not ai_consent.consent_granted:
            return None

        prompt_payload = {
            "purpose": baseline.purpose,
            "last_completed_work": baseline.last_completed_work,
            "key_decisions": baseline.key_decisions,
            "blockers": baseline.blockers,
            "unresolved_questions": baseline.unresolved_questions,
            "next_actions": baseline.next_actions,
            "metadata": {
                "activity_id": activity.id,
                "checkpoint_id": checkpoint.id,
                "provider": ai_consent.provider_name,
                "model": ai_consent.model_name,
            },
        }

        result = self.ai_provider_callback(baseline.purpose, prompt_payload)
        if not result or not isinstance(result, dict):
            return None

        # Sanitize all AI-provided content before returning
        return ResumeBrief(
            purpose=self._sanitize_string(result.get("purpose", baseline.purpose)),
            last_completed_work=self._sanitize_list(result.get("last_completed_work", baseline.last_completed_work)),
            key_decisions=self._sanitize_list(result.get("key_decisions", baseline.key_decisions)),
            blockers=self._sanitize_list(result.get("blockers", baseline.blockers)),
            unresolved_questions=self._sanitize_list(result.get("unresolved_questions", baseline.unresolved_questions)),
            next_actions=self._sanitize_list(result.get("next_actions", baseline.next_actions)),
            generated_at=datetime.now(timezone.utc).isoformat(),
            is_ai_enhanced=True,
            generator_id=f"ai_enhanced_{ai_consent.provider_name}_{ai_consent.model_name}",
        )

    @classmethod
    def format_brief_as_markdown(cls, brief: ResumeBrief, activity_title: str = "") -> str:
        """Formats a ResumeBrief into standard, human-readable GitHub-flavored markdown."""
        lines = []
        title_suffix = f" — {activity_title}" if activity_title else ""
        lines.append(f"### 🚀 CONTINUITY RESUME BRIEF{title_suffix}")
        lines.append(f"*Generated deterministically at {brief.generated_at} (Generator: `{brief.generator_id}`)*\n")

        lines.append("#### 🎯 1. Purpose & Working Goal")
        lines.append(f"{brief.purpose}\n")

        lines.append("#### ✅ 2. Last Completed Work")
        for item in brief.last_completed_work:
            lines.append(f"- {item}")
        lines.append("")

        lines.append("#### 💡 3. Key Decisions & Constraints")
        for item in brief.key_decisions:
            lines.append(f"- {item}")
        lines.append("")

        lines.append("#### 🛑 4. Blockers & Roadblocks")
        for item in brief.blockers:
            lines.append(f"- {item}")
        lines.append("")

        lines.append("#### ❓ 5. Unresolved Issues & Uncertainties")
        for item in brief.unresolved_questions:
            lines.append(f"- {item}")
        lines.append("")

        lines.append("#### ⏩ 6. Next Concrete Actions")
        for item in brief.next_actions:
            lines.append(f"1. {item}")
        lines.append("")

        return "\n".join(lines)
