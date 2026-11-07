"""Generic bit-position iterator, ported from ``src/iterator.c``.

The iterator walks the redundant-bit bitmap with a keyed ARC4 stream.  A
16-bit seed (embedded in the message header) is mixed into the stream after
the header, and the stride is adapted to the remaining message length with
``SKIPADJ``.  C ``float`` rounding must be emulated exactly.
"""

from __future__ import annotations

from ._compat import U32, f32, f32_div, f32_mul, f32_sub, u16
from .arc4 import ARC4Stream

INIT_SKIPMOD = 32
DEFAULT_ITER = 256


def skip_adjust(bits: int, off: int) -> float:
    """``SKIPADJ(bitmap->bits, bitmap->bits - iter->off)``.

    ``(x)/32`` is C integer division and the whole conditional expression has
    type ``float`` (the ``2`` branch is promoted from ``int``).
    """
    q = bits // 32  # C int division, bits > 0
    y = bits - off
    if y > q:
        return f32(2.0)
    if q == 0:
        return f32(2.0)
    quotient = f32_div(f32(float(q - y)), f32(float(q)))
    return f32_sub(2.0, quotient)


class Iterator:
    """``struct _iterator`` (the bitmap argument is unused by the C code)."""

    __slots__ = ("stream", "skipmod", "off")

    def __init__(self, key: bytes) -> None:
        self.stream = ARC4Stream.from_key("Seeding", key)
        self.skipmod = INIT_SKIPMOD
        self.off = self.stream.get_word() % self.skipmod

    @property
    def current(self) -> int:
        return self.off

    def copy(self) -> "Iterator":
        other = Iterator.__new__(Iterator)
        other.stream = self.stream.copy()
        other.skipmod = self.skipmod
        other.off = self.off
        return other

    def next(self) -> int:
        """Advance by ``(arc4_getword() % skipmod) + 1`` and return new offset."""
        self.off += (self.stream.get_word() % self.skipmod) + 1
        return self.off

    def seed(self, seed: int) -> None:
        """Mix the little-endian 16-bit seed into the ARC4 state."""
        seed = u16(seed)
        self.stream.add_random(bytes((seed & 0xFF, seed >> 8)))

    def adapt(self, bits: int, datalen: int) -> None:
        """``iterator_adapt`` -- recompute the stride for the next byte.

        The C expression is evaluated entirely in single precision and then
        truncated into an unsigned 32-bit ``skipmod``.
        """
        y = bits - self.off
        adj = skip_adjust(bits, self.off)
        numerator = f32_mul(adj, f32(float(y)))
        denominator = f32(float(8 * datalen))
        value = f32_div(numerator, denominator)
        # C casts the float result to u_int32_t (truncation toward zero).
        # The C loop guarantees off < bits here, hence value >= 0.
        self.skipmod = int(value) & U32
