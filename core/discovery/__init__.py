from core.discovery.postgres_provider import PostgresProviderAsync
from core.discovery.bigquery_provider import BigQueryProvider
from core.discovery.profiles import ProfileRegistry, get_registry
from core.discovery.base import SourceProvider
from core.discovery.registry import register_provider, get_provider, all_providers
from core.discovery.oracle_provider import OracleProvider
from core.discovery.mysql_provider import MySQLProvider
from core.discovery.mssql_provider import MSSQLProvider
from core.discovery.jira_provider import JiraProvider

# Backward-compatible alias
PostgresProvider = PostgresProviderAsync

# Auto-register providers on import
register_provider("postgres", PostgresProviderAsync())
register_provider("bigquery", BigQueryProvider())
register_provider("oracle", OracleProvider())
register_provider("mysql", MySQLProvider())
register_provider("mssql", MSSQLProvider())
register_provider("jira", JiraProvider())

__all__ = [
    "PostgresProviderAsync", "PostgresProvider", "BigQueryProvider", "OracleProvider",
    "MySQLProvider", "MSSQLProvider", "JiraProvider", "ProfileRegistry", "get_registry",
    "SourceProvider", "register_provider", "get_provider", "all_providers",
]
