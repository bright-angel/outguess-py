"""Golay (23,12,7) tables and 3-bit error correction."""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import pytest

from outguess import golay

VECTOR = Path(__file__).resolve().parent / "data" / "vectors" / "golay_tables.txt"


def _load() -> tuple[dict[int, int], dict[int, int], str, str]:
    enc: dict[int, int] = {}
    dec: dict[int, int] = {}
    enc_hash = dec_hash = ""
    for line in VECTOR.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "encoding_sha256":
            enc_hash = parts[1]
        elif parts[0] == "decoding_sha256":
            dec_hash = parts[1]
        elif parts[0] == "enc":
            enc[int(parts[1])] = int(parts[2])
        elif parts[0] == "dec":
            dec[int(parts[1])] = int(parts[2])
    return enc, dec, enc_hash, dec_hash


def test_table_checksums_match_reference() -> None:
    _, _, enc_hash, dec_hash = _load()
    assert hashlib.sha256(repr(golay.ENCODING_TABLE).encode()).hexdigest() == enc_hash
    assert hashlib.sha256(repr(golay.DECODING_TABLE).encode()).hexdigest() == dec_hash


def test_sampled_table_entries() -> None:
    enc, dec, _, _ = _load()
    for index, value in enc.items():
        assert golay.ENCODING_TABLE[index] == value
    for index, value in dec.items():
        assert golay.DECODING_TABLE[index] == value


@pytest.mark.parametrize("data", [0, 1, 2, 0x555, 0xAAA, 0xFFF])
def test_encode_decode_roundtrip(data: int) -> None:
    code = golay.encode(data)
    assert code & 0x7FFFFF == code
    assert (code >> 11) == data
    assert golay.decode(code) == code


def test_corrects_up_to_three_bit_errors() -> None:
    rng = random.Random(1234)
    for _ in range(300):
        data = rng.randrange(1 << 12)
        code = golay.encode(data)
        for _ in range(3):
            damaged = code
            for bit in rng.sample(range(23), 3):
                damaged ^= 1 << bit
            assert golay.decode(damaged) >> 11 == data


def test_syndrome_of_valid_codeword_is_zero() -> None:
    for data in range(0, 4096, 97):
        assert golay.get_syndrome(golay.encode(data)) == 0
