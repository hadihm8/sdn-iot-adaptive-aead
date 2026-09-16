#!/usr/bin/env python3
"""Receive, authenticate, decrypt, and log SDN-IoT MQTT messages."""

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import fmean
from threading import Event
from time import perf_counter

import paho.mqtt.client as mqtt

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

from secure_message import decrypt_envelope


def percentile(values, percentile_value):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * percentile_value / 100.0))
    return ordered[index]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", default="10.0.0.250")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic", default="sdn/iot/data")
    parser.add_argument("--expected", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--summary-output", required=True)
    parser.add_argument("--messages-output", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    completed = Event()
    records = []
    authentication_failures = 0
    first_message_time = None
    last_message_time = None

    def on_connect(client, userdata, flags, reason_code, properties):
        client.subscribe(args.topic, qos=0)

    def on_message(client, userdata, message):
        nonlocal authentication_failures, first_message_time, last_message_time
        now = perf_counter()
        if first_message_time is None:
            first_message_time = now
        last_message_time = now
        try:
            records.append(decrypt_envelope(message.payload))
        except Exception:
            authentication_failures += 1
        if len(records) + authentication_failures >= args.expected:
            completed.set()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sdn-iot-sink")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.broker, args.port, keepalive=30)
    client.loop_start()
    completed.wait(timeout=args.timeout)
    client.loop_stop()
    client.disconnect()

    summary_path = Path(args.summary_output)
    messages_path = Path(args.messages_output)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    messages_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "device_id",
        "sequence",
        "algorithm",
        "payload_bytes",
        "ciphertext_bytes",
        "wire_bytes",
        "decryption_ms",
        "e2e_latency_ms",
    ]
    with messages_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)

    latencies = [record["e2e_latency_ms"] for record in records]
    decryptions = [record["decryption_ms"] for record in records]
    duration_s = 0.0
    if first_message_time is not None and last_message_time is not None:
        duration_s = max(last_message_time - first_message_time, 0.0)
    received = len(records)
    total_payload_bytes = sum(record["payload_bytes"] for record in records)
    throughput_mbps = (
        total_payload_bytes * 8 / duration_s / 1_000_000 if duration_s > 0 else 0.0
    )
    summary = {
        "messages_expected": args.expected,
        "messages_received": received,
        "message_loss_pct": 100.0 * (args.expected - received) / args.expected,
        "authentication_failures": authentication_failures,
        "algorithm_counts": dict(Counter(record["algorithm"] for record in records)),
        "mean_decryption_ms": fmean(decryptions) if decryptions else 0.0,
        "mean_e2e_latency_ms": fmean(latencies) if latencies else 0.0,
        "p95_e2e_latency_ms": percentile(latencies, 95),
        "duration_s": duration_s,
        "throughput_mbps": throughput_mbps,
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
