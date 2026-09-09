"""
Project Continuum - Schema Generator and Validator
==================================================
Provides JSON Schema definitions, versioning metadata, and validation
utilities for CanonicalProjectState and all its subcomponents.
"""

import json
from typing import Any, Dict, List, Tuple
from core.enums import Status, EvidenceType, EvidenceLevel, NodeType, RelationType, TargetModel


CANONICAL_STATE_SCHEMA_VERSION = "1.0.0"

def get_canonical_project_state_schema() -> Dict[str, Any]:
    """
    Returns the full JSON Schema (Draft 2020-12 / Draft-07 compatible)
    for Project Continuum's Canonical Project State.
    """
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://project-continuum.dev/schemas/v{CANONICAL_STATE_SCHEMA_VERSION}/canonical-project-state.json",
        "title": "CanonicalProjectState",
        "description": "Root container for Project Continuum's verified state, segregating physical ground truth, conversational claims, and agent execution intent.",
        "type": "object",
        "required": [
            "schema_version",
            "project_id",
            "created_at",
            "updated_at",
            "project_state",
            "conversational_state",
            "agent_execution_state",
            "evidence_pool",
            "graph_nodes",
            "graph_edges",
            "contradictions"
        ],
        "properties": {
            "schema_version": {
                "type": "string",
                "pattern": r"^\d+\.\d+\.\d+$",
                "default": CANONICAL_STATE_SCHEMA_VERSION
            },
            "project_id": {"type": "string"},
            "created_at": {"type": "string", "format": "date-time"},
            "updated_at": {"type": "string", "format": "date-time"},
            
            # 1. Project State
            "project_state": {
                "type": "object",
                "required": ["root_path", "detected_languages", "files", "manifests", "symbols", "git_state", "test_results", "build_status", "todo_markers", "evidence_ids", "last_scanned_at"],
                "properties": {
                    "root_path": {"type": "string"},
                    "detected_languages": {"type": "array", "items": {"type": "string"}},
                    "files": {"type": "array", "items": {"type": "string"}},
                    "manifests": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["manifest_type", "file_path", "dependencies", "dev_dependencies", "scripts"],
                            "properties": {
                                "manifest_type": {"type": "string"},
                                "file_path": {"type": "string"},
                                "project_name": {"type": ["string", "null"]},
                                "version": {"type": ["string", "null"]},
                                "dependencies": {"type": "object"},
                                "dev_dependencies": {"type": "object"},
                                "scripts": {"type": "object"},
                                "evidence_id": {"type": ["string", "null"]}
                            }
                        }
                    },
                    "symbols": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name", "kind", "file_path", "line_start", "line_end", "exported"],
                            "properties": {
                                "name": {"type": "string"},
                                "kind": {"type": "string"},
                                "file_path": {"type": "string"},
                                "line_start": {"type": "integer", "minimum": 1},
                                "line_end": {"type": "integer", "minimum": 1},
                                "exported": {"type": "boolean"},
                                "docstring": {"type": ["string", "null"]},
                                "parameters": {"type": "array", "items": {"type": "string"}},
                                "return_type": {"type": ["string", "null"]},
                                "evidence_id": {"type": ["string", "null"]}
                            }
                        }
                    },
                    "git_state": {
                        "type": "object",
                        "required": ["is_repo", "is_dirty", "staged_files", "unstaged_files", "untracked_files", "recent_commits", "evidence_ids"],
                        "properties": {
                            "is_repo": {"type": "boolean"},
                            "branch": {"type": ["string", "null"]},
                            "head_commit": {"type": ["string", "null"]},
                            "is_dirty": {"type": "boolean"},
                            "staged_files": {"type": "array", "items": {"type": "string"}},
                            "unstaged_files": {"type": "array", "items": {"type": "string"}},
                            "untracked_files": {"type": "array", "items": {"type": "string"}},
                            "recent_commits": {"type": "array", "items": {"type": "object"}},
                            "evidence_ids": {"type": "array", "items": {"type": "string"}}
                        }
                    },
                    "test_results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["test_id", "name", "suite", "status", "exit_code", "duration_ms"],
                            "properties": {
                                "test_id": {"type": "string"},
                                "name": {"type": "string"},
                                "suite": {"type": "string"},
                                "status": {"type": "string", "enum": [s.value for s in Status]},
                                "exit_code": {"type": "integer"},
                                "duration_ms": {"type": "number"},
                                "output_snippet": {"type": "string"},
                                "error_message": {"type": ["string", "null"]},
                                "evidence_id": {"type": ["string", "null"]}
                            }
                        }
                    },
                    "build_status": {"type": "string", "enum": [s.value for s in Status]},
                    "todo_markers": {"type": "array", "items": {"type": "object"}},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "last_scanned_at": {"type": "string"}
                }
            },

            # 2. Conversational State
            "conversational_state": {
                "type": "object",
                "required": ["session_id", "user_requirements", "architectural_decisions", "agent_claims", "assumptions", "unresolved_questions", "transcript_provenance"],
                "properties": {
                    "session_id": {"type": "string"},
                    "user_requirements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "title", "description", "status"],
                            "properties": {
                                "id": {"type": "string"},
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "source_turn": {"type": ["integer", "null"]},
                                "status": {"type": "string", "enum": [s.value for s in Status]},
                                "evidence_id": {"type": ["string", "null"]}
                            }
                        }
                    },
                    "architectural_decisions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "title", "rationale", "constraints", "recorded_at"],
                            "properties": {
                                "id": {"type": "string"},
                                "title": {"type": "string"},
                                "rationale": {"type": "string"},
                                "constraints": {"type": "array", "items": {"type": "string"}},
                                "recorded_at": {"type": "string"},
                                "evidence_id": {"type": ["string", "null"]}
                            }
                        }
                    },
                    "agent_claims": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "claim_text", "claimed_status", "source_agent"],
                            "properties": {
                                "id": {"type": "string"},
                                "claim_text": {"type": "string"},
                                "target_component": {"type": ["string", "null"]},
                                "claimed_status": {"type": "string", "enum": [s.value for s in Status]},
                                "source_agent": {"type": "string"},
                                "turn_id": {"type": ["integer", "null"]},
                                "confidence_claimed": {"type": ["number", "null"]},
                                "evidence_id": {"type": ["string", "null"]}
                            }
                        }
                    },
                    "assumptions": {"type": "array", "items": {"type": "string"}},
                    "unresolved_questions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "question", "context", "blocking", "asked_at"],
                            "properties": {
                                "id": {"type": "string"},
                                "question": {"type": "string"},
                                "context": {"type": "string"},
                                "blocking": {"type": "boolean"},
                                "asked_at": {"type": "string"},
                                "evidence_id": {"type": ["string", "null"]}
                            }
                        }
                    },
                    "transcript_provenance": {"type": "array", "items": {"type": "string"}}
                }
            },

            # 3. Agent Execution State
            "agent_execution_state": {
                "type": "object",
                "required": ["agent_id", "model_name", "active_tasks", "modified_files_in_flight", "last_error_encountered", "next_action", "execution_context_metadata", "updated_at"],
                "properties": {
                    "agent_id": {"type": "string"},
                    "model_name": {"type": "string"},
                    "active_tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "title", "status", "target_files", "target_symbols", "notes"],
                            "properties": {
                                "id": {"type": "string"},
                                "title": {"type": "string"},
                                "status": {"type": "string", "enum": [s.value for s in Status]},
                                "target_files": {"type": "array", "items": {"type": "string"}},
                                "target_symbols": {"type": "array", "items": {"type": "string"}},
                                "notes": {"type": "string"}
                            }
                        }
                    },
                    "modified_files_in_flight": {"type": "array", "items": {"type": "string"}},
                    "last_error_encountered": {"type": ["string", "null"]},
                    "next_action": {
                        "type": ["object", "null"],
                        "properties": {
                            "action_type": {"type": "string"},
                            "target_uri": {"type": "string"},
                            "description": {"type": "string"},
                            "prerequisites": {"type": "array", "items": {"type": "string"}}
                        }
                    },
                    "execution_context_metadata": {"type": "object"},
                    "updated_at": {"type": "string"}
                }
            },

            # Global Evidence Pool
            "evidence_pool": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "required": ["id", "type", "level", "summary", "raw_payload", "checksum", "created_at"],
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string", "enum": [e.value for e in EvidenceType]},
                        "level": {"type": "integer", "enum": [int(l.value) for l in EvidenceLevel]},
                        "summary": {"type": "string"},
                        "raw_payload": {"type": "object"},
                        "provenance": {
                            "type": ["object", "null"],
                            "properties": {
                                "extractor_name": {"type": "string"},
                                "source_uri": {"type": "string"},
                                "locator": {"type": "string"},
                                "collected_at": {"type": "string"},
                                "environment_info": {"type": "object"}
                            }
                        },
                        "checksum": {"type": "string"},
                        "created_at": {"type": "string"},
                        "metadata": {"type": "object"}
                    }
                }
            },

            # Graph Nodes
            "graph_nodes": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "required": ["id", "name", "node_type", "status", "confidence_score", "evidence_ids"],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "node_type": {"type": "string", "enum": [n.value for n in NodeType]},
                        "status": {"type": "string", "enum": [s.value for s in Status]},
                        "confidence_score": {"type": "number", "minimum": 0.0, "maximum": 100.0},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "metadata": {"type": "object"}
                    }
                }
            },

            # Graph Edges
            "graph_edges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["source_id", "target_id", "relation"],
                    "properties": {
                        "source_id": {"type": "string"},
                        "target_id": {"type": "string"},
                        "relation": {"type": "string", "enum": [r.value for r in RelationType]}
                    }
                }
            },

            # Contradictions
            "contradictions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "severity", "claim_text", "explanation", "detected_at", "resolved"],
                    "properties": {
                        "id": {"type": "string"},
                        "severity": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
                        "claim_id": {"type": ["string", "null"]},
                        "claim_text": {"type": "string"},
                        "physical_evidence_id": {"type": ["string", "null"]},
                        "explanation": {"type": "string"},
                        "detected_at": {"type": "string"},
                        "resolved": {"type": "boolean"}
                    }
                }
            }
        }
    }


