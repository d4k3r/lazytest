#!/usr/bin/env python3
import os
import csv
import time
import json
import glob
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# CONFIG
# ============================================================

# Root folder containing model folders:
# generated_tests/
#   qwen_3.5_9b/
#     run_1_...
#     run_2_...
#   qwen_coder_next/
#     run_1_...
#     ...
BASE_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "testing", "generated_tests")
)

MODEL_DIRS = [
    "qwen_3.5",
    "qwen_3.5_cyankiwi",
    "qwen_3.5_9b",
    "qwen_3.5_9b_cyankiwi",
    "devstral_cyankiwi",
    "qwen_coder_next",
]

# Real local path to the checked-out TheAlgorithms repository.
# This is the path pytest/cov will actually use.
REPO_ROOT = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..", "testing", "repos_for_testing", "TheAlgorithms",
    )
)

# Folder inside each run folder where generated tests are stored.
# Example:
# run_3_no_repeat_mut_notfixed_long_trace/
#   TheAlgorithms/
#     boolean_algebra/
#       test_not_gate.py
GENERATED_REPO_FOLDER = "TheAlgorithms"

MAX_WORKERS = 14

# Original metrics CSV pattern.
# This should match metrics_qwen_coder_TheAlgorithms.csv
INPUT_CSV_GLOB = "metrics_qwen_coder_TheAlgorithms.csv"

# New output CSV. Old files will not be overwritten.
OUTPUT_CSV_NAME = "metrics_statement_branch_coverage.csv"

PYTEST_TIMEOUT_SECONDS = 10
SUBPROCESS_TIMEOUT_SECONDS = 45

# If True:
# - if pytest fails, coverage is not counted
# - file_cov_pct is set to 0.0
#
# This is stricter and probably better for your dissertation because failed
# generated tests should not receive partial coverage credit.
ONLY_COUNT_COVERAGE_IF_PYTEST_PASSES = True

# Extra columns appended to the original CSV.
EXTRA_COLUMNS = [
    "branch_cov_pct",
    "combined_cov_pct",
    "covered_branches",
    "num_branches",
    "missing_branches",
    "partial_branches",
    "pytest_exit_code",
    "coverage_eval_status",
]


# ============================================================
# HELPERS
# ============================================================

def pad_row(row, min_len=10):
    """Ensure row has at least the expected original CSV length."""
    if len(row) < min_len:
        return row + [""] * (min_len - len(row))
    return row


def append_note(row, text):
    """Append diagnostic information to the notes column."""
    row = pad_row(row)
    old_note = str(row[9]).strip()

    if old_note:
        row[9] = f"{old_note}; {text}"
    else:
        row[9] = text

    return row


def round_or_blank(value, digits=2):
    if value is None or value == "":
        return ""
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return ""


def int_or_blank(value):
    if value is None or value == "":
        return ""
    try:
        return int(value)
    except (TypeError, ValueError):
        return ""


def blank_extra(pytest_exit_code="", eval_status=""):
    """Blank values for the appended EXTRA_COLUMNS."""
    return ["", "", "", "", "", "", pytest_exit_code, eval_status]


def get_repo_relative_path(src_file):
    """
    Convert src_file into a path relative to TheAlgorithms.

    This deliberately ignores the old absolute base path from the CSV.

    Example:
    /old/checkout/TheAlgorithms/boolean_algebra/not_gate.py
    -> boolean_algebra/not_gate.py

    Also supports:
    TheAlgorithms/boolean_algebra/not_gate.py
    -> boolean_algebra/not_gate.py

    boolean_algebra/not_gate.py
    -> boolean_algebra/not_gate.py
    """
    src_file = str(src_file).strip().strip('"').strip("'")
    src_file = src_file.replace("\\", "/")

    marker = "TheAlgorithms/"

    if marker in src_file:
        rel_path = src_file.split(marker, 1)[-1]
    elif os.path.isabs(src_file):
        # Fallback only. This will use the current REPO_ROOT if the absolute path
        # actually exists on this machine.
        rel_path = os.path.relpath(src_file, REPO_ROOT)
    else:
        rel_path = src_file

    rel_path = rel_path.strip("/")
    return os.path.normpath(rel_path)


def find_target_file_coverage(data, target_rel_path):
    """
    Find the target source file inside Coverage.py JSON.

    We match by repository-relative path, not just basename, because different
    folders can contain files with the same name.
    """
    norm_target = os.path.normpath(target_rel_path).replace("\\", "/")

    for filepath, fdata in data.get("files", {}).items():
        norm_filepath = os.path.normpath(filepath).replace("\\", "/")
        stripped_filepath = norm_filepath.lstrip("./")

        if stripped_filepath == norm_target:
            return fdata

        if stripped_filepath.endswith("/" + norm_target):
            return fdata

        if norm_target.endswith("/" + stripped_filepath):
            return fdata

    return None


