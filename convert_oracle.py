#!/usr/bin/env python3
"""
Oracle-to-BigQuery Conversion CLI — Converts Oracle PL/SQL to BigQuery SQL
and generates the full production folder structure for Jenkins/GitLab deployment.

Usage:
  # Convert a single Oracle SQL file
  python convert_oracle.py --input oracle_procs/my_proc.sql --module new_dashboard

  # Convert with LLM refinement
  python convert_oracle.py --input oracle_procs/my_proc.sql --module new_dashboard --use-llm

  # Convert and immediately scaffold into the repo
  python convert_oracle.py --input oracle_procs/my_proc.sql --module new_dashboard --apply

  # Convert all .sql files in a directory
  python convert_oracle.py --input-dir oracle_procs/ --module new_dashboard --apply

  # Dry-run: preview what would be generated (no files written)
  python convert_oracle.py --input oracle_procs/my_proc.sql --module new_dashboard --dry-run

  # Specify custom procedure name (default: derived from filename)
  python convert_oracle.py --input oracle_procs/my_proc.sql --module new_dashboard --proc-name sp_onef_new_refresh
"""
import argparse
import json
import os
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml
from converters.oracle_to_bq import OracleToBQConverter
from converters.scaffold_generator import ScaffoldGenerator
from models.llm_client import LLMClient


def main():
    parser = argparse.ArgumentParser(
        description="Convert Oracle PL/SQL to BigQuery SQL with full OneFiber deployment scaffold",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert a single Oracle procedure
  python convert_oracle.py --input my_oracle_proc.sql --module new_dashboard

  # Convert all Oracle files in a directory
  python convert_oracle.py --input-dir oracle_sql/ --module new_dashboard --apply

  # Preview without writing files
  python convert_oracle.py --input my_oracle_proc.sql --module new_dashboard --dry-run

  # Convert with LLM refinement
  python convert_oracle.py --input my_oracle_proc.sql --module new_dashboard --use-llm
        """,
    )

    parser.add_argument("--input", "-i", help="Path to a single Oracle SQL file")
    parser.add_argument("--input-dir", "-d", help="Directory containing Oracle SQL files")
    parser.add_argument("--module", "-m", required=True, help="Target module name (e.g. 'new_dashboard')")
    parser.add_argument("--proc-name", "-p", help="Override procedure name (default: from filename)")
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), "configs", "config.yaml"),
        help="Path to config.yaml",
    )
    parser.add_argument("--apply", action="store_true", help="Write files to the repo (scaffold)")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview only (default)")
    parser.add_argument("--use-llm", action="store_true", help="Use LLM to refine conversion")
    parser.add_argument("--output-dir", help="Custom output directory for reports")

    args = parser.parse_args()

    if not args.input and not args.input_dir:
        parser.error("Either --input or --input-dir is required")

    # Load config
    config = {}
    if os.path.exists(args.config):
        with open(args.config, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

    # Initialize LLM client if needed
    llm_client = None
    if args.use_llm:
        llm_client = LLMClient(config.get("llm", {}))

    # Initialize converter
    converter = OracleToBQConverter(config=config, llm_client=llm_client)

    # Collect input files
    input_files = []
    if args.input:
        input_files.append(args.input)
    elif args.input_dir:
        input_files = sorted(glob.glob(os.path.join(args.input_dir, "*.sql")))
        if not input_files:
            print(f"ERROR: No .sql files found in {args.input_dir}")
            sys.exit(1)

    # Resolve repo root
    agents_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(agents_dir, config.get("project", {}).get("repo_root", "..")))

    print(f"\n{'='*60}")
    print(f"Oracle → BigQuery Conversion")
    print(f"{'='*60}")
    print(f"  Module:     {args.module}")
    print(f"  Input:      {len(input_files)} file(s)")
    print(f"  Repo Root:  {repo_root}")
    print(f"  Apply:      {args.apply}")
    print(f"  LLM:        {args.use_llm}")
    print(f"{'='*60}\n")

    all_results = []

    for sql_file in input_files:
        if not os.path.exists(sql_file):
            print(f"  ✗ File not found: {sql_file}")
            continue

        # Read Oracle SQL
        with open(sql_file, "r", encoding="utf-8") as f:
            oracle_sql = f.read()

        # Determine procedure name
        proc_name = args.proc_name
        if not proc_name:
            proc_name = os.path.splitext(os.path.basename(sql_file))[0]
            # Add sp_ prefix if not present
            if not proc_name.startswith("sp_"):
                proc_name = f"sp_onef_{proc_name}"

        print(f"  Converting: {os.path.basename(sql_file)} → {proc_name}")

        # Run conversion
        result = converter.convert(
            oracle_sql=oracle_sql,
            module_name=args.module,
            proc_name=proc_name,
            use_llm=args.use_llm,
        )

        all_results.append(result)

        # Print report
        report = result["report"]
        complexity = report["complexity"]
        print(f"    Complexity: {complexity.get('difficulty', 'N/A')} (score: {complexity.get('score', 0)})")
        print(f"    BQ SQL:     {report['bq_sql_lines']} lines")
        print(f"    Tables:     {report['total_tables_referenced']}")
        print(f"    DML ops:    {report['total_dml_operations']}")

        if report.get("functions_needing_manual_review"):
            print(f"    ⚠️  Manual review needed for: {', '.join(report['functions_needing_manual_review'])}")

        # Write scaffold if --apply
        if args.apply:
            scaffold = ScaffoldGenerator(repo_root)
            scaffold_result = scaffold.generate(args.module, result)
            print(f"    ✓ Scaffold: {scaffold_result['total_files']} files created")
            for fp in scaffold_result["files_created"]:
                rel = os.path.relpath(fp, repo_root)
                print(f"      + {rel}")
        else:
            print(f"    → Dry-run: use --apply to write {len(report['files_generated'])} files")

        print()

    # Save conversion report
    output_dir = args.output_dir or os.path.join(agents_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    report_path = os.path.join(output_dir, f"oracle_conversion_{args.module}.json")
    with open(report_path, "w", encoding="utf-8") as f:
        # Extract serializable parts
        serializable = []
        for r in all_results:
            serializable.append({
                "report": r["report"],
                "analysis": r["analysis"],
            })
        json.dump(serializable, f, indent=2, default=str)

    print(f"{'='*60}")
    print(f"Conversion complete!")
    print(f"  Report saved: {report_path}")
    if args.apply:
        print(f"  Module scaffold: {os.path.join(repo_root, args.module)}")
    print(f"{'='*60}\n")

    # Print review checklist
    for result in all_results:
        checklist = result["report"].get("review_checklist", [])
        if checklist:
            print("Review Checklist:")
            for item in checklist:
                print(f"  {item}")
            print()


if __name__ == "__main__":
    main()
