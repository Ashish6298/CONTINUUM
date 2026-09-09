"""
Project Continuum - Canonical Enums and Ontological Types
=========================================================
Defines the core enumerations, evidence types, evidence hierarchy levels,
status states, node types, and relationship types across the system.
"""

from enum import Enum, IntEnum, auto


class Status(str, Enum):
    """
    Standard status system used across all entities in Project Continuum.
    Represents the verified lifecycle state of components, tasks, and requirements.
    """
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    PARTIAL = "PARTIAL"
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def is_terminal_success(cls, status: "Status") -> bool:
        return status == cls.VERIFIED

    @classmethod
    def is_actionable(cls, status: "Status") -> bool:
        return status in {cls.PENDING, cls.IN_PROGRESS, cls.PARTIAL, cls.BLOCKED, cls.FAILED, cls.STALE}


class EvidenceType(str, Enum):
    """
    Canonical types of evidence harvested from the workspace, environment,
    verification pipelines, or conversations.
    """
    SOURCE_CODE = "SOURCE_CODE"
    AST_SYMBOL = "AST_SYMBOL"
    GIT_COMMIT = "GIT_COMMIT"
    GIT_DIFF = "GIT_DIFF"
    GIT_STATUS = "GIT_STATUS"
    TEST_RUN = "TEST_RUN"
    BUILD_LOG = "BUILD_LOG"
    CONFIG_FILE = "CONFIG_FILE"
    DOCUMENTATION = "DOCUMENTATION"
    RUNTIME_LOG = "RUNTIME_LOG"
    CONVERSATION_ASSERTION = "CONVERSATION_ASSERTION"
    USER_REQUIREMENT = "USER_REQUIREMENT"
    AGENT_CLAIM = "AGENT_CLAIM"


class EvidenceLevel(IntEnum):
    """
    The Evidence Hierarchy Matrix:
    Strict seniority ranking for truth arbitration.
    Lower numerical value indicates HIGHER priority / ground truth authority.
    
    Level 1: Runtime status & automated test execution exit codes (Highest)
    Level 2: AST structure, symbol exports, and physical source files
    Level 3: Git working tree diffs, staged index, and commit history
    Level 4: Architecture documentation, inline comments, and READMEs
    Level 5: Conversational statements and agent assertions (Lowest)
    """
    LEVEL_1_RUNTIME_TEST = 1
    LEVEL_2_CODE_AST = 2
    LEVEL_3_GIT_STATE = 3
    LEVEL_4_DOCUMENTATION = 4
    LEVEL_5_CONVERSATION = 5

    @classmethod
    def get_level_for_type(cls, evidence_type: EvidenceType) -> "EvidenceLevel":
        """Maps an evidence type to its fundamental hierarchy seniority level."""
        mapping = {
            EvidenceType.TEST_RUN: cls.LEVEL_1_RUNTIME_TEST,
            EvidenceType.BUILD_LOG: cls.LEVEL_1_RUNTIME_TEST,
            EvidenceType.RUNTIME_LOG: cls.LEVEL_1_RUNTIME_TEST,
            EvidenceType.SOURCE_CODE: cls.LEVEL_2_CODE_AST,
            EvidenceType.AST_SYMBOL: cls.LEVEL_2_CODE_AST,
            EvidenceType.CONFIG_FILE: cls.LEVEL_2_CODE_AST,
            EvidenceType.GIT_COMMIT: cls.LEVEL_3_GIT_STATE,
            EvidenceType.GIT_DIFF: cls.LEVEL_3_GIT_STATE,
            EvidenceType.GIT_STATUS: cls.LEVEL_3_GIT_STATE,
            EvidenceType.DOCUMENTATION: cls.LEVEL_4_DOCUMENTATION,
            EvidenceType.CONVERSATION_ASSERTION: cls.LEVEL_5_CONVERSATION,
            EvidenceType.USER_REQUIREMENT: cls.LEVEL_5_CONVERSATION,
            EvidenceType.AGENT_CLAIM: cls.LEVEL_5_CONVERSATION,
        }
        return mapping.get(evidence_type, cls.LEVEL_5_CONVERSATION)


class NodeType(str, Enum):
    """
    Types of entities present in the Canonical State Graph (DAG).
    """
    MILESTONE = "MILESTONE"
    PHASE = "PHASE"
    REQUIREMENT = "REQUIREMENT"
    MODULE = "MODULE"
    SERVICE = "SERVICE"
    API = "API"
    TASK = "TASK"
    TEST = "TEST"
    COMPONENT = "COMPONENT"


class RelationType(str, Enum):
    """
    Directed relationship types connecting nodes in the Canonical State Graph.
    """
    DEPENDS_ON = "DEPENDS_ON"
    IMPLEMENTS = "IMPLEMENTS"
    VERIFIES = "VERIFIES"
    BLOCKS = "BLOCKS"
    IMPORTS = "IMPORTS"
    REQUIRES = "REQUIRES"
    INVALIDATES = "INVALIDATES"


class TargetModel(str, Enum):
    """
    Target AI model families supported by specialized handoff adapters.
    """
    CLAUDE = "CLAUDE"
    CODEX_GPT = "CODEX_GPT"
    GEMINI = "GEMINI"
    LOCAL_LLM = "LOCAL_LLM"
    UNIVERSAL = "UNIVERSAL"
