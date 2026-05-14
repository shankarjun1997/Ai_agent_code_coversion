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
import os
from typing import Any, Dict, List, Optional

from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import (
    GraphEdge, GraphNode, MetadataGraph, StageStatus, TableScore,
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
            return [], [], [f"block:profile {profile_id!r} not found in registry"]

        dialect = profile.dialect
        provider = self._get_provider(dialect)
        if provider is None:
            return [], [], [f"block:no provider for dialect {dialect!r}"]

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
            notes.append(f"block:{profile_id}: list_schemas failed: {exc}")
            return nodes, edges, notes

        for schema_name in schemas:
            schema_id = _node_id(profile_id, schema_name)
            nodes.append(GraphNode(id=schema_id, kind="schema", label=schema_name, dialect=dialect))
            edges.append(GraphEdge(src=dialect_node_id, dst=schema_id, kind="contains"))

            try:
                tables = await provider.list_tables(profile, schema_name)
            except Exception as exc:
                notes.append(f"warn:{profile_id}.{schema_name}: list_tables failed: {exc}")
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
                    notes.append(f"warn:{profile_id}.{schema_name}.{tbl_name}: get_columns failed: {exc}")
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
                    notes.append(f"info:{profile_id}.{schema_name}.{tbl_name}: get_foreign_keys returned 0 (or failed: {exc})")

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
        profile_coverage: Dict[str, str] = {}

        registry = get_registry()
        for pid, result in zip(bb.selected_source_profiles, results):
            profile = registry.get(pid)
            dialect = profile.dialect if profile else "unknown"
            if isinstance(result, Exception):
                all_notes.append(f"block:{pid}: probe failed: {result}")
                profile_coverage[pid] = "failed"
                continue
            nodes, edges, notes = result
            all_nodes.extend(nodes)
            all_edges.extend(edges)
            all_notes.extend(notes)
            # Coverage method per profile
            if any("block:" in n and pid in n for n in notes):
                profile_coverage[pid] = "failed"
            else:
                profile_coverage[pid] = self._coverage_method(dialect)
                sources_probed.append(pid)

        # Ingest CSV attachments as synthetic source nodes so L3 can map against them
        csv_nodes, csv_edges, csv_notes = self._ingest_csv_attachments(bb, intent_keywords)
        all_nodes.extend(csv_nodes)
        all_edges.extend(csv_edges)
        all_notes.extend(csv_notes)
        if csv_nodes:
            sources_probed.append("csv:attachments")
            profile_coverage["csv:attachments"] = "inferred"

        # Crawl BQ target dataset and persist target_graph (consumed by L3/L4)
        target_graph = await self._crawl_bq_target(bb)
        if target_graph and target_graph.tables:
            t_nodes, t_edges = self._target_graph_to_nodes(target_graph)
            all_nodes.extend(t_nodes)
            all_edges.extend(t_edges)
            profile_coverage[f"bigquery:{target_graph.dataset}"] = "live"
        elif target_graph:
            profile_coverage[f"bigquery:{target_graph.dataset}"] = (
                "inferred" if target_graph.status == StageStatus.failed else "live"
            )

        # Sprint A: BQ-as-source for enhancement flow.
        # When intent_kind=enhance_existing AND the target table already exists in BQ,
        # promote its columns to source-side nodes so L3 can map "current target column"
        # → "new target column" rewrites grounded in the live BQ schema.
        if (
            getattr(bb.intent, "intent_kind", "new") == "enhance_existing"
            and target_graph and target_graph.tables
        ):
            src_nodes, src_edges, src_notes = self._promote_target_as_source(
                target_graph, bb.target_table, intent_keywords,
            )
            if src_nodes:
                all_nodes.extend(src_nodes)
                all_edges.extend(src_edges)
                all_notes.extend(src_notes)
                sources_probed.append(f"bq-source:{bb.target_table}")
                profile_coverage[f"bq-source:{bb.target_table}"] = "live"

        # Score source tables for Gate 1 ranking
        table_scores = self._score_tables(all_nodes, all_edges, intent_keywords)

        graph = MetadataGraph(
            nodes=all_nodes,
            edges=all_edges,
            sources_probed=sources_probed,
            coverage_notes=all_notes,
            status=StageStatus.ready,
            profile_coverage=profile_coverage,
            table_scores=table_scores,
        )

        updates: Dict[str, Any] = {"metadata_graph": graph, "current_stage": "L3"}
        if target_graph is not None:
            updates["target_graph"] = target_graph
        return BlackboardDelta(updates=updates)

    @staticmethod
    def _coverage_method(dialect: str) -> str:
        """Map dialect → resolution method label shown in Gate 1."""
        if dialect == "bigquery":
            return "information_schema"
        if dialect in ("postgres", "mysql", "mssql", "oracle"):
            return "live"
        if dialect == "csv":
            return "inferred"
        return "unknown"

    @staticmethod
    def _score_tables(
        nodes: List[GraphNode],
        edges: List[GraphEdge],
        intent_keywords: List[str],
    ) -> List[TableScore]:
        """Aggregate per-table relevance: keyword hits in name + concept_link
        edges from contained columns + FK density + row count."""
        kw_lower = [(k or "").lower() for k in intent_keywords if k]
        # Build table → cols, table → fk count
        cols_of: Dict[str, List[GraphNode]] = {}
        for n in nodes:
            if n.kind != "column":
                continue
            tbl_id = ".".join(n.id.split(".")[:-1])
            cols_of.setdefault(tbl_id, []).append(n)
        fk_count: Dict[str, int] = {}
        concept_hits: Dict[str, List[str]] = {}
        for e in edges:
            if e.kind == "fk":
                tbl_id = ".".join(e.src.split(".")[:-1])
                fk_count[tbl_id] = fk_count.get(tbl_id, 0) + 1
            elif e.kind == "concept_link":
                tbl_id = ".".join(e.src.split(".")[:-1])
                concept_hits.setdefault(tbl_id, []).append(e.evidence or "")
        scores: List[TableScore] = []
        for n in nodes:
            if n.kind != "table":
                continue
            tbl_id = n.id
            label = n.label or tbl_id
            score = 0.0
            evidence: List[str] = []
            # Name match against intent keywords (worth a lot)
            for kw in kw_lower:
                if kw and (kw in label.lower() or label.lower() in kw):
                    score += 0.45
                    evidence.append(f"name match: {kw}")
                    break
            # Column concept_link hits
            hits = concept_hits.get(tbl_id, [])
            if hits:
                score += min(0.4, 0.1 * len(hits))
                evidence.append(f"{len(hits)} col concept hits")
            # FK density (well-connected tables are usually relevant)
            fks = fk_count.get(tbl_id, 0)
            if fks:
                score += min(0.15, 0.03 * fks)
                evidence.append(f"{fks} FKs")
            row_est = (n.profile or {}).get("row_count") if n.profile else None
            scores.append(TableScore(
                table_id=tbl_id,
                label=label,
                dialect=n.dialect or "unknown",
                score=round(min(score, 1.0), 3),
                evidence=evidence,
                column_hits=len(hits),
                row_estimate=row_est,
            ))
        # Sort high → low
        scores.sort(key=lambda s: s.score, reverse=True)
        return scores

    def _promote_target_as_source(
        self,
        target_graph,
        target_table_name: str,
        intent_keywords: List[str],
    ) -> tuple[List[GraphNode], List[GraphEdge], List[str]]:
        """Treat the existing BQ target table as a source. Used in enhancement
        mode so L3 can map "old target column" → "rewritten target column"."""
        nodes: List[GraphNode] = []
        edges: List[GraphEdge] = []
        notes: List[str] = []
        tbl = next((t for t in target_graph.tables if t.name == target_table_name), None)
        if not tbl:
            notes.append(
                f"info:enhancement: target table {target_graph.dataset}.{target_table_name} "
                f"not found in BQ — treating as new (no source promotion)."
            )
            return nodes, edges, notes
        dialect_id = _node_id("bq-source")
        nodes.append(GraphNode(id=dialect_id, kind="dialect", label="bq-source", dialect="bigquery"))
        schema_id = _node_id("bq-source", target_graph.dataset)
        nodes.append(GraphNode(id=schema_id, kind="schema", label=target_graph.dataset, dialect="bigquery"))
        edges.append(GraphEdge(src=dialect_id, dst=schema_id, kind="contains"))
        tbl_id = _node_id("bq-source", target_graph.dataset, tbl.name)
        nodes.append(GraphNode(
            id=tbl_id, kind="table", label=tbl.name, dialect="bigquery",
            profile={"row_count": tbl.row_count} if tbl.row_count is not None else None,
        ))
        edges.append(GraphEdge(src=schema_id, dst=tbl_id, kind="contains"))
        for col in (tbl.columns or []):
            col_id = _node_id("bq-source", target_graph.dataset, tbl.name, col.get("name", ""))
            nodes.append(GraphNode(
                id=col_id, kind="column", label=col.get("name", ""), dialect="bigquery",
                data_type=col.get("type", "STRING"),
                nullable=col.get("mode", "NULLABLE") != "REQUIRED",
            ))
            edges.append(GraphEdge(src=tbl_id, dst=col_id, kind="contains"))
            col_lower = (col.get("name") or "").lower()
            for kw in intent_keywords:
                if kw and (kw.lower() in col_lower or col_lower in kw.lower()):
                    edges.append(GraphEdge(
                        src=col_id, dst=_node_id("concept", kw),
                        kind="concept_link", confidence=0.85,
                        evidence=f"baseline target column ({kw})",
                    ))
        notes.append(
            f"info:enhancement: promoted {len(tbl.columns or [])} BQ columns from "
            f"{target_graph.dataset}.{tbl.name} as source (baseline)."
        )
        return nodes, edges, notes

    def _ingest_csv_attachments(
        self,
        bb,
        intent_keywords: List[str],
    ) -> tuple[List[GraphNode], List[GraphEdge], List[str]]:
        """Promote each CSV attachment to a virtual table + column nodes."""
        nodes: List[GraphNode] = []
        edges: List[GraphEdge] = []
        notes: List[str] = []
        attachments = getattr(bb, "attachments", None) or []
        csv_atts = [a for a in attachments if a.kind == "csv" and a.csv_schema]
        if not csv_atts:
            return nodes, edges, notes
        dialect_id = _node_id("csv")
        nodes.append(GraphNode(id=dialect_id, kind="dialect", label="csv", dialect="csv"))
        for att in csv_atts:
            schema_id = _node_id("csv", att.id)
            tbl_label = (att.filename or att.id).rsplit(".", 1)[0]
            nodes.append(GraphNode(id=schema_id, kind="schema", label="uploaded", dialect="csv"))
            edges.append(GraphEdge(src=dialect_id, dst=schema_id, kind="contains"))
            tbl_id = _node_id("csv", att.id, tbl_label)
            nodes.append(GraphNode(id=tbl_id, kind="table", label=tbl_label, dialect="csv"))
            edges.append(GraphEdge(src=schema_id, dst=tbl_id, kind="contains"))
            for col in (att.csv_schema or {}).get("columns", []):
                col_id = _node_id("csv", att.id, tbl_label, col["name"])
                nodes.append(GraphNode(
                    id=col_id, kind="column", label=col["name"], dialect="csv",
                    data_type=col.get("type", "STRING"), nullable=True,
                    profile={"samples": col.get("samples", [])},
                ))
                edges.append(GraphEdge(src=tbl_id, dst=col_id, kind="contains"))
                col_lower = col["name"].lower()
                for kw in intent_keywords:
                    if kw and (kw.lower() in col_lower or col_lower in kw.lower()):
                        edges.append(GraphEdge(
                            src=col_id, dst=_node_id("concept", kw),
                            kind="concept_link", confidence=0.7,
                            evidence=f"keyword:{kw}",
                        ))
            notes.append(f"csv:{att.filename} → {len((att.csv_schema or {}).get('columns', []))} columns")
        return nodes, edges, notes

    async def _crawl_bq_target(self, bb):
        """Discover the target BQ dataset schema. Populates BqTargetGraph."""
        from core.stm.blackboard import BqTargetGraph, BqTargetTable
        from datetime import datetime, timezone
        from core.discovery import get_registry as _reg

        registry = _reg()
        bq_profile = None
        for pid in bb.selected_source_profiles:
            p = registry.get(pid)
            if p and p.dialect == "bigquery":
                bq_profile = p
                break

        project_id = (bq_profile.dsn if bq_profile else os.environ.get("BQ_PROJECT_ID", "")) or ""
        if not project_id:
            return BqTargetGraph(project_id="", dataset=bb.target_dataset, status=StageStatus.failed)

        graph = BqTargetGraph(project_id=project_id, dataset=bb.target_dataset, status=StageStatus.running)
        try:
            from core import bq_cli
            crawl = await asyncio.to_thread(
                bq_cli.crawl_project, project_id, bb.target_dataset,
            )
            datasets = crawl.get("datasets", {}) if isinstance(crawl, dict) else {}
            ds = datasets.get(bb.target_dataset) or {}
            for tbl_name, tbl_info in (ds.get("tables", {}) or {}).items():
                cols = []
                for c in (tbl_info.get("schema", []) or []):
                    cols.append({
                        "name": c.get("name"),
                        "type": c.get("type", "STRING"),
                        "mode": c.get("mode", "NULLABLE"),
                        "description": c.get("description"),
                    })
                graph.tables.append(BqTargetTable(
                    name=tbl_name,
                    columns=cols,
                    row_count=tbl_info.get("num_rows"),
                    last_modified=tbl_info.get("last_modified"),
                ))
            graph.status = StageStatus.ready
            graph.fetched_at = datetime.now(timezone.utc)
        except Exception as exc:
            logger.warning("BQ target crawl failed for %s.%s: %s", project_id, bb.target_dataset, exc)
            graph.status = StageStatus.failed
        return graph

    def _target_graph_to_nodes(self, target_graph):
        """Render BqTargetGraph as graph nodes so cytoscape view can show source+target."""
        nodes: List[GraphNode] = []
        edges: List[GraphEdge] = []
        dialect_id = _node_id("bigquery")
        nodes.append(GraphNode(id=dialect_id, kind="dialect", label="bigquery", dialect="bigquery"))
        schema_id = _node_id("bigquery", target_graph.dataset or "target")
        nodes.append(GraphNode(id=schema_id, kind="schema", label=target_graph.dataset or "target", dialect="bigquery"))
        edges.append(GraphEdge(src=dialect_id, dst=schema_id, kind="contains"))
        for tbl in target_graph.tables:
            tbl_id = _node_id("bigquery", target_graph.dataset, tbl.name)
            nodes.append(GraphNode(
                id=tbl_id, kind="table", label=tbl.name, dialect="bigquery",
                profile={"row_count": tbl.row_count} if tbl.row_count is not None else None,
            ))
            edges.append(GraphEdge(src=schema_id, dst=tbl_id, kind="contains"))
            for col in tbl.columns:
                col_id = _node_id("bigquery", target_graph.dataset, tbl.name, col.get("name", ""))
                nodes.append(GraphNode(
                    id=col_id, kind="column", label=col.get("name", ""), dialect="bigquery",
                    data_type=col.get("type", "STRING"),
                    nullable=col.get("mode", "NULLABLE") != "REQUIRED",
                ))
                edges.append(GraphEdge(src=tbl_id, dst=col_id, kind="contains"))
        return nodes, edges
