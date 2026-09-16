# Data Dictionary

| Field group | Main fields | Meaning |
|---|---|---|
| Matrix identity | `experiment_phase`, `condition_id`, `replicate`, `condition_order`, `matrix_seed` | Identifies the phase, randomized condition, and repetition. |
| Policy | `mode`, `requested_algorithm`, `selected_algorithms` | Records fixed or adaptive operation and the AEAD configuration selected in the run. |
| Workload | `load`, `network_load_pct`, `devices`, `messages_per_device`, `payload_bytes` | Defines the traffic condition. |
| Resource state | `state_cpu_pct`, `state_memory_pct` | Configured policy-input state for the run. |
| Delivery and integrity | `messages_expected`, `messages_received`, `message_loss_pct`, `authentication_failures` | Records message delivery and authentication outcomes. |
| Cryptographic timing | `mean_encryption_ms`, `mean_decryption_ms` | Mean AEAD encryption and decryption time in milliseconds. |
| Network performance | `mean_e2e_latency_ms`, `p95_e2e_latency_ms`, `throughput_mbps` | End-to-end latency and throughput measurements. |
| Process measurements | `mean_process_cpu_pct`, `mean_rss_mb`, `estimated_energy_j` | Mean process CPU use, resident memory, and comparative estimated-energy proxy. |
