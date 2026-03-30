#!/usr/bin/env python3
"""
OneFiber Migration AI Agent Framework — CLI Entry Point

Usage:
  python main.py --module ned_dashboard --mode full --dry-run
  python main.py --mode convert                          # scan all modules
  python main.py --module ned_dashboard --mode fix        # auto-fix (dry-run by default)
  python main.py --module ned_dashboard --mode fix --apply  # actually apply fixes
  python main.py --mode fix-only --debug-report output/debug_result.json --apply
  python main.py --list-modules                           # show discovered modules
"""
import argparse
import json
import os
import sys

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml
from agents import BaseAgent
from workflows.migration_pipeline import MigrationPipeline


def main():
    parser = argparse.ArgumentParser(
        description="OneFiber Migration AI Agent Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan a single module (conversion only)
  python main.py --module ned_dashboard --mode convert

  # Full pipeline scan (dry-run, no changes)
  python main.py --module ned_dashboard --mode full --dry-run

  # Full pipeline on ALL modules
  python main.py --mode full --dry-run

  # Debug only (find + diagnose issues)
  python main.py --module ned_dashboard --mode debug

  # Apply fixes
  python main.py --module ned_dashboard --mode fix --apply

  # Re-run fix from a previous debug report
  python main.py --mode fix-only --debug-report output/debug_result.json --apply

  # List all discovered modules
  python main.py --list-modules
        """,
    )

    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), "configs", "config.yaml"),
        help="Path to config.yaml (default: configs/config.yaml)",
    )
    parser.add_argument(
        "--module",
        default=None,
        help="Specific module name (e.g. ned_dashboard). Omit to scan all.",
    )
    parser.add_argument(
        "--mode",
        choices=MigrationPipeline.MODES,
        default="full",
        help="Pipeline mode (default: full)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Dry-run mode — Fix agent reports changes but does NOT apply them (default)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Actually apply fixes (overrides --dry-run)",
    )
    parser.add_argument(
        "--debug-report",
        default=None,
        help="Path to a previous debug_result.json (for fix-only mode)",
    )
    parser.add_argument(
        "--list-modules",
        action="store_true",
        help="List all discovered modules and exit",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override output directory",
    )

    args = parser.parse_args()

    # Load config
    if not os.path.exists(args.config):
        print(f"ERROR: Config file not found: {args.config}")
        sys.exit(1)

    with open(args.config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # List modules
    if args.list_modules:
        repo_root = config["gcp"]["repo_root"]
        modules = BaseAgent.discover_modules(repo_root)
        print(f"\nDiscovered {len(modules)} modules in {repo_root}:\n")
        for m in modules:
            print(f"  {m['name']:<50s}  ({len(m.get('sql_files', []))} SQL files)")
        sys.exit(0)

    # Override output dir
    if args.output_dir:
        config["output"] = config.get("output", {})
        config["output"]["base_dir"] = args.output_dir

    # Determine dry_run
    dry_run = not args.apply

    # Run pipeline
    pipeline = MigrationPipeline(args.config)

    if args.output_dir:
        pipeline.output_dir = args.output_dir
        os.makedirs(args.output_dir, exist_ok=True)

    results = pipeline.run(
        module=args.module,
        mode=args.mode,
        dry_run=dry_run,
        debug_report_path=args.debug_report,
    )

    # Print summary
    summary = results.get("summary", {})
    print("\n" + "=" * 60)
    print("PIPELINE SUMMARY")
    print("=" * 60)
    print(f"  Mode:              {results['mode']}")
    print(f"  Module:            {results['module']}")
    print(f"  Dry Run:           {dry_run}")
    print(f"  Elapsed:           {results.get('elapsed_seconds', '?')}s")
    print(f"  Total Issues:      {summary.get('total_issues', 'N/A')}")
    print(f"  Auto-fixable:      {summary.get('auto_fixable', 'N/A')}")
    print(f"  Fixed:             {summary.get('fixed', 'N/A')}")
    print(f"  Human Review:      {summary.get('needs_human_review', 'N/A')}")
    by_sev = summary.get("by_severity", {})
    if by_sev:
        print(f"  By Severity:       critical={by_sev.get('critical',0)}  high={by_sev.get('high',0)}  "
              f"medium={by_sev.get('medium',0)}  low={by_sev.get('low',0)}  info={by_sev.get('info',0)}")
    print("=" * 60)
    print(f"  Results saved to:  {pipeline.output_dir}/")
    print()

    # Exit with non-zero if critical issues found
    if by_sev.get("critical", 0) > 0 and dry_run:
        sys.exit(1)


if __name__ == "__main__":
    main()