def validate_canonical_state_dict(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Lightweight validator that verifies dictionary structure against Canonical schema rules.
    Returns (is_valid, list_of_errors).
    """
    errors: List[str] = []

    # Required top level keys
    required_top = [
        "schema_version", "project_id", "created_at", "updated_at",
        "project_state", "conversational_state", "agent_execution_state",
        "evidence_pool", "graph_nodes", "graph_edges", "contradictions"
    ]
    for key in required_top:
        if key not in data:
            errors.append(f"Missing required top-level field: '{key}'")

    if errors:
        return False, errors

    # Check state separation
    if not isinstance(data.get("project_state"), dict):
        errors.append("'project_state' must be an object")
    if not isinstance(data.get("conversational_state"), dict):
        errors.append("'conversational_state' must be an object")
    if not isinstance(data.get("agent_execution_state"), dict):
        errors.append("'agent_execution_state' must be an object")

    # Validate statuses inside test_results
    for test in data.get("project_state", {}).get("test_results", []):
        st = test.get("status")
        if st not in [s.value for s in Status]:
            errors.append(f"Invalid TestResult status '{st}'")

    # Validate evidence pool
    for ev_id, ev in data.get("evidence_pool", {}).items():
        if not isinstance(ev, dict):
            errors.append(f"Evidence '{ev_id}' must be an object")
            continue
        ev_type = ev.get("type")
        if ev_type not in [e.value for e in EvidenceType]:
            errors.append(f"Invalid EvidenceType '{ev_type}' in evidence '{ev_id}'")
        ev_lvl = ev.get("level")
        if ev_lvl not in [int(l.value) for l in EvidenceLevel]:
            errors.append(f"Invalid EvidenceLevel '{ev_lvl}' in evidence '{ev_id}'")

    # Validate Graph Nodes
    for n_id, node in data.get("graph_nodes", {}).items():
        if not isinstance(node, dict):
            errors.append(f"GraphNode '{n_id}' must be an object")
            continue
        nt = node.get("node_type")
        if nt not in [n.value for n in NodeType]:
            errors.append(f"Invalid NodeType '{nt}' in node '{n_id}'")
        conf = node.get("confidence_score", 0.0)
        if not (0.0 <= conf <= 100.0):
            errors.append(f"Confidence score {conf} out of range [0, 100] in node '{n_id}'")

    # Validate Graph Edges
    for edge in data.get("graph_edges", []):
        rel = edge.get("relation")
        if rel not in [r.value for r in RelationType]:
            errors.append(f"Invalid RelationType '{rel}' in edge")

    return (len(errors) == 0, errors)
