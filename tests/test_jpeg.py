"""JPEG codec: marker parsing, DCT/IDCT, colour conversion and bit extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from outguess.jpeg import codec, color, markers, tables
from outguess.jpeg.dct import fdct_islow, idct_islow

DATA = Path(__file__).resolve().parent / "data"


def _bitmap_dump(name: str) -> tuple[int, bytes]:
    raw = (DATA / name).read_bytes()
    bits = int.from_bytes(raw[:4], "big")
    return bits, raw[4 : 4 + (bits + 7) // 8]


def _bits_of(bitmap: object, count: int) -> list[int]:
    return [bitmap.get_bit(i) for i in range(count)]


def test_natural_order_is_a_permutation() -> None:
    assert len(tables.NATURAL_ORDER) == 80
    assert sorted(tables.NATURAL_ORDER[:64]) == list(range(64))
    assert tables.NATURAL_ORDER[64:] == [63] * 16


@pytest.mark.parametrize("quality", [10, 50, 75, 90, 100])
def test_quality_tables_are_clamped(quality: int) -> None:
    luma, chroma = tables.quality_tables(quality)
    for table in (luma, chroma):
        assert len(table) == 64
        assert all(1 <= value <= 255 for value in table)


def test_quality_75_luminance_matches_reference() -> None:
    luma, _ = tables.quality_tables(75)
    assert luma[:8] == [8, 6, 5, 8, 12, 20, 26, 31]


def test_quality_monotonic() -> None:
    coarse, _ = tables.quality_tables(30)
    fine, _ = tables.quality_tables(95)
    assert sum(coarse) > sum(fine)


def test_huffman_tables_have_the_standard_symbol_counts() -> None:
    for key, expected in (
        (("dc", 0), 12),
        (("ac", 0), 162),
        (("dc", 1), 12),
        (("ac", 1), 162),
    ):
        entry = tables.STD_HUFF_TABLES[key]
        assert sum(entry["bits"]) == expected
        assert len(entry["values"]) == expected


def test_huffman_prefix_codes_are_unique() -> None:
    huff = tables.standard_huffman()
    for table in huff.values():
        codes = set()
        for symbol, (code, length) in table.codes.items():
            assert (length, code) not in codes
            codes.add((length, code))


def test_fdct_constant_block() -> None:
    coeffs = fdct_islow([0] * 64)
    assert coeffs[0] == 0
    assert all(value == 0 for value in coeffs[1:])


def test_fdct_dc_only() -> None:
    coeffs = fdct_islow([10] * 64)
    assert coeffs[0] == 10 * 64
    assert all(value == 0 for value in coeffs[1:])


def test_idct_flat_block() -> None:
    quant = [8] * 64
    pixels = idct_islow([40] + [0] * 63, quant)
    assert set(pixels) == {168}


def test_idct_clamps_to_sample_range() -> None:
    pixels = idct_islow([1024] + [0] * 63, [1] * 64)
    assert all(0 <= value <= 255 for value in pixels)


def test_ycc_to_rgb_grey_is_identity() -> None:
    assert color.ycc_to_rgb(128, 128, 128) == (128, 128, 128)


def test_marker_parse_sof() -> None:
    data = (DATA / "sample.jpg").read_bytes()
    info = markers.parse(data)
    assert info.width == 160
    assert info.height == 120
    assert len(info.components) == 3
    assert info.components[0].h == 2 and info.components[0].v == 2


@pytest.mark.parametrize(
    "name,mapname",
    [("sample.jpg", "map_sample.bin"), ("sample_jpeg_golden.jpg", "map_golden.bin")],
)
def test_decoded_bitmap_matches_reference(name: str, mapname: str) -> None:
    bits, expected = _bitmap_dump(mapname)
    with open(DATA / name, "rb") as handle:
        image = codec.read_jpeg(handle)
    assert image.bitmap.bits == bits
    # Compare bit by bit: the reference dump leaves the unused high bits of
    # the final byte uninitialised, so a byte-wise comparison is not stable.
    for index in range(bits):
        assert image.bitmap.get_bit(index) == ((expected[index >> 3] >> (index & 7)) & 1), index


def test_recompression_is_deterministic() -> None:
    with open(DATA / "sample.jpg", "rb") as handle:
        image = codec.read_jpeg(handle)
    first = codec.compress_jpeg_bitmap(image, 75)
    second = codec.compress_jpeg_bitmap(image, 75)
    assert first.bits == second.bits
    assert [first.get_bit(i) for i in range(first.bits)] == [
        second.get_bit(i) for i in range(second.bits)
    ]


def test_decode_reencode_is_stable() -> None:
    with open(DATA / "sample.jpg", "rb") as handle:
        image = codec.read_jpeg(handle)
    first = codec.compress_jpeg_bitmap(image, 75)
    second = codec.compress_jpeg_bitmap(image, 75)
    assert first.bits == second.bits
    assert first.data == second.data


def test_fancy_upsample_h2v1_matches_reference_columns() -> None:
    # libjpeg's 3/4 + 1/4 alternation with the border special cases.
    plane = bytearray([10, 20, 30, 40])
    out = color.h2v1_fancy_upsample(plane, 4, 1)
    assert list(out) == [
        10,
        (30 + 20 + 2) >> 2,          # first column pair, +2 bias
        (60 + 10 + 1) >> 2,          # general case, +1 bias
        (60 + 30 + 2) >> 2,          # general case, +2 bias
        (90 + 20 + 1) >> 2,
        (90 + 40 + 2) >> 2,
        (120 + 30 + 1) >> 2,         # last column pair, +1 bias
        40,
    ]


def test_fancy_upsample_h2v1_single_column() -> None:
    assert list(color.h2v1_fancy_upsample(bytearray([7]), 1, 1)) == [7, 7]


@pytest.mark.parametrize("name", ["photo_422.jpg", "photo_444.jpg"])
def test_sampling_factors_are_detected(name: str) -> None:
    info = markers.parse((DATA / name).read_bytes())
    factors = [(c.h, c.v) for c in info.components]
    expected = [(2, 1), (1, 1), (1, 1)] if name == "photo_422.jpg" else [(1, 1)] * 3
    assert factors == expected


@pytest.mark.parametrize("name", ["photo_422.jpg", "photo_444.jpg"])
def test_non_subsampled_carriers_recompress(name: str) -> None:
    """4:2:2 and 4:4:4 carriers decode and re-compress without errors."""
    with open(DATA / name, "rb") as handle:
        image = codec.read_jpeg(handle)
    assert image.depth == 3
    assert len(image.img) == image.x * image.y * 3
    bitmap = codec.compress_jpeg_bitmap(image, 75)
    assert bitmap.bits > 0


def test_greyscale_carrier_is_rejected_for_embedding() -> None:
    """Upstream aborts with "Bogus input colorspace"; so do we."""
    with open(DATA / "photo_gray.jpg", "rb") as handle:
        image = codec.read_jpeg(handle)
    assert image.depth == 1
    with pytest.raises(ValueError, match="Bogus input colorspace"):
        codec.compress_jpeg_bitmap(image, 75)
