#!/usr/bin/env python3
"""Authenticated message format used by the SDN-IoT experiment.

The built-in secret is for a repeatable laboratory simulation only. It must not
be reused in a production deployment.
"""

import base64
import hashlib
import json
import struct
from os import urandom
from time import perf_counter_ns

from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

from crypto_policy import OperatingState, select_algorithm


ALGORITHMS = ("AES-128-GCM", "AES-256-GCM", "ChaCha20-Poly1305")
LAB_MASTER_SECRET = b"sdn-iot-adaptive-lab-v0.2-repeatable-key"
HEADER = struct.Struct("!QI")


def derive_key(algorithm: str) -> bytes:
    digest = hashlib.sha256(LAB_MASTER_SECRET + algorithm.encode("ascii")).digest()
    if algorithm == "AES-128-GCM":
        return digest[:16]
    if algorithm in ("AES-256-GCM", "ChaCha20-Poly1305"):
        return digest
    raise ValueError(f"Unsupported algorithm: {algorithm}")


def make_cipher(algorithm: str):
    key = derive_key(algorithm)
    if algorithm.startswith("AES-"):
        return AESGCM(key)
    if algorithm == "ChaCha20-Poly1305":
        return ChaCha20Poly1305(key)
    raise ValueError(f"Unsupported algorithm: {algorithm}")


def choose_algorithm(
    mode: str,
    fixed_algorithm: str,
    network_load_pct: float,
    cpu_pct: float,
    memory_pct: float,
    payload_bytes: int,
) -> str:
    if mode == "fixed":
        if fixed_algorithm not in ALGORITHMS:
            raise ValueError(f"Unsupported fixed algorithm: {fixed_algorithm}")
        return fixed_algorithm
    if mode != "adaptive":
        raise ValueError("mode must be fixed or adaptive")
    state = OperatingState(
        network_load_pct=network_load_pct,
        cpu_pct=cpu_pct,
        memory_pct=memory_pct,
        payload_bytes=payload_bytes,
    )
    return select_algorithm(state)


def encrypt_envelope(
    device_id: str,
    sequence: int,
    application_payload: bytes,
    algorithm: str,
) -> tuple[bytes, float]:
    start_ns = perf_counter_ns()
    plaintext = HEADER.pack(start_ns, sequence) + application_payload
    aad = f"{device_id}:{sequence}:{algorithm}".encode("utf-8")
    nonce = urandom(12)
    cipher = make_cipher(algorithm)
    ciphertext = cipher.encrypt(nonce, plaintext, aad)
    encryption_ms = (perf_counter_ns() - start_ns) / 1_000_000
    envelope = {
        "version": 1,
        "device_id": device_id,
        "sequence": sequence,
        "algorithm": algorithm,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }
    return json.dumps(envelope, separators=(",", ":")).encode("utf-8"), encryption_ms


def decrypt_envelope(message: bytes) -> dict:
    envelope = json.loads(message.decode("utf-8"))
    device_id = str(envelope["device_id"])
    sequence = int(envelope["sequence"])
    algorithm = str(envelope["algorithm"])
    nonce = base64.b64decode(envelope["nonce"], validate=True)
    ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
    aad = f"{device_id}:{sequence}:{algorithm}".encode("utf-8")
    start_dec_ns = perf_counter_ns()
    plaintext = make_cipher(algorithm).decrypt(nonce, ciphertext, aad)
    received_ns = perf_counter_ns()
    decryption_ms = (received_ns - start_dec_ns) / 1_000_000
    sent_ns, embedded_sequence = HEADER.unpack(plaintext[: HEADER.size])
    if embedded_sequence != sequence:
        raise ValueError("Authenticated sequence does not match envelope sequence")
    payload = plaintext[HEADER.size :]
    return {
        "device_id": device_id,
        "sequence": sequence,
        "algorithm": algorithm,
        "payload_bytes": len(payload),
        "ciphertext_bytes": len(ciphertext),
        "wire_bytes": len(message),
        "decryption_ms": decryption_ms,
        "e2e_latency_ms": (received_ns - sent_ns) / 1_000_000,
    }
