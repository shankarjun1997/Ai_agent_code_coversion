from core.discovery.postgres_provider import PostgresProviderAsync
from core.discovery.profiles import ProfileRegistry, get_registry
from core.discovery.base import SourceProvider
from core.discovery.registry import register_provider, get_provider, all_providers

# Auto-register Postgres on import
register_provider("postgres", PostgresProviderAsync())

__all__ = [
    "PostgresProviderAsync", "ProfileRegistry", "get_registry",
    "SourceProvider", "register_provider", "get_provider", "all_providers",
]
