"""Rule-based source-to-target mapping engine.

Deterministic — no LLM. Produces a Source-to-Target Mapping (STM) given
discovered Postgres columns. Designed for live demo predictability.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# ── Type mapping (Postgres → BigQuery) ───────────────────────────────────────
_TYPE_RULES: List[tuple[re.Pattern, str]] = [
    (re.compile(r"^(varchar|character varying|text|char|character|bpchar)"), "STRING"),
    (re.compile(r"^(uuid|name)"),                                              "STRING"),
    (re.compile(r"^(json|jsonb)"),                                             "JSON"),
    (re.compile(r"^(bytea)"),                                                  "BYTES"),
    (re.compile(r"^(boolean|bool)"),                                           "BOOL"),
    (re.compile(r"^(smallint|integer|int|bigint|int2|int4|int8|serial|bigserial)"), "INT64"),
    (re.compile(r"^(numeric|decimal)"),                                        "NUMERIC"),
    (re.compile(r"^(real|double precision|float|float4|float8)"),              "FLOAT64"),
    (re.compile(r"^(timestamp)"),                                              "TIMESTAMP"),
    (re.compile(r"^date(\b|$)"),                                               "DATE"),
    (re.compile(r"^time(?!stamp)"),                                            "TIME"),
    (re.compile(r"^(interval)"),                                               "STRING"),
]

def map_type(pg_type: str) -> str:
    t = (pg_type or "").lower().strip()
    for pat, bq in _TYPE_RULES:
        if pat.search(t):
            return bq
    return "STRING"


# ── PII detection ────────────────────────────────────────────────────────────
_PII_HIGH = {
    "email", "email_address", "phone", "phone_number", "mobile",
    "ssn", "social_security", "tax_id", "passport",
    "date_of_birth", "dob", "birthday", "birthdate",
    "credit_card", "card_number", "cvv", "iban", "account_number",
    "ip_address", "ip",
}
_PII_MED = {
    "first_name", "last_name", "full_name", "given_name", "family_name", "middle_name",
    "address", "street", "city", "postal_code", "zip", "zipcode", "country",
    "gender", "nationality",
}

def detect_pii(col_name: str) -> tuple[bool, str]:
    n = col_name.lower()
    if n in _PII_HIGH:                                       return True, "high"
    if any(k in n for k in _PII_HIGH):                       return True, "high"
    if n in _PII_MED:                                        return True, "medium"
    if any(k in n for k in _PII_MED):                        return True, "medium"
    return False, "none"


# ── Snake-case helper (column already snake; this normalises edge cases) ─────
def to_snake(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]+", "_", s)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower().strip("_")


# ── Transform inference ──────────────────────────────────────────────────────
def infer_transform(col_name: str, pg_type: str, bq_type: str,
                    is_pii: bool, pii_level: str) -> str:
    n = col_name.lower()
    if is_pii and pii_level == "high":
        return f"TO_HEX(SHA256(CAST({col_name} AS STRING)))  -- PII hash"
    if "timestamp with time zone" in pg_type.lower() or "timestamptz" in pg_type.lower():
        return f"{col_name}  -- already timestamptz"
    if pg_type.lower().startswith("timestamp"):
        return f"TIMESTAMP({col_name}, 'UTC')"
    if bq_type == "STRING" and any(k in n for k in ("status", "channel", "tier", "category")):
        return f"UPPER({col_name})"
    if bq_type == "BOOL" and pg_type.lower().startswith(("smallint", "integer")):
        return f"CASE WHEN {col_name} = 1 THEN TRUE ELSE FALSE END"
    return col_name  # passthrough


# ── Partition / cluster inference ────────────────────────────────────────────
def infer_partition(columns: List[Dict[str, Any]]) -> Optional[str]:
    candidates = ["order_date", "event_date", "event_time", "created_at",
                  "placed_at", "occurred_at", "date"]
    by_name = {c["name"].lower(): c["name"] for c in columns}
    for c in candidates:
        if c in by_name:
            return by_name[c]
    for col in columns:
        if "date" in col["type"].lower() or "timestamp" in col["type"].lower():
            return col["name"]
    return None


# ── Result dataclasses ───────────────────────────────────────────────────────
@dataclass
class MappingRow:
    source_system:    str
    source_schema:    str
    source_table:     str
    source_column:    str
    source_type:      str
    source_nullable:  bool
    source_description: Optional[str]

    target_dataset:   str
    target_table:     str
    target_column:    str
    target_type:      str

    transformation:   str
    is_pii:           bool
    sensitivity:      str
    notes:            str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MappingResult:
    stm_id:               str
    profile_id:           str
    source_system:        str
    source_schema:        str
    source_tables:        List[str]
    target_dataset:       str
    target_table:         str
    partition_field:      Optional[str]
    rows:                 List[MappingRow]
    business_rules:       List[str] = field(default_factory=list)
    pii_count:            int = 0
    field_count:          int = 0
    idempotency_strategy: str = "delete_insert"
    idempotency_key:      Optional[str] = None
    generated_at:         str = ""

    def summary(self) -> Dict[str, Any]:
        return {
            "stm_id": self.stm_id,
            "profile_id": self.profile_id,
            "source_system": self.source_system,
            "source_schema": self.source_schema,
            "source_tables": self.source_tables,
            "target_dataset": self.target_dataset,
            "target_table": self.target_table,
            "partition_field": self.partition_field,
            "field_count": self.field_count,
            "pii_count": self.pii_count,
            "idempotency_strategy": self.idempotency_strategy,
            "idempotency_key": self.idempotency_key,
            "business_rules": self.business_rules,
            "generated_at": self.generated_at,
            "rows": [r.to_dict() for r in self.rows],
        }


# ── Build STM ─────────────────────────────────────────────────────────────────
def build_stm(
    *,
    profile_id: str,
    source_system: str,
    schema: str,
    selections: List[Dict[str, Any]],
    columns_by_table: Dict[str, List[Dict[str, Any]]],
    target_dataset: str,
    target_table: str,
    business_rules: Optional[List[str]] = None,
    stm_id: Optional[str] = None,
) -> MappingResult:
    """Construct a MappingResult from selected source columns.

    selections: list of {"table": str, "column": str}
    columns_by_table: {table_name: [column dicts from PostgresProvider.get_columns]}
    """
    import uuid
    from datetime import datetime, timezone

    rows: List[MappingRow] = []
    all_columns_flat: List[Dict[str, Any]] = []
    pii_count = 0

    # Lookups for fast access
    col_index: Dict[tuple[str, str], Dict[str, Any]] = {}
    for tbl, cols in columns_by_table.items():
        for c in cols:
            col_index[(tbl, c["name"])] = c
            all_columns_flat.append({**c, "_table": tbl})

    seen_targets: Dict[str, int] = {}
    for sel in selections:
        tbl = sel["table"]
        col = sel["column"]
        c = col_index.get((tbl, col))
        if not c:
            continue
        bq_type = map_type(c["type"])
        is_pii, level = detect_pii(c["name"])
        transform = infer_transform(c["name"], c["type"], bq_type, is_pii, level)
        # Hashed PII produces a hex STRING regardless of source type
        if is_pii and level == "high":
            bq_type = "STRING"
        target_col = to_snake(c["name"])
        # Disambiguate if same target name shows up across multiple source tables
        key = target_col
        if key in seen_targets:
            seen_targets[key] += 1
            target_col = f"{target_col}_{tbl.lower()}"
        else:
            seen_targets[key] = 1
        if is_pii and level == "high":
            target_col = f"{to_snake(c['name'])}_hash"

        rows.append(MappingRow(
            source_system=source_system,
            source_schema=schema,
            source_table=tbl,
            source_column=c["name"],
            source_type=c["type"],
            source_nullable=bool(c.get("nullable", True)),
            source_description=c.get("description"),
            target_dataset=target_dataset,
            target_table=target_table,
            target_column=target_col,
            target_type=bq_type,
            transformation=transform,
            is_pii=is_pii,
            sensitivity=level,
            notes="primary key" if c.get("is_primary_key") else "",
        ))
        if is_pii:
            pii_count += 1

    partition_field = infer_partition(all_columns_flat)
    idempotency_key = None
    for r in rows:
        if r.notes == "primary key":
            idempotency_key = r.target_column
            break

    return MappingResult(
        stm_id=stm_id or uuid.uuid4().hex[:8],
        profile_id=profile_id,
        source_system=source_system,
        source_schema=schema,
        source_tables=sorted({r.source_table for r in rows}),
        target_dataset=target_dataset,
        target_table=target_table,
        partition_field=partition_field,
        rows=rows,
        business_rules=business_rules or [
            "Hash PII (email, phone, dob) before publishing to BigQuery.",
            "Filter out cancelled and returned orders from the active customer view.",
            "Deduplicate by primary key; keep latest updated_at per row.",
        ],
        pii_count=pii_count,
        field_count=len(rows),
        idempotency_strategy="delete_insert",
        idempotency_key=idempotency_key,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
