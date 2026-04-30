#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import shlex
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


# ==============================================================================
# User-editable defaults
# ==============================================================================

# Leave empty to auto-discover all model directories under testing/generated_tests.
# Or set manually, for example:
# MODELS = ["qwen_3.5", "gemini", "chatgpt"]
MODELS: list[str] = []

REPO_NAME = "TheAlgorithms"

# Conservative default because each task copies the repository and runs mutation
# testing. Increase on a strong server, but disk I/O can become the bottleneck.
DEFAULT_MAX_WORKERS = 7

DEFAULT_BASELINE_TIMEOUT = 60
DEFAULT_COSMIC_INIT_TIMEOUT = 60
DEFAULT_COSMIC_EXEC_TIMEOUT = 300
DEFAULT_PER_TEST_TIMEOUT = 20

DEFAULT_OUT_CSV_NAME = "mutation_cosmic_ray.csv"
DEFAULT_COMBINED_CSV_NAME = "mutation_cosmic_ray_all.csv"

DEBUG = False


# ==============================================================================
# Paths
# ==============================================================================

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[2]  # repository root if script is testing/scripts/...
DEFAULT_GENERATED_ROOT = PROJECT_ROOT / "testing" / "generated_tests"
DEFAULT_REPO_ROOT = PROJECT_ROOT / "testing" / "repos_for_testing" / REPO_NAME


# ==============================================================================
# CSV schema
# ==============================================================================

FIELDNAMES = [
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


TERMINAL_STATUSES = {
    "mutation_processed",
    "baseline_failed",
    "baseline_timeout",
    "source_not_found",
    "test_file_not_found",
    "cosmic_init_timeout",
    "cosmic_init_error",
    "cosmic_exec_timeout",
    "cosmic_exec_error",
    "cosmic_db_missing",
    "cosmic_db_parse_error",
    "no_mutants",
    "unexpected_error",
}


# ==============================================================================
# Utility functions
# ==============================================================================

def debug(msg: str) -> None:
    if DEBUG:
        print(msg, flush=True)


def natural_key(path_or_name: str | Path) -> list[Any]:
    text = str(path_or_name)
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", text)
    ]


def sanitize_note(text: str, limit: int = 500) -> str:
    text = (text or "").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def atomic_write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_suffix(path.suffix + ".tmp")

    with tmp_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()

        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDNAMES})

    tmp_path.replace(path)


