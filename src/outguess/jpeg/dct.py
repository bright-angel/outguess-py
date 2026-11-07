"""IJG libjpeg 6b 整数 DCT / IDCT 的纯 Python 移植。

模块说明
--------
本模块提供两个公开函数：

* ``fdct_islow(block)`` —— 慢速但精确的整数前向 DCT，对应
  ``jpeg_fdct_islow``。输入为长度 64、自然顺序（行优先）、已完成
  level-shift（0..255 减 128）的 DCTELEM；输出为长度 64、自然顺序的
  DCT 系数，按 C 实现放大 8 倍（PASS1_BITS 缩放已在 pass 2 移除）。
* ``idct_islow(coeffs, quant)`` —— 反量化 + 整数逆 DCT，对应
  ``jpeg_idct_islow``。输入为自然顺序的量化后 JCOEF 系数与自然顺序的
  量化表（ISLOW_MULT_TYPE，即原始 quantval，无额外缩放）；输出为长度 64、
  自然顺序的 JSAMPLE（0..255）。

实现约束
--------
* 全部使用 Python 整数，没有任何浮点运算、不依赖 numpy / 第三方库。
* 逐行忠实翻译 C 源码的两阶段结构（pass 1 行 / 列、pass 2 列 / 行），
  常量、移位、``DESCALE`` 舍入、乘加顺序均与 C 保持一致；
  ``MULTIPLY(var, const)`` 即 ``var * const``，``DESCALE(x, n)`` 即
  ``(x + (1 << (n-1))) >> n``（算术右移）。
* 8-bit 样本下各中间量不会溢出 32 位有符号整数，因此用 Python 任意精度
  整数照抄即可得到与 C int32 逐位一致的结果。
* 输出端的 ``range_limit`` 表被精确重建（含 ``+ CENTERJSAMPLE`` 与
  ``& RANGE_MASK`` 掩码回绕）；对合法范围的样本等价于 clamp 到 0..255。

版权归属
--------
原始 C 代码来自 Independent JPEG Group (IJG) 的 libjpeg 6b：

    jfdctint.c  Copyright (C) 1991-1996, Thomas G. Lane.
    jidctint.c  Copyright (C) 1991-1998, Thomas G. Lane.
    jdct.h      Copyright (C) 1994-1996, Thomas G. Lane.

    This file is part of the Independent JPEG Group's software.
    For conditions of distribution and use, see the accompanying README file.

本文件逐位移植自 jfdctint.c / jidctint.c（并参照 jdct.h、jdmaster.c 的
宏与 range_limit 表定义）。
"""

from __future__ import annotations

import random

# ---------------------------------------------------------------------------
# jdct.h / jfdctint.c / jidctint.c 中的常量与宏
# ---------------------------------------------------------------------------

DCTSIZE = 8
DCTSIZE2 = 64

# BITS_IN_JSAMPLE == 8 分支
CONST_BITS = 13
PASS1_BITS = 2

ONE = 1
CONST_SCALE = ONE << CONST_BITS  # 8192（保留，便于与 C 核对）

CENTERJSAMPLE = 128
MAXJSAMPLE = 255
RANGE_MASK = MAXJSAMPLE * 4 + 3  # 1023：比合法样本宽 2 bit

# FIX(x) = (INT32)(x * CONST_SCALE + 0.5) 的预计算值（CONST_BITS == 13）
FIX_0_298631336 = 2446
FIX_0_390180644 = 3196
FIX_0_541196100 = 4433
FIX_0_765366865 = 6270
FIX_0_899976223 = 7373
FIX_1_175875602 = 9633
FIX_1_501321110 = 12299
FIX_1_847759065 = 15137
FIX_1_961570560 = 16069
FIX_2_053119869 = 16819
FIX_2_562915447 = 20995
FIX_3_072711026 = 25172


def MULTIPLY(var, const):
    """C: MULTIPLY16C16(var,const) -> ((var) * (const))。"""
    return var * const


