"""
Migration Pipeline — Orchestrates the 4-agent workflow:
  Conversion → Validation → Debug → Fix → (Human Review)

Supports modes:
  - full       : Run all 4 agents end-to-end
  - convert    : Run only the Conversion agent
  - validate   : Run Conversion + Validation
  - debug      : Run Conversion + Validation + Debug
  - fix        : Run all 4 agents (same as full)
  - fix-only   : Run Fix agent on a previous debug report
"""
import os
import json
import time
import logging
from typing import Optional

import yaml

from agents import AgentResult, BaseAgent
from agents.conversion_agent import ConversionAgent
from agents.validation_agent import ValidationAgent
from agents.debug_agent import DebugAgent
from agents.fix_agent import FixAgent
from models.llm_client import LLMClient

logger = logging.getLogger(__name__)


class MigrationPipeline:
    """Orchestrate the multi-agent migration pipeline."""

    MODES = ("full", "convert", "validate", "debug", "fix", "fix-only")

    def __init__(self, config_path: str):
        """
        Args:
            config_path: Path to configs/config.yaml
        """
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.repo_root = self.config["gcp"]["repo_root"]
        self.output_dir = self.config.get("output", {}).get("base_dir", "output")
        os.makedirs(self.output_dir, exist_ok=True)

        # Initialize LLM client (lazy — won't fail if keys not set)
        self.llm_client = LLMClient(self.config.get("llm", {}))

        self._setup_logging()

    def _setup_logging(self):
        """Configure logging based on config."""
        log_cfg = self.config.get("logging", {})
        level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
        log_file = log_cfg.get("file", os.path.join(self.output_dir, "pipeline.log"))
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(),
            ],
        )

    def run(
        self,
        module: Optional[str] = None,
        mode: str = "full",
        dry_run: bool = True,
        debug_report_path: Optional[str] = None,
    ) -> dict:
        """
        Execute the migration pipeline.

        Args:
            module: Specific module name (e.g. 'ned_dashboard'), or None for all
            mode: Pipeline mode — one of MODES
            dry_run: If True, Fix agent won't apply changes
            debug_report_path: Path to a previous debug report (for 'fix-only' mode)

        Returns:
            dict with overall summary and per-agent results
        """
        if mode not in self.MODES:
            raise ValueError(f"Invalid mode '{mode}'. Choose from: {self.MODES}")

        start_time = time.time()
        results = {"mode": mode, "module": module or "ALL", "dry_run": dry_run, "agents": {}}

        # Discover modules
        if module:
            modules = [module]
        else:
            modules = [m["name"] for m in BaseAgent.discover_modules(self.repo_root)]
        logger.info("Pipeline starting — mode=%s, modules=%d, dry_run=%s", mode, len(modules), dry_run)

        # ---------- Agent 1: Conversion ----------
        if mode in ("full", "convert", "validate", "debug", "fix"):
            logger.info("=" * 60)
            logger.info("AGENT 1: Conversion Agent")
            logger.info("=" * 60)
            conversion_agent = ConversionAgent(self.config, self.repo_root)
            conversion_result = conversion_agent.execute(modules)
            results["agents"]["conversion"] = conversion_result.to_dict()
            self._save_agent_result("conversion", conversion_result)

            if mode == "convert":
                results["elapsed_seconds"] = round(time.time() - start_time, 2)
                self._save_pipeline_summary(results)
                return results

        # ---------- Agent 2: Validation ----------
        if mode in ("full", "validate", "debug", "fix"):
            logger.info("=" * 60)
            logger.info("AGENT 2: Validation Agent")
            logger.info("=" * 60)
            validation_agent = ValidationAgent(self.config, self.repo_root)
            validation_result = validation_agent.execute(modules)
            results["agents"]["validation"] = validation_result.to_dict()
            self._save_agent_result("validation", validation_result)

            if mode == "validate":
                results["elapsed_seconds"] = round(time.time() - start_time, 2)
                self._save_pipeline_summary(results)
                return results

        # ---------- Agent 3: Debug ----------
        if mode in ("full", "debug", "fix"):
            logger.info("=" * 60)
            logger.info("AGENT 3: Debug Agent")
            logger.info("=" * 60)
            # Merge issues from conversion + validation
            all_issues = []
            for agent_key in ("conversion", "validation"):
                agent_data = results["agents"].get(agent_key, {}).get("data", {})
                for mod_name, mod_data in agent_data.items():
                    if isinstance(mod_data, dict):
                        for category, items in mod_data.items():
                            if isinstance(items, list):
                                for item in items:
                                    if isinstance(item, dict) and "issue" in item:
                                        item["module"] = mod_name
                                        item["source_agent"] = agent_key
                                        all_issues.append(item)

            debug_agent = DebugAgent(self.config, self.repo_root, llm_client=self.llm_client)
            debug_result = debug_agent.execute(all_issues)
            results["agents"]["debug"] = debug_result.to_dict()
            self._save_agent_result("debug", debug_result)

            if mode == "debug":
                results["elapsed_seconds"] = round(time.time() - start_time, 2)
                self._save_pipeline_summary(results)
                return results

        # ---------- Agent 4: Fix ----------
        if mode in ("full", "fix", "fix-only"):
            logger.info("=" * 60)
            logger.info("AGENT 4: Fix Agent (dry_run=%s)", dry_run)
            logger.info("=" * 60)

            if mode == "fix-only" and debug_report_path:
                with open(debug_report_path, "r", encoding="utf-8") as f:
                    debug_data = json.load(f)
                diagnosed_issues = debug_data.get("data", {}).get("diagnosed", [])
            else:
                diagnosed_issues = results["agents"].get("debug", {}).get("data", {}).get("diagnosed", [])

            fix_agent = FixAgent(self.config, self.repo_root, dry_run=dry_run)
            fix_result = fix_agent.execute(diagnosed_issues)
            results["agents"]["fix"] = fix_result.to_dict()
            self._save_agent_result("fix", fix_result)

        # ---------- Summary ----------
        results["elapsed_seconds"] = round(time.time() - start_time, 2)
        results["summary"] = self._build_summary(results)
        self._save_pipeline_summary(results)

        logger.info("=" * 60)
        logger.info("PIPELINE COMPLETE — %.1fs", results["elapsed_seconds"])
        logger.info("  Total issues found: %d", results["summary"].get("total_issues", 0))
        logger.info("  Auto-fixable: %d", results["summary"].get("auto_fixable", 0))
        logger.info("  Fixed: %d", results["summary"].get("fixed", 0))
        logger.info("  Needs human review: %d", results["summary"].get("needs_human_review", 0))
        logger.info("=" * 60)

        return results

    def _build_summary(self, results: dict) -> dict:
        """Build a high-level summary from all agent results."""
        summary = {
            "total_issues": 0,
            "auto_fixable": 0,
            "fixed": 0,
            "needs_human_review": 0,
            "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0},
        }

        # Count from debug results
        debug_data = results.get("agents", {}).get("debug", {}).get("data", {})
        diagnosed = debug_data.get("diagnosed", [])
        for issue in diagnosed:
            if isinstance(issue, dict):
                summary["total_issues"] += 1
                if issue.get("auto_fixable"):
                    summary["auto_fixable"] += 1
                severity = issue.get("severity", "medium").lower()
                if severity in summary["by_severity"]:
                    summary["by_severity"][severity] += 1

        # Count from fix results
        fix_data = results.get("agents", {}).get("fix", {}).get("data", {})
        summary["fixed"] = fix_data.get("applied", 0) if isinstance(fix_data, dict) else 0
        summary["needs_human_review"] = summary["total_issues"] - summary["auto_fixable"]

        return summary

    def _save_agent_result(self, agent_name: str, result: AgentResult):
        """Save individual agent result to output dir."""
        path = os.path.join(self.output_dir, f"{agent_name}_result.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(result.to_json())
        logger.info("Saved %s result → %s", agent_name, path)

    def _save_pipeline_summary(self, results: dict):
        """Save full pipeline summary."""
        path = os.path.join(self.output_dir, "pipeline_summary.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)
        logger.info("Saved pipeline summary → %s", path)
