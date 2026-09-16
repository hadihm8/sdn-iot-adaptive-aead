# SDN Controlled Adaptive Authenticated Encryption for IoT

This repository contains the experimental artifact for a controlled study of SDN-managed authenticated-encryption policies in resource-constrained IoT networks. The study compares fixed AES-128-GCM, fixed AES-256-GCM, fixed ChaCha20-Poly1305, and an adaptive policy that selects an AEAD configuration from the observed operating state.

The artifact includes the source code, FAUCET and MQTT configuration files, the randomized experimental plan, the complete CSV output from 3,240 final runs, and scripts for reproducing the published summaries and figures.

## Experimental scope

The final design crosses four policies, three network-load levels, three IoT device counts, three payload sizes, and 30 repetitions:

`4 policies x 3 loads x 3 device counts x 3 payload sizes x 30 repetitions = 3,240 runs`

The implementation was evaluated in Ubuntu on WSL2 using Mininet, Open vSwitch, FAUCET, MQTT, and Python. Each run records encryption and decryption time, end-to-end latency, throughput, process CPU use, resident memory, delivery, packet loss, and authentication failures.

## Repository contents

| Path | Contents |
|---|---|
| `app/` | AEAD policy, authenticated-message functions, MQTT publisher, and MQTT subscriber. |
| `configs/` | FAUCET VLAN/port configuration and Mosquitto configuration. |
| `topology/` | Mininet IoT topology. |
| `scripts/` | Pilot runner, randomized matrix runner, and results-analysis script. |
| `results/raw/` | Complete final CSV output for the 3,240 experimental runs. |
| `results/plans/` | Seeded randomized plan for the final matrix. |
| `figures/` | Research architecture and figures generated from the final data. |
| `docs/` | Experimental design, data dictionary, and reproducibility notes. |

## Quick start

This artifact requires a Linux environment with Mininet, Open vSwitch, FAUCET, Mosquitto, and Python 3. The experiment runner starts network namespaces and therefore must be run with `sudo`.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# Verify the recorded final dataset and regenerate the figures.
.venv/bin/python scripts/analyze_results.py

# Inspect the seeded matrix without starting Mininet.
.venv/bin/python scripts/run_matrix.py --phase final --dry-run
```

To execute the full matrix in a prepared FAUCET/Mininet environment:

```bash
sudo .venv/bin/python scripts/run_matrix.py --phase final
```

See `docs/REPRODUCIBILITY.md` before running the full experiment.

## Adaptive policy

The adaptive policy makes an auditable decision for every run. Under the evaluated design, AES-256-GCM is selected for low and medium network-load classes, while AES-128-GCM is selected for the high-load class. ChaCha20-Poly1305 remains a fixed baseline and a future adaptive candidate when direct endpoint CPU or memory pressure crosses the specified threshold.

The embedded laboratory key material is only for a repeatable simulation. It is not a production key-management design and must never be reused in a deployed system.

## Data and publication status

`results/raw/final_experiment.csv` is the authoritative final experimental record. It contains 3,240 rows, one per completed final run. The repository does not contain the manuscript file, author metadata, or credentials. It is intended to remain private while the manuscript is under editorial consideration. A public release and archival DOI can be created after the journal's submission and publication requirements are confirmed.

## License

The source code is available under the MIT License. The experimental data and figures are provided for verification and scholarly use with appropriate attribution.