def DESCALE(x, n):
    """C: RIGHT_SHIFT((x) + (ONE << ((n)-1)), n)，算术右移。"""
    return (x + (ONE << (n - 1))) >> n


def DEQUANTIZE(coef, quantval):
    """C: DEQUANTIZE(coef,quantval) -> (coef) * (quantval)。"""
    return coef * quantval


def _build_range_limit():
    """复刻 jdmaster.c 的 prepare_range_limit_table 中 post-IDCT 部分。

    C 里 ``range_limit = sample_range_limit + CENTERJSAMPLE``，查表用
    ``range_limit[x & RANGE_MASK]``。该 1024 项表按 jdmaster.c 注释为：
        CENTERJSAMPLE .. MAXJSAMPLE,
        MAXJSAMPLE 重复 (2*(MAXJSAMPLE+1)-CENTERJSAMPLE) 次,
        0          重复 (2*(MAXJSAMPLE+1)-CENTERJSAMPLE) 次,
        0 .. CENTERJSAMPLE-1
    对正常范围内的 x，等价于 clamp(x + CENTERJSAMPLE, 0, MAXJSAMPLE)；
    对越界值则保留 C 的掩码回绕语义（逐位一致）。
    """
    repeat = 2 * (MAXJSAMPLE + 1) - CENTERJSAMPLE  # 384
    table = []
    table.extend(range(CENTERJSAMPLE, MAXJSAMPLE + 1))   # 128 .. 255
    table.extend([MAXJSAMPLE] * repeat)                  # 255 ...
    table.extend([0] * repeat)                           # 0 ...
    table.extend(range(0, CENTERJSAMPLE))                # 0 .. 127
    return table


RANGE_LIMIT = _build_range_limit()


def _range_limit(x):
    """C: range_limit[(int)(x) & RANGE_MASK]。"""
    return RANGE_LIMIT[x & RANGE_MASK]


# ---------------------------------------------------------------------------
# jpeg_fdct_islow  (jfdctint.c)
# ---------------------------------------------------------------------------

