"""
Project Continuum - AI Model Handoff System
===========================================
Milestone 6: AI Model Handoff System.
Contains Universal Handoff Package Generation (Phase 14) and Model-Specific Adapters (Phase 15).
"""

from handoff.models import HandoffPackage
from handoff.packager import UniversalHandoffPackager
from handoff.adapters import (
    BaseModelAdapter,
    ClaudeAdapter,
    CodexGptAdapter,
    GeminiAdapter,
    LocalModelAdapter,
    get_adapter_for_model,
)

__all__ = [
    "HandoffPackage",
    "UniversalHandoffPackager",
    "BaseModelAdapter",
    "ClaudeAdapter",
    "CodexGptAdapter",
    "GeminiAdapter",
    "LocalModelAdapter",
    "get_adapter_for_model",
]
