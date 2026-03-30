"""
Oracle SQL Parser — Parses Oracle-native PL/SQL stored procedures/packages.
Extracts: procedure name, parameters, table references, Oracle-specific syntax,
          cursor declarations, exception handlers, data types, DML operations.
"""
import re
from typing import Optional


class OracleSQLParser:
    """Parse Oracle PL/SQL stored procedures for migration analysis."""

    # Oracle data types → BigQuery mapping
    DATATYPE_MAP = {
        # Numeric
        "NUMBER": "NUMERIC",
        "INTEGER": "INT64",
        "INT": "INT64",
        "SMALLINT": "INT64",
        "FLOAT": "FLOAT64",
        "DOUBLE PRECISION": "FLOAT64",
        "BINARY_FLOAT": "FLOAT64",
        "BINARY_DOUBLE": "FLOAT64",
        "DECIMAL": "NUMERIC",
        "DEC": "NUMERIC",
        "PLS_INTEGER": "INT64",
        "BINARY_INTEGER": "INT64",
        "NATURAL": "INT64",
        "POSITIVE": "INT64",
        "NATURALN": "INT64",
        "POSITIVEN": "INT64",
        "SIGNTYPE": "INT64",
        # String
        "VARCHAR2": "STRING",
        "VARCHAR": "STRING",
        "NVARCHAR2": "STRING",
        "CHAR": "STRING",
        "NCHAR": "STRING",
        "CLOB": "STRING",
        "NCLOB": "STRING",
        "LONG": "STRING",
        "RAW": "BYTES",
        "LONG RAW": "BYTES",
        "BLOB": "BYTES",
        # Date/Time
        "DATE": "DATETIME",
        "TIMESTAMP": "TIMESTAMP",
        "TIMESTAMP WITH TIME ZONE": "TIMESTAMP",
        "TIMESTAMP WITH LOCAL TIME ZONE": "TIMESTAMP",
        "INTERVAL YEAR TO MONTH": "STRING",
        "INTERVAL DAY TO SECOND": "STRING",
        # Boolean
        "BOOLEAN": "BOOL",
        # Other
        "ROWID": "STRING",
        "UROWID": "STRING",
        "XMLTYPE": "STRING",
        "SYS_REFCURSOR": None,  # No direct BQ equivalent
    }

    # Oracle functions → BigQuery equivalents
    FUNCTION_MAP = {
        "SYSDATE": "CURRENT_DATETIME()",
        "SYSTIMESTAMP": "CURRENT_TIMESTAMP()",
        "NVL": "IFNULL",
        "NVL2": "IF",
        "DECODE": "CASE",
        "TO_DATE": "PARSE_DATETIME",
        "TO_CHAR": "FORMAT_DATETIME",
        "TO_NUMBER": "CAST",
        "TO_TIMESTAMP": "PARSE_TIMESTAMP",
        "TRUNC": "DATE_TRUNC",
        "ADD_MONTHS": "DATE_ADD",
        "MONTHS_BETWEEN": "DATE_DIFF",
        "LAST_DAY": "LAST_DAY",
        "NEXT_DAY": None,  # Manual conversion needed
        "ROWNUM": "ROW_NUMBER() OVER()",
        "LISTAGG": "STRING_AGG",
        "WM_CONCAT": "STRING_AGG",
        "REGEXP_SUBSTR": "REGEXP_EXTRACT",
        "REGEXP_INSTR": None,  # Manual conversion
        "INSTR": "STRPOS",
        "SUBSTR": "SUBSTR",
        "LENGTH": "LENGTH",
        "LPAD": "LPAD",
        "RPAD": "RPAD",
        "TRIM": "TRIM",
        "LTRIM": "LTRIM",
        "RTRIM": "RTRIM",
        "REPLACE": "REPLACE",
        "UPPER": "UPPER",
        "LOWER": "LOWER",
        "INITCAP": "INITCAP",
        "CEIL": "CEIL",
        "FLOOR": "FLOOR",
        "ROUND": "ROUND",
        "MOD": "MOD",
        "ABS": "ABS",
        "SIGN": "SIGN",
        "POWER": "POWER",
        "SQRT": "SQRT",
        "GREATEST": "GREATEST",
        "LEAST": "LEAST",
        "COALESCE": "COALESCE",
        "NULLIF": "NULLIF",
        "DBMS_OUTPUT.PUT_LINE": "SELECT",  # Debug output
    }

    # Oracle join syntax patterns
    ORACLE_JOIN_PATTERN = re.compile(
        r'(\w+\.\w+)\s*=\s*(\w+\.\w+)\s*\(\+\)',
        re.IGNORECASE
    )

    def __init__(self, content: str, filename: str = ""):
        self.content = content
        self.filename = filename

    def parse(self) -> dict:
        """Full parse of Oracle PL/SQL file."""
        return {
            "filename": self.filename,
            "procedure_name": self.get_procedure_name(),
            "parameters": self.get_parameters(),
            "local_variables": self.get_local_variables(),
            "cursors": self.get_cursors(),
            "table_references": self.get_table_references(),
            "oracle_functions": self.get_oracle_functions_used(),
            "dml_operations": self.get_dml_operations(),
            "exception_handlers": self.get_exception_handlers(),
            "oracle_join_syntax": self.get_oracle_join_syntax(),
            "sequences_used": self.get_sequences(),
            "synonyms_used": self.get_synonyms(),
            "hints_used": self.get_hints(),
            "has_dynamic_sql": self.has_dynamic_sql(),
            "has_autonomous_transaction": self.has_autonomous_transaction(),
            "has_bulk_operations": self.has_bulk_operations(),
            "complexity_score": self.get_complexity_score(),
        }

    def get_procedure_name(self) -> Optional[str]:
        """Extract procedure/function name."""
        m = re.search(
            r'(?:CREATE\s+(?:OR\s+REPLACE\s+)?)?(?:PROCEDURE|FUNCTION)\s+(\w+(?:\.\w+)*)',
            self.content, re.IGNORECASE
        )
        if m:
            name = m.group(1)
            # Strip schema prefix
            if "." in name:
                name = name.split(".")[-1]
            return name
        return None

    def get_parameters(self) -> list:
        """Extract procedure parameters with IN/OUT/IN OUT modes and types."""
        params = []
        # Find parameter block between procedure name and IS/AS
        m = re.search(
            r'(?:PROCEDURE|FUNCTION)\s+\w+(?:\.\w+)*\s*\((.*?)\)\s*(?:RETURN\s+\w+\s*)?(?:IS|AS)',
            self.content, re.IGNORECASE | re.DOTALL
        )
        if not m:
            return params

        param_block = m.group(1)
        for p in re.finditer(
            r'(\w+)\s+(IN\s+OUT|IN|OUT)?\s*(\w+(?:\([^)]*\))?)',
            param_block, re.IGNORECASE
        ):
            params.append({
                "name": p.group(1),
                "mode": (p.group(2) or "IN").strip().upper(),
                "oracle_type": p.group(3).upper(),
                "bq_type": self._map_datatype(p.group(3)),
            })
        return params

    def get_local_variables(self) -> list:
        """Extract local variable declarations."""
        variables = []
        for m in re.finditer(
            r'(\w+)\s+(\w+(?:\([^)]*\))?)\s*(?::=\s*(.+?))?;',
            self.content
        ):
            name = m.group(1).upper()
            if name in ("BEGIN", "END", "IF", "THEN", "ELSE", "LOOP", "RETURN", "SELECT",
                        "INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "DROP"):
                continue
            vtype = m.group(2).upper()
            if vtype in self.DATATYPE_MAP or any(vtype.startswith(dt) for dt in self.DATATYPE_MAP):
                variables.append({
                    "name": m.group(1),
                    "oracle_type": m.group(2),
                    "bq_type": self._map_datatype(m.group(2)),
                    "default_value": m.group(3).strip() if m.group(3) else None,
                })
        return variables

    def get_cursors(self) -> list:
        """Extract cursor declarations."""
        cursors = []
        for m in re.finditer(
            r'CURSOR\s+(\w+)(?:\s*\(([^)]*)\))?\s+IS\s+(.*?);',
            self.content, re.IGNORECASE | re.DOTALL
        ):
            cursors.append({
                "name": m.group(1),
                "parameters": m.group(2) if m.group(2) else None,
                "query": m.group(3).strip(),
            })
        return cursors

    def get_table_references(self) -> list:
        """Extract all table references (schema.table or just table)."""
        tables = set()
        # FROM / JOIN clauses
        for m in re.finditer(
            r'(?:FROM|JOIN|INTO|UPDATE|MERGE\s+INTO)\s+(\w+(?:\.\w+)?)',
            self.content, re.IGNORECASE
        ):
            table = m.group(1)
            if table.upper() not in ("DUAL", "SELECT", "WHERE", "SET", "VALUES"):
                tables.add(table)
        return sorted(tables)

    def get_oracle_functions_used(self) -> list:
        """Identify Oracle-specific functions that need conversion."""
        found = []
        content_upper = self.content.upper()
        for oracle_func, bq_func in self.FUNCTION_MAP.items():
            # Check if function name appears (word boundary)
            if re.search(rf'\b{re.escape(oracle_func)}\b', content_upper):
                found.append({
                    "oracle_function": oracle_func,
                    "bq_equivalent": bq_func,
                    "needs_manual_review": bq_func is None,
                    "occurrences": len(re.findall(rf'\b{re.escape(oracle_func)}\b', content_upper)),
                })
        return found

    def get_dml_operations(self) -> list:
        """Identify DML operations."""
        ops = []
        patterns = [
            (r'INSERT\s+INTO\s+(\w+(?:\.\w+)*)', "INSERT"),
            (r'UPDATE\s+(\w+(?:\.\w+)*)\s+SET', "UPDATE"),
            (r'DELETE\s+FROM\s+(\w+(?:\.\w+)*)', "DELETE"),
            (r'MERGE\s+INTO\s+(\w+(?:\.\w+)*)', "MERGE"),
            (r'TRUNCATE\s+TABLE\s+(\w+(?:\.\w+)*)', "TRUNCATE"),
        ]
        for pat, op_type in patterns:
            for m in re.finditer(pat, self.content, re.IGNORECASE):
                ops.append({"type": op_type, "target": m.group(1)})
        return ops

    def get_exception_handlers(self) -> list:
        """Extract EXCEPTION WHEN blocks."""
        handlers = []
        for m in re.finditer(
            r'WHEN\s+(\w+)\s+THEN\s*(.*?)(?=WHEN\s|\bEND\b)',
            self.content, re.IGNORECASE | re.DOTALL
        ):
            handlers.append({
                "exception": m.group(1),
                "handler_body": m.group(2).strip()[:200],  # truncate
            })
        return handlers

    def get_oracle_join_syntax(self) -> list:
        """Find Oracle (+) outer join syntax."""
        joins = []
        for m in self.ORACLE_JOIN_PATTERN.finditer(self.content):
            joins.append({
                "left": m.group(1),
                "right": m.group(2),
                "line": self.content[:m.start()].count('\n') + 1,
            })
        return joins

    def get_sequences(self) -> list:
        """Find sequence references (schema.sequence.NEXTVAL/CURRVAL)."""
        seqs = []
        for m in re.finditer(r'(\w+(?:\.\w+)?)\.(?:NEXTVAL|CURRVAL)', self.content, re.IGNORECASE):
            seqs.append(m.group(1))
        return list(set(seqs))

    def get_synonyms(self) -> list:
        """Detect potential synonym references (bare table names without schema)."""
        tables = self.get_table_references()
        return [t for t in tables if "." not in t]

    def get_hints(self) -> list:
        """Extract optimizer hints /*+ ... */."""
        return re.findall(r'/\*\+\s*(.*?)\s*\*/', self.content, re.DOTALL)

    def has_dynamic_sql(self) -> bool:
        """Check for EXECUTE IMMEDIATE / DBMS_SQL."""
        return bool(re.search(r'EXECUTE\s+IMMEDIATE|DBMS_SQL', self.content, re.IGNORECASE))

    def has_autonomous_transaction(self) -> bool:
        """Check for PRAGMA AUTONOMOUS_TRANSACTION."""
        return "AUTONOMOUS_TRANSACTION" in self.content.upper()

    def has_bulk_operations(self) -> bool:
        """Check for BULK COLLECT / FORALL."""
        return bool(re.search(r'BULK\s+COLLECT|FORALL', self.content, re.IGNORECASE))

    def get_complexity_score(self) -> dict:
        """Calculate a complexity score for migration difficulty."""
        score = 0
        factors = []

        cursors = self.get_cursors()
        if cursors:
            score += len(cursors) * 3
            factors.append(f"{len(cursors)} cursors")

        oracle_funcs = self.get_oracle_functions_used()
        manual_funcs = [f for f in oracle_funcs if f["needs_manual_review"]]
        score += len(oracle_funcs) * 1
        score += len(manual_funcs) * 5
        if manual_funcs:
            factors.append(f"{len(manual_funcs)} functions need manual review")

        if self.has_dynamic_sql():
            score += 10
            factors.append("Dynamic SQL")

        if self.has_autonomous_transaction():
            score += 8
            factors.append("Autonomous transaction")

        if self.has_bulk_operations():
            score += 5
            factors.append("Bulk operations")

        oracle_joins = self.get_oracle_join_syntax()
        if oracle_joins:
            score += len(oracle_joins) * 2
            factors.append(f"{len(oracle_joins)} Oracle (+) joins")

        sequences = self.get_sequences()
        if sequences:
            score += len(sequences) * 4
            factors.append(f"{len(sequences)} sequences")

        exceptions = self.get_exception_handlers()
        if exceptions:
            score += len(exceptions) * 2
            factors.append(f"{len(exceptions)} exception handlers")

        params = self.get_parameters()
        out_params = [p for p in params if "OUT" in p["mode"]]
        if out_params:
            score += len(out_params) * 3
            factors.append(f"{len(out_params)} OUT parameters")

        if score <= 5:
            difficulty = "LOW"
        elif score <= 15:
            difficulty = "MEDIUM"
        elif score <= 30:
            difficulty = "HIGH"
        else:
            difficulty = "VERY_HIGH"

        return {
            "score": score,
            "difficulty": difficulty,
            "factors": factors,
        }

    def _map_datatype(self, oracle_type: str) -> Optional[str]:
        """Map an Oracle data type to its BigQuery equivalent."""
        upper = oracle_type.upper().split("(")[0].strip()
        return self.DATATYPE_MAP.get(upper, "STRING")
