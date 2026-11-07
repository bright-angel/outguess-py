"""JPEG carrier handler.

Implemented in :mod:`outguess.jpeg`; the handler wires the coefficient-level
codec into the generic stego engine (``src/jpg.c`` in the original).
"""

from __future__ import annotations

from typing import BinaryIO, Optional

from ..bitmap import Bitmap
from ..steg import STEG_RETRIEVE, StegState
from .base import Handler, Image

JPG_THRES_MAX = 0x25
JPG_THRES_LOW = 0x04
JPG_THRES_MIN = 0x03


class JPEGHandler(Handler):
    extension = "jpg"
    extension_alternative = None

    def __init__(self) -> None:
        self.quality = 75
        self.state: Optional[StegState] = None
        self._writing: Optional[Bitmap] = None

    def init(self, parameter: Optional[str]) -> None:
        if parameter:
            try:
                self.quality = int(parameter)
            except ValueError:
                self.quality = 0
        if self.quality < 75:
            self.quality = 75
        if self.quality > 100:
            self.quality = 100
        import sys

        print(f"JPEG compression quality set to {self.quality}", file=sys.stderr)

    def read(self, stream: BinaryIO) -> Image:
        from ..jpeg.codec import read_jpeg

        return read_jpeg(stream, self.quality)

    def write(self, stream: BinaryIO, image: Image) -> None:
        from ..jpeg.codec import write_jpeg

        write_jpeg(stream, image, self.quality, self._writing)
        self._writing = None

    def get_bitmap(self, image: Image, flags: int) -> Bitmap:
        if flags & STEG_RETRIEVE:
            if image.bitmap is None:
                raise ValueError("JPEG image has no extracted bitmap")
            bitmap = image.bitmap
            image.bitmap = None
            return bitmap
        from ..jpeg.codec import compress_jpeg_bitmap

        return compress_jpeg_bitmap(image, self.quality)

    def put_bitmap(self, image: Image, bitmap: Bitmap, flags: int) -> None:
        self._writing = bitmap

    def preserve(self, bitmap: Bitmap, off: int) -> int:
        from ..jpeg.codec import preserve_jpg

        return preserve_jpg(bitmap, off)


jpg_handler = JPEGHandler()
