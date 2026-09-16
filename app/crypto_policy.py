#!/usr/bin/env python3
"""AEAD implementations and a transparent resource-aware selection policy."""

from dataclasses import dataclass
from os import urandom
from time import perf_counter_ns

from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305


ALGORITHMS = ("AES-128-GCM", "AES-256-GCM", "ChaCha20-Poly1305")


@dataclass(frozen=True)
class OperatingState:
    network_load_pct: float
    cpu_pct: float
    memory_pct: float
    payload_bytes: int


def select_algorithm(state: OperatingState) -> str:
    """Return a deterministic decision that can be audited in experiment logs."""
    if state.cpu_pct >= 70 or state.memory_pct >= 75:
        return "ChaCha20-Poly1305"
    if state.network_load_pct >= 70 or state.payload_bytes >= 1_048_576:
        return "AES-128-GCM"
    return "AES-256-GCM"


def new_key(algorithm: str) -> bytes:
    if algorithm == "AES-128-GCM":
        return AESGCM.generate_key(bit_length=128)
    if algorithm == "AES-256-GCM":
        return AESGCM.generate_key(bit_length=256)
    if algorithm == "ChaCha20-Poly1305":
        return ChaCha20Poly1305.generate_key()
    raise ValueError(f"Unsupported algorithm: {algorithm}")


def _cipher(algorithm: str, key: bytes):
    if algorithm.startswith("AES-"):
        return AESGCM(key)
    if algorithm == "ChaCha20-Poly1305":
        return ChaCha20Poly1305(key)
    raise ValueError(f"Unsupported algorithm: {algorithm}")


def measure_roundtrip(algorithm: str, payload: bytes, aad: bytes = b"sdn-iot") -> dict:
    key = new_key(algorithm)
    nonce = urandom(12)
    cipher = _cipher(algorithm, key)

    start = perf_counter_ns()
    ciphertext = cipher.encrypt(nonce, payload, aad)
    enc_ms = (perf_counter_ns() - start) / 1_000_000

    start = perf_counter_ns()
    plaintext = cipher.decrypt(nonce, ciphertext, aad)
    dec_ms = (perf_counter_ns() - start) / 1_000_000

    if plaintext != payload:
        raise RuntimeError("Authenticated decryption did not recover the payload")

    return {
        "algorithm": algorithm,
        "payload_bytes": len(payload),
        "ciphertext_bytes": len(ciphertext),
        "encryption_ms": enc_ms,
        "decryption_ms": dec_ms,
    }

