#!/usr/bin/env python3
"""Verify compact public result evidence against integer counts and README values."""

import argparse
import csv
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV = PROJECT_ROOT / "results" / "main_comparisons.csv"
DEFAULT_README = PROJECT_ROOT / "README.md"
EXPECTED_ROUTES = ("Qwen 27B", "Qwen 9B", "Qwen 9B AWQ")
EXPECTED_TARGETS = 1144
TWO_PLACES = Decimal("0.01")


def percentage(passing: int, targets: int) -> Decimal:
    return (Decimal(passing) * Decimal(100) / Decimal(targets)).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate the six-row public comparison CSV and README table."
    )
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--readme", type=Path, default=DEFAULT_README)
    return parser.parse_args(argv)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 6:
        raise ValueError(f"expected 6 public rows, found {len(rows)}")
    return rows


def read_readme_comparisons(path: Path) -> dict[str, tuple[Decimal, Decimal, Decimal]]:
    row_pattern = re.compile(
        r"^\|\s*(Qwen 27B|Qwen 9B|Qwen 9B AWQ)\s*\|"
        r"\s*([0-9]+\.[0-9]{2})%\s*\|"
        r"\s*([0-9]+\.[0-9]{2})%\s*\|"
        r"\s*\+([0-9]+\.[0-9]{2}) pp\s*\|$"
    )
    found = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = row_pattern.match(line)
        if match:
            found[match.group(1)] = tuple(Decimal(value) for value in match.groups()[1:])
    if tuple(found) != EXPECTED_ROUTES:
        raise ValueError(f"README matched-comparison rows are missing or reordered: {tuple(found)}")
    return found


def verify(csv_path: Path, readme_path: Path) -> None:
    rows = read_rows(csv_path)
    readme = read_readme_comparisons(readme_path)
    grouped: dict[str, dict[str, dict[str, str]]] = {}

    for row in rows:
        targets = int(row["target_count"])
        passing = int(row["final_passing_count"])
        reported = Decimal(row["final_pass_percentage"])
        if targets != EXPECTED_TARGETS:
            raise ValueError(f"{row['public_condition_label']}: target_count={targets}, expected 1144")
        recomputed = percentage(passing, targets)
        if reported != recomputed:
            raise ValueError(
                f"{row['public_condition_label']}: percentage {reported} != {recomputed} from counts"
            )
        grouped.setdefault(row["route"], {})[row["pipeline_type"]] = row

    if tuple(grouped) != EXPECTED_ROUTES:
        raise ValueError(f"unexpected route set or ordering: {tuple(grouped)}")

    for route in EXPECTED_ROUTES:
        conditions = grouped[route]
        baseline = conditions.get("generic baseline")
        lazytest = conditions.get("repository-aware LazyTest")
        if baseline is None or lazytest is None:
            raise ValueError(f"{route}: expected one baseline and one LazyTest row")
        baseline_pct = Decimal(baseline["final_pass_percentage"])
        lazytest_pct = Decimal(lazytest["final_pass_percentage"])
        difference = (lazytest_pct - baseline_pct).quantize(TWO_PLACES)
        recorded_difference = Decimal(lazytest["matched_difference_pp"])
        if difference != recorded_difference:
            raise ValueError(f"{route}: difference {recorded_difference} != {difference}")
        if baseline["matched_difference_pp"].strip():
            raise ValueError(f"{route}: baseline row must not repeat the matched difference")
        if readme[route] != (baseline_pct, lazytest_pct, difference):
            raise ValueError(f"{route}: README values {readme[route]} drift from public CSV")

    print("Public result evidence verified: 6 rows, 1,144 targets, 3 matched differences.")


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        verify(args.csv.resolve(), args.readme.resolve())
    except (OSError, KeyError, ValueError, csv.Error) as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
