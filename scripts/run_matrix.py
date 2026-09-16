#!/usr/bin/env python3
"""Run the randomized, resumable SDN-IoT experimental matrix."""

import argparse
import csv
import json
import os
import random
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import sleep


PROJECT_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_DIR / "results"
RUN_PILOT = PROJECT_DIR / "scripts" / "run_pilot.py"

LOADS = ("low", "medium", "high")
DEVICE_DENSITIES = (5, 10, 20)
PAYLOAD_BYTES = (256, 1024, 4096)
POLICIES = (
    ("fixed_aes128", "fixed", "AES-128-GCM"),
    ("fixed_aes256", "fixed", "AES-256-GCM"),
    ("fixed_chacha20", "fixed", "ChaCha20-Poly1305"),
    ("adaptive", "adaptive", "AES-256-GCM"),
)
PHASE_REPETITIONS = {"preflight": 1, "final": 30}
DEFAULT_RESULTS = {
    "preflight": "matrix_preflight_sync2.csv",
    "final": "final_experiment.csv",
}


@dataclass(frozen=True)
class Condition:
    condition_number: int
    condition_id: str
    policy: str
    mode: str
    algorithm: str
    load: str
    devices: int
    payload_bytes: int


@dataclass(frozen=True)
class ScheduledRun:
    run_id: int
    replicate: int
    condition_order: int
    condition: Condition


def positive_int(value):
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def nonnegative_float(value):
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=tuple(PHASE_REPETITIONS), default="preflight")
    parser.add_argument("--messages", type=positive_int, default=20)
    parser.add_argument("--seed", type=int, default=20260905)
    parser.add_argument("--cooldown-seconds", type=nonnegative_float, default=1.0)
    parser.add_argument("--results-file")
    parser.add_argument("--max-runs", type=positive_int)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def validate_results_filename(value):
    candidate = Path(value)
    if candidate.name != value or candidate.suffix.lower() != ".csv":
        raise SystemExit("--results-file must be a CSV filename without directories")
    return value


def build_conditions():
    conditions = []
    number = 0
    for policy, mode, algorithm in POLICIES:
        for load in LOADS:
            for devices in DEVICE_DENSITIES:
                for payload_bytes in PAYLOAD_BYTES:
                    number += 1
                    condition_id = (
                        f"{policy}__{load}__d{devices}__p{payload_bytes}"
                    )
                    conditions.append(
                        Condition(
                            condition_number=number,
                            condition_id=condition_id,
                            policy=policy,
                            mode=mode,
                            algorithm=algorithm,
                            load=load,
                            devices=devices,
                            payload_bytes=payload_bytes,
                        )
                    )
    return conditions


def build_schedule(conditions, repetitions, seed):
    schedule = []
    condition_count = len(conditions)
    for replicate in range(1, repetitions + 1):
        randomized = list(conditions)
        random.Random(seed + replicate).shuffle(randomized)
        for order, condition in enumerate(randomized, start=1):
            run_id = (replicate - 1) * condition_count + condition.condition_number
            schedule.append(
                ScheduledRun(
                    run_id=run_id,
                    replicate=replicate,
                    condition_order=order,
                    condition=condition,
                )
            )
    return schedule


def completed_keys(results_path, phase, seed, messages):
    if not results_path.exists():
        return set()
    with results_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {
            "experiment_phase",
            "condition_id",
            "replicate",
            "matrix_seed",
            "messages_per_device",
        }
        if not required.issubset(reader.fieldnames or []):
            raise SystemExit(
                f"Cannot resume: {results_path.name} does not contain matrix metadata"
            )
        completed = set()
        for row in reader:
            if (
                row["experiment_phase"] != phase
                or int(row["matrix_seed"]) != seed
                or int(row["messages_per_device"]) != messages
            ):
                raise SystemExit(
                    f"Cannot resume: {results_path.name} contains a different design"
                )
            condition_id = (row.get("condition_id") or "").strip()
            replicate = (row.get("replicate") or "").strip()
            if condition_id and replicate:
                completed.add((condition_id, int(replicate)))
        return completed


def schedule_record(item):
    record = asdict(item.condition)
    record.update(
        {
            "run_id": item.run_id,
            "replicate": item.replicate,
            "condition_order": item.condition_order,
        }
    )
    return record


def ensure_plan(path, plan):
    if not path.exists():
        atomic_write_json(path, plan)
        return
    existing = json.loads(path.read_text(encoding="utf-8"))
    comparison_keys = (
        "phase",
        "seed",
        "policies",
        "loads",
        "device_densities",
        "payload_bytes",
        "messages_per_device",
        "repetitions",
        "conditions_per_replicate",
        "planned_runs",
        "publisher_synchronization",
        "schedule",
    )
    if any(existing.get(key) != plan.get(key) for key in comparison_keys):
        raise SystemExit(
            f"Existing plan {path.name} does not match the requested design"
        )


def write_progress(path, phase, seed, results_file, total, completed, status, current=None):
    value = {
        "phase": phase,
        "seed": seed,
        "results_file": results_file,
        "planned_runs": total,
        "completed_runs": completed,
        "remaining_runs": max(total - completed, 0),
        "status": status,
        "updated_at_utc": utc_now(),
        "current": schedule_record(current) if current else None,
    }
    atomic_write_json(path, value)


