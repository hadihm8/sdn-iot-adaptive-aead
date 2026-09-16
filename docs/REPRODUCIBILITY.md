# Reproducibility Notes

## Environment

The final study was run on Ubuntu under WSL2 with Mininet, Open vSwitch, FAUCET, Mosquitto, and Python. Mininet and Open vSwitch must be installed through the Linux distribution. FAUCET must be configured as the remote controller listening on TCP port 6653. Mosquitto is started by the pilot runner using `configs/mosquitto.conf`.

## Dataset verification

The complete final data file is included at `results/raw/final_experiment.csv`. Run:

```bash
.venv/bin/python scripts/analyze_results.py
```

The verification output should report 3,240 runs, 756,000 expected messages, 756,000 received messages, zero authentication failures, and zero rows with non-zero loss. Figures and a verification CSV are written to `results/generated/`.

## Re-running the matrix

Use the dry-run mode first to inspect the 3,240 scheduled runs:

```bash
.venv/bin/python scripts/run_matrix.py --phase final --dry-run
```

The full execution requires a prepared Linux testbed and administrative privileges:

```bash
sudo .venv/bin/python scripts/run_matrix.py --phase final
```

The runner stores run state and supports resumption when the result file contains the same phase, randomization seed, and message count. Do not overwrite the supplied final CSV. Use a separate `--results-file` name for a new reproduction run.

## Safety

The repository is a laboratory artifact. It does not provide production key management, certificate handling, access control, or deployment hardening. Never reuse the embedded repeatable laboratory secret outside an isolated test environment.
