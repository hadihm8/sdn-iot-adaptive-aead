#!/usr/bin/env python3
"""Run one reproducible encrypted MQTT pilot inside the Mininet topology."""

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
from collections import Counter
from pathlib import Path
from statistics import fmean
from time import monotonic, sleep, time

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "topology"))

from iot_topology import (
    CONTROLLER_IP,
    CONTROLLER_PORT,
    IoTTopology,
    configure_ovs_tls,
)
from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController


LOADS = {
    "low": {"rate": 10.0, "network_load_pct": 20.0},
    "medium": {"rate": 50.0, "network_load_pct": 50.0},
    "high": {"rate": 100.0, "network_load_pct": 80.0},
}
SYNCHRONIZED_START_LEAD_SECONDS = 0.25


def percentage(value):
    parsed = float(value)
    if not 0.0 <= parsed <= 100.0:
        raise argparse.ArgumentTypeError("percentage must be between 0 and 100")
    return parsed


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--devices", type=int, choices=(5, 10, 20), default=5)
    parser.add_argument("--messages", type=int, default=20)
    parser.add_argument("--payload-bytes", type=int, default=1024)
    parser.add_argument("--load", choices=tuple(LOADS), default="low")
    parser.add_argument("--state-cpu-pct", type=percentage, default=20.0)
    parser.add_argument("--state-memory-pct", type=percentage, default=30.0)
    parser.add_argument("--mode", choices=("fixed", "adaptive"), default="adaptive")
    parser.add_argument(
        "--algorithm",
        choices=("AES-128-GCM", "AES-256-GCM", "ChaCha20-Poly1305"),
        default="AES-256-GCM",
    )
    parser.add_argument("--run-id", type=int, default=1)
    parser.add_argument("--results-file", default="pilot_results.csv")
    parser.add_argument(
        "--experiment-phase",
        choices=("pilot", "preflight", "final"),
        default="pilot",
    )
    parser.add_argument("--condition-id", default="")
    parser.add_argument("--replicate", type=int, default=0)
    parser.add_argument("--condition-order", type=int, default=0)
    parser.add_argument("--matrix-seed", type=int, default=0)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def resolve_results_path(results_dir, requested):
    candidate = Path(requested)
    if not candidate.is_absolute():
        candidate = results_dir / candidate
    candidate = candidate.resolve()
    results_root = results_dir.resolve()
    if candidate != results_root and results_root not in candidate.parents:
        raise SystemExit("--results-file must be inside the project results directory")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


