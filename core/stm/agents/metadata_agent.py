"""L2 Metadata Intelligence Agent.

Probes all selected_source_profiles in parallel, builds a MetadataGraph
(nodes + edges) representing the source schema topology.

Discovery strategy
------------------
1. For each profile, use its SourceProvider to list schemas → tables → columns.
2. Build GraphNodes for dialect / schema / table / column levels.
3. Add FK edges from get_foreign_keys().
4. Mark keyword-matched columns with concept_link edges using intent keywords.
5. Falls back to a deterministic skeleton when providers fail (coverage_notes logs the error).

Rules-as-floor: graph is always built deterministically from provider data;
no LLM calls in this agent.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import (
    GraphEdge, GraphNode, MetadataGraph, StageStatus,
)
from core.discovery import get_registry

logger = logging.getLogger(__name__)


def _node_id(*parts: str) -> str:
    return ".".join(p.lower() for p in parts if p)


class MetadataAgent(StmAgent):
    """L2 — probes source systems and builds MetadataGraph."""

    stage = "L2"

    def __init__(self, provider_factory=None) -> None:
        """
        provider_factory: callable(profile_id, dialect) → SourceProvider
        If None, uses core.discovery.get_provider.
        """
        self._provider_factory = provider_factory

    def _get_provider(self, dialect: str):
        if self._provider_factory is not None:
            return self._provider_factory(dialect)
        from core.discovery.registry import get_provider
        return get_provider(dialect)

    async def _probe_profile(
        self,
        profile_id: str,
        intent_keywords: List[str],
    ) -> tuple[List[GraphNode], List[GraphEdge], List[str]]:
        """Probe a single profile. Returns (nodes, edges, coverage_notes)."""
        registry = get_registry()
        profile = registry.get(profile_id)
        if profile is None:
            return [], [], [f"profile {profile_id!r} not found in registry"]

        dialect = profile.dialect
        provider = self._get_provider(dialect)
        if provider is None:
            return [], [], [f"no provider for dialect {dialect!r}"]

        nodes: List[GraphNode] = []
        edges: List[GraphEdge] = []
        notes: List[str] = []

        # Dialect node
        dialect_node_id = _node_id(dialect)
        nodes.append(GraphNode(id=dialect_node_id, kind="dialect", label=dialect, dialect=dialect))

        try:
            schemas_raw = await provider.list_schemas(profile)
            # Normalise: providers may return List[str] or List[SchemaInfo]
            schemas = [s if isinstance(s, str) else s.name for s in schemas_raw]
        except Exception as exc:
            notes.append(f"{profile_id}: list_schemas failed: {exc}")
            return nodes, edges, notes

        for schema_name in schemas:
            schema_id = _node_id(profile_id, schema_name)
            nodes.append(GraphNode(id=schema_id, kind="schema", label=schema_name, dialect=dialect))
            edges.append(GraphEdge(src=dialect_node_id, dst=schema_id, kind="contains"))

            try:
                tables = await provider.list_tables(profile, schema_name)
            except Exception as exc:
                notes.append(f"{profile_id}.{schema_name}: list_tables failed: {exc}")
                continue

            for tbl in tables:
                tbl_name = tbl.name if hasattr(tbl, "name") else str(tbl)
                tbl_id = _node_id(profile_id, schema_name, tbl_name)
                nodes.append(GraphNode(
                    id=tbl_id, kind="table", label=tbl_name, dialect=dialect,
                ))
                edges.append(GraphEdge(src=schema_id, dst=tbl_id, kind="contains"))

                try:
                    cols = await provider.get_columns(profile, schema_name, tbl_name)
                except Exception as exc:
                    notes.append(f"{profile_id}.{schema_name}.{tbl_name}: get_columns failed: {exc}")
                    cols = []

                for col in cols:
                    col_name = col.name if hasattr(col, "name") else str(col)
                    col_type = col.data_type if hasattr(col, "data_type") else "unknown"
                    nullable = col.nullable if hasattr(col, "nullable") else True
                    col_id = _node_id(profile_id, schema_name, tbl_name, col_name)
                    nodes.append(GraphNode(
                        id=col_id, kind="column", label=col_name, dialect=dialect,
                        data_type=col_type, nullable=nullable,
                    ))
                    edges.append(GraphEdge(src=tbl_id, dst=col_id, kind="contains"))

                    # concept_link for keyword matches
                    col_lower = col_name.lower()
                    for kw in intent_keywords:
                        if kw.lower() in col_lower or col_lower in kw.lower():
                            edges.append(GraphEdge(
                                src=col_id,
                                dst=_node_id("concept", kw),
                                kind="concept_link",
                                confidence=0.7,
                                evidence=f"keyword:{kw}",
                            ))

                # FK edges
                try:
                    fks = await provider.get_foreign_keys(profile, schema_name, tbl_name)
                    for fk in fks:
                        src_col_id = _node_id(profile_id, schema_name, tbl_name, fk.column)
                        dst_col_id = _node_id(profile_id, fk.ref_schema, fk.ref_table, fk.ref_column)
                        edges.append(GraphEdge(
                            src=src_col_id, dst=dst_col_id, kind="fk",
                            confidence=1.0,
                            evidence=fk.constraint_name or "fk",
                        ))
                except Exception as exc:
                    notes.append(f"{profile_id}.{schema_name}.{tbl_name}: get_foreign_keys failed: {exc}")

        return nodes, edges, notes

    async def _execute(self, ctx: AgentContext) -> BlackboardDelta:
        bb = ctx.blackboard
        intent_keywords = bb.intent.extracted_keywords or [bb.intent.entity] if bb.intent.entity else []

        # Probe all profiles in parallel
        tasks = [
            self._probe_profile(pid, intent_keywords)
            for pid in bb.selected_source_profiles
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_nodes: List[GraphNode] = []
        all_edges: List[GraphEdge] = []
        all_notes: List[str] = []
        sources_probed: List[str] = []

        for pid, result in zip(bb.selected_source_profiles, results):
            if isinstance(result, Exception):
                all_notes.append(f"{pid}: probe failed: {result}")
            else:
                nodes, edges, notes = result
                all_nodes.extend(nodes)
                all_edges.extend(edges)
                all_notes.extend(notes)
                # Only count as probed if we got at least some schema data
                had_error = any(pid in n for n in notes if "not found" in n or "failed" in n)
                if not had_error:
                    sources_probed.append(pid)

        graph = MetadataGraph(
            nodes=all_nodes,
            edges=all_edges,
            sources_probed=sources_probed,
            coverage_notes=all_notes,
            status=StageStatus.ready,
        )

        return BlackboardDelta(
            updates={"metadata_graph": graph, "current_stage": "L3"},
        )
