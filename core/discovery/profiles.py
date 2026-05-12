"""In-memory connection profile registry. Demo-grade; persists for process lifetime."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ConnectionProfile:
    id:       str
    label:    str
    dialect:  str            # "postgres" | "oracle" | "mysql" | "mssql" | "bigquery"
    dsn:      str
    host:     str
    last_used: Optional[str] = None
    icon:     str = "DB"
    status:   str = "connected"


class ProfileRegistry:
    def __init__(self):
        self._profiles: Dict[str, ConnectionProfile] = {}
        self._seed_demo_profiles()

    def _seed_demo_profiles(self) -> None:
        """Auto-register the demo Postgres + a few illustrative profiles for the UI."""
        demo_dsn = os.getenv("DEMO_DB_DSN", "postgresql://demo:demo@demo-db:5432/crm_demo")
        self.register(ConnectionProfile(
            id="postgres-crm-demo",
            label="Postgres — CRM Demo",
            dialect="postgres",
            dsn=demo_dsn,
            host=demo_dsn.split("@", 1)[-1] if "@" in demo_dsn else demo_dsn,
            icon="PG",
            last_used="just now",
        ))
        # Illustrative-only profiles (for the demo screen — mark as not_connected)
        for p in [
            ConnectionProfile(id="oracle-prod-crm", label="Oracle PROD — CRM",
                              dialect="oracle", dsn="oracle://-", host="crm.prod.corp:1521/CRM",
                              icon="OR", status="illustrative", last_used="—"),
            ConnectionProfile(id="mssql-erp", label="MS SQL — Legacy ERP",
                              dialect="mssql", dsn="mssql://-", host="erp-db.legacy:1433/ERP",
                              icon="MS", status="illustrative", last_used="—"),
            ConnectionProfile(id="mysql-billing", label="MySQL — Billing Replica",
                              dialect="mysql", dsn="mysql://-", host="billing-ro:3306/billing",
                              icon="MY", status="illustrative", last_used="—"),
        ]:
            self.register(p)

    def register(self, profile: ConnectionProfile) -> ConnectionProfile:
        self._profiles[profile.id] = profile
        return profile

    def get(self, profile_id: str) -> Optional[ConnectionProfile]:
        return self._profiles.get(profile_id)

    def list(self) -> List[ConnectionProfile]:
        return list(self._profiles.values())

    def add_postgres(self, label: str, dsn: str) -> ConnectionProfile:
        pid = "pg-" + uuid.uuid4().hex[:8]
        host = dsn.split("@", 1)[-1] if "@" in dsn else dsn
        p = ConnectionProfile(id=pid, label=label, dialect="postgres",
                              dsn=dsn, host=host, icon="PG", last_used="just now")
        return self.register(p)


_registry: Optional[ProfileRegistry] = None


def get_registry() -> ProfileRegistry:
    global _registry
    if _registry is None:
        _registry = ProfileRegistry()
    return _registry