def load_existing_results(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.exists():
        return {}

    existing: dict[tuple[str, str], dict[str, Any]] = {}

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            source_file = row.get("source_file", "")
            test_file = row.get("test_file", "")
            status = row.get("mutation_status", "")

            if source_file and test_file and status in TERMINAL_STATUSES:
                existing[(source_file, test_file)] = dict(row)

    return existing


def classify_failure(note: str) -> str:
    text = (note or "").lower()

    if "source file not found" in text:
        return "source_not_found"

    if "test file not found" in text:
        return "test_file_not_found"

    if "baseline timeout" in text:
        return "baseline_timeout"

    if "baseline test failed" in text:
        if "syntaxerror" in text:
            return "syntax_error"
        if "modulenotfounderror" in text or "no module named" in text:
            return "missing_dependency"
        if "importerror" in text:
            return "import_error"
        if "typeerror" in text:
            return "wrong_signature_type_error"
        if "assertionerror" in text or "failed" in text:
            return "assertion_failure"
        return "baseline_failure"

    if "cosmic ray init timeout" in text:
        return "cosmic_init_timeout"

    if "cosmic ray init error" in text:
        return "cosmic_init_error"

    if "cosmic ray exec timeout" in text:
        return "cosmic_exec_timeout"

    if "cosmic ray exec error" in text:
        return "cosmic_exec_error"

    if "session.sqlite not found" in text:
        return "cosmic_db_missing"

    if "sqlite" in text or "db parse" in text:
        return "cosmic_db_parse_error"

    if "0 mutants" in text or "no mutants" in text:
        return "no_mutants"

    if "timeout" in text:
        return "timeout"

    if "syntaxerror" in text:
        return "syntax_error"

    if "modulenotfounderror" in text or "no module named" in text:
        return "missing_dependency"

    if "importerror" in text:
        return "import_error"

    if "typeerror" in text:
        return "wrong_signature_type_error"

    if "assertionerror" in text:
        return "assertion_failure"

    if "error" in text or "exception" in text or "traceback" in text:
        return "other_runtime_error"

    return "none"


def run_subprocess(
    cmd: list[str],
    *,
    env: dict[str, str],
    cwd: Path,
    timeout: int,
    label: str,
) -> tuple[int, str, str, float]:
    """
    Run command with timeout and kill the whole process group on timeout.

    Returns:
        (returncode, stdout, stderr, elapsed_s)

    Return codes:
        -1 = timeout
        -2 = subprocess setup/runtime error
    """
    start = time.monotonic()
    proc: subprocess.Popen[str] | None = None

    try:
        proc = subprocess.Popen(
            cmd,
            env=env,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

        stdout, stderr = proc.communicate(timeout=timeout)
        elapsed = time.monotonic() - start
        return proc.returncode, stdout or "", stderr or "", elapsed

    except subprocess.TimeoutExpired:
        if proc is not None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass

            try:
                stdout, stderr = proc.communicate(timeout=5)
            except Exception:
                stdout, stderr = "", ""

        elapsed = time.monotonic() - start
        debug(f"[TIMEOUT] {label} timed out after {timeout}s")
        return -1, stdout or "", (stderr or "") + f"\nTIMEOUT after {timeout}s", elapsed

    except Exception as exc:
        elapsed = time.monotonic() - start
        debug(f"[ERROR] {label}: {exc}")
        return -2, "", str(exc), elapsed


def quote_sql_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def parse_cosmic_ray_db(db_path: Path) -> dict[str, Any]:
    """
    Parse a Cosmic Ray sqlite database and count mutation outcomes.

    The Cosmic Ray schema can differ across versions, so this searches for a
    table containing an outcome-like column.
    """
    result = {
        "ok": False,
        "table": "",
        "outcome_column": "",
        "killed": 0,
        "survived": 0,
        "incompetent": 0,
        "timeout": 0,
        "other": 0,
        "notes": "",
    }

    if not db_path.exists():
        result["notes"] = "session.sqlite not found"
        return result

    candidate_cols = [
        "test_outcome",
        "worker_outcome",
        "outcome",
        "status",
    ]

    best: dict[str, Any] | None = None

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]

        for table in tables:
            quoted_table = quote_sql_identifier(table)

            try:
                cursor.execute(f"PRAGMA table_info({quoted_table});")
                cols_original = [row[1] for row in cursor.fetchall()]
            except sqlite3.Error:
                continue

            cols_lower = {col.lower(): col for col in cols_original}

            for candidate in candidate_cols:
                if candidate not in cols_lower:
                    continue

                actual_col = cols_lower[candidate]
                quoted_col = quote_sql_identifier(actual_col)

                try:
                    cursor.execute(
                        f"SELECT {quoted_col}, COUNT(*) FROM {quoted_table} GROUP BY {quoted_col};"
                    )
                    grouped = cursor.fetchall()
                except sqlite3.Error:
                    continue

                counts = {
                    "killed": 0,
                    "survived": 0,
                    "incompetent": 0,
                    "timeout": 0,
                    "other": 0,
                }

                for outcome, count in grouped:
                    outcome_str = str(outcome or "").strip().upper()

                    if outcome_str == "KILLED":
                        counts["killed"] += int(count)
                    elif outcome_str == "SURVIVED":
                        counts["survived"] += int(count)
                    elif outcome_str == "INCOMPETENT":
                        counts["incompetent"] += int(count)
                    elif outcome_str in {"TIMEOUT", "TIMED_OUT"}:
                        counts["timeout"] += int(count)
                    else:
                        counts["other"] += int(count)

                total = sum(counts.values())
                known = (
                    counts["killed"]
                    + counts["survived"]
                    + counts["incompetent"]
                    + counts["timeout"]
                )

                if total == 0:
                    continue

                candidate_result = {
                    "ok": True,
                    "table": table,
                    "outcome_column": actual_col,
                    **counts,
                    "notes": "",
                    "total": total,
                    "known": known,
                }

                if best is None:
                    best = candidate_result
                else:
                    # Prefer the table with the most recognised mutation outcomes.
                    if candidate_result["known"] > best["known"]:
                        best = candidate_result
                    elif (
                        candidate_result["known"] == best["known"]
                        and candidate_result["total"] > best["total"]
                    ):
                        best = candidate_result

        conn.close()

    except sqlite3.Error as exc:
        result["notes"] = f"SQLite DB parse error: {exc}"
        return result

    if best is None:
        result["notes"] = "Could not find Cosmic Ray outcome table/column"
        return result

    result.update(best)
    result.pop("total", None)
    result.pop("known", None)
    return result


def calculate_scores(
    *,
    killed: int,
    survived: int,
    incompetent: int,
    timeout: int,
    other: int,
) -> dict[str, Any]:
    viable = killed + survived
    total = killed + survived + incompetent + timeout + other

    if viable > 0:
        score_viable = round((killed / viable) * 100.0, 2)
    else:
        score_viable = ""

    if total > 0:
        score_raw = round((killed / total) * 100.0, 2)
    else:
        score_raw = ""

    return {
        "viable_mutants": viable,
        "total_mutants": total,
        "mutation_score_viable": score_viable,
        "mutation_score_raw": score_raw,
    }


def find_cosmic_ray_binary(user_value: str) -> str:
    if user_value != "auto":
        return user_value

    found = shutil.which("cosmic-ray")
    if found:
        return found

    raise RuntimeError(
        "Could not find 'cosmic-ray' on PATH. Install it or pass --cosmic-ray-bin."
    )


def base_result(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": task["model"],
        "run": task["run"],
        "repo": REPO_NAME,
        "source_file": task["source_file"],
        "test_file": task["test_file"],
        "source_exists": str(task["source_abs"].exists()).lower(),
        "test_exists": str(task["test_abs"].exists()).lower(),
        "baseline_status": "",
        "baseline_rc": "",
        "baseline_elapsed_s": "",
        "mutation_status": "",
        "failure_category": "",
        "mutation_score_viable": "",
        "mutation_score_raw": "",
        "viable_mutants": "",
        "total_mutants": "",
        "mutants_killed": "",
        "mutants_survived": "",
        "mutants_incompetent": "",
        "mutants_timeout": "",
        "mutants_other": "",
        "cosmic_init_rc": "",
        "cosmic_exec_rc": "",
        "cosmic_init_elapsed_s": "",
        "cosmic_exec_elapsed_s": "",
        "elapsed_s": "",
        "cosmic_table": "",
        "cosmic_outcome_column": "",
        "notes": "",
    }


def finish_result(row: dict[str, Any], *, status: str, notes: str, started_at: float) -> dict[str, Any]:
    row["mutation_status"] = status
    row["notes"] = sanitize_note(notes)
    row["failure_category"] = classify_failure(notes)
    row["elapsed_s"] = round(time.monotonic() - started_at, 3)
    return row


# ==============================================================================
# Discovery
# ==============================================================================

def discover_models(generated_root: Path, cli_models: list[str] | None) -> list[str]:
    if cli_models:
        return cli_models

    if MODELS:
        return MODELS

    if not generated_root.exists():
        return []

    return sorted(
        [
            path.name
            for path in generated_root.iterdir()
            if path.is_dir()
        ],
        key=natural_key,
    )


def discover_runs(model_dir: Path, run_pattern: str) -> list[Path]:
    if not model_dir.exists():
        return []

    candidates = [
        path
        for path in model_dir.iterdir()
        if path.is_dir() and path.match(run_pattern)
    ]

    return sorted(candidates, key=natural_key)


def discover_tasks_for_run(
    *,
    model: str,
    run_dir: Path,
    repo_root: Path,
) -> list[dict[str, Any]]:
    generated_repo_root = run_dir / REPO_NAME

    if not generated_repo_root.exists():
        print(f"  [SKIP] Generated repo folder not found: {generated_repo_root}")
        return []

    tasks: list[dict[str, Any]] = []

    for test_abs in sorted(generated_repo_root.rglob("test_*.py"), key=natural_key):
        if "__pycache__" in test_abs.parts:
            continue

        rel_test_inside_repo = test_abs.relative_to(generated_repo_root)
        source_name = test_abs.stem.removeprefix("test_") + ".py"
        source_rel = rel_test_inside_repo.parent / source_name
        source_abs = repo_root / source_rel

        tasks.append(
            {
                "model": model,
                "run": run_dir.name,
                "run_dir": run_dir,
                "generated_repo_root": generated_repo_root,
                "source_file": source_rel.as_posix(),
                "test_file": (Path(REPO_NAME) / rel_test_inside_repo).as_posix(),
                "source_abs": source_abs,
                "test_abs": test_abs,
            }
        )

    return tasks


def load_targets(targets_file: Path | None) -> set[str] | None:
    if targets_file is None:
        return None

    if not targets_file.exists():
        raise FileNotFoundError(f"Targets file not found: {targets_file}")

    targets = {
        line.strip()
        for line in targets_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    return targets


def filter_tasks(
    tasks: list[dict[str, Any]],
    *,
    targets: set[str] | None,
    max_files: int | None,
    seed: int,
) -> list[dict[str, Any]]:
    filtered = tasks

    if targets is not None:
        filtered = [
            task
            for task in filtered
            if task["source_file"] in targets
        ]

    filtered = sorted(filtered, key=lambda t: natural_key(t["source_file"]))

    if max_files is not None and max_files > 0 and len(filtered) > max_files:
        rng = random.Random(seed)
        filtered = rng.sample(filtered, max_files)
        filtered = sorted(filtered, key=lambda t: natural_key(t["source_file"]))

    return filtered


# ==============================================================================
# Core evaluation
# ==============================================================================

def evaluate_task(
    task: dict[str, Any],
    *,
    repo_root: Path,
    cosmic_ray_bin: str,
    baseline_timeout: int,
    cosmic_init_timeout: int,
    cosmic_exec_timeout: int,
    per_test_timeout: int,
    keep_temp_on_failure: bool,
    extra_rewrite_paths: list[str],
) -> dict[str, Any]:
    started_at = time.monotonic()
    row = base_result(task)

    source_abs = task["source_abs"]
    test_abs = task["test_abs"]

    if not source_abs.exists():
        return finish_result(
            row,
            status="source_not_found",
            notes=f"Source file not found: {source_abs}",
            started_at=started_at,
        )

    if not test_abs.exists():
        return finish_result(
            row,
            status="test_file_not_found",
            notes=f"Test file not found: {test_abs}",
            started_at=started_at,
        )

    tmp_context: tempfile.TemporaryDirectory[str] | None = None

    try:
        tmp_context = tempfile.TemporaryDirectory(prefix="lazytest_mutation_")
        tmpdir = Path(tmp_context.name)

        repo_copy_dir = tmpdir / REPO_NAME

        shutil.copytree(
            repo_root,
            repo_copy_dir,
            ignore=shutil.ignore_patterns(
                ".git",
                ".pytest_cache",
                "__pycache__",
                ".mypy_cache",
                ".ruff_cache",
                ".venv",
                "venv",
            ),
        )

        isolated_source_file = repo_copy_dir / task["source_file"]
        isolated_test_file = tmpdir / Path(task["test_file"]).name

        test_content = test_abs.read_text(encoding="utf-8", errors="replace")

        rewrite_paths = {
            str(repo_root),
            str(repo_root.resolve()),
            str(task["generated_repo_root"]),
            str(task["generated_repo_root"].resolve()),
            "/workspace/lazytest/testing/repos_for_testing/TheAlgorithms",
            os.path.expanduser("~/git/lazytest/testing/repos_for_testing/TheAlgorithms"),
        }

        rewrite_paths.update(extra_rewrite_paths)

        for old_path in sorted(rewrite_paths, key=len, reverse=True):
            if old_path:
                test_content = test_content.replace(old_path, str(repo_copy_dir))

        isolated_test_file.write_text(test_content, encoding="utf-8")

        env = os.environ.copy()
        env["PYTHONPATH"] = f"{repo_copy_dir}{os.pathsep}{env.get('PYTHONPATH', '')}"

        # Prevent pytest from picking up repository-level config.
        for conf_file in ["pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg"]:
            conf_path = repo_copy_dir / conf_file
            if conf_path.exists():
                conf_path.unlink()

        safe_pytest_args = [
            "-q",
            "--disable-warnings",
            "-p", "no:cacheprovider",
            "-p", "no:doctest",
            "-p", "no:xdist",
            "-c", "/dev/null",
            f"--timeout={per_test_timeout}",
        ]

        baseline_cmd = [
            sys.executable,
            "-m",
            "pytest",
            str(isolated_test_file),
            *safe_pytest_args,
            "--tb=short",
        ]

        rc, stdout, stderr, elapsed = run_subprocess(
            baseline_cmd,
            env=env,
            cwd=repo_copy_dir,
            timeout=baseline_timeout,
            label=f"baseline {task['source_file']}",
        )

        row["baseline_rc"] = rc
        row["baseline_elapsed_s"] = round(elapsed, 3)

        if rc == -1:
            row["baseline_status"] = "timeout"
            return finish_result(
                row,
                status="baseline_timeout",
                notes=f"Baseline timeout. {stderr[-300:]}",
                started_at=started_at,
            )

        if rc != 0:
            row["baseline_status"] = "failed"
            return finish_result(
                row,
                status="baseline_failed",
                notes=f"Baseline test failed. stdout={stdout[-300:]} stderr={stderr[-300:]}",
                started_at=started_at,
            )

        row["baseline_status"] = "passed"

        db_path = repo_copy_dir / "session.sqlite"
        toml_path = repo_copy_dir / "cr.toml"

        test_cmd_parts = [
            shlex.quote(sys.executable),
            "-m",
            "pytest",
            shlex.quote(str(isolated_test_file)),
            *[shlex.quote(arg) for arg in safe_pytest_args],
            "--tb=no",
        ]

        test_cmd = " ".join(test_cmd_parts)

        toml_content = f"""[cosmic-ray]
module-path = {json.dumps(str(isolated_source_file))}
timeout = {float(per_test_timeout)}
test-command = {json.dumps(test_cmd)}
excluded-modules = []

[cosmic-ray.distributor]
name = "local"
"""

        toml_path.write_text(toml_content, encoding="utf-8")

        init_cmd = [
            cosmic_ray_bin,
            "init",
            str(toml_path),
            str(db_path),
        ]

        rc_init, stdout_init, stderr_init, elapsed_init = run_subprocess(
            init_cmd,
            env=env,
            cwd=repo_copy_dir,
            timeout=cosmic_init_timeout,
            label=f"cosmic-ray init {task['source_file']}",
        )

        row["cosmic_init_rc"] = rc_init
        row["cosmic_init_elapsed_s"] = round(elapsed_init, 3)

        if rc_init == -1:
            return finish_result(
                row,
                status="cosmic_init_timeout",
                notes=f"Cosmic Ray init timeout. stderr={stderr_init[-300:]}",
                started_at=started_at,
            )

        if rc_init != 0:
            return finish_result(
                row,
                status="cosmic_init_error",
                notes=f"Cosmic Ray init error rc={rc_init}. stdout={stdout_init[-300:]} stderr={stderr_init[-300:]}",
                started_at=started_at,
            )

        exec_cmd = [
            cosmic_ray_bin,
            "exec",
            str(toml_path),
            str(db_path),
        ]

        rc_exec, stdout_exec, stderr_exec, elapsed_exec = run_subprocess(
            exec_cmd,
            env=env,
            cwd=repo_copy_dir,
            timeout=cosmic_exec_timeout,
            label=f"cosmic-ray exec {task['source_file']}",
        )

        row["cosmic_exec_rc"] = rc_exec
        row["cosmic_exec_elapsed_s"] = round(elapsed_exec, 3)

        if rc_exec == -1:
            # Do not report a normal mutation score from a timed-out session.
            parsed_timeout = parse_cosmic_ray_db(db_path)

            row["mutants_killed"] = parsed_timeout.get("killed", 0)
            row["mutants_survived"] = parsed_timeout.get("survived", 0)
            row["mutants_incompetent"] = parsed_timeout.get("incompetent", 0)
            row["mutants_timeout"] = parsed_timeout.get("timeout", 0)
            row["mutants_other"] = parsed_timeout.get("other", 0)
            row["cosmic_table"] = parsed_timeout.get("table", "")
            row["cosmic_outcome_column"] = parsed_timeout.get("outcome_column", "")

            scores = calculate_scores(
                killed=int(row["mutants_killed"] or 0),
                survived=int(row["mutants_survived"] or 0),
                incompetent=int(row["mutants_incompetent"] or 0),
                timeout=int(row["mutants_timeout"] or 0),
                other=int(row["mutants_other"] or 0),
            )
            row.update(scores)

            return finish_result(
                row,
                status="cosmic_exec_timeout",
                notes=f"Cosmic Ray exec timeout. Partial DB parsed={parsed_timeout.get('ok')}. stderr={stderr_exec[-300:]}",
                started_at=started_at,
            )

        parsed = parse_cosmic_ray_db(db_path)

        row["cosmic_table"] = parsed.get("table", "")
        row["cosmic_outcome_column"] = parsed.get("outcome_column", "")
        row["mutants_killed"] = parsed.get("killed", 0)
        row["mutants_survived"] = parsed.get("survived", 0)
        row["mutants_incompetent"] = parsed.get("incompetent", 0)
        row["mutants_timeout"] = parsed.get("timeout", 0)
        row["mutants_other"] = parsed.get("other", 0)

        scores = calculate_scores(
            killed=int(row["mutants_killed"] or 0),
            survived=int(row["mutants_survived"] or 0),
            incompetent=int(row["mutants_incompetent"] or 0),
            timeout=int(row["mutants_timeout"] or 0),
            other=int(row["mutants_other"] or 0),
        )
        row.update(scores)

        if not parsed.get("ok"):
            return finish_result(
                row,
                status="cosmic_db_parse_error",
                notes=parsed.get("notes", "Could not parse Cosmic Ray DB"),
                started_at=started_at,
            )

        if int(row["total_mutants"] or 0) == 0:
            return finish_result(
                row,
                status="no_mutants",
                notes="Cosmic Ray produced 0 mutants",
                started_at=started_at,
            )

        if int(row["viable_mutants"] or 0) == 0:
            return finish_result(
                row,
                status="no_viable_mutants",
                notes=(
                    "Cosmic Ray produced mutants but none were viable "
                    f"(killed={row['mutants_killed']}, survived={row['mutants_survived']}, "
                    f"incompetent={row['mutants_incompetent']}, timeout={row['mutants_timeout']}, "
                    f"other={row['mutants_other']})"
                ),
                started_at=started_at,
            )

        notes = (
            f"Cosmic Ray processed. "
            f"killed={row['mutants_killed']} "
            f"survived={row['mutants_survived']} "
            f"incompetent={row['mutants_incompetent']} "
            f"timeout={row['mutants_timeout']} "
            f"other={row['mutants_other']} "
            f"score_viable={row['mutation_score_viable']}"
        )

        if rc_exec != 0:
            notes += f". Cosmic Ray exec returned rc={rc_exec}, but DB results were parsed."

        return finish_result(
            row,
            status="mutation_processed",
            notes=notes,
            started_at=started_at,
        )

    except Exception as exc:
        return finish_result(
            row,
            status="unexpected_error",
            notes=f"Unexpected error: {exc}",
            started_at=started_at,
        )

    finally:
        if tmp_context is not None:
            # By default TemporaryDirectory cleans itself. If debugging failed
            # tasks, keep_temp_on_failure can be added later by replacing this
            # block with conditional cleanup. For now we always clean to avoid
            # filling the disk overnight.
            tmp_context.cleanup()


# ==============================================================================
# Run processing
# ==============================================================================

def process_run(
    *,
    model: str,
    run_dir: Path,
    repo_root: Path,
    args: argparse.Namespace,
    cosmic_ray_bin: str,
    targets: set[str] | None,
) -> list[dict[str, Any]]:
    print(f"\n[{model}/{run_dir.name}] Discovering tests...")

    all_tasks = discover_tasks_for_run(
        model=model,
        run_dir=run_dir,
        repo_root=repo_root,
    )

    tasks = filter_tasks(
        all_tasks,
        targets=targets,
        max_files=args.max_files_per_run,
        seed=args.seed,
    )

    out_csv = run_dir / args.out_csv_name

    existing = {} if args.rerun else load_existing_results(out_csv)
    processed_rows: list[dict[str, Any]] = []
    tasks_to_process: list[dict[str, Any]] = []

    for task in tasks:
        key = (task["source_file"], task["test_file"])

        if key in existing:
            processed_rows.append(existing[key])
        else:
            tasks_to_process.append(task)

    print(
        f"[{model}/{run_dir.name}] "
        f"found={len(all_tasks)} selected={len(tasks)} "
        f"already_done={len(processed_rows)} remaining={len(tasks_to_process)}"
    )

    if args.dry_run:
        return processed_rows

    if not tasks_to_process:
        if processed_rows:
            atomic_write_csv(out_csv, processed_rows)
        return processed_rows

    completed_since_save = 0

    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(
                evaluate_task,
                task,
                repo_root=repo_root,
                cosmic_ray_bin=cosmic_ray_bin,
                baseline_timeout=args.baseline_timeout,
                cosmic_init_timeout=args.cosmic_init_timeout,
                cosmic_exec_timeout=args.cosmic_exec_timeout,
                per_test_timeout=args.per_test_timeout,
                keep_temp_on_failure=args.keep_temp_on_failure,
                extra_rewrite_paths=args.rewrite_path,
            ): task
            for task in tasks_to_process
        }

        for index, future in enumerate(as_completed(futures), start=1):
            task = futures[future]

            try:
                row = future.result()
            except Exception as exc:
                row = base_result(task)
                row = finish_result(
                    row,
                    status="unexpected_error",
                    notes=f"Unhandled future exception: {exc}",
                    started_at=time.monotonic(),
                )

            processed_rows.append(row)
            completed_since_save += 1

            status = row.get("mutation_status", "")
            score = row.get("mutation_score_viable", "")
            print(
                f"  [{model}/{run_dir.name}] "
                f"{index}/{len(tasks_to_process)} "
                f"{row.get('source_file')} -> {status} "
                f"score={score}",
                flush=True,
            )

            if completed_since_save >= args.save_every:
                atomic_write_csv(out_csv, processed_rows)
                completed_since_save = 0
                print(f"  [{model}/{run_dir.name}] saved {len(processed_rows)} rows")

    atomic_write_csv(out_csv, processed_rows)
    print(f"[{model}/{run_dir.name}] Done. Saved to {out_csv}")

    return processed_rows


def summarise_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    processed = [
        row for row in rows
        if row.get("mutation_status") == "mutation_processed"
    ]

    scores = [
        float(row["mutation_score_viable"])
        for row in processed
        if str(row.get("mutation_score_viable", "")).strip() != ""
    ]

    status_counts: dict[str, int] = {}

    for row in rows:
        status = row.get("mutation_status", "unknown") or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

    mean_score = round(sum(scores) / len(scores), 2) if scores else ""

    return {
        "total_rows": len(rows),
        "processed_rows": len(processed),
        "mean_mutation_score_viable": mean_score,
        "status_counts": status_counts,
    }


def write_run_config(args: argparse.Namespace, path: Path) -> None:
    config = {
        "generated_root": str(args.generated_root),
        "repo_root": str(args.repo_root),
        "models": args.models if args.models else MODELS if MODELS else "auto-discovered",
        "run_pattern": args.run_pattern,
        "out_csv_name": args.out_csv_name,
        "combined_csv_name": args.combined_csv_name,
        "max_workers": args.max_workers,
        "baseline_timeout": args.baseline_timeout,
        "cosmic_init_timeout": args.cosmic_init_timeout,
        "cosmic_exec_timeout": args.cosmic_exec_timeout,
        "per_test_timeout": args.per_test_timeout,
        "max_files_per_run": args.max_files_per_run,
        "seed": args.seed,
        "targets_file": str(args.targets_file) if args.targets_file else None,
        "score_definition": {
            "mutation_score_viable": "killed / (killed + survived) * 100",
            "mutation_score_raw": "killed / (killed + survived + incompetent + timeout + other) * 100",
            "incompetent_handling": "logged separately and not counted as killed",
        },
    }

    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


# ==============================================================================
# CLI
# ==============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run Cosmic Ray mutation testing over generated LazyTest test runs. "
            "Expected structure: testing/generated_tests/<model>/<run>/TheAlgorithms/..."
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
        "--models",
        nargs="*",
        default=None,
        help="Model folder names to process. If omitted, uses MODELS list or auto-discovers all folders.",
    )

    parser.add_argument(
        "--run-pattern",
        default="run*",
        help="Glob pattern for run folders inside each model directory. Default: run*",
    )

    parser.add_argument(
        "--out-csv-name",
        default=DEFAULT_OUT_CSV_NAME,
        help=f"Per-run output CSV name. Default: {DEFAULT_OUT_CSV_NAME}",
    )

    parser.add_argument(
        "--combined-csv-name",
        default=DEFAULT_COMBINED_CSV_NAME,
        help=f"Combined output CSV name under generated root. Default: {DEFAULT_COMBINED_CSV_NAME}",
    )

    parser.add_argument(
        "--cosmic-ray-bin",
        default="auto",
        help="Path to cosmic-ray executable, or 'auto'. Default: auto",
    )

    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help=f"Parallel files per run. Default: {DEFAULT_MAX_WORKERS}",
    )

    parser.add_argument(
        "--baseline-timeout",
        type=int,
        default=DEFAULT_BASELINE_TIMEOUT,
        help=f"Seconds for baseline pytest. Default: {DEFAULT_BASELINE_TIMEOUT}",
    )

    parser.add_argument(
        "--cosmic-init-timeout",
        type=int,
        default=DEFAULT_COSMIC_INIT_TIMEOUT,
        help=f"Seconds for cosmic-ray init. Default: {DEFAULT_COSMIC_INIT_TIMEOUT}",
    )

    parser.add_argument(
        "--cosmic-exec-timeout",
        type=int,
        default=DEFAULT_COSMIC_EXEC_TIMEOUT,
        help=f"Seconds for cosmic-ray exec per file. Default: {DEFAULT_COSMIC_EXEC_TIMEOUT}",
    )

    parser.add_argument(
        "--per-test-timeout",
        type=int,
        default=DEFAULT_PER_TEST_TIMEOUT,
        help=f"pytest-timeout per-test timeout. Default: {DEFAULT_PER_TEST_TIMEOUT}",
    )

    parser.add_argument(
        "--max-files-per-run",
        type=int,
        default=None,
        help="Optional fixed-size sample per run. Useful for quick checks.",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed used with --max-files-per-run. Default: 42",
    )

    parser.add_argument(
        "--targets-file",
        type=Path,
        default=None,
        help="Optional file of source paths to evaluate, one relative path per line.",
    )

    parser.add_argument(
        "--rewrite-path",
        action="append",
        default=[],
        help="Additional absolute path to rewrite to the isolated repo copy. Can be used multiple times.",
    )

    parser.add_argument(
        "--save-every",
        type=int,
        default=5,
        help="Save per-run CSV after this many completed tasks. Default: 5",
    )

    parser.add_argument(
        "--rerun",
        action="store_true",
        help="Ignore existing per-run CSV files and recompute everything.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only discover models/runs/tests; do not run mutation testing.",
    )

    parser.add_argument(
        "--keep-temp-on-failure",
        action="store_true",
        help="Reserved for debugging; currently temporary directories are cleaned to avoid filling disk.",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.",
    )

    return parser.parse_args()


