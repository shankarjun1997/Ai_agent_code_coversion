"""Parser tests — ported from mapping-agent.jsx tryFastParse strategies."""
from pathlib import Path

import pytest

from core.catalog.parser import ParsedTable, parse_schema_file


FIXTURES = Path(__file__).parent / "fixtures" / "catalog"


def test_strategy_0_data_sample_uses_headers_as_columns():
    """device_activation_event_source.xlsx: 1 sheet with 44 column headers + data rows.
    Strategy 0 should detect data-sample mode and treat headers as the column list.
    """
    result = parse_schema_file(FIXTURES / "device_activation_event_source.xlsx")
    assert len(result.tables) == 1
    t = result.tables[0]
    assert t.table_name == "device_activation_event"
    assert t.column_count == 44
    assert len(t.columns) == 44
    assert any(c["name"] for c in t.columns)
    types = {c.get("type") for c in t.columns}
    assert len(types) > 1, f"All columns inferred as same type — type inference failing: {types}"
