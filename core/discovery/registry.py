"""Dialect → SourceProvider registry."""
from typing import Dict
from core.discovery.base import SourceProvider, Dialect

_PROVIDERS: Dict[str, SourceProvider] = {}


def register_provider(dialect: Dialect, provider: SourceProvider) -> None:
    _PROVIDERS[dialect] = provider


def get_provider(dialect: str) -> SourceProvider:
    p = _PROVIDERS.get(dialect)
    if p is None:
        raise ValueError(f"Unknown dialect: {dialect}")
    return p


def all_providers() -> Dict[str, SourceProvider]:
    return dict(_PROVIDERS)