def main() -> int:
    global DEBUG

    args = parse_args()
    DEBUG = args.debug

    generated_root = args.generated_root.expanduser().resolve()
    repo_root = args.repo_root.expanduser().resolve()

    args.generated_root = generated_root
    args.repo_root = repo_root

    if not generated_root.exists():
        print(f"ERROR: generated root not found: {generated_root}", file=sys.stderr)
        return 1

    if not repo_root.exists():
        print(f"ERROR: repo root not found: {repo_root}", file=sys.stderr)
        return 1

    try:
        cosmic_ray_bin = find_cosmic_ray_binary(args.cosmic_ray_bin)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    targets = load_targets(args.targets_file.expanduser().resolve() if args.targets_file else None)

    models = discover_models(generated_root, args.models)

    if not models:
        print(f"ERROR: no model directories found under {generated_root}", file=sys.stderr)
        return 1

    print("=" * 80)
    print("LazyTest Cosmic Ray mutation evaluation")
    print("=" * 80)
    print(f"Generated root: {generated_root}")
    print(f"Repo root:      {repo_root}")
    print(f"Cosmic Ray:     {cosmic_ray_bin}")
    print(f"Models:         {models}")
    print(f"Max workers:    {args.max_workers}")
    print(f"Run pattern:    {args.run_pattern}")
    print("=" * 80)

    write_run_config(args, generated_root / "mutation_run_config.json")

    all_rows: list[dict[str, Any]] = []
    started_at = time.monotonic()

    for model in models:
        model_dir = generated_root / model

        if not model_dir.exists():
            print(f"\n[SKIP] Model directory not found: {model_dir}")
            continue

        run_dirs = discover_runs(model_dir, args.run_pattern)

        if not run_dirs:
            print(f"\n[SKIP] No run folders found for model {model}: {model_dir}")
            continue

        print(f"\n[{model}] Found {len(run_dirs)} run folders")

        for run_dir in run_dirs:
            rows = process_run(
                model=model,
                run_dir=run_dir,
                repo_root=repo_root,
                args=args,
                cosmic_ray_bin=cosmic_ray_bin,
                targets=targets,
            )
            all_rows.extend(rows)

    combined_path = generated_root / args.combined_csv_name

    if all_rows:
        atomic_write_csv(combined_path, all_rows)
        print(f"\nCombined CSV saved to: {combined_path}")

        summary = summarise_rows(all_rows)
        summary_path = generated_root / "mutation_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Summary JSON saved to: {summary_path}")
        print(json.dumps(summary, indent=2))

    elapsed = time.monotonic() - started_at
    print(f"\nAll done in {int(elapsed // 60)}m {int(elapsed % 60)}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())