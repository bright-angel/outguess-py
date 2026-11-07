"""Helpers that reproduce the exact C semantics used by OutGuess 0.4.

The reference implementation is written in C and relies on a number of
implementation-defined behaviours (32-bit wrap-around, ``float`` rounding,
signed ``char``).  Bit-for-bit compatibility requires emulating those
behaviours rather than using Python's arbitrary precision integers/floats.

Nothing in this module is steganography specific; it is the shared
"ABI emulation layer" used by the rest of the package.
"""

from __future__ import annotations

import struct
from typing import Iterable

U8 = 0xFF
U16 = 0xFFFF
U32 = 0xFFFFFFFF
U64 = 0xFFFFFFFFFFFFFFFF


def u8(value: int) -> int:
    """Truncate to ``unsigned char``."""
    return value & U8


def u16(value: int) -> int:
    return value & U16


def u32(value: int) -> int:
    return value & U32


def i8(value: int) -> int:
    """Truncate to the platform's ``char`` (signed on x86/MSVC/MinGW)."""
    value &= U8
    return value - 256 if value >= 128 else value


def c_div(a: int, b: int) -> int:
    """C integer division: truncate toward zero (Python floors)."""
    if b == 0:
        raise ZeroDivisionError("C integer division by zero")
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def f32(value: float) -> float:
    """Round a Python double to IEEE-754 binary32 (C ``float``)."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def f32_add(a: float, b: float) -> float:
    return f32(f32(a) + f32(b))


def f32_sub(a: float, b: float) -> float:
    return f32(f32(a) - f32(b))


def f32_mul(a: float, b: float) -> float:
    return f32(f32(a) * f32(b))


def f32_div(a: float, b: float) -> float:
    return f32(f32(a) / f32(b))


class BitArray:
    """Packed LSB-first bit array matching ``TEST_BIT``/``WRITE_BIT``.

    ``TEST_BIT(x,y)   == (x[y//8] >> (y & 7)) & 1``
    ``WRITE_BIT(x,y,v)`` replaces bit ``y`` with ``v``.
    """

    __slots__ = ("_buf",)

    def __init__(self, nbytes: int, initial: bytes | None = None) -> None:
        self._buf = bytearray(nbytes)
        if initial is not None:
            self._buf[: len(initial)] = initial[:nbytes]

    @classmethod
    def from_bits(cls, bits: Iterable[int], nbits: int | None = None) -> "BitArray":
        seq = list(bits)
        n = len(seq) if nbits is None else nbits
        obj = cls((n + 7) // 8)
        for i, value in enumerate(seq[:n]):
            if value:
                obj.set(i)
        return obj

    def __len__(self) -> int:
        return len(self._buf) * 8

    @property
    def buffer(self) -> bytearray:
        return self._buf

    def get(self, index: int) -> int:
        if index < 0:
            return 0
        byte = index >> 3
        if byte >= len(self._buf):
            return 0  # C reads out of bounds; zero is the only sane emulation
        return (self._buf[byte] >> (index & 7)) & 1

    def set(self, index: int, value: int = 1) -> None:
        if index < 0:
            return
        byte = index >> 3
        if byte >= len(self._buf):
            return
        mask = 1 << (index & 7)
        if value:
            self._buf[byte] |= mask
        else:
            self._buf[byte] &= ~mask & U8

    def to_bytes(self, nbytes: int | None = None) -> bytes:
        return bytes(self._buf if nbytes is None else self._buf[:nbytes])

    def as_list(self, nbits: int) -> list[int]:
        return [self.get(i) for i in range(nbits)]
