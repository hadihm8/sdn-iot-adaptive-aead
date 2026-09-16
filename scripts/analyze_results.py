#!/usr/bin/env python3
"""Validate the final matrix and regenerate the principal result figures."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "results" / "raw" / "final_experiment.csv"
OUT = ROOT / "results" / "generated"
OUT.mkdir(parents=True, exist_ok=True)

POLICIES = ["AES-128-GCM", "AES-256-GCM", "ChaCha20-Poly1305", "Adaptive"]
STYLES = {
    "AES-128-GCM": {"color": "#777777", "marker": "o", "linestyle": "-"},
    "AES-256-GCM": {"color": "#555555", "marker": "s", "linestyle": "--"},
    "ChaCha20-Poly1305": {"color": "#999999", "marker": "^", "linestyle": ":"},
    "Adaptive": {"color": "#000000", "marker": "D", "linestyle": "-", "linewidth": 2.4},
}


def load_data() -> pd.DataFrame:
    df = pd.read_csv(DATA)
    if len(df) != 3240:
        raise ValueError(f"Expected 3,240 final runs; found {len(df):,}.")
    df["policy"] = np.where(df["mode"].eq("adaptive"), "Adaptive", df["requested_algorithm"])
    df["policy"] = pd.Categorical(df["policy"], categories=POLICIES, ordered=True)
    return df


def summarize(df: pd.DataFrame, factor: str, metric: str) -> pd.DataFrame:
    grouped = df.groupby([factor, "policy"], observed=True)[metric]
    result = grouped.agg(["mean", "std", "count"]).reset_index()
    result["ci95"] = stats.t.ppf(0.975, result["count"] - 1) * result["std"] / np.sqrt(result["count"])
    return result


def line_figure(df, factor, metric, x_values, xlabel, ylabel, title, filename, log_x=False):
    summary = summarize(df, factor, metric)
    fig, ax = plt.subplots(figsize=(8.2, 5.0))
    fig.subplots_adjust(left=0.12, right=0.98, bottom=0.14, top=0.84)
    for policy in POLICIES:
        subset = summary[summary["policy"].eq(policy)].sort_values(factor)
        style = STYLES[policy].copy()
        linewidth = style.pop("linewidth", 1.7)
        ax.errorbar(subset[factor].astype(float), subset["mean"], yerr=subset["ci95"], label=policy,
                    linewidth=linewidth, markersize=5.5, capsize=3, **style)
    if log_x:
        ax.set_xscale("log", base=2)
    ax.set_xticks(x_values)
    ax.set_xticklabels([f"{int(value):,}" for value in x_values])
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title, pad=12, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#d9d9d9", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, ncol=2, loc="upper left")
    fig.savefig(OUT / filename, dpi=300, facecolor="white")
    plt.close(fig)


def main() -> None:
    plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 10})
    df = load_data()
    line_figure(df, "network_load_pct", "mean_e2e_latency_ms", [20, 50, 80],
                "Configured network load (%)", "Mean end-to-end latency (ms)",
                "End-to-End Latency across Network Loads", "Figure_4_1_Latency_by_Load.png")
    line_figure(df, "devices", "mean_e2e_latency_ms", [5, 10, 20],
                "Number of IoT devices", "Mean end-to-end latency (ms)",
                "End-to-End Latency across Device Populations", "Figure_4_2_Latency_by_Device_Count.png")
    line_figure(df, "payload_bytes", "throughput_mbps", [256, 1024, 4096],
                "Payload size (bytes)", "Throughput (Mbps)",
                "Throughput across Payload Sizes", "Figure_4_3_Throughput_by_Payload.png", log_x=True)

    checks = {
        "runs": len(df),
        "messages_expected": int(df["messages_expected"].sum()),
        "messages_received": int(df["messages_received"].sum()),
        "authentication_failures": int(df["authentication_failures"].sum()),
        "loss_rows": int(df["message_loss_pct"].ne(0).sum()),
    }
    pd.Series(checks, name="value").to_csv(OUT / "verification_checks.csv")
    print(pd.Series(checks).to_string())


if __name__ == "__main__":
    main()
