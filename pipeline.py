"""CLI entry point — trigger pipeline runs, approve gates, inspect state."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def cmd_trigger(args: argparse.Namespace) -> None:
    from core.orchestrator import PipelineOrchestrator
    orch = PipelineOrchestrator()
    raw  = args.input or ""
    if args.input_file:
        raw = Path(args.input_file).read_text()

    run = orch.trigger(
        raw_input=raw,
        jira_issue_key=args.issue_key,
        legacy_code=Path(args.legacy_code).read_text() if args.legacy_code else None,
        legacy_dialect=args.legacy_dialect,
    )
    print(f"Pipeline started — run_id: {run.run_id}")
    print(f"Jira issue: {run.jira_issue}")

    if args.wait:
        from core import state_db
        while True:
            row = state_db.get_run(run.run_id)
            if not row:
                break
            print(f"  [{row['stage']}] {row['status']}")
            if row["status"] in ("waiting_review", "completed", "failed"):
                break
            time.sleep(3)


def cmd_approve(args: argparse.Namespace) -> None:
    from core.orchestrator import PipelineOrchestrator
    orch = PipelineOrchestrator()
    ok   = orch.approve(args.run_id, args.reviewer, args.notes or "")
    print(f"{'Approved' if ok else 'Failed — check run status'}")


def cmd_reject(args: argparse.Namespace) -> None:
    from core.orchestrator import PipelineOrchestrator
    orch = PipelineOrchestrator()
    ok   = orch.reject(args.run_id, args.reviewer, args.notes or "")
    print(f"{'Rejected' if ok else 'Failed — check run status'}")


def cmd_status(args: argparse.Namespace) -> None:
    from core import state_db
    if args.run_id:
        row = state_db.get_run(args.run_id)
        if not row:
            print("Run not found")
            return
        print(json.dumps(row, indent=2, default=str))
    else:
        runs = state_db.get_recent_runs(args.limit)
        for r in runs:
            print(f"  {r['run_id'][:8]}  [{r['stage']:25s}]  {r['status']:15s}  {r['jira_issue']}")


def cmd_artifacts(args: argparse.Namespace) -> None:
    from core import state_db
    arts = state_db.get_run_artifacts(args.run_id)
    for a in arts:
        print(f"\n{'='*60}")
        print(f"File: {a['filename']}  type={a['artifact_type']}")
        if args.show_content:
            print(a["content"])


def main() -> None:
    parser = argparse.ArgumentParser(description="SQL-Gen Agentic Pipeline CLI")
    sub    = parser.add_subparsers(dest="command")

    # trigger
    p_trig = sub.add_parser("trigger", help="Start a new pipeline run")
    p_trig.add_argument("--input",        help="Raw requirements text")
    p_trig.add_argument("--input-file",   help="Path to requirements text file")
    p_trig.add_argument("--issue-key",    help="Jira issue key to read from")
    p_trig.add_argument("--legacy-code",  help="Path to legacy SQL/ETL file for conversion")
    p_trig.add_argument("--legacy-dialect", default="teradata")
    p_trig.add_argument("--wait",         action="store_true", help="Wait for first review gate")

    # approve
    p_app = sub.add_parser("approve", help="Approve a review gate")
    p_app.add_argument("run_id")
    p_app.add_argument("--reviewer", required=True)
    p_app.add_argument("--notes", default="")

    # reject
    p_rej = sub.add_parser("reject", help="Reject a review gate")
    p_rej.add_argument("run_id")
    p_rej.add_argument("--reviewer", required=True)
    p_rej.add_argument("--notes", default="")

    # status
    p_st = sub.add_parser("status", help="Show run status")
    p_st.add_argument("run_id", nargs="?")
    p_st.add_argument("--limit", type=int, default=10)

    # artifacts
    p_art = sub.add_parser("artifacts", help="List/show artifacts for a run")
    p_art.add_argument("run_id")
    p_art.add_argument("--show-content", action="store_true")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    dispatch = {
        "trigger":   cmd_trigger,
        "approve":   cmd_approve,
        "reject":    cmd_reject,
        "status":    cmd_status,
        "artifacts": cmd_artifacts,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
