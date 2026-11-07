"""Carrier handler interface (``struct _handler`` / ``struct _image``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import BinaryIO, Optional

from ..bitmap import Bitmap


@dataclass
class Image:
    """``struct _image`` -- raw RGB/PGM samples plus an optional cached bitmap."""

    x: int = 0
    y: int = 0
    depth: int = 3
    maxval: int = 255
    img: bytearray = field(default_factory=bytearray)
    bitmap: Optional[Bitmap] = None
    flags: int = 0


class Handler:
    """Data-source specific hooks used by the stego engine."""

    extension: str = ""
    extension_alternative: Optional[str] = None

    def init(self, parameter: Optional[str]) -> None:  # pragma: no cover - default
        pass

    def read(self, stream: BinaryIO) -> Image:
        raise NotImplementedError

    def write(self, stream: BinaryIO, image: Image) -> None:
        raise NotImplementedError

    def get_bitmap(self, image: Image, flags: int) -> Bitmap:
        raise NotImplementedError

    def put_bitmap(self, image: Image, bitmap: Bitmap, flags: int) -> None:
        raise NotImplementedError

    def preserve(self, bitmap: Bitmap, off: int) -> int:
        raise NotImplementedError


def get_handler(name: str) -> Optional[Handler]:
    """Resolve a filename extension to a handler (case-insensitive)."""
    from .jpeg import jpg_handler
    from .pnm import pnm_handler

    handlers = (pnm_handler, jpg_handler)
    if "." not in name:
        return None
    ext = name.rsplit(".", 1)[1].lower()
    for handler in reversed(handlers):
        if ext == handler.extension:
            return handler
        if handler.extension_alternative and ext == handler.extension_alternative:
            return handler
    return None