def extract_target_metrics(summary):
    """
    Extract statement, branch and combined coverage values.

    With --cov-branch enabled:
    - percent_statements_covered = statement/file coverage
    - percent_branches_covered = branch coverage
    - percent_covered = combined statement + branch coverage
    """
    statement_cov = summary.get(
        "percent_statements_covered",
        summary.get("percent_covered", 0.0)
    )

    branch_cov = summary.get("percent_branches_covered", "")
    combined_cov = summary.get("percent_covered", "")

    return {
        "statement_cov": round_or_blank(statement_cov),
        "branch_cov": round_or_blank(branch_cov),
        "combined_cov": round_or_blank(combined_cov),
        "covered_branches": int_or_blank(summary.get("covered_branches", "")),
        "num_branches": int_or_blank(summary.get("num_branches", "")),
        "missing_branches": int_or_blank(summary.get("missing_branches", "")),
        "partial_branches": int_or_blank(summary.get("num_partial_branches", "")),
    }


def cleanup_coverage_files(cov_db, cov_json):
    """Remove temporary coverage files created by one pytest run."""
    for path in [cov_json, cov_db, cov_db + ".db"]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    # Sometimes coverage.py can create suffixed files.
    for path in glob.glob(cov_db + "*"):
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


def find_input_csv(run_dir):
    """
    Find the original metrics CSV in a run folder.

    It intentionally ignores files like:
    - metrics_fixed_coverage.csv
    - metrics_statement_branch_coverage.csv
    - anything with fixed/coverage/branch/statement in the name
    """
    candidates = glob.glob(os.path.join(run_dir, INPUT_CSV_GLOB))

    filtered = []
    banned_words = [
        "fixed",
        "coverage",
        "branch",
        "statement",
        "mutation_score",
        "mut_score",
    ]

    for path in candidates:
        name = os.path.basename(path).lower()
        if any(word in name for word in banned_words):
            continue
        filtered.append(path)

    if len(filtered) == 1:
        return filtered[0]

    if len(filtered) > 1:
        print(f"  [WARNING] Multiple possible input CSVs in {run_dir}:")
        for p in filtered:
            print(f"    - {os.path.basename(p)}")
        print(f"  [USING] {os.path.basename(filtered[0])}")
        return filtered[0]

    return None


def get_col_index(header, preferred_name, fallback_index):
    """
    Use header name if available, otherwise fallback to index.

    Your current CSV has:
    repo, source_file, status, gen_time_s, chars, n_tests,
    attempts, file_cov_pct, repo_cov_pct, notes
    """
    try:
        return header.index(preferred_name)
    except ValueError:
        return fallback_index


# ============================================================
# MAIN EVALUATION
# ============================================================