def fdct_islow(block: list[int]) -> list[int]:
    """对 64 个已 level-shift 的样本做整数前向 DCT，返回放大 8 倍的系数。

    对应 C 的 ``jpeg_fdct_islow(DCTELEM * data)``，就地变换 ``data``；
    这里用 list 拷贝实现，不修改调用方传入的 ``block``。
    """
    data = list(block)

    # Pass 1: process rows.
    # 注意结果相对真实 DCT 放大 sqrt(8)，并额外放大 2**PASS1_BITS。
    dataptr = 0
    for ctr in range(DCTSIZE - 1, -1, -1):
        tmp0 = data[dataptr + 0] + data[dataptr + 7]
        tmp7 = data[dataptr + 0] - data[dataptr + 7]
        tmp1 = data[dataptr + 1] + data[dataptr + 6]
        tmp6 = data[dataptr + 1] - data[dataptr + 6]
        tmp2 = data[dataptr + 2] + data[dataptr + 5]
        tmp5 = data[dataptr + 2] - data[dataptr + 5]
        tmp3 = data[dataptr + 3] + data[dataptr + 4]
        tmp4 = data[dataptr + 3] - data[dataptr + 4]

        # Even part per LL&M figure 1.
        tmp10 = tmp0 + tmp3
        tmp13 = tmp0 - tmp3
        tmp11 = tmp1 + tmp2
        tmp12 = tmp1 - tmp2

        data[dataptr + 0] = (tmp10 + tmp11) << PASS1_BITS
        data[dataptr + 4] = (tmp10 - tmp11) << PASS1_BITS

        z1 = MULTIPLY(tmp12 + tmp13, FIX_0_541196100)
        data[dataptr + 2] = DESCALE(
            z1 + MULTIPLY(tmp13, FIX_0_765366865), CONST_BITS - PASS1_BITS)
        data[dataptr + 6] = DESCALE(
            z1 + MULTIPLY(tmp12, -FIX_1_847759065), CONST_BITS - PASS1_BITS)

        # Odd part per figure 8; i0..i3 in the paper are tmp4..tmp7 here.
        z1 = tmp4 + tmp7
        z2 = tmp5 + tmp6
        z3 = tmp4 + tmp6
        z4 = tmp5 + tmp7
        z5 = MULTIPLY(z3 + z4, FIX_1_175875602)  # sqrt(2) * c3

        tmp4 = MULTIPLY(tmp4, FIX_0_298631336)   # sqrt(2) * (-c1+c3+c5-c7)
        tmp5 = MULTIPLY(tmp5, FIX_2_053119869)   # sqrt(2) * ( c1+c3-c5+c7)
        tmp6 = MULTIPLY(tmp6, FIX_3_072711026)   # sqrt(2) * ( c1+c3+c5-c7)
        tmp7 = MULTIPLY(tmp7, FIX_1_501321110)   # sqrt(2) * ( c1+c3-c5-c7)
        z1 = MULTIPLY(z1, -FIX_0_899976223)      # sqrt(2) * (c7-c3)
        z2 = MULTIPLY(z2, -FIX_2_562915447)      # sqrt(2) * (-c1-c3)
        z3 = MULTIPLY(z3, -FIX_1_961570560)      # sqrt(2) * (-c3-c5)
        z4 = MULTIPLY(z4, -FIX_0_390180644)      # sqrt(2) * (c5-c3)

        z3 += z5
        z4 += z5

        data[dataptr + 7] = DESCALE(tmp4 + z1 + z3, CONST_BITS - PASS1_BITS)
        data[dataptr + 5] = DESCALE(tmp5 + z2 + z4, CONST_BITS - PASS1_BITS)
        data[dataptr + 3] = DESCALE(tmp6 + z2 + z3, CONST_BITS - PASS1_BITS)
        data[dataptr + 1] = DESCALE(tmp7 + z1 + z4, CONST_BITS - PASS1_BITS)

        dataptr += DCTSIZE  # advance pointer to next row

    # Pass 2: process columns.
    # 移除 PASS1_BITS 缩放，但保留整体放大 8 倍。
    dataptr = 0
    for ctr in range(DCTSIZE - 1, -1, -1):
        tmp0 = data[dataptr + DCTSIZE * 0] + data[dataptr + DCTSIZE * 7]
        tmp7 = data[dataptr + DCTSIZE * 0] - data[dataptr + DCTSIZE * 7]
        tmp1 = data[dataptr + DCTSIZE * 1] + data[dataptr + DCTSIZE * 6]
        tmp6 = data[dataptr + DCTSIZE * 1] - data[dataptr + DCTSIZE * 6]
        tmp2 = data[dataptr + DCTSIZE * 2] + data[dataptr + DCTSIZE * 5]
        tmp5 = data[dataptr + DCTSIZE * 2] - data[dataptr + DCTSIZE * 5]
        tmp3 = data[dataptr + DCTSIZE * 3] + data[dataptr + DCTSIZE * 4]
        tmp4 = data[dataptr + DCTSIZE * 3] - data[dataptr + DCTSIZE * 4]

        # Even part per LL&M figure 1.
        tmp10 = tmp0 + tmp3
        tmp13 = tmp0 - tmp3
        tmp11 = tmp1 + tmp2
        tmp12 = tmp1 - tmp2

        data[dataptr + DCTSIZE * 0] = DESCALE(tmp10 + tmp11, PASS1_BITS)
        data[dataptr + DCTSIZE * 4] = DESCALE(tmp10 - tmp11, PASS1_BITS)

        z1 = MULTIPLY(tmp12 + tmp13, FIX_0_541196100)
        data[dataptr + DCTSIZE * 2] = DESCALE(
            z1 + MULTIPLY(tmp13, FIX_0_765366865), CONST_BITS + PASS1_BITS)
        data[dataptr + DCTSIZE * 6] = DESCALE(
            z1 + MULTIPLY(tmp12, -FIX_1_847759065), CONST_BITS + PASS1_BITS)

        # Odd part per figure 8.
        z1 = tmp4 + tmp7
        z2 = tmp5 + tmp6
        z3 = tmp4 + tmp6
        z4 = tmp5 + tmp7
        z5 = MULTIPLY(z3 + z4, FIX_1_175875602)  # sqrt(2) * c3

        tmp4 = MULTIPLY(tmp4, FIX_0_298631336)
        tmp5 = MULTIPLY(tmp5, FIX_2_053119869)
        tmp6 = MULTIPLY(tmp6, FIX_3_072711026)
        tmp7 = MULTIPLY(tmp7, FIX_1_501321110)
        z1 = MULTIPLY(z1, -FIX_0_899976223)
        z2 = MULTIPLY(z2, -FIX_2_562915447)
        z3 = MULTIPLY(z3, -FIX_1_961570560)
        z4 = MULTIPLY(z4, -FIX_0_390180644)

        z3 += z5
        z4 += z5

        data[dataptr + DCTSIZE * 7] = DESCALE(
            tmp4 + z1 + z3, CONST_BITS + PASS1_BITS)
        data[dataptr + DCTSIZE * 5] = DESCALE(
            tmp5 + z2 + z4, CONST_BITS + PASS1_BITS)
        data[dataptr + DCTSIZE * 3] = DESCALE(
            tmp6 + z2 + z3, CONST_BITS + PASS1_BITS)
        data[dataptr + DCTSIZE * 1] = DESCALE(
            tmp7 + z1 + z4, CONST_BITS + PASS1_BITS)

        dataptr += 1  # advance pointer to next column

    return data


