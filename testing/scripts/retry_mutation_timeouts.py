#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[2]

DEFAULT_GENERATED_ROOT = PROJECT_ROOT / "testing" / "generated_tests"
DEFAULT_REPO_ROOT = PROJECT_ROOT / "testing" / "repos_for_testing" / "TheAlgorithms"
DEFAULT_MUTATION_SCRIPT = SCRIPT_PATH.parent / "mutation_score.py"

DEFAULT_SOURCE_CSV_NAME = "mutation_cosmic_ray.csv"
DEFAULT_RETRY_CSV_NAME = "mutation_cosmic_ray_timeout_retry.csv"
DEFAULT_TARGETS_NAME = "timeout_targets_retry.txt"

DEFAULT_RETRY_ALL_CSV_NAME = "mutation_cosmic_ray_timeout_retry_all.csv"
DEFAULT_RETRY_SUMMARY_NAME = "mutation_timeout_retry_summary.json"


FIELDNAMES_FALLBACK = [
    "model",
    "run",
    "repo",
    "source_file",
    "test_file",
    "source_exists",
    "test_exists",
    "baseline_status",
    "baseline_rc",
    "baseline_elapsed_s",
    "mutation_status",
    "failure_category",
    "mutation_score_viable",
    "mutation_score_raw",
    "viable_mutants",
    "total_mutants",
    "mutants_killed",
    "mutants_survived",
    "mutants_incompetent",
    "mutants_timeout",
    "mutants_other",
    "cosmic_init_rc",
    "cosmic_exec_rc",
    "cosmic_init_elapsed_s",
    "cosmic_exec_elapsed_s",
    "elapsed_s",
    "cosmic_table",
    "cosmic_outcome_column",
    "notes",
]


def natural_key(path_or_name: str | Path) -> list[Any]:
    import re

    text = str(path_or_name)
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", text)
    ]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []

    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        return

    fieldnames = list(rows[0].keys()) if rows else FIELDNAMES_FALLBACK

    # Ensure stable order for mutation_score.py-compatible CSVs.
    if set(FIELDNAMES_FALLBACK).issubset(set(fieldnames)):
        fieldnames = FIELDNAMES_FALLBACK

    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})

    tmp_path.replace(path)


def discover_models(generated_root: Path, models: list[str] | None) -> list[str]:
    if models:
        return models

    return sorted(
        [p.name for p in generated_root.iterdir() if p.is_dir()],
        key=natural_key,
    )


def discover_runs(model_dir: Path, run_pattern: str) -> list[Path]:
    return sorted(
        [p for p in model_dir.iterdir() if p.is_dir() and p.match(run_pattern)],
        key=natural_key,
    )


def collect_timeout_targets(
    *,
    run_dir: Path,
    source_csv_name: str,
    targets_name: str,
) -> tuple[Path, list[str]]:
    source_csv = run_dir / source_csv_name
    targets_path = run_dir / targets_name

    rows = read_csv(source_csv)

    targets = sorted(
        {
            row["source_file"]
            for row in rows
            if row.get("mutation_status") == "cosmic_exec_timeout"
            and row.get("source_file")
        },
        key=natural_key,
    )

    if targets:
        targets_path.write_text("\n".join(targets) + "\n", encoding="utf-8")
    else:
        if targets_path.exists():
            targets_path.unlink()

    return targets_path, targets


def summarise_retry_csv(path: Path) -> dict[str, Any]:
    rows = read_csv(path)
    status_counts = Counter(row.get("mutation_status", "unknown") or "unknown" for row in rows)

    scores = [
        float(row["mutation_score_viable"])
        for row in rows
        if row.get("mutation_status") == "mutation_processed"
        and str(row.get("mutation_score_viable", "")).strip() != ""
    ]

    mean_score = round(sum(scores) / len(scores), 2) if scores else ""

    return {
        "retry_rows": len(rows),
        "retry_processed": status_counts.get("mutation_processed", 0),
        "retry_timeouts": status_counts.get("cosmic_exec_timeout", 0),
        "retry_baseline_failed": status_counts.get("baseline_failed", 0),
        "mean_retry_mutation_score_viable": mean_score,
        "status_counts": dict(status_counts),
    }


