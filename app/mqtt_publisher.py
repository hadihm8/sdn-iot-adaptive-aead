#!/usr/bin/env python3
"""Publish authenticated encrypted IoT messages and record sender metrics."""

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from statistics import fmean
from threading import Event
from time import perf_counter, sleep

import paho.mqtt.client as mqtt
import psutil

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

from secure_message import ALGORITHMS, choose_algorithm, encrypt_envelope


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", default="10.0.0.250")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic", default="sdn/iot/data")
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--messages", type=int, default=20)
    parser.add_argument("--payload-bytes", type=int, default=1024)
    parser.add_argument("--rate", type=float, default=10.0)
    parser.add_argument("--mode", choices=("fixed", "adaptive"), default="adaptive")
    parser.add_argument("--algorithm", choices=ALGORITHMS, default="AES-256-GCM")
    parser.add_argument("--network-load-pct", type=float, default=20.0)
    parser.add_argument("--state-cpu-pct", type=float, default=20.0)
    parser.add_argument("--state-memory-pct", type=float, default=30.0)
    parser.add_argument("--estimated-cpu-power-w", type=float, default=5.0)
    parser.add_argument("--ready-file")
    parser.add_argument("--start-file")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if bool(args.ready_file) != bool(args.start_file):
        parser.error("--ready-file and --start-file must be used together")
    return args


def main():
    args = parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = os.urandom(args.payload_bytes)
    process = psutil.Process()
    connected = Event()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=args.device_id)

    def on_connect(_client, _userdata, _flags, reason_code, _properties):
        if reason_code == 0:
            connected.set()

    client.on_connect = on_connect
    client.connect(args.broker, args.port, keepalive=30)
    client.loop_start()
    try:
        if not connected.wait(timeout=10):
            raise RuntimeError("MQTT publisher did not connect before timeout")

        scheduled_start_monotonic = 0.0
        if args.ready_file:
            ready_file = Path(args.ready_file)
            start_file = Path(args.start_file)
            ready_file.parent.mkdir(parents=True, exist_ok=True)
            ready_file.touch()
            gate_deadline = perf_counter() + 20.0
            while not start_file.exists():
                if perf_counter() >= gate_deadline:
                    raise RuntimeError("publisher synchronization gate timed out")
                sleep(0.005)
            scheduled_start_monotonic = float(
                start_file.read_text(encoding="utf-8").strip()
            )
            remaining = scheduled_start_monotonic - perf_counter()
            if remaining > 0.002:
                sleep(remaining - 0.002)
            while perf_counter() < scheduled_start_monotonic:
                pass

        actual_start_monotonic = perf_counter()
        start_lateness_ms = (
            max(0.0, actual_start_monotonic - scheduled_start_monotonic) * 1000.0
            if scheduled_start_monotonic
            else 0.0
        )
        cpu_start = sum(process.cpu_times()[:2])
        wall_start = actual_start_monotonic
        encryption_samples = []
        wire_bytes = 0
        algorithms = Counter()
        interval = 1.0 / args.rate if args.rate > 0 else 0.0
        next_send = wall_start
        published = 0
        for sequence in range(1, args.messages + 1):
            algorithm = choose_algorithm(
                mode=args.mode,
                fixed_algorithm=args.algorithm,
                network_load_pct=args.network_load_pct,
                cpu_pct=args.state_cpu_pct,
                memory_pct=args.state_memory_pct,
                payload_bytes=args.payload_bytes,
            )
            message, encryption_ms = encrypt_envelope(
                args.device_id,
                sequence,
                payload,
                algorithm,
            )
            info = client.publish(args.topic, message, qos=0)
            if info.rc == mqtt.MQTT_ERR_SUCCESS:
                published += 1
            encryption_samples.append(encryption_ms)
            wire_bytes += len(message)
            algorithms[algorithm] += 1
            next_send += interval
            remaining = next_send - perf_counter()
            if remaining > 0:
                sleep(remaining)
        wall_end = perf_counter()
        cpu_end = sum(process.cpu_times()[:2])
    finally:
        client.loop_stop()
        client.disconnect()
    elapsed_s = max(wall_end - wall_start, 1e-9)
    process_cpu_pct = 100.0 * (cpu_end - cpu_start) / elapsed_s
    estimated_energy_j = (
        args.estimated_cpu_power_w * elapsed_s * process_cpu_pct / 100.0
    )
    summary = {
        "device_id": args.device_id,
        "mode": args.mode,
        "requested_algorithm": args.algorithm if args.mode == "fixed" else "adaptive",
        "algorithm_counts": dict(algorithms),
        "messages_requested": args.messages,
        "messages_published": published,
        "payload_bytes": args.payload_bytes,
        "rate_messages_per_s": args.rate,
        "network_load_pct": args.network_load_pct,
        "state_cpu_pct": args.state_cpu_pct,
        "state_memory_pct": args.state_memory_pct,
        "scheduled_start_monotonic": scheduled_start_monotonic,
        "actual_start_monotonic": actual_start_monotonic,
        "start_lateness_ms": start_lateness_ms,
        "mean_encryption_ms": fmean(encryption_samples) if encryption_samples else 0.0,
        "elapsed_s": elapsed_s,
        "wire_bytes": wire_bytes,
        "process_cpu_pct": process_cpu_pct,
        "rss_mb": process.memory_info().rss / (1024 * 1024),
        "estimated_energy_j": estimated_energy_j,
    }
    output.write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
