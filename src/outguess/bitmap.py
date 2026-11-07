"""``struct _bitmap``: the carrier-independent redundant-bit container."""

from __future__ import annotations

from typing import Callable, Optional

from ._compat import BitArray, i8

PreserveFn = Callable[["Bitmap", int], int]


class Bitmap:
    """Redundant bits plus the bookkeeping arrays used by the embedder.

    Attributes mirror ``struct _bitmap`` one-for-one.  ``detect`` and ``data``
    are arrays of *signed* C ``char`` values.
    """

    __slots__ = (
        "bitmap",
        "locked",
        "metalock",
        "detect",
        "data",
        "bytes",
        "bits",
        "preserve",
        "maxcorrect",
        "foil",
        "foilfail",
        "extra",
    )

    def __init__(self, bits: int, nbytes: int | None = None) -> None:
        self.bits = bits
        self.bytes = (bits + 7) // 8 if nbytes is None else nbytes
        self.bitmap = BitArray(self.bytes)
        self.locked = BitArray(self.bytes)
        self.metalock = BitArray(self.bytes)
        self.detect: list[int] = [0] * bits
        self.data: list[int] = [0] * bits
        self.preserve: Optional[PreserveFn] = None
        self.maxcorrect: int = 0
        # Mirrors the C globals steg_foil / steg_foilfail, plus handler scratch.
        self.foil = 0
        self.foilfail = 0
        self.extra: dict = {}

    @classmethod
    def from_arrays(
        cls,
        bits: int,
        bitmap: bytearray,
        locked: bytearray,
        data: list[int],
        detect: list[int],
        metalock: bytearray | None = None,
    ) -> "Bitmap":
        nbytes = (bits + 7) // 8
        obj = cls(bits, nbytes)
        obj.bitmap = BitArray(nbytes, bytes(bitmap))
        obj.locked = BitArray(nbytes, bytes(locked))
        obj.metalock = BitArray(nbytes, bytes(metalock) if metalock else None)
        obj.data = [i8(v) for v in data[:bits]]
        obj.detect = [i8(v) for v in detect[:bits]]
        return obj

    def get_bit(self, index: int) -> int:
        return self.bitmap.get(index)

    def set_bit(self, index: int, value: int) -> None:
        self.bitmap.set(index, value)

    def is_locked(self, index: int) -> int:
        return self.locked.get(index)

    def is_metalocked(self, index: int) -> int:
        return self.metalock.get(index)

    def lock(self, index: int) -> None:
        self.locked.set(index, 1)
