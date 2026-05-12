"""SourceProvider abstract interface for cross-dialect discovery."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional


Dialect = Literal["postgres", "oracle", "mysql", "mssql", "bigquery"]


@dataclass
class PingResult:
    ok: bool
    latency_ms: Optional[int] = None
    message: Optional[str] = None


@dataclass
class TableInfo:
    schema: str
    name: str
    row_estimate: Optional[int] = None
    comment: Optional[str] = None


@dataclass
class ColumnInfo:
    schema: str
    table: str
    name: str
    data_type: str
    nullable: bool
    is_primary_key: bool = False
    default: Optional[str] = None
    comment: Optional[str] = None


@dataclass
class FKInfo:
    schema: str
    table: str
    column: str
    ref_schema: str
    ref_table: str
    ref_column: str
    constraint_name: Optional[str] = None


@dataclass
class ColumnProfile:
    row_count: Optional[int] = None
    distinct_count: Optional[int] = None
    null_pct: Optional[float] = None
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None
    sample_values: List[Any] = field(default_factory=list)


@dataclass
class ColumnHit:
    schema: str
    table: str
    column: str
    data_type: str
    score: float
    matched_on: Literal["name", "comment", "value"]


class SourceProvider(ABC):
    dialect: Dialect

    @abstractmethod
    async def ping(self, profile: Any) -> PingResult: ...

    @abstractmethod
    async def list_schemas(self, profile: Any) -> List[str]: ...

    @abstractmethod
    async def list_tables(self, profile: Any, schema: str) -> List[TableInfo]: ...

    @abstractmethod
    async def get_columns(self, profile: Any, schema: str, table: str) -> List[ColumnInfo]: ...

    @abstractmethod
    async def get_foreign_keys(self, profile: Any, schema: str, table: str) -> List[FKInfo]: ...

    @abstractmethod
    async def profile_column(
        self, profile: Any, schema: str, table: str, column: str,
        sample_rows: int = 0,
    ) -> ColumnProfile: ...

    @abstractmethod
    async def search_by_keywords(
        self, profile: Any, keywords: List[str], limit: int = 50,
    ) -> List[ColumnHit]: ...