def run_retry_for_run(
    *,
    args: argparse.Namespace,
    model: str,
    run_dir: Path,
    targets_path: Path,
) -> int:
    # Avoid overwriting the main combined CSV produced by the main pass.
    throwaway_combined_name = f"_mutation_retry_latest_{model}_{run_dir.name}.csv"

    cmd = [
        sys.executable,
        str(args.mutation_script),
        "--generated-root",
        str(args.generated_root),
        "--repo-root",
        str(args.repo_root),
        "--models",
        model,
        "--run-pattern",
        run_dir.name,
        "--targets-file",
        str(targets_path),
        "--max-workers",
        str(args.max_workers),
        "--cosmic-exec-timeout",
        str(args.cosmic_exec_timeout),
        "--per-test-timeout",
        str(args.per_test_timeout),
        "--save-every",
        str(args.save_every),
        "--progress-every",
        str(args.progress_every),
        "--out-csv-name",
        args.retry_csv_name,
        "--combined-csv-name",
        throwaway_combined_name,
    ]

    if args.rerun_retry:
        cmd.append("--rerun")

    if args.debug:
        cmd.append("--debug")

    print("\nRunning retry command:")
    print(" ".join(str(part) for part in cmd), flush=True)

    if args.dry_run:
        return 0

    env = os.environ.copy()

    if args.tmpdir:
        Path(args.tmpdir).mkdir(parents=True, exist_ok=True)
        env["TMPDIR"] = str(args.tmpdir)

    completed = subprocess.run(cmd, env=env)
    return completed.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Retry only Cosmic Ray timeout cases from LazyTest mutation runs. "
            "Reads mutation_cosmic_ray.csv from each run folder and writes "
            "mutation_cosmic_ray_timeout_retry.csv next to it."
        )
    )

    parser.add_argument(
        "--generated-root",
        type=Path,
        default=DEFAULT_GENERATED_ROOT,
        help=f"Root containing model folders. Default: {DEFAULT_GENERATED_ROOT}",
    )

    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help=f"Original repository root. Default: {DEFAULT_REPO_ROOT}",
    )

    parser.add_argument(
        "--mutation-script",
        type=Path,
        default=DEFAULT_MUTATION_SCRIPT,
        help=f"Path to mutation_score.py. Default: {DEFAULT_MUTATION_SCRIPT}",
    )

    parser.add_argument(
        "--models",
        nargs="*",
        default=None,
        help="Model folder names to process. If omitted, auto-discovers all model folders.",
    )

    parser.add_argument(
        "--run-pattern",
        default="run*",
        help="Run folder glob pattern. Default: run*",
    )

    parser.add_argument(
        "--source-csv-name",
        default=DEFAULT_SOURCE_CSV_NAME,
        help=f"Main pass CSV name. Default: {DEFAULT_SOURCE_CSV_NAME}",
    )

    parser.add_argument(
        "--retry-csv-name",
        default=DEFAULT_RETRY_CSV_NAME,
        help=f"Retry output CSV name. Default: {DEFAULT_RETRY_CSV_NAME}",
    )

    parser.add_argument(
        "--targets-name",
        default=DEFAULT_TARGETS_NAME,
        help=f"Temporary timeout targets file name. Default: {DEFAULT_TARGETS_NAME}",
    )

    parser.add_argument(
        "--max-workers",
        type=int,
        default=40,
        help="Workers for retry pass. Default: 40",
    )

    parser.add_argument(
        "--cosmic-exec-timeout",
        type=int,
        default=900,
        help="Cosmic Ray exec timeout in seconds for retry pass. Default: 900",
    )

    parser.add_argument(
        "--per-test-timeout",
        type=int,
        default=20,
        help="pytest-timeout per-test timeout. Default: 20",
    )

    parser.add_argument(
        "--save-every",
        type=int,
        default=5,
        help="Save retry CSV every N completed tasks. Default: 5",
    )

    parser.add_argument(
        "--progress-every",
        type=int,
        default=5,
        help="Print progress every N completed tasks. Default: 5",
    )

    parser.add_argument(
        "--tmpdir",
        type=Path,
        default=None,
        help="Optional TMPDIR for mutation_score.py temporary repository copies.",
    )

    parser.add_argument(
        "--rerun-retry",
        action="store_true",
        help="Ignore existing retry CSV files and recompute retry results.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover timeout targets but do not run retry mutation testing.",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Pass --debug through to mutation_score.py.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    args.generated_root = args.generated_root.expanduser().resolve()
    args.repo_root = args.repo_root.expanduser().resolve()
    args.mutation_script = args.mutation_script.expanduser().resolve()

    if not args.generated_root.exists():
        print(f"ERROR: generated root not found: {args.generated_root}", file=sys.stderr)
        return 1

    if not args.repo_root.exists():
        print(f"ERROR: repo root not found: {args.repo_root}", file=sys.stderr)
        return 1

    if not args.mutation_script.exists():
        print(f"ERROR: mutation script not found: {args.mutation_script}", file=sys.stderr)
        return 1

    models = discover_models(args.generated_root, args.models)

    print("=" * 80)
    print("LazyTest Cosmic Ray timeout retry")
    print("=" * 80)
    print(f"Generated root:       {args.generated_root}")
    print(f"Repo root:            {args.repo_root}")
    print(f"Mutation script:      {args.mutation_script}")
    print(f"Models:               {models}")
    print(f"Run pattern:          {args.run_pattern}")
    print(f"Source CSV:           {args.source_csv_name}")
    print(f"Retry CSV:            {args.retry_csv_name}")
    print(f"Retry workers:        {args.max_workers}")
    print(f"Retry exec timeout:   {args.cosmic_exec_timeout}s")
    print("=" * 80)

    all_retry_rows: list[dict[str, str]] = []
    summary: list[dict[str, Any]] = []
    total_targets = 0
    failures = 0

    for model in models:
        model_dir = args.generated_root / model

        if not model_dir.exists():
            print(f"\n[SKIP] model not found: {model}")
            continue

        run_dirs = discover_runs(model_dir, args.run_pattern)

        if not run_dirs:
            print(f"\n[SKIP] no runs for model: {model}")
            continue

        for run_dir in run_dirs:
            source_csv = run_dir / args.source_csv_name

            if not source_csv.exists():
                print(f"[SKIP] {model}/{run_dir.name}: source CSV not found")
                continue

            targets_path, targets = collect_timeout_targets(
                run_dir=run_dir,
                source_csv_name=args.source_csv_name,
                targets_name=args.targets_name,
            )

            if not targets:
                print(f"[SKIP] {model}/{run_dir.name}: no timeout targets")
                continue

            total_targets += len(targets)

            print(
                f"\n[RETRY] {model}/{run_dir.name}: "
                f"{len(targets)} timeout targets"
            )

            rc = run_retry_for_run(
                args=args,
                model=model,
                run_dir=run_dir,
                targets_path=targets_path,
            )

            if rc != 0:
                failures += 1
                print(f"[WARN] retry command failed for {model}/{run_dir.name} with rc={rc}")

            retry_csv = run_dir / args.retry_csv_name
            retry_rows = read_csv(retry_csv)
            all_retry_rows.extend(retry_rows)

            retry_summary = summarise_retry_csv(retry_csv)
            retry_summary.update(
                {
                    "model": model,
                    "run": run_dir.name,
                    "original_timeout_targets": len(targets),
                    "retry_csv": str(retry_csv),
                }
            )
            summary.append(retry_summary)

    combined_retry_csv = args.generated_root / DEFAULT_RETRY_ALL_CSV_NAME
    summary_json = args.generated_root / DEFAULT_RETRY_SUMMARY_NAME

    if all_retry_rows:
        write_csv(combined_retry_csv, all_retry_rows)
        print(f"\nCombined retry CSV saved to: {combined_retry_csv}")

    summary_payload = {
        "total_original_timeout_targets": total_targets,
        "failed_retry_invocations": failures,
        "retry_exec_timeout_s": args.cosmic_exec_timeout,
        "retry_workers": args.max_workers,
        "per_test_timeout_s": args.per_test_timeout,
        "runs": summary,
    }

    summary_json.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")
    print(f"Retry summary saved to: {summary_json}")
    print(json.dumps(summary_payload, indent=2))

    if failures:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())