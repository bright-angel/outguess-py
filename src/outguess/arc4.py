"""ARC4 stream cipher, bit-compatible with ``src/arc.c`` of OutGuess 0.4.

The reference derives the initial state from ``MD5(type || key)`` and then
feeds that digest into an OpenBSD-style ``arc4_addrandom``.  Note the unusual
``i--`` before the mixing loop and the big-endian word assembly in
``arc4_getword`` -- both are essential for compatibility.
"""

from __future__ import annotations

import hashlib

from ._compat import U32, u8


class ARC4Stream:
    """Mutable RC4-like stream (``struct arc4_stream``)."""

    __slots__ = ("i", "j", "s")

    def __init__(self) -> None:
        self.i = 0
        self.j = 0
        self.s = list(range(256))

    @classmethod
    def from_key(cls, type_name: str | bytes, key: bytes) -> "ARC4Stream":
        """``arc4_initkey(as, type, key, keylen)``."""
        tag = type_name.encode("ascii") if isinstance(type_name, str) else type_name
        digest = hashlib.md5(tag + bytes(key)).digest()
        stream = cls()
        stream.add_random(digest)
        return stream

    def copy(self) -> "ARC4Stream":
        other = ARC4Stream.__new__(ARC4Stream)
        other.i = self.i
        other.j = self.j
        other.s = self.s.copy()
        return other

    def get_byte(self) -> int:
        """``arc4_getbyte`` -- i/j are unsigned chars and wrap at 256."""
        self.i = u8(self.i + 1)
        si = self.s[self.i]
        self.j = u8(self.j + si)
        sj = self.s[self.j]
        self.s[self.i] = sj
        self.s[self.j] = si
        return self.s[u8(si + sj)]

    def get_word(self) -> int:
        """``arc4_getword`` -- four bytes, most significant first."""
        value = self.get_byte() << 24
        value |= self.get_byte() << 16
        value |= self.get_byte() << 8
        value |= self.get_byte()
        return value & U32

    def add_random(self, data: bytes) -> None:
        """``arc4_addrandom`` -- mixes exactly 256 bytes of ``data`` cyclically."""
        if not data:
            raise ValueError("arc4_addrandom requires non-empty data")
        stream = self.s
        datlen = len(data)
        self.i = u8(self.i - 1)
        for n in range(256):
            self.i = u8(self.i + 1)
            si = stream[self.i]
            self.j = u8(self.j + si + data[n % datlen])
            stream[self.i] = stream[self.j]
            stream[self.j] = si
