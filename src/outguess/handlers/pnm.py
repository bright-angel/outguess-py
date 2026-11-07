"""PNM/PPM carrier handler, ported from ``src/pnm.c``.

Supports P2/P3 (ASCII) and P5/P6 (binary) input; output is always written as
binary P5/P6, exactly like ``write_pnm``.
"""

from __future__ import annotations

from typing import BinaryIO, Optional

from .._compat import i8
from ..bitmap import Bitmap
from ..steg import STEG_MARK
from .base import Handler, Image

PNM_THRES_MAX = 0xF0
PNM_THRES_MIN = 0x10
BITSHIFT = 0


class _Reader:
    """Byte cursor implementing ``fgets``/``fscanf``/``getc`` semantics."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def getc(self) -> int:
        if self.pos >= len(self.data):
            return -1
        c = self.data[self.pos]
        self.pos += 1
        return c

    def ungetc(self) -> None:
        self.pos -= 1

    def fgets(self, limit: int = 10) -> bytes:
        start = self.pos
        end = self.data.find(b"\n", start)
        if end < 0:
            end = len(self.data) - 1
        end = min(end, start + limit - 2)
        self.pos = min(end + 1, len(self.data))
        return self.data[start : self.pos]

    def skip_white(self) -> None:
        while True:
            while True:
                c = self.getc()
                if c == -1 or not (0 < c < 256 and chr(c).isspace()):
                    break
            if c == ord("#"):
                while True:
                    c = self.getc()
                    if c == ord("\n") or c == -1:
                        break
            else:
                if c != -1:
                    self.ungetc()
                return

    def read_int(self) -> int:
        self.skip_white()
        sign = 1
        c = self.getc()
        if c == ord("-"):
            sign = -1
            c = self.getc()
        elif c == ord("+"):
            c = self.getc()
        digits = []
        while c != -1 and 0x30 <= c <= 0x39:
            digits.append(chr(c))
            c = self.getc()
        if c != -1:
            self.ungetc()
        if not digits:
            raise ValueError("Failed to read image integer value")
        return sign * int("".join(digits))


def read_pnm(stream: BinaryIO) -> Image:
    data = stream.read()
    reader = _Reader(data)
    magic = reader.fgets(10)
    if len(magic) < 3 or magic[0:1] != b"P" or not magic[1:2].isdigit() or magic[2:3] != b"\n":
        raise ValueError("Unsupported input file type!")

    x = reader.read_int()
    y = reader.read_int()
    maxval = reader.read_int()
    reader.getc()  # consume the single whitespace byte after maxval
    if maxval > 255 or maxval <= 0 or x <= 1 or y <= 1:
        raise ValueError("Unsupported value range!")

    kind = magic[1:2]
    if kind in (b"2", b"5"):
        depth = 1
    elif kind in (b"3", b"6"):
        depth = 3
    else:
        raise ValueError(f"Unsupported input file type 'P{chr(kind[0])}'!")

    size = x * y * depth
    img = bytearray(size)
    if kind in (b"2", b"3"):
        for i in range(size):
            value = reader.read_int()
            if value < 0 or value > maxval:
                raise ValueError(f"Out of range value {value}!")
            img[i] = value
    else:
        raw = data[reader.pos : reader.pos + size]
        if len(raw) != size:
            raise ValueError("Failed to read PPM image data!")
        img[:] = raw

    return Image(x=x, y=y, depth=depth, maxval=maxval, img=img)


def write_pnm(stream: BinaryIO, image: Image) -> None:
    header = f"P{5 if image.depth == 1 else 6}\n{image.x} {image.y}\n{image.maxval}\n"
    stream.write(header.encode("ascii"))
    stream.write(image.img)


def bitmap_from_pnm(image: Image, flags: int = 0) -> Bitmap:
    bits = image.x * image.y * image.depth
    bitmap = Bitmap(bits)
    img = image.img
    off = 0
    i = 0
    while i < bits:
        tmp = 0
        for j in range(8):
            if i >= bits:
                break
            value = img[i]
            if value >= PNM_THRES_MAX:
                bitmap.detect[i] = -1
            elif value <= PNM_THRES_MIN:
                bitmap.detect[i] = 1
            else:
                bitmap.detect[i] = 0
            bitmap.data[i] = i8(value)
            tmp |= ((value & (1 << BITSHIFT)) >> BITSHIFT) << j
            i += 1
        bitmap.bitmap.buffer[off] = tmp
        off += 1
    return bitmap


def bitmap_to_pnm(image: Image, bitmap: Bitmap, flags: int) -> None:
    img = image.img
    off = 0
    i = 0
    while i < bitmap.bits:
        tmp = bitmap.bitmap.buffer[off]
        off += 1
        for _ in range(8):
            if i >= bitmap.bits:
                break
            if (flags & STEG_MARK) and bitmap.is_locked(i):
                img[i] = 255
            img[i] = (img[i] & ~(1 << BITSHIFT)) | ((tmp & 1) << BITSHIFT)
            i += 1
            tmp >>= 1


def preserve_pnm(bitmap: Bitmap, off: int) -> int:
    if off == -1:
        bitmap.preserve = preserve_pnm
    return -1


class PNMHandler(Handler):
    extension = "ppm"
    extension_alternative = "pnm"

    def init(self, parameter: Optional[str]) -> None:
        pass

    def read(self, stream: BinaryIO) -> Image:
        return read_pnm(stream)

    def write(self, stream: BinaryIO, image: Image) -> None:
        write_pnm(stream, image)

    def get_bitmap(self, image: Image, flags: int) -> Bitmap:
        return bitmap_from_pnm(image, flags)

    def put_bitmap(self, image: Image, bitmap: Bitmap, flags: int) -> None:
        bitmap_to_pnm(image, bitmap, flags)

    def preserve(self, bitmap: Bitmap, off: int) -> int:
        return preserve_pnm(bitmap, off)


pnm_handler = PNMHandler()
