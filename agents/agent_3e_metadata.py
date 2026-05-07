"""Agent 3e — Metadata Generator Agent.

Extracts column-level lineage, generates BigQuery table/column descriptions,
publishes to Dataplex / Data Catalog, and tags PII and sensitivity classifications.
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from core.llm_client import LLMClient
from core.schemas import DataMapping, FieldMapping, MetadataEntry

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a data governance and metadata specialist.

Generate comprehensive, business-friendly metadata for BigQuery tables:
  - Clear, concise table and column descriptions (business language, not technical jargon)
  - Accurate PII classification based on field names and transformation logic
  - Sensitivity labels: public | internal | confidential | restricted
  - Dataplex-compatible tag template values
  - BigQuery column labels for Data Catalog discoverability

Return strict JSON.
"""


class MetadataAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(self, mapping: DataMapping) -> MetadataEntry:
        """Generate metadata entry for the target table defined in the mapping."""
        target_fqn = ".".join(filter(None, [
            mapping.target_project, mapping.target_dataset, mapping.target_table
        ]))

        fields_desc = "\n".join(
            f"  {f.target_field} ({f.data_type}): source={f.source_expression}, "
            f"is_pii={f.is_pii}, sensitivity={f.sensitivity or 'unknown'}"
            f"{', desc=' + f.description if f.description else ''}"
            for f in mapping.field_mappings
        )

        prompt = f"""Generate metadata for this BigQuery table:

Table FQN: {target_fqn}
Jira issue: {mapping.jira_issue}
Data owner: {mapping.data_owner or 'not set'}
Data steward: {mapping.data_steward or 'not set'}
Business rules: {'; '.join(mapping.business_rules) or 'none'}
Tags: {', '.join(mapping.tags) or 'none'}

Fields:
{fields_desc}

Upstream tables: {', '.join(f'{t.dataset}.{t.table}' for t in mapping.source_tables)}

Return JSON with this exact structure:
{{
  "description": "Table description in plain business language",
  "column_descriptions": {{
    "field_name": "description"
  }},
  "pii_columns": ["field_name"],
  "sensitivity_labels": {{
    "field_name": "public|internal|confidential|restricted"
  }},
  "dataplex_tags": {{
    "data_product": "...",
    "data_domain": "...",
    "classification": "...",
    "update_frequency": "...",
    "sla_hours": {mapping.sla_hours or 24}
  }},
  "bq_labels": {{
    "team": "data-engineering",
    "jira_issue": "{mapping.jira_issue.lower().replace('-', '_')}",
    "data_classification": "internal"
  }}
}}
"""
        payload = self.llm.complete_json(prompt, system=SYSTEM_PROMPT)

        # Augment with fields already marked as PII in the mapping
        known_pii = [f.target_field for f in mapping.field_mappings if f.is_pii]
        pii_list  = list(set(payload.get("pii_columns", []) + known_pii))

        entry = MetadataEntry(
            table_fqn=target_fqn,
            description=payload.get("description", ""),
            data_owner=mapping.data_owner,
            data_steward=mapping.data_steward,
            column_descriptions=payload.get("column_descriptions", {}),
            pii_columns=pii_list,
            sensitivity_labels=payload.get("sensitivity_labels", {}),
            lineage_upstream=[f"{t.dataset}.{t.table}" for t in mapping.source_tables],
            lineage_downstream=[],
            dataplex_tags=payload.get("dataplex_tags", {}),
            bq_labels=payload.get("bq_labels", {}),
        )

        logger.info(
            "Agent 3e: metadata for %s — %d columns described, %d PII fields",
            target_fqn, len(entry.column_descriptions), len(entry.pii_columns),
        )
        return entry

    def to_bq_update_sql(self, entry: MetadataEntry) -> str:
        """Generate ALTER TABLE statements to set BigQuery column descriptions."""
        lines = [f"-- Metadata update for {entry.table_fqn}"]
        parts = []
        for col, desc in entry.column_descriptions.items():
            safe_desc = desc.replace("'", "\\'")
            parts.append(
                f"  ALTER COLUMN `{col}` SET OPTIONS(description='{safe_desc}')"
            )
        if parts:
            lines.append(f"ALTER TABLE `{entry.table_fqn}`")
            lines.append(",\n".join(parts) + ";")

        # Table description
        if entry.description:
            safe = entry.description.replace("'", "\\'")
            lines.append(
                f"ALTER TABLE `{entry.table_fqn}` SET OPTIONS(description='{safe}');"
            )
        return "\n".join(lines)

    def to_dataplex_yaml(self, entry: MetadataEntry) -> str:
        """Generate Dataplex tag attachment YAML."""
        tags_yaml = "\n".join(
            f"  {k}: \"{v}\"" for k, v in entry.dataplex_tags.items()
        )
        return f"""# Dataplex tag attachment for {entry.table_fqn}
resource: {entry.table_fqn}
tag_template: projects/$PROJECT/locations/$REGION/tagTemplates/data_catalog_template
fields:
{tags_yaml}
  pii_columns: "{', '.join(entry.pii_columns)}"
  data_owner: "{entry.data_owner or ''}"
  data_steward: "{entry.data_steward or ''}"
"""