def main():
    args = parse_args()
    repetitions = PHASE_REPETITIONS[args.phase]
    results_file = validate_results_filename(
        args.results_file or DEFAULT_RESULTS[args.phase]
    )
    results_path = RESULTS_DIR / results_file
    stem = Path(results_file).stem
    plan_path = RESULTS_DIR / f"{stem}_plan.json"
    progress_path = RESULTS_DIR / f"{stem}_progress.json"
    conditions = build_conditions()
    schedule = build_schedule(conditions, repetitions, args.seed)
    all_keys = {
        (item.condition.condition_id, item.replicate) for item in schedule
    }

    plan = {
        "phase": args.phase,
        "seed": args.seed,
        "randomization": "conditions shuffled independently within each replicate",
        "publisher_synchronization": (
            "all publishers connected, declared ready, and scheduled for one shared "
            "monotonic start time"
        ),
        "policies": [item[0] for item in POLICIES],
        "loads": list(LOADS),
        "device_densities": list(DEVICE_DENSITIES),
        "payload_bytes": list(PAYLOAD_BYTES),
        "messages_per_device": args.messages,
        "repetitions": repetitions,
        "conditions_per_replicate": len(conditions),
        "planned_runs": len(schedule),
        "created_at_utc": utc_now(),
        "schedule": [schedule_record(item) for item in schedule],
    }
    print(
        f"MATRIX {args.phase}: {len(conditions)} conditions x "
        f"{repetitions} replicate(s) = {len(schedule)} runs"
    )
    print(f"Seed: {args.seed}")
    print(f"Results: {results_path}")
    print(f"Plan: {plan_path}")
    if args.dry_run:
        print("DRY RUN PASS")
        for item in schedule[:5]:
            print(
                f"run={item.run_id} rep={item.replicate} "
                f"order={item.condition_order} {item.condition.condition_id}"
            )
        return 0

    if os.geteuid() != 0:
        raise SystemExit(
            "Run with sudo: sudo .venv/bin/python scripts/run_matrix.py"
        )

    ensure_plan(plan_path, plan)
    completed = completed_keys(
        results_path,
        args.phase,
        args.seed,
        args.messages,
    ) & all_keys
    pending = [
        item
        for item in schedule
        if (item.condition.condition_id, item.replicate) not in completed
    ]
    if args.max_runs:
        pending = pending[: args.max_runs]

    print(f"Already complete: {len(completed)}; scheduled now: {len(pending)}")
    write_progress(
        progress_path,
        args.phase,
        args.seed,
        results_file,
        len(schedule),
        len(completed),
        "running" if pending else "complete",
    )

    for item in pending:
        condition = item.condition
        position = len(completed) + 1
        print(
            f"[{position}/{len(schedule)}] rep={item.replicate} "
            f"order={item.condition_order} {condition.condition_id}",
            flush=True,
        )
        write_progress(
            progress_path,
            args.phase,
            args.seed,
            results_file,
            len(schedule),
            len(completed),
            "running",
            item,
        )
        command = [
            sys.executable,
            str(RUN_PILOT),
            "--devices",
            str(condition.devices),
            "--messages",
            str(args.messages),
            "--payload-bytes",
            str(condition.payload_bytes),
            "--load",
            condition.load,
            "--mode",
            condition.mode,
            "--algorithm",
            condition.algorithm,
            "--run-id",
            str(item.run_id),
            "--results-file",
            results_file,
            "--experiment-phase",
            args.phase,
            "--condition-id",
            condition.condition_id,
            "--replicate",
            str(item.replicate),
            "--condition-order",
            str(item.condition_order),
            "--matrix-seed",
            str(args.seed),
            "--quiet",
        ]
        try:
            result = subprocess.run(command, cwd=PROJECT_DIR, check=False)
        except KeyboardInterrupt:
            write_progress(
                progress_path,
                args.phase,
                args.seed,
                results_file,
                len(schedule),
                len(completed),
                "interrupted",
                item,
            )
            print("MATRIX INTERRUPTED; rerun the same command to resume.")
            return 130
        if result.returncode != 0:
            write_progress(
                progress_path,
                args.phase,
                args.seed,
                results_file,
                len(schedule),
                len(completed),
                "failed",
                item,
            )
            print(
                f"MATRIX STOPPED: run {item.run_id} exited with "
                f"status {result.returncode}. Rerun the same command to resume."
            )
            return result.returncode
        completed.add((condition.condition_id, item.replicate))
        write_progress(
            progress_path,
            args.phase,
            args.seed,
            results_file,
            len(schedule),
            len(completed),
            "running",
        )
        if args.cooldown_seconds:
            sleep(args.cooldown_seconds)

    remaining = len(schedule) - len(completed)
    status = "complete" if remaining == 0 else "paused"
    write_progress(
        progress_path,
        args.phase,
        args.seed,
        results_file,
        len(schedule),
        len(completed),
        status,
    )
    if remaining == 0:
        print(f"MATRIX PASS: {len(completed)}/{len(schedule)} runs complete")
    else:
        print(
            f"MATRIX PAUSED: {len(completed)}/{len(schedule)} complete; "
            "rerun the same command to continue"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