def evaluate_test(row, run_dir, col):
    row = pad_row(row)

    repo_from_csv = row[col["repo"]]
    src_file = row[col["source_file"]]
    status = row[col["status"]]

    if status != "ok":
        return row + blank_extra(eval_status="skipped_non_ok_generation_status")

    rel_path = get_repo_relative_path(src_file)
    base = os.path.splitext(os.path.basename(rel_path))[0]

    # Primary expected location:
    # run_dir/TheAlgorithms/<same folders>/test_<module>.py
    candidate_test_file = os.path.join(
        run_dir,
        GENERATED_REPO_FOLDER,
        os.path.dirname(rel_path),
        f"test_{base}.py"
    )

    # Fallback to the repo name from CSV, just in case.
    fallback_test_file = os.path.join(
        run_dir,
        repo_from_csv,
        os.path.dirname(rel_path),
        f"test_{base}.py"
    )

    if os.path.exists(candidate_test_file):
        test_file = candidate_test_file
    else:
        test_file = fallback_test_file

    if not os.path.exists(test_file):
        row[col["file_cov_pct"]] = 0.0
        row = append_note(row, f"Test file not found on disk: {test_file}")
        return row + blank_extra(eval_status="missing_test_file")

    cov_json = f"{test_file}.branch_cov.json"
    cov_db = f"{test_file}.branch_coverage"

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["COVERAGE_FILE"] = cov_db

    cmd = [
        "pytest",
        test_file,
        "-o", "addopts=",
        f"--cov={REPO_ROOT}",
        "--cov-branch",
        f"--cov-report=json:{cov_json}",
        "-q",
        f"--timeout={PYTEST_TIMEOUT_SECONDS}",
        "--disable-warnings",
        "-p", "no:cacheprovider",
    ]

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
            cwd=REPO_ROOT,
        )

        pytest_exit_code = result.returncode

        if result.returncode != 0:
            row = append_note(row, f"pytest failed during coverage eval, exit={result.returncode}")

            if ONLY_COUNT_COVERAGE_IF_PYTEST_PASSES:
                row[col["file_cov_pct"]] = 0.0
                return row + blank_extra(
                    pytest_exit_code=pytest_exit_code,
                    eval_status="pytest_failed_coverage_not_counted",
                )

        if not os.path.exists(cov_json):
            row[col["file_cov_pct"]] = 0.0
            row = append_note(row, "Coverage JSON not created")
            return row + blank_extra(
                pytest_exit_code=pytest_exit_code,
                eval_status="coverage_json_missing",
            )

        with open(cov_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        target_fdata = find_target_file_coverage(data, rel_path)

        if target_fdata is None:
            row[col["file_cov_pct"]] = 0.0
            row = append_note(row, f"Target file not found in coverage JSON: {rel_path}")
            return row + blank_extra(
                pytest_exit_code=pytest_exit_code,
                eval_status="target_file_missing_from_coverage_json",
            )

        file_summary = target_fdata.get("summary", {})
        metrics = extract_target_metrics(file_summary)

        # Keep the old meaning:
        # file_cov_pct = target-file statement coverage.
        row[col["file_cov_pct"]] = metrics["statement_cov"]

        # Important:
        # Do NOT change repo_cov_pct.
        # In the original per-file CSV it is not analytically useful because it
        # measures whole-repository coverage from one generated test file.
        # We leave it untouched as old diagnostic data.

        extra = [
            metrics["branch_cov"],
            metrics["combined_cov"],
            metrics["covered_branches"],
            metrics["num_branches"],
            metrics["missing_branches"],
            metrics["partial_branches"],
            pytest_exit_code,
            "ok" if result.returncode == 0 else "pytest_failed_but_coverage_read",
        ]

        return row + extra

    except subprocess.TimeoutExpired:
        row[col["file_cov_pct"]] = 0.0
        row = append_note(row, "Pytest timeout during branch coverage eval")

        if os.path.exists(test_file):
            zombie_path = test_file + ".zombie"
            try:
                os.rename(test_file, zombie_path)
            except OSError:
                pass

        return row + blank_extra(eval_status="pytest_timeout")

    except Exception as e:
        row = append_note(row, f"Eval error: {str(e)}")
        return row + blank_extra(eval_status="eval_exception")

    finally:
        cleanup_coverage_files(cov_db, cov_json)


def process_directory(run_dir):
    folder_name = os.path.basename(run_dir)

    csv_in = find_input_csv(run_dir)
    csv_out = os.path.join(run_dir, OUTPUT_CSV_NAME)

    if csv_in is None:
        print(f"  [SKIP] No original metrics CSV found in: {run_dir}")
        return

    print(f"\n[{folder_name}] Input:  {os.path.basename(csv_in)}")
    print(f"[{folder_name}] Output: {os.path.basename(csv_out)}")

    with open(csv_in, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    col = {
        "repo": get_col_index(header, "repo", 0),
        "source_file": get_col_index(header, "source_file", 1),
        "status": get_col_index(header, "status", 2),
        "file_cov_pct": get_col_index(header, "file_cov_pct", 7),
        "repo_cov_pct": get_col_index(header, "repo_cov_pct", 8),
        "notes": get_col_index(header, "notes", 9),
    }

    output_header = header + EXTRA_COLUMNS

    # Preserve original row order.
    processed_rows = [None] * len(rows)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(evaluate_test, row, run_dir, col): idx
            for idx, row in enumerate(rows)
        }

        completed = 0

        for future in as_completed(futures):
            idx = futures[future]

            try:
                processed_rows[idx] = future.result()
            except Exception as e:
                bad_row = pad_row(rows[idx])
                bad_row = append_note(bad_row, f"Unhandled future error: {str(e)}")
                processed_rows[idx] = bad_row + blank_extra(eval_status="unhandled_future_error")

            completed += 1

            if completed % 100 == 0:
                print(f"  [{folder_name}] Checked {completed}/{len(rows)} tests...", flush=True)

    with open(csv_out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(output_header)
        writer.writerows(processed_rows)

    print(f"[{folder_name}] DONE -> {csv_out}")


def main():
    if not os.path.exists(BASE_ROOT):
        print(f"ERROR: BASE_ROOT not found: {BASE_ROOT}")
        return

    if not os.path.exists(REPO_ROOT):
        print(f"ERROR: REPO_ROOT not found: {REPO_ROOT}")
        return

    start_time = time.time()

    for model_dir in MODEL_DIRS:
        base_dir = os.path.join(BASE_ROOT, model_dir)

        if not os.path.exists(base_dir):
            print(f"[WARNING] Model folder not found, skipping: {base_dir}")
            continue

        run_folders = sorted([
            f for f in os.listdir(base_dir)
            if os.path.isdir(os.path.join(base_dir, f)) and f.startswith("run_")
        ])

        print("\n" + "=" * 70)
        print(f"MODEL: {model_dir} | run folders found: {len(run_folders)}", flush=True)
        print("=" * 70)

        for folder in run_folders:
            process_directory(os.path.join(base_dir, folder))

    elapsed = time.time() - start_time

    print("\n" + "=" * 70)
    print("ALL DONE")
    print(f"Total time: {int(elapsed // 60)}m {int(elapsed % 60)}s")
    print("=" * 70)


if __name__ == "__main__":
    main()