# ---------------------------------------------------------------------------
# jpeg_idct_islow  (jidctint.c)
# ---------------------------------------------------------------------------

def idct_islow(coeffs: list[int], quant: list[int]) -> list[int]:
    """反量化 + 整数逆 DCT，返回 64 个 JSAMPLE（0..255）。

    对应 C 的 ``jpeg_idct_islow``。``coeffs`` 为自然顺序的 JCOEF，
    ``quant`` 为自然顺序的 ISLOW_MULT_TYPE 量化表（原始 quantval）。
    C 中的 ``output_col`` 固定为 0，``output_buf`` 为 8 行样本。
    """
    inptr = 0
    quantptr = 0
    wsptr = 0
    workspace = [0] * DCTSIZE2  # buffers data between passes
    out = [0] * DCTSIZE2
    outptr = 0

    # Pass 1: process columns from input, store into work array.
    # 结果相对真实 IDCT 放大 sqrt(8)，并额外放大 2**PASS1_BITS。
    for ctr in range(DCTSIZE, 0, -1):
        # AC 项全为 0 的捷径：每个输出都等于 DC 系数（按需缩放）。
        if (coeffs[inptr + DCTSIZE * 1] == 0 and
                coeffs[inptr + DCTSIZE * 2] == 0 and
                coeffs[inptr + DCTSIZE * 3] == 0 and
                coeffs[inptr + DCTSIZE * 4] == 0 and
                coeffs[inptr + DCTSIZE * 5] == 0 and
                coeffs[inptr + DCTSIZE * 6] == 0 and
                coeffs[inptr + DCTSIZE * 7] == 0):
            dcval = (DEQUANTIZE(coeffs[inptr + DCTSIZE * 0],
                                quant[quantptr + DCTSIZE * 0])
                     << PASS1_BITS)
            workspace[wsptr + DCTSIZE * 0] = dcval
            workspace[wsptr + DCTSIZE * 1] = dcval
            workspace[wsptr + DCTSIZE * 2] = dcval
            workspace[wsptr + DCTSIZE * 3] = dcval
            workspace[wsptr + DCTSIZE * 4] = dcval
            workspace[wsptr + DCTSIZE * 5] = dcval
            workspace[wsptr + DCTSIZE * 6] = dcval
            workspace[wsptr + DCTSIZE * 7] = dcval
            inptr += 1
            quantptr += 1
            wsptr += 1
            continue

        # Even part: reverse the even part of the forward DCT.
        z2 = DEQUANTIZE(coeffs[inptr + DCTSIZE * 2],
                        quant[quantptr + DCTSIZE * 2])
        z3 = DEQUANTIZE(coeffs[inptr + DCTSIZE * 6],
                        quant[quantptr + DCTSIZE * 6])

        z1 = MULTIPLY(z2 + z3, FIX_0_541196100)
        tmp2 = z1 + MULTIPLY(z3, -FIX_1_847759065)
        tmp3 = z1 + MULTIPLY(z2, FIX_0_765366865)

        z2 = DEQUANTIZE(coeffs[inptr + DCTSIZE * 0],
                        quant[quantptr + DCTSIZE * 0])
        z3 = DEQUANTIZE(coeffs[inptr + DCTSIZE * 4],
                        quant[quantptr + DCTSIZE * 4])

        tmp0 = (z2 + z3) << CONST_BITS
        tmp1 = (z2 - z3) << CONST_BITS

        tmp10 = tmp0 + tmp3
        tmp13 = tmp0 - tmp3
        tmp11 = tmp1 + tmp2
        tmp12 = tmp1 - tmp2

        # Odd part per figure 8; i0..i3 是 y7,y5,y3,y1。
        tmp0 = DEQUANTIZE(coeffs[inptr + DCTSIZE * 7],
                          quant[quantptr + DCTSIZE * 7])
        tmp1 = DEQUANTIZE(coeffs[inptr + DCTSIZE * 5],
                          quant[quantptr + DCTSIZE * 5])
        tmp2 = DEQUANTIZE(coeffs[inptr + DCTSIZE * 3],
                          quant[quantptr + DCTSIZE * 3])
        tmp3 = DEQUANTIZE(coeffs[inptr + DCTSIZE * 1],
                          quant[quantptr + DCTSIZE * 1])

        z1 = tmp0 + tmp3
        z2 = tmp1 + tmp2
        z3 = tmp0 + tmp2
        z4 = tmp1 + tmp3
        z5 = MULTIPLY(z3 + z4, FIX_1_175875602)  # sqrt(2) * c3

        tmp0 = MULTIPLY(tmp0, FIX_0_298631336)
        tmp1 = MULTIPLY(tmp1, FIX_2_053119869)
        tmp2 = MULTIPLY(tmp2, FIX_3_072711026)
        tmp3 = MULTIPLY(tmp3, FIX_1_501321110)
        z1 = MULTIPLY(z1, -FIX_0_899976223)
        z2 = MULTIPLY(z2, -FIX_2_562915447)
        z3 = MULTIPLY(z3, -FIX_1_961570560)
        z4 = MULTIPLY(z4, -FIX_0_390180644)

        z3 += z5
        z4 += z5

        tmp0 += z1 + z3
        tmp1 += z2 + z4
        tmp2 += z2 + z3
        tmp3 += z1 + z4

        # Final output stage: inputs are tmp10..tmp13, tmp0..tmp3
        workspace[wsptr + DCTSIZE * 0] = DESCALE(
            tmp10 + tmp3, CONST_BITS - PASS1_BITS)
        workspace[wsptr + DCTSIZE * 7] = DESCALE(
            tmp10 - tmp3, CONST_BITS - PASS1_BITS)
        workspace[wsptr + DCTSIZE * 1] = DESCALE(
            tmp11 + tmp2, CONST_BITS - PASS1_BITS)
        workspace[wsptr + DCTSIZE * 6] = DESCALE(
            tmp11 - tmp2, CONST_BITS - PASS1_BITS)
        workspace[wsptr + DCTSIZE * 2] = DESCALE(
            tmp12 + tmp1, CONST_BITS - PASS1_BITS)
        workspace[wsptr + DCTSIZE * 5] = DESCALE(
            tmp12 - tmp1, CONST_BITS - PASS1_BITS)
        workspace[wsptr + DCTSIZE * 3] = DESCALE(
            tmp13 + tmp0, CONST_BITS - PASS1_BITS)
        workspace[wsptr + DCTSIZE * 4] = DESCALE(
            tmp13 - tmp0, CONST_BITS - PASS1_BITS)

        inptr += 1
        quantptr += 1
        wsptr += 1

    # Pass 2: process rows from work array, store into output array.
    # 需要再降采样 8 == 2**3，并撤销 PASS1_BITS 缩放。
    wsptr = 0
    for ctr in range(0, DCTSIZE):
        outptr = ctr * DCTSIZE  # output_buf[ctr] + output_col(0)

        # AC 项全为 0 的捷径。
        if (workspace[wsptr + 1] == 0 and workspace[wsptr + 2] == 0 and
                workspace[wsptr + 3] == 0 and workspace[wsptr + 4] == 0 and
                workspace[wsptr + 5] == 0 and workspace[wsptr + 6] == 0 and
                workspace[wsptr + 7] == 0):
            dcval = _range_limit(
                DESCALE(workspace[wsptr + 0], PASS1_BITS + 3))
            out[outptr + 0] = dcval
            out[outptr + 1] = dcval
            out[outptr + 2] = dcval
            out[outptr + 3] = dcval
            out[outptr + 4] = dcval
            out[outptr + 5] = dcval
            out[outptr + 6] = dcval
            out[outptr + 7] = dcval
            wsptr += DCTSIZE
            continue

        # Even part: reverse the even part of the forward DCT.
        z2 = workspace[wsptr + 2]
        z3 = workspace[wsptr + 6]

        z1 = MULTIPLY(z2 + z3, FIX_0_541196100)
        tmp2 = z1 + MULTIPLY(z3, -FIX_1_847759065)
        tmp3 = z1 + MULTIPLY(z2, FIX_0_765366865)

        tmp0 = (workspace[wsptr + 0] + workspace[wsptr + 4]) << CONST_BITS
        tmp1 = (workspace[wsptr + 0] - workspace[wsptr + 4]) << CONST_BITS

        tmp10 = tmp0 + tmp3
        tmp13 = tmp0 - tmp3
        tmp11 = tmp1 + tmp2
        tmp12 = tmp1 - tmp2

        # Odd part per figure 8.
        tmp0 = workspace[wsptr + 7]
        tmp1 = workspace[wsptr + 5]
        tmp2 = workspace[wsptr + 3]
        tmp3 = workspace[wsptr + 1]

        z1 = tmp0 + tmp3
        z2 = tmp1 + tmp2
        z3 = tmp0 + tmp2
        z4 = tmp1 + tmp3
        z5 = MULTIPLY(z3 + z4, FIX_1_175875602)  # sqrt(2) * c3

        tmp0 = MULTIPLY(tmp0, FIX_0_298631336)
        tmp1 = MULTIPLY(tmp1, FIX_2_053119869)
        tmp2 = MULTIPLY(tmp2, FIX_3_072711026)
        tmp3 = MULTIPLY(tmp3, FIX_1_501321110)
        z1 = MULTIPLY(z1, -FIX_0_899976223)
        z2 = MULTIPLY(z2, -FIX_2_562915447)
        z3 = MULTIPLY(z3, -FIX_1_961570560)
        z4 = MULTIPLY(z4, -FIX_0_390180644)

        z3 += z5
        z4 += z5

        tmp0 += z1 + z3
        tmp1 += z2 + z4
        tmp2 += z2 + z3
        tmp3 += z1 + z4

        # Final output stage: DESCALE by 8 (2**3) + PASS1_BITS + CONST_BITS.
        # range_limit 内含 + CENTERJSAMPLE 与 clamp 到 0..255。
        out[outptr + 0] = _range_limit(
            DESCALE(tmp10 + tmp3, CONST_BITS + PASS1_BITS + 3))
        out[outptr + 7] = _range_limit(
            DESCALE(tmp10 - tmp3, CONST_BITS + PASS1_BITS + 3))
        out[outptr + 1] = _range_limit(
            DESCALE(tmp11 + tmp2, CONST_BITS + PASS1_BITS + 3))
        out[outptr + 6] = _range_limit(
            DESCALE(tmp11 - tmp2, CONST_BITS + PASS1_BITS + 3))
        out[outptr + 2] = _range_limit(
            DESCALE(tmp12 + tmp1, CONST_BITS + PASS1_BITS + 3))
        out[outptr + 5] = _range_limit(
            DESCALE(tmp12 - tmp1, CONST_BITS + PASS1_BITS + 3))
        out[outptr + 3] = _range_limit(
            DESCALE(tmp13 + tmp0, CONST_BITS + PASS1_BITS + 3))
        out[outptr + 4] = _range_limit(
            DESCALE(tmp13 - tmp0, CONST_BITS + PASS1_BITS + 3))

        wsptr += DCTSIZE

    return out


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def _div_round(num, den):
    """四舍五入的整数除法（den > 0），用于自检里的量化，避免浮点。"""
    if num >= 0:
        return (num + den // 2) // den
    return -((-num + den // 2) // den)


def selftest():
    print("=== dct.py selftest (IJG libjpeg 6b islow) ===")

    # 1) 常量块（全部 0）：fdct 全 0，idct 全 128
    zero = [0] * 64
    fz = fdct_islow(zero)
    assert all(x == 0 for x in fz), "fdct(全 0) 必须全 0"
    # 用非平凡量化表也走一遍（顺便覆盖两个 AC 全零捷径）
    q0 = [3 + (r + c) for r in range(8) for c in range(8)]
    iz = idct_islow([0] * 64, q0)
    assert all(x == 128 for x in iz), "idct(全 0 系数) 必须全 128"
    print("[1] 全 0 块: fdct 全 0, idct 全 128 ...................... OK")

    # 2) 只有 DC 的输入（所有样本 = v）：coeff[0] == 64*v，其余为 0
    for v in (-128, -80, -1, 0, 1, 37, 127):
        c = fdct_islow([v] * 64)
        assert c[0] == 64 * v, (v, c[0], 64 * v)
        assert all(x == 0 for x in c[1:]), (v, c[1:])
    print("[2] DC-only: coeff[0] == v*8*8 == 64*v, 其余 0 ........... OK")

    # 3) 随机块 fdct -> /(8*quant) 取整 -> idct，检查像素误差
    rng = random.Random(20240607)
    quant = [4 + (r + c) for r in range(8) for c in range(8)]  # 自然顺序
    den = [8 * qv for qv in quant]
    max_err = 0
    sum_err = 0
    n_samples = 0
    blocks = 200
    for _ in range(blocks):
        block = [rng.randint(-128, 127) for _ in range(64)]
        coef = fdct_islow(block)
        qcoef = [_div_round(c, d) for c, d in zip(coef, den)]
        recon = idct_islow(qcoef, quant)
        for b, rc in zip(block, recon):
            orig = b + 128  # 还原未 level-shift 的像素（本就在 0..255）
            assert 0 <= rc <= 255
            e = abs(orig - rc)
            max_err = max(max_err, e)
            sum_err += e
            n_samples += 1
    mean_err = sum_err / n_samples
    print("[3] 随机 %d 块 fdct->量化->idct: 最大像素误差=%d, 平均=%.3f"
          % (blocks, max_err, mean_err))
    assert max_err <= 30 and mean_err <= 6.0, "重建误差超出合理范围"
    print("    误差在合理范围内 ........................................ OK")

    # 4) 附加：DC-only 像素块经量化/反量化后应接近常数 (128+v)
    for v in (-90, -20, 0, 33, 100):
        block = [v] * 64
        coef = fdct_islow(block)
        qcoef = [_div_round(c, d) for c, d in zip(coef, den)]
        recon = idct_islow(qcoef, quant)
        target = max(0, min(255, v + 128))
        assert max(abs(x - target) for x in recon) <= 2, (v, recon[:8])
    print("[4] 常数像素块重建 ~= 128+v ................................ OK")

    print("=== ALL TESTS PASSED ===")


if __name__ == "__main__":
    selftest()
