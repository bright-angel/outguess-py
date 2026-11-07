"""ARC4 / MD5 key stream must match the reference C implementation exactly."""

from __future__ import annotations

from pathlib import Path

import pytest

from outguess._compat import i8
from outguess.arc4 import ARC4Stream

VECTOR = Path(__file__).resolve().parent / "data" / "vectors" / "arc4_fixture-key.txt"


def _load() -> tuple[list[int], list[int], list[int]]:
    words, seeded, bytes_ = [], [], []
    for line in VECTOR.read_text().splitlines():
        kind, value = line.split()
        {"W": words, "S": seeded, "B": bytes_}[kind].append(int(value))
    return words, seeded, bytes_


def test_initial_keystream() -> None:
    words, _, _ = _load()
    stream = ARC4Stream.from_key("Seeding", b"fixture-key")
    assert [stream.get_word() for _ in range(len(words))] == words


def test_addrandom_reseeds_in_place() -> None:
    _, seeded, _ = _load()
    stream = ARC4Stream.from_key("Seeding", b"fixture-key")
    for _ in range(16):
        stream.get_word()
    stream.add_random(bytes((7, 0)))
    assert [stream.get_word() for _ in range(len(seeded))] == seeded


def test_getbyte_after_words() -> None:
    _, _, expected = _load()
    stream = ARC4Stream.from_key("Seeding", b"fixture-key")
    for _ in range(16):
        stream.get_word()
    stream.add_random(bytes((7, 0)))
    for _ in range(8):
        stream.get_word()
    assert [stream.get_byte() for _ in range(len(expected))] == expected


def test_key_prefix_matters() -> None:
    """``arc4_initkey`` hashes the literal type string before the key."""
    a = ARC4Stream.from_key("Seeding", b"k")
    b = ARC4Stream.from_key("Encrypting", b"k")
    assert a.get_word() != b.get_word()


@pytest.mark.parametrize("value", [-129, -128, -1, 0, 127, 128, 255, 256])
def test_signed_char_helper(value: int) -> None:
    result = i8(value)
    assert -128 <= result <= 127
    assert (result & 0xFF) == (value & 0xFF)
