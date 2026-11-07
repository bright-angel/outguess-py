"""Coefficient-level JPEG codec wired to OutGuess' ``steg_use_bit`` hook.

The patched libjpeg calls ``steg_use_bit`` for every quantized DCT
coefficient of every *real* block, in MCU / block / natural-order sequence.
Coefficients whose unsigned-short value is 0 or 1 are skipped; all others
contribute their least-significant bit to the redundant-bit bitmap.  This
module reproduces that traversal both when decoding a JPEG and when
re-compressing raw pixels at a given quality, which is what makes carriers
interchangeable with the original C program.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Optional

from .._compat import BitArray, f32, f32_div, i8
from ..bitmap import Bitmap
from ..steg import DCTENTRIES, DCTFREQMIN, DCTFREQRANGE, DCTFREQREDUCE
from . import color, markers
from .bitio import BitReader, BitWriter, decode_block, encode_block
from .dct import fdct_islow, idct_islow

JPG_THRES_MAX = 0x25
JPG_THRES_LOW = 0x04
JPG_THRES_MIN = 0x03


def _ceil_div(a: int, b: int) -> int:
    return (a + b - 1) // b


def _i16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value >= 0x8000 else value


@dataclass
class Geometry:
    width: int
    height: int
    max_h: int
    max_v: int
    mcus_per_row: int
    total_rows: int
    comps: list[dict]

    @classmethod
    def build(cls, width: int, height: int, factors: list[tuple[int, int]],
              interleaved: bool = True) -> "Geometry":
        max_h = max(h for h, _ in factors)
        max_v = max(v for _, v in factors)
        if interleaved:
            mcus_per_row = _ceil_div(width, max_h * 8)
            total_rows = _ceil_div(height, max_v * 8)
            mcu_w = [h for h, _ in factors]
            mcu_h = [v for _, v in factors]
        else:
            mcus_per_row = _ceil_div(width * factors[0][0], max_h * 8)
            total_rows = _ceil_div(height * factors[0][1], max_v * 8)
            mcu_w = [1] * len(factors)
            mcu_h = [1] * len(factors)
        comps = []
        for (h, v), mw, mh in zip(factors, mcu_w, mcu_h):
            width_in_blocks = _ceil_div(width * h, max_h * 8)
            height_in_blocks = _ceil_div(height * v, max_v * 8)
            last_col = width_in_blocks % mw or mw
            last_row = height_in_blocks % mh or mh
            comps.append(
                dict(
                    h=h, v=v, mcu_w=mw, mcu_h=mh,
                    width_in_blocks=width_in_blocks,
                    height_in_blocks=height_in_blocks,
                    downsampled_width=_ceil_div(width * h, max_h),
                    downsampled_height=_ceil_div(height * v, max_v),
                    last_col=last_col, last_row=last_row,
                    plane_width=mcus_per_row * mw * 8,
                    plane_height=total_rows * mh * 8,
                )
            )
        return cls(width, height, max_h, max_v, mcus_per_row, total_rows, comps)


class _BitmapBuilder:
    """Emulates ``steg_use_bit`` in JPEG_READING / JPEG_WRITING state."""

    __slots__ = ("bits", "data", "override", "off")

    def __init__(self, override: Optional[Bitmap] = None) -> None:
        self.bits: list[int] = []
        self.data: list[int] = []
        self.override = override
        self.off = 0

    def use(self, temp: int) -> int:
        unsigned = temp & 0xFFFF
        if (unsigned & 1) == unsigned:  # temp is 0 or 1 -> not usable
            return _i16(unsigned)
        if self.override is None:
            self.bits.append(unsigned & 1)
            self.data.append(i8(unsigned))
        else:
            bit = self.override.get_bit(self.off)
            unsigned = (unsigned & ~1) | bit
        self.off += 1
        return _i16(unsigned)

    def finish(self) -> Bitmap:
        nbits = len(self.bits)
        bitmap = Bitmap(nbits)
        for i, value in enumerate(self.bits):
            if value:
                bitmap.set_bit(i, 1)
        bitmap.data = self.data[:nbits]
        for i in range(nbits):
            temp = i8(abs(bitmap.data[i]))
            if temp >= JPG_THRES_MAX:
                bitmap.detect[i] = -1
            elif temp >= JPG_THRES_LOW:
                bitmap.detect[i] = 0
            elif temp >= JPG_THRES_MIN:
                bitmap.detect[i] = 1
            else:
                bitmap.detect[i] = 2
        return bitmap


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def decode_coefficients(data: bytes, info: markers.JPEGInfo
                        ) -> tuple[list[list[int]], _BitmapBuilder, Geometry, list[tuple[int, int, int]]]:
    """Decode the entropy stream; also build the OutGuess bitmap.

    Returns ``(blocks, builder, geometry, placements)`` where ``placements``
    maps each *real* block to ``(component_index, block_row, block_col)``.
    """
    factors = [(c.h, c.v) for c in info.components]
    interleaved = len(info.scan) > 1
    geom = Geometry.build(info.width, info.height, factors, interleaved)
    reader = BitReader(data, info.entropy_pos, info.restart_interval)
    builder = _BitmapBuilder()
    last_dc = {ci: 0 for ci in info.scan}
    blocks: list[list[int]] = []
    real_blocks: list[list[int]] = []
    placements: list[tuple[int, int, int]] = []

    for irow in range(geom.total_rows):
        for mcu_col in range(geom.mcus_per_row):
            for ci in info.scan:
                comp = info.components[ci]
                spec = geom.comps[ci]
                blockcnt = spec["mcu_w"] if mcu_col < geom.mcus_per_row - 1 else spec["last_col"]
                for yindex in range(spec["mcu_h"]):
                    row_relevant = (
                        irow < geom.total_rows - 1
                        or yindex < spec["last_row"]
                    )
                    for xindex in range(spec["mcu_w"]):
                        block, last_dc[ci] = decode_block(
                            reader,
                            info.dc_tables.get(comp.td) or info.dc_tables[0],
                            info.ac_tables.get(comp.ta) or info.ac_tables[0],
                            last_dc[ci],
                        )
                        real = row_relevant and xindex < blockcnt
                        if real:
                            for k in range(64):
                                block[k] = builder.use(block[k])
                            real_blocks.append(block)
                            placements.append((ci, irow * spec["mcu_h"] + yindex,
                                               mcu_col * spec["mcu_w"] + xindex))
                        blocks.append(block)
            reader.mcu_done()
    return real_blocks, builder, geom, placements


def _reconstruct_pixels(blocks: list[list[int]], placements: list[tuple[int, int, int]],
                        geom: Geometry, info: markers.JPEGInfo) -> bytearray:
    """IDCT + fancy upsampling + YCbCr->RGB, matching libjpeg 6b."""
    planes: dict[int, bytearray] = {}
    for ci in info.scan:
        spec = geom.comps[ci]
        planes[ci] = bytearray(spec["plane_width"] * spec["plane_height"])

    quant_for = [info.quant.get(c.tq) or info.quant[0] for c in info.components]
    for block, (ci, brow, bcol) in zip(blocks, placements):
        spec = geom.comps[ci]
        plane = planes[ci]
        samples = idct_islow(block, quant_for[ci])
        x0, y0 = bcol * 8, brow * 8
        stride = spec["plane_width"]
        for row in range(8):
            base = (y0 + row) * stride + x0
            plane[base : base + 8] = bytes(samples[row * 8 : row * 8 + 8])

    # Upsample chroma components to full resolution where needed.  jdmaster.c
    # picks the method from the sampling factors: 2x2 -> h2v2_fancy_upsample,
    # 2x1 -> h2v1_fancy_upsample, "same size" -> no upsampling at all.
    full: list[bytearray] = []
    for ci in info.scan:
        spec = geom.comps[ci]
        plane = planes[ci]
        if spec["h"] * 2 == geom.max_h and spec["v"] * 2 == geom.max_v:
            up = color.h2v2_fancy_upsample(
                plane, spec["plane_width"], spec["downsampled_height"],
                geom.width, loop_width=spec["downsampled_width"],
            )
            up_stride = 2 * spec["downsampled_width"]
            padded = bytearray(geom.width * geom.height)
            for row in range(min(geom.height, len(up) // up_stride)):
                src = row * up_stride
                dst = row * geom.width
                padded[dst : dst + min(geom.width, up_stride)] = up[src : src + min(geom.width, up_stride)]
            full.append(padded)
        elif spec["h"] * 2 == geom.max_h and spec["v"] == geom.max_v:
            # 4:2:2 -- horizontal triangle filter only.
            up = color.h2v1_fancy_upsample(
                plane, spec["downsampled_width"], spec["plane_height"]
            )
            up_stride = 2 * spec["downsampled_width"]
            padded = bytearray(geom.width * geom.height)
            for row in range(geom.height):
                src = row * up_stride
                dst = row * geom.width
                padded[dst : dst + min(geom.width, up_stride)] = up[
                    src : src + min(geom.width, up_stride)
                ]
            full.append(padded)
        else:
            padded = bytearray(geom.width * geom.height)
            for row in range(geom.height):
                src = row * spec["plane_width"]
                dst = row * geom.width
                padded[dst : dst + geom.width] = plane[src : src + geom.width]
            full.append(padded)

    if len(info.scan) == 1:
        return full[0]

    y_plane, cb_plane, cr_plane = full[0], full[1], full[2]
    out = bytearray(geom.width * geom.height * 3)
    p = 0
    for i in range(geom.width * geom.height):
        r, g, b = color.ycc_to_rgb(y_plane[i], cb_plane[i], cr_plane[i])
        out[p], out[p + 1], out[p + 2] = r, g, b
        p += 3
    return out


def read_jpeg(stream: BinaryIO, quality: int = 75):
    """``read_JPEG_file`` -- decode a JPEG and extract its redundant bits."""
    from ..handlers.base import Image

    data = stream.read()
    info = markers.parse(data)
    if info.progressive:
        raise ValueError("progressive JPEG is not supported by OutGuess")
    blocks, builder, geom, placements = decode_coefficients(data, info)
    bitmap = builder.finish()
    image = Image(
        x=info.width, y=info.height,
        depth=3 if len(info.scan) > 1 else 1,
        maxval=255,
        bitmap=bitmap,
    )
    if len(info.scan) > 1:
        image.img = _reconstruct_pixels(blocks, placements, geom, info)
    else:
        image.img = bytearray()
    return image


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def _build_planes_from_rgb(image, quality: int) -> tuple[list[bytearray], Geometry, list[list[int]]]:
    width, height = image.x, image.y
    # The upstream compressor always declares JCS_YCbCr / 3 components, so a
    # single-component source (greyscale JPEG or a PGM) makes libjpeg abort
    # with "Bogus input colorspace".  Refuse it here with the same wording
    # instead of failing somewhere inside the colour conversion.
    if image.depth != 3:
        raise ValueError("Bogus input colorspace")
    factors = [(2, 2), (1, 1), (1, 1)]
    geom = Geometry.build(width, height, factors, True)
    full_w = geom.mcus_per_row * geom.max_h * 8
    full_h = geom.total_rows * geom.max_v * 8

    y, cb, cr = color.rgb_planes(bytes(image.img), width, height, image.depth)
    y_pad = color.pad_plane(y, width, height, full_w, full_h)

    # Chroma is subsampled 2x2.  libjpeg first pads the *full resolution*
    # buffer to an even number of rows (jcprepct.c expand_bottom_edge /
    # h2v2_downsample reading a full pair), downsamples, and only then pads
    # the *downsampled* plane up to the iMCU height by duplicating its last
    # row (jcprepct.c "pad the output to a full iMCU height").  Padding the
    # full resolution plane all the way to ``full_h`` first would instead
    # duplicate row ``height-1`` into the downsampler, changing the last
    # chroma row.
    even_h = height + (height & 1)
    cw, ch = full_w // 2, full_h // 2
    planes = [y_pad]
    for plane in (cb, cr):
        # Horizontal padding happens BEFORE downsampling: jcsample.c calls
        # expand_right_edge() to ``width_in_blocks * DCTSIZE * 2`` columns,
        # duplicating the last source column of *each* row.  Because the two
        # rows of a pair may then differ, the rounding bias (1,2,1,2,...)
        # produces the characteristic 95/96 alternation at the right edge.
        padded = color.pad_plane(plane, width, height, full_w, even_h)
        down = color.h2v2_downsample(padded, full_w, even_h)
        # Vertical padding happens AFTER downsampling: jcprepct.c replicates
        # the last *downsampled* row up to the iMCU height.
        planes.append(color.pad_plane(down, cw, even_h // 2, cw, ch))
    luma, chroma = markers.quality_tables(quality)
    quants = [luma, chroma, chroma]
    return planes, geom, quants


def _quantize_block(samples: list[int], quant: list[int]) -> list[int]:
    workspace = fdct_islow([v - 128 for v in samples])
    out = [0] * 64
    for i in range(64):
        qval = quant[i] << 3
        temp = workspace[i]
        negative = temp < 0
        if negative:
            temp = -temp
        temp += qval >> 1
        temp = temp // qval if temp >= qval else 0
        out[i] = -temp if negative else temp
    return out


def encode_coefficients(image, quality: int, override: Optional[Bitmap] = None
                        ) -> tuple[list[list[int]], _BitmapBuilder, Geometry, bytes, dict]:
    """Compress raw pixels and return the entropy-ready coefficient blocks.

    ``override`` selects JPEG_WRITING mode: coefficient LSBs are replaced with
    the supplied bitmap.  ``None`` selects JPEG_READING mode (bitmap capture).
    """
    planes, geom, quants = _build_planes_from_rgb(image, quality)
    builder = _BitmapBuilder(override)
    blocks: list[list[int]] = []
    last_dc = [0, 0, 0]

    for irow in range(geom.total_rows):
        for mcu_col in range(geom.mcus_per_row):
            for ci in range(3):
                spec = geom.comps[ci]
                plane = planes[ci]
                stride = spec["plane_width"]
                blockcnt = spec["mcu_w"] if mcu_col < geom.mcus_per_row - 1 else spec["last_col"]
                for yindex in range(spec["mcu_h"]):
                    row_relevant = irow < geom.total_rows - 1 or yindex < spec["last_row"]
                    for xindex in range(spec["mcu_w"]):
                        if row_relevant and xindex < blockcnt:
                            brow = irow * spec["mcu_h"] + yindex
                            bcol = mcu_col * spec["mcu_w"] + xindex
                            samples = [0] * 64
                            for row in range(8):
                                base = (brow * 8 + row) * stride + bcol * 8
                                samples[row * 8 : row * 8 + 8] = plane[base : base + 8]
                            block = _quantize_block(samples, quants[ci])
                            for k in range(64):
                                block[k] = builder.use(block[k])
                        else:
                            # Dummy block: all AC zero, DC repeats predictor.
                            block = [last_dc[ci]] + [0] * 63
                        blocks.append(block)
                        last_dc[ci] = block[0]

    header, _, huff = markers.write_header(image.x, image.y, quality)
    return blocks, builder, geom, header, huff


def _entropy_bytes(blocks: list[list[int]], huff: dict) -> bytes:
    writer = BitWriter()
    last_dc = [0, 0, 0]
    # blocks_in_MCU = 4 (Y) + 1 (Cb) + 1 (Cr) = 6
    per_mcu = 6
    for index in range(0, len(blocks), per_mcu):
        mcu = blocks[index : index + per_mcu]
        for ci, block in zip((0, 0, 0, 0, 1, 2), mcu):
            table = 0 if ci == 0 else 1
            dc = huff[("dc", table)]
            ac = huff[("ac", table)]
            last_dc[ci] = encode_block(writer, block, last_dc[ci], dc, ac)
    return writer.flush()


def compress_jpeg_bitmap(image, quality: int = 75) -> Bitmap:
    """``compress_JPEG`` (dummy destination): encode and capture bitmap."""
    _, builder, _, _, _ = encode_coefficients(image, quality)
    return builder.finish()


def write_jpeg(stream: BinaryIO, image, quality: int = 75,
               bitmap: Optional[Bitmap] = None) -> None:
    """``write_JPEG_file`` -- re-compress with the stego LSBs written back."""
    blocks, _, _, header, huff = encode_coefficients(image, quality, bitmap)
    stream.write(header)
    stream.write(_entropy_bytes(blocks, huff))
    stream.write(b"\xff\xd9")


# ---------------------------------------------------------------------------
# Statistical foiling (src/jpg.c preserve_jpg / preserve_single)
# ---------------------------------------------------------------------------


def _preserve_single(bitmap: Bitmap, off: int, coeff: int) -> int:
    data = bitmap.data
    for i in range(off - 1, -1, -1):
        if bitmap.is_locked(i) or bitmap.is_metalocked(i):
            continue
        if data[i] == coeff:
            data[i] = i8(coeff ^ 1)
            cbit = (coeff & 0xFF) & 1
            bitmap.set_bit(i, cbit ^ 1)
            bitmap.metalock.set(i, 1)
            return i
    return -1


def preserve_jpg(bitmap: Bitmap, off: int) -> int:
    """``preserve_jpg`` -- keep the DCT coefficient histogram balanced.

    The reference implementation keeps two adjacent ``static int[256]``
    tables, ``dctadjust`` then ``dctfreq``, and indexes them with
    ``data[i] + 127`` where ``data`` is a plain ``char`` array.  Because a
    coefficient byte of ``0x80`` reads back as ``-128``, C also reaches
    index ``-1``:

    * ``dctfreq[-1]`` aliases ``dctadjust[255]``, so the flush loop later
      pops those slots as ``coeff = (char)(255 - 127) == -128``.
    * ``dctadjust[-1]`` is *not* part of any array: it lands in the
      alignment padding between ``dctmax`` and ``dctadjust``.  That cell is
      writable ``.bss``, starts at zero and is never memset by
      ``preserve_jpg(-1)``, so it behaves like a 257th counter that starts
      at 0 and -- being outside the flush loop -- is never drained.  We
      model it explicitly instead of relying on undefined behaviour; the
      measured layout is recorded in ``validation/NOTES.md``.

    The ``dctadjust`` array is therefore stored shifted by one:
    ``adjust[i + 1]`` mirrors C's ``dctadjust[i]`` and ``adjust[0]`` mirrors
    C's ``dctadjust[-1]``.
    """
    if off == -1:
        bitmap.preserve = preserve_jpg
        bitmap.metalock = BitArray(bitmap.bytes)
        adjust = [0] * (DCTENTRIES + 1)
        freq = [0] * DCTENTRIES
        for i in range(bitmap.bits):
            value = bitmap.data[i]
            if value == -128:
                # ``dctfreq[-1]`` is ``dctadjust[255]``; the raw count of
                # -128 coefficients is parked there and is never scaled.
                adjust[DCTENTRIES] += 1
            else:
                freq[value + 127] += 1

        a = freq[-1 + 127]
        b = freq[-2 + 127]
        if a < b:
            bitmap.extra["estimate_error"] = True
            res = -1
        else:
            bitmap.extra["estimate_error"] = False
            res = 2 * bitmap.bits * b // (a + b) if (a + b) else -1

        scale = f32_div(f32(float(bitmap.bits)), f32(float(DCTFREQRANGE)))
        for i in range(DCTENTRIES):
            value = int(f32_div(f32(float(freq[i])), scale))
            value //= DCTFREQREDUCE
            freq[i] = max(value, DCTFREQMIN)

        # C stores the return value into ``size_t maxcorrect``; -1 becomes
        # SIZE_MAX and stays "truthy", which is what callers test against.
        bitmap.maxcorrect = res & ((1 << 64) - 1)
        bitmap.extra["dctadjust"] = adjust
        bitmap.extra["dctfreq"] = freq
        return res

    adjust = bitmap.extra["dctadjust"]
    freq = bitmap.extra["dctfreq"]

    def get_adjust(index: int) -> int:
        """Read C's ``dctadjust[index]`` (``-1`` is the padding cell)."""
        if index < -1 or index >= DCTENTRIES:
            return 0
        return adjust[index + 1]

    def set_adjust(index: int, value: int) -> None:
        if -1 <= index < DCTENTRIES:
            adjust[index + 1] = value

    def get_freq(index: int) -> int:
        """Read C's ``dctfreq[index]``; ``-1`` aliases ``dctadjust[255]``."""
        if index == -1:
            return adjust[DCTENTRIES]
        if 0 <= index < DCTENTRIES:
            return freq[index]
        return 0

    if off >= bitmap.bits:
        for i in range(DCTENTRIES):
            while adjust[i + 1]:
                adjust[i + 1] -= 1
                coeff = i8(i - 127)
                if _preserve_single(bitmap, bitmap.bits - 1, coeff) != -1:
                    bitmap.foil += 1
                else:
                    bitmap.foilfail += 1
        return 0

    value = bitmap.data[off]
    coeff = i8(value ^ 1)
    data_index = value + 127
    coeff_index = coeff + 127

    if get_adjust(data_index):
        # Still missing compensation for the opposite direction.
        set_adjust(data_index, get_adjust(data_index) - 1)
        return 0

    if get_adjust(coeff_index) < get_freq(coeff_index):
        set_adjust(coeff_index, get_adjust(coeff_index) + 1)
        return 0

    found = _preserve_single(bitmap, off, coeff)
    if found != -1:
        bitmap.foil += 1
        return found

    # One too many of this coefficient.
    set_adjust(coeff_index, get_adjust(coeff_index) + 1)
    return -1
