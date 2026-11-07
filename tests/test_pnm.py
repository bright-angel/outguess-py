"""PNM/PPM container handling."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from outguess.handlers.pnm import bitmap_from_pnm, bitmap_to_pnm, read_pnm, write_pnm


def _read(name: str) -> object:
    return read_pnm(io.BytesIO((Path(__file__).parent / "data" / name).read_bytes()))


def test_read_ppm() -> None:
    image = _read("sample.ppm")
    assert (image.x, image.y, image.depth) == (64, 64, 3)
    assert len(image.img) == 64 * 64 * 3


def test_read_pgm() -> None:
    image = _read("sample.pnm")
    assert (image.x, image.y, image.depth) == (40, 30, 1)
    assert len(image.img) == 40 * 30


@pytest.mark.parametrize("name", ["sample.ppm", "sample.pnm"])
def test_roundtrip_is_byte_identical(name: str) -> None:
    raw = (Path(__file__).parent / "data" / name).read_bytes()
    image = read_pnm(io.BytesIO(raw))
    out = io.BytesIO()
    write_pnm(out, image)
    assert out.getvalue() == raw


def test_bitmap_uses_lsb_of_every_sample() -> None:
    image = _read("sample.ppm")
    bitmap = bitmap_from_pnm(image, 0)
    assert bitmap.bits == image.x * image.y * image.depth
    for index in range(bitmap.bits):
        assert bitmap.get_bit(index) == (image.img[index] & 1)


def test_bitmap_to_pnm_writes_back_bits() -> None:
    image = _read("sample.ppm")
    bitmap = bitmap_from_pnm(image, 0)
    for index in range(0, bitmap.bits, 7):
        bitmap.set_bit(index, bitmap.get_bit(index) ^ 1)
    bitmap_to_pnm(image, bitmap, 0)
    for index in range(bitmap.bits):
        assert (image.img[index] & 1) == bitmap.get_bit(index)


def test_rejects_bad_magic() -> None:
    with pytest.raises(ValueError):
        read_pnm(io.BytesIO(b"P3\n1 1\n255\n0 0 0\n"))
