"""Fixed-point colour conversion and chroma sampling of IJG libjpeg 6b.

Ported from ``jccolor.c`` (RGB->YCbCr), ``jdcolor.c`` (YCbCr->RGB),
``jcsample.c`` (h2v2 downsample) and ``jdsample.c`` (h2v2 fancy upsample).
All constants are scaled by 2^16 exactly as in the C sources.
"""

from __future__ import annotations

SCALEBITS = 16
ONE_HALF = 1 << (SCALEBITS - 1)
CBCR_OFFSET = 128 << SCALEBITS
CENTERJSAMPLE = 128
MAXJSAMPLE = 255


def FIX(x: float) -> int:
    return int(x * (1 << SCALEBITS) + 0.5)


# ---------------------------------------------------------------------------
# RGB -> YCbCr  (jccolor.c rgb_ycc_start / rgb_ycc_convert)
# ---------------------------------------------------------------------------

_R_Y = [FIX(0.29900) * i for i in range(256)]
_G_Y = [FIX(0.58700) * i for i in range(256)]
_B_Y = [FIX(0.11400) * i + ONE_HALF for i in range(256)]
_R_CB = [(-FIX(0.16874)) * i for i in range(256)]
_G_CB = [(-FIX(0.33126)) * i for i in range(256)]
_B_CB = [FIX(0.50000) * i + CBCR_OFFSET + ONE_HALF - 1 for i in range(256)]
_R_CR = _B_CB  # B=>Cb and R=>Cr tables are the same
_G_CR = [(-FIX(0.41869)) * i for i in range(256)]
_B_CR = [(-FIX(0.08131)) * i for i in range(256)]


def rgb_to_ycc(r: int, g: int, b: int) -> tuple[int, int, int]:
    return (
        (_R_Y[r] + _G_Y[g] + _B_Y[b]) >> SCALEBITS,
        (_R_CB[r] + _G_CB[g] + _B_CB[b]) >> SCALEBITS,
        (_R_CR[r] + _G_CR[g] + _B_CR[b]) >> SCALEBITS,
    )


def rgb_planes(pixels: bytes, width: int, height: int, depth: int = 3
               ) -> tuple[bytearray, bytearray, bytearray]:
    """Convert an interleaved RGB buffer into three full-resolution planes."""
    y = bytearray(width * height)
    cb = bytearray(width * height)
    cr = bytearray(width * height)
    if depth == 1:
        for i in range(width * height):
            v = pixels[i]
            y[i] = (_R_Y[v] + _G_Y[v] + _B_Y[v]) >> SCALEBITS
            cb[i] = (_R_CB[v] + _G_CB[v] + _B_CB[v]) >> SCALEBITS
            cr[i] = (_R_CR[v] + _G_CR[v] + _B_CR[v]) >> SCALEBITS
    else:
        p = 0
        for i in range(width * height):
            r, g, b = pixels[p], pixels[p + 1], pixels[p + 2]
            p += 3
            y[i] = (_R_Y[r] + _G_Y[g] + _B_Y[b]) >> SCALEBITS
            cb[i] = (_R_CB[r] + _G_CB[g] + _B_CB[b]) >> SCALEBITS
            cr[i] = (_R_CR[r] + _G_CR[g] + _B_CR[b]) >> SCALEBITS
    return y, cb, cr


# ---------------------------------------------------------------------------
# YCbCr -> RGB  (jdcolor.c build_ycc_rgb_table / ycc_rgb_convert)
# ---------------------------------------------------------------------------

_CR_R = [0] * 256
_CB_B = [0] * 256
_CR_G = [0] * 256
_CB_G = [0] * 256
for _i in range(256):
    _x = _i - CENTERJSAMPLE
    _CR_R[_i] = (FIX(1.40200) * _x + ONE_HALF) >> SCALEBITS
    _CB_B[_i] = (FIX(1.77200) * _x + ONE_HALF) >> SCALEBITS
    _CR_G[_i] = (-FIX(0.71414)) * _x
    _CB_G[_i] = (-FIX(0.34414)) * _x + ONE_HALF


def _sample_limit(value: int) -> int:
    """C 的 ``cinfo->sample_range_limit[x]``（简单表，未加 CENTERJSAMPLE）。

    jdcolor.c 的颜色转换使用的是 ``sample_range_limit`` 本身，而不是
    ``sample_range_limit + CENTERJSAMPLE``（后者只有 IDCT 使用）。两者
    相差 128：简单表区间为 ``limit[x] = x``（0..255），负数取 0，超过 255
    取 255，等价于一次普通钳位。
    """
    if value < 0:
        return 0
    if value > MAXJSAMPLE:
        return MAXJSAMPLE
    return value


def ycc_to_rgb(y: int, cb: int, cr: int) -> tuple[int, int, int]:
    """``ycc_rgb_convert``：定点 YCbCr -> RGB。"""
    return (
        _sample_limit(y + _CR_R[cr]),
        _sample_limit(y + ((_CB_G[cb] + _CR_G[cr]) >> SCALEBITS)),
        _sample_limit(y + _CB_B[cb]),
    )