def write_aggregate(path, row):
    exists = path.exists()
    fieldnames = list(row)
    if exists:
        with path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            existing_fieldnames = reader.fieldnames or []
            existing_rows = list(reader)
        fieldnames = existing_fieldnames + [
            field for field in fieldnames if field not in existing_fieldnames
        ]
        if fieldnames != existing_fieldnames:
            temporary = path.with_suffix(path.suffix + ".tmp")
            with temporary.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(existing_rows)
            os.replace(temporary, path)
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def main():
    args = parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo: sudo .venv/bin/python scripts/run_pilot.py")

    results_dir = PROJECT_DIR / "results"
    results_path = resolve_results_path(results_dir, args.results_file)
    safe_condition = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in args.condition_id
    )[:80]
    phase_prefix = args.experiment_phase
    if safe_condition:
        phase_prefix += (
            f"_{safe_condition}_rep{args.replicate}_ord{args.condition_order}"
        )
    run_tag = (
        f"{phase_prefix}_r{args.run_id}_{args.mode}_{args.load}_"
        f"d{args.devices}_p{args.payload_bytes}_"
        f"cpu{args.state_cpu_pct:g}_mem{args.state_memory_pct:g}_{int(time())}"
    )
    run_dir = results_dir / run_tag
    run_dir.mkdir(parents=True, exist_ok=True)
    python_bin = PROJECT_DIR / ".venv" / "bin" / "python"
    if not python_bin.exists():
        raise SystemExit("Missing .venv. Create and install requirements first.")

    subprocess.run(["mn", "-c"], check=True, stdout=subprocess.DEVNULL)
    configure_ovs_tls()
    topo = IoTTopology(devices=args.devices)
    controller = RemoteController(
        "c0",
        ip=CONTROLLER_IP,
        port=CONTROLLER_PORT,
        protocol="ssl",
    )
    net = Mininet(
        topo=topo,
        controller=None,
        switch=OVSSwitch,
        link=TCLink,
        autoSetMacs=True,
    )
    net.addController(controller)
    broker_process = None
    subscriber_process = None
    broker_log_handle = None
    publishers = []
    try:
        net.start()
        sleep(3)
        broker = net.get("broker")
        sink = net.get("sink")
        ping_output = sink.cmd("ping -c 2 -W 1 10.0.0.250")
        if "0% packet loss" not in ping_output:
            raise RuntimeError("SDN connectivity check failed before MQTT pilot")

        broker_log_handle = (run_dir / "mosquitto.log").open("w", encoding="utf-8")
        broker_process = broker.popen(
            ["mosquitto", "-c", str(PROJECT_DIR / "configs" / "mosquitto.conf"), "-v"],
            stdout=broker_log_handle,
            stderr=subprocess.STDOUT,
        )
        sleep(1)
        expected = args.devices * args.messages
        subscriber_summary = run_dir / "subscriber_summary.json"
        messages_csv = run_dir / "messages.csv"
        subscriber_process = sink.popen(
            [
                str(python_bin),
                str(PROJECT_DIR / "app" / "mqtt_subscriber.py"),
                "--expected",
                str(expected),
                "--timeout",
                "45",
                "--summary-output",
                str(subscriber_summary),
                "--messages-output",
                str(messages_csv),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        sleep(1)
        load = LOADS[args.load]
        sync_dir = run_dir / "publisher_sync"
        sync_dir.mkdir(parents=True, exist_ok=True)
        start_file = sync_dir / "start"
        for index in range(1, args.devices + 1):
            device_id = f"iot{index}"
            host = net.get(device_id)
            output = run_dir / f"{device_id}_publisher.json"
            ready_file = sync_dir / f"{device_id}.ready"
            command = [
                str(python_bin),
                str(PROJECT_DIR / "app" / "mqtt_publisher.py"),
                "--device-id",
                device_id,
                "--messages",
                str(args.messages),
                "--payload-bytes",
                str(args.payload_bytes),
                "--rate",
                str(load["rate"]),
                "--mode",
                args.mode,
                "--algorithm",
                args.algorithm,
                "--network-load-pct",
                str(load["network_load_pct"]),
                "--state-cpu-pct",
                str(args.state_cpu_pct),
                "--state-memory-pct",
                str(args.state_memory_pct),
                "--ready-file",
                str(ready_file),
                "--start-file",
                str(start_file),
                "--output",
                str(output),
            ]
            publishers.append((host.popen(command), output, ready_file))

        readiness_deadline = monotonic() + 20.0
        while True:
            failed = [
                process.returncode
                for process, _, _ in publishers
                if process.poll() is not None
            ]
            if failed:
                raise RuntimeError(f"Publisher failed before synchronization: {failed}")
            if all(ready_file.exists() for _, _, ready_file in publishers):
                break
            if monotonic() >= readiness_deadline:
                raise RuntimeError("Publishers did not become ready before timeout")
            sleep(0.01)

        scheduled_start_monotonic = (
            monotonic() + SYNCHRONIZED_START_LEAD_SECONDS
        )
        temporary_start_file = start_file.with_suffix(".tmp")
        temporary_start_file.write_text(
            f"{scheduled_start_monotonic:.9f}\n", encoding="utf-8"
        )
        os.replace(temporary_start_file, start_file)

        for process, _, _ in publishers:
            return_code = process.wait(timeout=60)
            if return_code != 0:
                raise RuntimeError(f"Publisher exited with status {return_code}")
        subscriber_stdout, subscriber_stderr = subscriber_process.communicate(timeout=50)
        if subscriber_process.returncode != 0:
            raise RuntimeError(
                f"Subscriber failed: {subscriber_stderr or subscriber_stdout}"
            )

        sender_summaries = [
            json.loads(output.read_text(encoding="utf-8"))
            for _, output, _ in publishers
        ]
        receiver = json.loads(subscriber_summary.read_text(encoding="utf-8"))
        algorithm_counts = Counter()
        for summary in sender_summaries:
            algorithm_counts.update(summary["algorithm_counts"])
        aggregate = {
            "experiment_phase": args.experiment_phase,
            "condition_id": args.condition_id,
            "replicate": args.replicate,
            "condition_order": args.condition_order,
            "matrix_seed": args.matrix_seed,
            "run_tag": run_tag,
            "run_id": args.run_id,
            "mode": args.mode,
            "requested_algorithm": args.algorithm if args.mode == "fixed" else "adaptive",
            "selected_algorithms": json.dumps(dict(algorithm_counts), sort_keys=True),
            "load": args.load,
            "network_load_pct": load["network_load_pct"],
            "state_cpu_pct": args.state_cpu_pct,
            "state_memory_pct": args.state_memory_pct,
            "publisher_start_spread_ms": (
                max(item["actual_start_monotonic"] for item in sender_summaries)
                - min(item["actual_start_monotonic"] for item in sender_summaries)
            )
            * 1000.0,
            "max_publisher_start_lateness_ms": max(
                item["start_lateness_ms"] for item in sender_summaries
            ),
            "devices": args.devices,
            "messages_per_device": args.messages,
            "payload_bytes": args.payload_bytes,
            "messages_expected": receiver["messages_expected"],
            "messages_received": receiver["messages_received"],
            "message_loss_pct": receiver["message_loss_pct"],
            "authentication_failures": receiver["authentication_failures"],
            "mean_encryption_ms": fmean(
                item["mean_encryption_ms"] for item in sender_summaries
            ),
            "mean_decryption_ms": receiver["mean_decryption_ms"],
            "mean_e2e_latency_ms": receiver["mean_e2e_latency_ms"],
            "p95_e2e_latency_ms": receiver["p95_e2e_latency_ms"],
            "throughput_mbps": receiver["throughput_mbps"],
            "mean_process_cpu_pct": fmean(
                item["process_cpu_pct"] for item in sender_summaries
            ),
            "mean_rss_mb": fmean(item["rss_mb"] for item in sender_summaries),
            "estimated_energy_j": sum(
                item["estimated_energy_j"] for item in sender_summaries
            ),
        }
        write_aggregate(results_path, aggregate)
        (run_dir / "aggregate.json").write_text(
            json.dumps(aggregate, indent=2), encoding="utf-8"
        )
        if args.quiet:
            print(
                "PILOT PASS "
                f"run={args.run_id} condition={args.condition_id or 'pilot'} "
                f"received={receiver['messages_received']}/{receiver['messages_expected']} "
                f"loss={receiver['message_loss_pct']:.3f}%"
            )
        else:
            print("PILOT PASS")
            print(json.dumps(aggregate, indent=2))
            print(f"CSV: {results_path}")
    finally:
        for process, _, _ in publishers:
            if process.poll() is None:
                process.terminate()
        if subscriber_process and subscriber_process.poll() is None:
            subscriber_process.terminate()
        if broker_process and broker_process.poll() is None:
            broker_process.send_signal(signal.SIGTERM)
            try:
                broker_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                broker_process.kill()
        if broker_log_handle:
            broker_log_handle.close()
        net.stop()
        subprocess.run(["mn", "-c"], check=False, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
