# Experimental Design

The experiment evaluates four authenticated-encryption policies under matched IoT traffic conditions:

1. Fixed AES-128-GCM
2. Fixed AES-256-GCM
3. Fixed ChaCha20-Poly1305
4. Adaptive policy

The matrix combines three network-load classes (20%, 50%, and 80%), three IoT publisher counts (5, 10, and 20), three payload sizes (256, 1,024, and 4,096 bytes), and 30 independent repetitions. Conditions are shuffled independently within each repetition using seed `20260905`.

The adaptive policy selects AES-256-GCM for the low and medium load classes and AES-128-GCM for the high load class. The decision is logged in the `selected_algorithms` field. The fixed ChaCha20-Poly1305 policy remains a direct baseline. The policy module also defines a ChaCha20-Poly1305 selection branch for direct endpoint CPU or memory pressure, which was not reached by the configured resource-state values in the final matrix.

The output records delivery and integrity outcomes alongside timing and process measurements. One row represents one completed run.
