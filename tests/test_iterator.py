"""Skip-adjusted bit iterator positions must match the C implementation."""

from __future__ import annotations

from pathlib import Path

import pytest

from outguess.iterator import INIT_SKIPMOD, Iterator, skip_adjust

VECTOR = Path(__file__).resolve().parent / "data" / "vectors" / "iterator_fixture-key.txt"


def _load() -> tuple[int, list[tuple[int, list[int]]]]:
    start = -1
    rows: list[tuple[int, list[int]]] = []
    for line in VECTOR.read_text().splitlines():
        parts = line.split()
        if parts[0] == "O":
            start = int(parts[1])
        elif parts[0] == "B":
            rows.append((int(parts[1]), [int(v) for v in parts[2:]]))
    return start, rows


def test_initial_offset_matches() -> None:
    start, _ = _load()
    assert Iterator(b"fixture-key").current == start


def test_adaptive_positions_match() -> None:
    _, rows = _load()
    it = Iterator(b"fixture-key")
    remaining = len(rows)
    for skipmod, positions in rows:
        it.adapt(12288, remaining)
        assert it.skipmod == skipmod
        seen = []
        for _ in positions:
            seen.append(it.current)
            it.next()
        assert seen == positions
        remaining -= 1


def test_copy_is_independent() -> None:
    it = Iterator(b"k")
    clone = it.copy()
    assert clone.current == it.current
    assert clone.next() == it.next()
    clone.next()
    assert clone.current != it.current


def test_skip_adjust_stays_between_one_and_two() -> None:
    for bits in (256, 1024, 40960):
        for off in (0, 1, bits // 4, bits // 2, bits - 2):
            value = skip_adjust(bits, off)
            assert 1.0 <= value <= 2.0


def test_initial_skipmod_constant() -> None:
    assert INIT_SKIPMOD == 32


def test_offset_monotonically_increases() -> None:
    it = Iterator(b"monotonic")
    previous = it.current
    for _ in range(200):
        current = it.next()
        assert current > previous
        previous = current


def test_seed_is_little_endian() -> None:
    a, b = Iterator(b"k"), Iterator(b"k")
    a.seed(0x1234)
    b.stream.add_random(bytes((0x34, 0x12)))
    assert a.stream.get_word() == b.stream.get_word()


@pytest.mark.parametrize("bits", [64, 256, 4096])
def test_adapt_never_divides_by_zero(bits: int) -> None:
    it = Iterator(b"k")
    it.adapt(bits, 1)
    assert it.skipmod >= 1
