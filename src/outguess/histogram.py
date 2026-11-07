"""``histogram`` utility, ported from ``src/histogram.c``.

Reads the bitmap dump produced by ``outguess-extract`` (a 4-byte big-endian bit
count followed by the packed bits) and prints bit / run-length statistics.

The run-length report reproduces an upstream quirk verbatim: ``histogram.c``
compares ``TEST_BIT()`` results directly instead of normalising them to 0/1.
``TEST_BIT(data, i)`` yields the *masked* value ``data[i / 8] & (1 << (i & 7))``,
so for consecutive indices ``i`` and ``i + 1`` the masks differ even when both
bits are set.  The comparison ``TEST_BIT(data, i) != what`` therefore only
reports "no change" while the current bit is ``0`` and the previous one was
``0``; every ``1`` bit terminates a run.  We keep that behaviour so the
histogram of a given carrier is identical to the C tool's -- see
``validation/NOTES.md``.
"""

from __future__ import annotations

import struct
import sys
from typing import Optional, Sequence

from ._compat import f32, f32_div

MAXRUNLEN = 25


def _test_bit(data: bytes, index: int) -> int:
    """``TEST_BIT(data, index)`` -- the raw masked value, *not* 0/1."""
    return data[index >> 3] & (1 << (index & 7))


def _ratio(count: int, bits: int) -> str:
    """``(float)count / bits`` formatted like C's ``%f``."""
    if not bits:
        return "nan"
    return f"{f32_div(f32(float(count)), f32(float(bits))):f}"


def histogram_simple(data: bytes, bits: int) -> str:
    one = sum(1 for i in range(bits) if _test_bit(data, i))
    zero = bits - one
    return (
        f"Bits: {bits:6d}\n"
        f"One:  {one:6d}, {_ratio(one, bits)}\n"
        f"Zero: {zero:6d}, {_ratio(zero, bits)}\n"
    )


def histogram_runlen(data: bytes, bits: int) -> str:
    buckets = [0] * MAXRUNLEN
    what = _test_bit(data, 0) if bits else 0
    count = 1
    for i in range(1, bits):
        current = _test_bit(data, i)
        # Deliberately mirrors upstream: `current` and `what` are masked
        # values at *different* bit positions, so they only compare equal
        # when both are zero.
        if current != what:
            if count >= MAXRUNLEN:
                count = MAXRUNLEN - 1
            buckets[count] += 1
            what = current
            count = 1
        else:
            count += 1
    if count >= MAXRUNLEN:
        count = MAXRUNLEN - 1
    buckets[count] += 1
    return "".join(
        f"{i:3d}:  {buckets[i]:6d}, {_ratio(buckets[i], bits)}\n"
        for i in range(1, MAXRUNLEN)
    )


def analyze(path: str) -> str:
    with open(path, "rb") as handle:
        raw = handle.read()
    if len(raw) < 4:
        raise ValueError("fread(1): 0")
    bits = struct.unpack(">I", raw[:4])[0]
    nbytes = (bits + 7) // 8
    data = raw[4 : 4 + nbytes]
    if len(data) != nbytes:
        raise ValueError(f"fread(2): {len(data)}")
    return histogram_simple(data, bits) + histogram_runlen(data, bits)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(f"{sys.argv[0]}: <file>", file=sys.stderr)
        return 1
    try:
        sys.stdout.write(analyze(args[0]))
    except (OSError, ValueError) as exc:
        print(f"histogram: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
