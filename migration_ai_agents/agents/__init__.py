"""
Base Agent - Abstract base class for all migration agents.
All agents inherit from this and implement the execute() method.
"""
import os
import json
import yaml
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AgentResult:
    """Standard result object passed between agents."""

    def __init__(self, agent_name: str, module_name: str):
        self.agent_name = agent_name
        self.module_name = module_name
        self.status = "pending"  # pending | success | failure | mismatch
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.data = {}
        self.errors = []
        self.warnings = []
        self.metrics = {}

    def set_success(self, data: dict = None):
        self.status = "success"
        if data:
            self.data.update(data)
        return self

    def set_failure(self, error: str, data: dict = None):
        self.status = "failure"
        self.errors.append(error)
        if data:
            self.data.update(data)
        return self

    def set_mismatch(self, data: dict = None):
        self.status = "mismatch"
        if data:
            self.data.update(data)
        return self

    def add_warning(self, warning: str):
        self.warnings.append(warning)
        return self

    def to_dict(self) -> dict:
        return {
            "agent": self.agent_name,
            "module": self.module_name,
            "status": self.status,
            "timestamp": self.timestamp,
            "data": self.data,
            "errors": self.errors,
            "warnings": self.warnings,
            "metrics": self.metrics,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)

    def __repr__(self):
        return f"AgentResult({self.agent_name}, {self.module_name}, {self.status})"


class BaseAgent(ABC):
    """Abstract base class for all migration agents."""

    def __init__(self, config: dict, module_name: str):
        self.config = config
        self.module_name = module_name
        self.repo_root = self._resolve_repo_root()
        self.module_dir = os.path.join(self.repo_root, module_name)
        self.output_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            config.get("output", {}).get("directory", "output"),
        )
        os.makedirs(self.output_dir, exist_ok=True)

        # Set up logging
        self.logger = logging.getLogger(self.__class__.__name__)
        self._setup_logging()

    def _resolve_repo_root(self) -> str:
        """Resolve the absolute path to the onefiber repo root."""
        agents_dir = os.path.dirname(os.path.dirname(__file__))
        rel = self.config.get("project", {}).get("repo_root", "..")
        return os.path.abspath(os.path.join(agents_dir, rel))

    def _setup_logging(self):
        log_cfg = self.config.get("logging", {})
        level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
        self.logger.setLevel(level)
        if not self.logger.handlers:
            # Console handler
            ch = logging.StreamHandler()
            ch.setLevel(level)
            fmt = log_cfg.get("format", "%(asctime)s | %(name)s | %(levelname)s | %(message)s")
            ch.setFormatter(logging.Formatter(fmt))
            self.logger.addHandler(ch)
            # File handler
            log_file = log_cfg.get("file")
            if log_file:
                log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), log_file)
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                fh = logging.FileHandler(log_path)
                fh.setLevel(level)
                fh.setFormatter(logging.Formatter(fmt))
                self.logger.addHandler(fh)

    # ---- Module Discovery Helpers ----

    def get_module_path(self, *sub_paths) -> str:
        """Get absolute path within the module directory."""
        return os.path.join(self.module_dir, *sub_paths)

    def get_sql_dir(self) -> str:
        struct = self.config.get("modules", {}).get("structure", {})
        return self.get_module_path(struct.get("sql_path", "pipelines/src/main/sql"))

    def get_config_dir(self) -> str:
        struct = self.config.get("modules", {}).get("structure", {})
        return self.get_module_path(struct.get("config_path", "pipelines/src/main/config"))

    def get_dag_python_dir(self) -> str:
        struct = self.config.get("modules", {}).get("structure", {})
        return self.get_module_path(struct.get("dag_python_path", "dag/python"))

    def get_dag_config_dir(self) -> str:
        struct = self.config.get("modules", {}).get("structure", {})
        return self.get_module_path(struct.get("dag_config_path", "dag/config"))

    def list_sql_files(self) -> list:
        sql_dir = self.get_sql_dir()
        if not os.path.isdir(sql_dir):
            return []
        return sorted([
            os.path.join(sql_dir, f)
            for f in os.listdir(sql_dir)
            if f.endswith(".sql")
        ])

    def list_config_files(self) -> list:
        cfg_dir = self.get_config_dir()
        if not os.path.isdir(cfg_dir):
            return []
        return sorted([
            os.path.join(cfg_dir, f)
            for f in os.listdir(cfg_dir)
            if f.endswith(".cfg")
        ])

    def list_dag_python_files(self) -> list:
        dag_dir = self.get_dag_python_dir()
        if not os.path.isdir(dag_dir):
            return []
        return sorted([
            os.path.join(dag_dir, f)
            for f in os.listdir(dag_dir)
            if f.endswith(".py")
        ])

    def list_dag_config_files(self) -> list:
        dag_dir = self.get_dag_config_dir()
        if not os.path.isdir(dag_dir):
            return []
        return sorted([
            os.path.join(dag_dir, f)
            for f in os.listdir(dag_dir)
            if f.endswith((".yml", ".yaml"))
        ])

    # ---- File I/O ----

    def read_file(self, filepath: str) -> str:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    def write_file(self, filepath: str, content: str):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

    def save_result(self, result: AgentResult):
        """Save agent result as JSON to output directory."""
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{result.agent_name}_{result.module_name}_{ts}.json"
        filepath = os.path.join(self.output_dir, filename)
        self.write_file(filepath, result.to_json())
        self.logger.info(f"Result saved to {filepath}")
        return filepath

    # ---- Discover All Modules ----

    @classmethod
    def discover_modules(cls, repo_root: str) -> list:
        """Auto-discover all modules that have the standard pipeline structure."""
        modules = []
        for item in sorted(os.listdir(repo_root)):
            module_dir = os.path.join(repo_root, item)
            sql_dir = os.path.join(module_dir, "pipelines", "src", "main", "sql")
            if os.path.isdir(sql_dir):
                sql_files = [f for f in os.listdir(sql_dir) if f.endswith(".sql")]
                if sql_files:
                    modules.append(item)
        return modules

    # ---- Abstract Method ----

    @abstractmethod
    def execute(self, input_data: AgentResult = None) -> AgentResult:
        """
        Execute the agent's task.
        
        Args:
            input_data: Optional AgentResult from a previous agent in the pipeline.
            
        Returns:
            AgentResult with the outcome of this agent's work.
        """
        pass