# ---------------------------------------------------------------------------
# Sampling helpers
# ---------------------------------------------------------------------------


def pad_plane(plane: bytes, width: int, height: int,
              padded_width: int, padded_height: int) -> bytearray:
    """Replicate the right/bottom edges like jcmainct.c does for MCUs."""
    out = bytearray(padded_width * padded_height)
    for row in range(padded_height):
        src_row = min(row, height - 1)
        base = src_row * width
        dst = row * padded_width
        out[dst : dst + min(width, padded_width)] = plane[base : base + min(width, padded_width)]
        last = plane[base + width - 1] if width else 0
        for col in range(width, padded_width):
            out[dst + col] = last
    return out


def h2v2_downsample(plane: bytearray, width: int, height: int
                    ) -> bytearray:
    """jcsample.c h2v2_downsample over a whole (already edge-padded) plane."""
    out_width = width // 2
    out_height = height // 2
    out = bytearray(out_width * out_height)
    for oy in range(out_height):
        r0 = (2 * oy) * width
        r1 = (2 * oy + 1) * width
        bias = 1
        dst = oy * out_width
        for ox in range(out_width):
            c = 2 * ox
            out[dst + ox] = (
                plane[r0 + c] + plane[r0 + c + 1]
                + plane[r1 + c] + plane[r1 + c + 1] + bias
            ) >> 2
            bias ^= 3  # 1 -> 2 -> 1
    return out


def h2v1_fancy_upsample(plane: bytearray, width: int, height: int) -> bytearray:
    """jdsample.c h2v1_fancy_upsample -- horizontal 2x triangle filter.

    ``width`` is ``downsampled_width``; the result is ``2 * width`` wide.  The
    ``(x * 3 + y + 1) >> 2`` / ``(x * 3 + y + 2) >> 2`` alternation is what
    libjpeg uses, and the first/last column are special-cased so the borders
    stay sharp.
    """
    stride = 2 * width
    out = bytearray(stride * height)
    if width == 0:
        return out
    for row in range(height):
        src = row * width
        dst = row * stride
        if width == 1:
            value = plane[src]
            out[dst] = value
            out[dst + 1] = value
            continue
        # First column.
        out[dst] = plane[src]
        out[dst + 1] = (plane[src] * 3 + plane[src + 1] + 2) >> 2
        o = 2
        for col in range(1, width - 1):
            value = plane[src + col] * 3
            out[dst + o] = (value + plane[src + col - 1] + 1) >> 2
            out[dst + o + 1] = (value + plane[src + col + 1] + 2) >> 2
            o += 2
        # Last column.
        value = plane[src + width - 1]
        out[dst + o] = (value * 3 + plane[src + width - 2] + 1) >> 2
        out[dst + o + 1] = value
    return out


def h2v2_fancy_upsample(plane: bytearray, width: int, height: int,
                        out_width: int, loop_width: int | None = None) -> bytearray:
    """jdsample.c h2v2_fancy_upsample (triangle filter, 3/4 + 1/4).

    ``width``/``height`` are the downsampled dimensions, ``out_width`` is the
    full-resolution row width (2 * width).  Edge rows are replicated by the
    caller, matching the context rows supplied by jdmainct.c.
    """
    loop_width = width if loop_width is None else loop_width
    stride = 2 * loop_width
    out = bytearray(stride * (height * 2))
    if loop_width < 2:
        for inrow in range(height):
            value = plane[inrow * width]
            for orow in range(inrow * 2, inrow * 2 + 2):
                out[orow * stride : orow * stride + stride] = bytes([value]) * stride
        return out
    for inrow in range(height):
        above = max(inrow - 1, 0) * width
        here = inrow * width
        below = min(inrow + 1, height - 1) * width
        # v == 0: nearest = here, further = above
        # v == 1: nearest = here, further = below
        for v in range(2):
            near = here
            far = above if v == 0 else below
            outrow = inrow * 2 + v
            dst = outrow * stride

            thiscolsum = plane[near] * 3 + plane[far]
            nextcolsum = plane[near + 1] * 3 + plane[far + 1]
            out[dst] = (thiscolsum * 4 + 8) >> 4
            out[dst + 1] = (thiscolsum * 3 + nextcolsum + 7) >> 4
            lastcolsum, thiscolsum = thiscolsum, nextcolsum
            o = 2
            for col in range(1, loop_width - 1):
                nextcolsum = plane[near + col + 1] * 3 + plane[far + col + 1]
                out[dst + o] = (thiscolsum * 3 + lastcolsum + 8) >> 4
                out[dst + o + 1] = (thiscolsum * 3 + nextcolsum + 7) >> 4
                lastcolsum, thiscolsum = thiscolsum, nextcolsum
                o += 2
            out[dst + o] = (thiscolsum * 3 + lastcolsum + 8) >> 4
            out[dst + o + 1] = (thiscolsum * 4 + 7) >> 4
    return out
