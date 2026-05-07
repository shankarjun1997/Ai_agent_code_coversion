"""Agent 3 — Engineering Orchestrator.

Manages all sub-agents (3a–3e), runs them in parallel where possible,
then packages outputs into a consolidated EngineeringPackage for engineer review.
Assigned to: Pradeep / Chirag / Rahul / Dinesh
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from agents.agent_3a_sql_gen     import SQLGeneratorAgent
from agents.agent_3b_code_conv   import CodeConversionAgent
from agents.agent_3c_dq          import DQAgent
from agents.agent_3d_observability import ObservabilityAgent
from agents.agent_3e_metadata    import MetadataAgent
from agents.shared.github_client import GitHubClient
from core.bq_client              import BQClient
from core.llm_client             import LLMClient
from core.schemas                import (
    DataMapping,
    EngineeringPackage,
    GeneratedArtifact,
    OutputType,
)

logger = logging.getLogger(__name__)


class EngineeringOrchestrator:
    def __init__(
        self,
        llm:         LLMClient,
        bq:          BQClient,
        github:      Optional[GitHubClient] = None,
        legacy_code: Optional[str] = None,         # for 3b
        legacy_dialect: Optional[str] = None,
    ):
        self.sql_gen     = SQLGeneratorAgent(llm, bq)
        self.code_conv   = CodeConversionAgent(llm)
        self.dq_agent    = DQAgent(llm)
        self.obs_agent   = ObservabilityAgent(llm)
        self.meta_agent  = MetadataAgent(llm)
        self.github      = github
        self.legacy_code = legacy_code
        self.legacy_dialect = legacy_dialect or "teradata"

    def run(self, mapping: DataMapping) -> EngineeringPackage:
        """
        Execute all sub-agents in parallel, collect results into a package.
        """
        pkg = EngineeringPackage(jira_issue=mapping.jira_issue)

        # Run 3c, 3d, 3e in parallel; 3a sequentially before 3b (3a output informs 3b)
        with ThreadPoolExecutor(max_workers=4) as pool:
            fut_sql = pool.submit(self.sql_gen.run, mapping)
            fut_dq  = pool.submit(self.dq_agent.run, mapping)
            fut_obs = pool.submit(self.obs_agent.run, mapping)
            fut_meta= pool.submit(self.meta_agent.run, mapping)

            # Wait for SQL first, then optionally run code conversion
            try:
                sql_artifacts = fut_sql.result()
                pkg.artifacts.extend(sql_artifacts)
                logger.info("3a: %d SQL artifacts", len(sql_artifacts))
            except Exception as exc:
                logger.error("3a SQL generation failed: %s", exc)
                pkg.artifacts.append(GeneratedArtifact(
                    artifact_type=OutputType.SQL_QUERY,
                    filename="error.txt",
                    content=str(exc),
                    explanation="SQL generation failed",
                ))

            try:
                pkg.dq_report = fut_dq.result()
                logger.info("3c: %d DQ rules", len(pkg.dq_report.rules))
            except Exception as exc:
                logger.error("3c DQ failed: %s", exc)

            try:
                pkg.observability = fut_obs.result()
                logger.info("3d: observability config ready")
            except Exception as exc:
                logger.error("3d observability failed: %s", exc)

            try:
                pkg.metadata = fut_meta.result()
                logger.info("3e: metadata ready — %d cols", len(pkg.metadata.column_descriptions))
            except Exception as exc:
                logger.error("3e metadata failed: %s", exc)

        # 3b: code conversion (only if legacy code provided)
        if self.legacy_code:
            try:
                conv_artifact = self.code_conv.convert(
                    legacy_code=self.legacy_code,
                    source_dialect=self.legacy_dialect,
                    jira_issue=mapping.jira_issue,
                )
                pkg.artifacts.append(conv_artifact)
                logger.info("3b: code conversion complete")
            except Exception as exc:
                logger.error("3b code conversion failed: %s", exc)

        # Add metadata DDL and observability patches as artifacts
        if pkg.metadata:
            ddl = self.meta_agent.to_bq_update_sql(pkg.metadata)
            pkg.artifacts.append(GeneratedArtifact(
                artifact_type=OutputType.SQL_DDL,
                filename=f"metadata_update_{mapping.target_table}.sql",
                content=ddl,
                explanation="ALTER TABLE statements to set column/table descriptions",
            ))
            dataplex_yaml = self.meta_agent.to_dataplex_yaml(pkg.metadata)
            pkg.artifacts.append(GeneratedArtifact(
                artifact_type=OutputType.PYTHON_SCRIPT,
                filename=f"dataplex_tags_{mapping.target_table}.yaml",
                content=dataplex_yaml,
                explanation="Dataplex tag attachment YAML",
            ))

        if pkg.observability:
            obs_hook = self.obs_agent.generate_python_logging_hook(mapping)
            pkg.artifacts.append(GeneratedArtifact(
                artifact_type=OutputType.PYTHON_SCRIPT,
                filename=f"logging_{mapping.target_table}.py",
                content=obs_hook,
                explanation="Structured logging hooks for Cloud Logging",
            ))
            audit_ddl = self.obs_agent.generate_audit_ddl_patch(mapping, pkg.observability)
            if audit_ddl.strip():
                pkg.artifacts.append(GeneratedArtifact(
                    artifact_type=OutputType.SQL_DDL,
                    filename=f"audit_columns_{mapping.target_table}.sql",
                    content=audit_ddl,
                    explanation="ALTER TABLE to add audit columns",
                ))

        if pkg.dq_report:
            pkg.artifacts.append(GeneratedArtifact(
                artifact_type=OutputType.DATAFORM_SQLX,
                filename=f"dq_assertions_{mapping.target_table}.yaml",
                content=pkg.dq_report.dataform_yaml or "",
                explanation="Dataform assertions YAML",
            ))
            if pkg.dq_report.bq_procedure:
                pkg.artifacts.append(GeneratedArtifact(
                    artifact_type=OutputType.STORED_PROCEDURE,
                    filename=f"sp_dq_{mapping.target_table}.sql",
                    content=pkg.dq_report.bq_procedure,
                    explanation="BigQuery DQ stored procedure",
                ))

        # Create GitHub PR if client is configured
        if self.github:
            try:
                artifact_files = [
                    {"filename": a.filename, "content": a.content}
                    for a in pkg.artifacts
                ]
                pr_body = self._build_pr_body(mapping, pkg)
                pr_url = self.github.publish_artifacts(
                    jira_issue=mapping.jira_issue,
                    artifacts=artifact_files,
                    pr_title=f"feat({mapping.jira_issue}): {mapping.target_table} pipeline",
                    pr_body=pr_body,
                )
                pkg.github_pr_url = pr_url
                logger.info("GitHub PR: %s", pr_url)
            except Exception as exc:
                logger.error("GitHub PR creation failed: %s", exc)

        logger.info(
            "Agent 3 package complete: %d artifacts, DQ=%s, Obs=%s, Meta=%s, PR=%s",
            len(pkg.artifacts),
            bool(pkg.dq_report),
            bool(pkg.observability),
            bool(pkg.metadata),
            pkg.github_pr_url or "not created",
        )
        return pkg

    def _build_pr_body(self, mapping: DataMapping, pkg: EngineeringPackage) -> str:
        artifact_list = "\n".join(
            f"- `{a.filename}` — {a.explanation}"
            + (f" (dry-run: {'✓' if a.dry_run_valid else '✗'})" if a.dry_run_valid is not None else "")
            for a in pkg.artifacts
        )
        dq_count = len(pkg.dq_report.rules) if pkg.dq_report else 0
        return f"""## Engineering Package — {mapping.jira_issue}

**Target:** `{mapping.target_dataset}.{mapping.target_table}`
**Mapping ID:** {mapping.mapping_id}
**Idempotency:** {mapping.idempotency_strategy.value} on `{mapping.idempotency_key}`

### Artifacts
{artifact_list}

### Sub-agent Summary
| Agent | Status |
|-------|--------|
| 3a SQL Generation | {'✓' if any(a.artifact_type in (OutputType.SQL_VIEW, OutputType.SQL_QUERY, OutputType.DBT_MODEL) for a in pkg.artifacts) else '✗'} |
| 3b Code Conversion | {'✓' if any('converted' in a.filename for a in pkg.artifacts) else 'N/A'} |
| 3c DQ Rules | {'✓ ' + str(dq_count) + ' rules' if pkg.dq_report else '✗'} |
| 3d Observability | {'✓' if pkg.observability else '✗'} |
| 3e Metadata | {'✓' if pkg.metadata else '✗'} |

### Checklist
- [ ] SQL logic reviewed against mapping document
- [ ] DQ rules match acceptance criteria
- [ ] Observability alerts configured correctly
- [ ] PII classifications verified
- [ ] Performance / cost impact assessed

🤖 Generated by SQL-Gen Engineering Orchestrator (Agent 3)
"""
