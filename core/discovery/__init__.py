from core.discovery.postgres_provider import PostgresProviderAsync
from core.discovery.bigquery_provider import BigQueryProvider
from core.discovery.profiles import ProfileRegistry, get_registry
from core.discovery.base import SourceProvider
from core.discovery.registry import register_provider, get_provider, all_providers

# Auto-register providers on import
register_provider("postgres", PostgresProviderAsync())
register_provider("bigquery", BigQueryProvider())

__all__ = [
    "PostgresProviderAsync", "BigQueryProvider", "ProfileRegistry", "get_registry",
    "SourceProvider", "register_provider", "get_provider", "all_providers",
]
