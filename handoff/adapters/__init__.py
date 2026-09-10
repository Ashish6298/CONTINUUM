"""
Project Continuum - Model Adapter Factory and Package Exports
=============================================================
Milestone 6 - Phase 15: Model-Specific Handoff Adapters.
"""

from typing import Dict, Type

from core.enums import TargetModel
from core.interfaces import IModelAdapter
from handoff.adapters.base import BaseModelAdapter
from handoff.adapters.claude_adapter import ClaudeAdapter
from handoff.adapters.codex_gpt_adapter import CodexGptAdapter
from handoff.adapters.gemini_adapter import GeminiAdapter
from handoff.adapters.local_model_adapter import LocalModelAdapter


ADAPTER_REGISTRY: Dict[TargetModel, Type[BaseModelAdapter]] = {
    TargetModel.CLAUDE: ClaudeAdapter,
    TargetModel.CODEX_GPT: CodexGptAdapter,
    TargetModel.GEMINI: GeminiAdapter,
    TargetModel.LOCAL_LLM: LocalModelAdapter,
}


def get_adapter_for_model(target_model: TargetModel) -> BaseModelAdapter:
    """
    Factory function to retrieve the specialized adapter instance for a target AI platform.
    """
    adapter_cls = ADAPTER_REGISTRY.get(target_model)
    if not adapter_cls:
        # Fallback to Codex/GPT general markdown adapter
        return CodexGptAdapter()
    return adapter_cls()


__all__ = [
    "BaseModelAdapter",
    "ClaudeAdapter",
    "CodexGptAdapter",
    "GeminiAdapter",
    "LocalModelAdapter",
    "get_adapter_for_model",
    "ADAPTER_REGISTRY",
]
