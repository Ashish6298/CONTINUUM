"""
Project Continuum - Dependency Invalidation & Propagation Engine
================================================================
Milestone 4 - Phase 10: Dependency Invalidation & Status Propagation.
Handles:
1. Identifying affected downstream components when an upstream node changes.
2. Propagating BLOCKED when a critical prerequisite fails.
3. Propagating STALE when upstream evidence is modified (without falsely marking FAILED).
4. Discovering unresolved dependencies.
5. Determining next actionable work and generating concrete next actions.
"""

from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

from core.enums import NodeType, RelationType, Status
from core.state_models import (
    GraphEdge,
    GraphNode,
    NextActionRecommendation,
)
from graph.models import PropagationResult


class DependencyPropagator:
    """
    Executes precise invalidation and status propagation through the Canonical State Graph.
    """

    CRITICAL_DEPENDENCY_RELATIONS = {
        RelationType.DEPENDS_ON,
        RelationType.REQUIRES,
        RelationType.BLOCKS,
    }

    def __init__(self, manager: Any):
        self._manager = manager

    def propagate_change(
        self,
        changed_node_id: str,
        new_status: Optional[Status] = None,
        reason: str = "upstream_change"
    ) -> PropagationResult:
        """
        Propagates status updates to all affected downstream components.
        - If upstream node is FAILED -> critical dependents become BLOCKED.
        - If upstream node is modified/STALE/IN_PROGRESS -> dependents become STALE.
        - Avoids incorrectly marking components FAILED when they are only affected.
        """
        changed_node = self._manager.get_node(changed_node_id)
        if not changed_node:
            return PropagationResult(
                changed_node_id=changed_node_id,
                explanation=f"Node '{changed_node_id}' does not exist in graph."
            )

        if new_status:
            changed_node.status = new_status

        result = PropagationResult(changed_node_id=changed_node_id)
        
        # Traverse downstream dependents in topological / BFS order
        queue: deque = deque([changed_node_id])
        visited: Set[str] = set()

        while queue:
            curr_id = queue.popleft()
            curr_node = self._manager.get_node(curr_id)
            if not curr_node:
                continue

            # Check incoming edges to find who depends on curr_id
            for edge in self._manager._in_edges.get(curr_id, []):
                dep_id = edge.source_id
                dep_node = self._manager.get_node(dep_id)
                if not dep_node:
                    continue

                if dep_id not in visited:
                    visited.add(dep_id)
                    result.affected_node_ids.append(dep_id)

                    # Determine appropriate status based on upstream condition & relationship
                    if curr_node.status == Status.FAILED and edge.relation in self.CRITICAL_DEPENDENCY_RELATIONS:
                        dep_node.status = Status.BLOCKED
                        result.blocked_node_ids.append(dep_id)
                    else:
                        # Only mark STALE if it was previously VERIFIED or UNKNOWN; preserve FAILED/BLOCKED if existing
                        if dep_node.status in {Status.VERIFIED, Status.UNKNOWN, Status.PARTIAL}:
                            dep_node.status = Status.STALE
                            result.stale_node_ids.append(dep_id)

                    # Record unresolved prerequisites
                    unresolved = self.get_unresolved_dependencies(dep_id)
                    if unresolved:
                        result.unresolved_prerequisites[dep_id] = [u.id for u in unresolved]

                    queue.append(dep_id)

        # Build explanation
        stale_count = len(result.stale_node_ids)
        blocked_count = len(result.blocked_node_ids)
        result.explanation = (
            f"Propagated change from '{changed_node.name}' ({changed_node.status.value}): "
            f"{blocked_count} node(s) BLOCKED, {stale_count} node(s) marked STALE."
        )

        return result

    def get_unresolved_dependencies(self, node_id: str) -> List[GraphNode]:
        """
        Returns all direct upstream dependencies of `node_id` that are NOT yet VERIFIED.
        """
        direct_deps = self._manager.get_dependencies(node_id, recursive=False)
        return [d for d in direct_deps if d.status != Status.VERIFIED]

    def determine_next_actionable_nodes(self) -> List[GraphNode]:
        """
        Identifies unblocked graph nodes ready for execution:
        - Nodes whose upstream dependencies are 100% VERIFIED or have zero dependencies.
        - Nodes whose current status is PENDING, STALE, or IN_PROGRESS (not VERIFIED or BLOCKED).
        """
        actionable: List[GraphNode] = []

        for node in self._manager.nodes.values():
            if node.status in {Status.VERIFIED, Status.FAILED, Status.BLOCKED}:
                continue

            unresolved = self.get_unresolved_dependencies(node.id)
            if not unresolved:
                actionable.append(node)

        # Sort deterministically: Tasks first, then APIs/Components, then Requirements
        type_priority = {
            NodeType.TASK: 1,
            NodeType.TEST: 2,
            NodeType.API: 3,
            NodeType.COMPONENT: 4,
            NodeType.SERVICE: 5,
            NodeType.MODULE: 6,
            NodeType.REQUIREMENT: 7,
            NodeType.PHASE: 8,
            NodeType.MILESTONE: 9,
        }
        actionable.sort(key=lambda n: (type_priority.get(n.node_type, 10), n.id))
        return actionable

    def recommend_next_action(self) -> Optional[NextActionRecommendation]:
        """
        Synthesizes a concrete, actionable recommendation for the AI agent or developer.
        """
        actionable_nodes = self.determine_next_actionable_nodes()

        # If there are blocked or failed nodes with clear blockers, check those
        failed_nodes = [n for n in self._manager.nodes.values() if n.status == Status.FAILED]
        if failed_nodes:
            target = failed_nodes[0]
            return NextActionRecommendation(
                action_type="FIX_FAILED_COMPONENT",
                target_uri=target.id,
                description=f"Fix failing component '{target.name}' to unblock downstream dependencies.",
                prerequisites=[]
            )

        if not actionable_nodes:
            # Check if everything is VERIFIED
            unverified_nodes = [n for n in self._manager.nodes.values() if n.status != Status.VERIFIED]
            if not unverified_nodes:
                return NextActionRecommendation(
                    action_type="COMPLETE_PROJECT",
                    target_uri="project_root",
                    description="All graph nodes are VERIFIED. Ready for milestone handoff.",
                    prerequisites=[]
                )
            return None

        primary_target = actionable_nodes[0]
        action_type_map = {
            NodeType.TEST: "RUN_TEST",
            NodeType.TASK: "EXECUTE_TASK",
            NodeType.COMPONENT: "IMPLEMENT_COMPONENT",
            NodeType.SERVICE: "IMPLEMENT_SERVICE",
            NodeType.API: "IMPLEMENT_API",
            NodeType.REQUIREMENT: "SATISFY_REQUIREMENT",
        }

        act_type = action_type_map.get(primary_target.node_type, "WORK_ON_NODE")
        return NextActionRecommendation(
            action_type=act_type,
            target_uri=primary_target.id,
            description=f"Execute unblocked {primary_target.node_type.value} '{primary_target.name}'.",
            prerequisites=[d.id for d in self._manager.get_dependencies(primary_target.id, recursive=False)]
        )
