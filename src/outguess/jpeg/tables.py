"""标准 JPEG 表与质量缩放算法 —— 数据来源于 IJG libjpeg 6b。

本模块只使用 Python 标准库，不依赖 numpy / Pillow；所有数值均逐字抄录自
OutGuess 0.4 内嵌的 IJG libjpeg 6b C 源码，未经任何重排或「凭记忆」补写：

    _upstream/src/jpeg-6b-steg/jutils.c   jpeg_natural_order[DCTSIZE2+16]
    _upstream/src/jpeg-6b-steg/jcparam.c  std_luminance_quant_tbl[DCTSIZE2]
                                         std_chrominance_quant_tbl[DCTSIZE2]
                                         jpeg_add_quant_table()
                                         jpeg_quality_scaling()
                                         jpeg_set_quality()
                                         jpeg_set_linear_quality()
                                         std_huff_tables() 中的 4 张标准 Huffman 表
    _upstream/src/jpeg-6b-steg/jchuff.c   jpeg_make_c_derived_tbl() 的码字生成
    _upstream/src/jpeg-6b-steg/jcmarker.c write_dqt()   （确认自然序 / zigzag 关系）
    _upstream/src/jpeg-6b-steg/jdmarker.c get_dqt()     （确认自然序 / zigzag 关系）

命名差异说明
------------
本份 6b 源码里两张标准量化表是 ``jpeg_set_linear_quality()`` 内部的
``static const unsigned int std_luminance_quant_tbl[DCTSIZE2]`` 与
``std_chrominance_quant_tbl[DCTSIZE2]``（jcparam.c:76 / :86），并非某些移植
版本里的全局 ``jpeg_std_luminance_quant_tbl`` / ``jpeg_std_chrominance_quant_tbl``；
本模块公开名按要求取 ``STD_LUM_QUANT`` / ``STD_CHROMA_QUANT``。

顺序约定（重要）
----------------
C 里的 ``basic_table`` 保持 JPEG 规范 K.1 的**自然顺序**（行优先 8x8 矩阵，
下标 i = row*8+col）。``jpeg_add_quant_table()`` 也直接以同一个下标 i 写入
``(*qtblptr)->quantval[i] = temp``（jcparam.c:48-56），**该函数内部没有任何
zigzag 重排**。``jpeg_natural_order`` 只出现在 DQT 读写的边界上：

    jcmarker.c:169-170  /* 表项必须按 zigzag 顺序输出 */
                        unsigned int qval = qtbl->quantval[jpeg_natural_order[i]];
    jdmarker.c:521-522  /* 把 zigzag 顺序的表转成自然数组顺序 */
                        quant_ptr->quantval[jpeg_natural_order[i]] = (UINT16) tmp;

即：内存中的 ``quantval`` 是自然顺序，写进 JPEG 文件/从文件读出时才用
``jpeg_natural_order`` 做 zigzag <-> 自然序的转换。结论：
``quality_tables()`` 返回的两个表就是自然顺序，等价于
``jpeg_set_quality(&cinfo, quality, TRUE)`` 后的
``cinfo.quant_tbl_ptrs[0]->quantval`` / ``[1]->quantval``，
**不得再用 NATURAL_ORDER 额外重排**。

标准 Huffman 表（jcparam.c ``std_huff_tables()``）由 ``jpeg_set_defaults()``
安装到 ``cinfo->dc_huff_tbl_ptrs[0..1]`` / ``ac_huff_tbl_ptrs[0..1]``：
表索引 0 = 亮度(luma)，1 = 色度(chroma)，DC 与 AC 各一组，共 4 张表；
``jpeg_set_defaults()`` 先 ``jpeg_set_quality(cinfo, 75, TRUE)`` 再
``std_huff_tables(cinfo)``。C 中 bits 数组长度为 17（下标 0 是未使用的哑元
0），本模块的 ``bits`` 按要求去掉哑元，只保留码长 1..16 共 16 个元素。

版权归属
--------
原始 C 代码来自 Independent JPEG Group (IJG) 的 libjpeg 6b：

    jutils.c   Copyright (C) 1991-1996, Thomas G. Lane.
    jcparam.c  Copyright (C) 1991-1998, Thomas G. Lane.
    jchuff.c   Copyright (C) 1991-1998, Thomas G. Lane.

    This file is part of the Independent JPEG Group's software.
    For conditions of distribution and use, see the accompanying README file.
"""

from __future__ import annotations

__all__ = [
    "NATURAL_ORDER",
    "NATURAL_TO_ZIGZAG",
    "STD_LUM_QUANT",
    "STD_CHROMA_QUANT",
    "quality_tables",
    "STD_HUFF_TABLES",
    "HuffmanTable",
    "standard_huffman",
]


# ---------------------------------------------------------------------------
# jutils.c:53-64  const int jpeg_natural_order[DCTSIZE2+16]
#
# jpeg_natural_order[i] 是 zigzag 顺序第 i 个元素在自然顺序（行优先）中的位置。
# 末尾 16 个 63 不是笔误：解码器遇到超长零游程时可能越界访问，源码故意补 16 个
# 63 让越界写落到 block[63]，避免野指针（jutils.c:39-51 的注释）。
# ---------------------------------------------------------------------------
NATURAL_ORDER: list[int] = [
    0,  1,  8, 16,  9,  2,  3, 10,
   17, 24, 32, 25, 18, 11,  4,  5,
   12, 19, 26, 33, 40, 48, 41, 34,
   27, 20, 13,  6,  7, 14, 21, 28,
   35, 42, 49, 56, 57, 50, 43, 36,
   29, 22, 15, 23, 30, 37, 44, 51,
   58, 59, 52, 45, 38, 31, 39, 46,
   53, 60, 61, 54, 47, 55, 62, 63,
   63, 63, 63, 63, 63, 63, 63, 63,  # 解码器安全用的额外表项
   63, 63, 63, 63, 63, 63, 63, 63,
]

# 反查表：自然序下标 -> zigzag 序号，长度 64（只取前 DCTSIZE2 项，尾部 63 无意义）。
NATURAL_TO_ZIGZAG: list[int] = [0] * 64
for _zig, _nat in enumerate(NATURAL_ORDER[:64]):
    NATURAL_TO_ZIGZAG[_nat] = _zig
del _zig, _nat


# ---------------------------------------------------------------------------
# jcparam.c:76-95  std_luminance_quant_tbl / std_chrominance_quant_tbl
#
# JPEG 规范 K.1 的示例表，按自然顺序（8x8 行优先）逐字抄录。它们是「基本表」，
# 尚未经过质量缩放；jpeg_set_linear_quality()/jpeg_set_quality() 以它们为
# basic_table 调 jpeg_add_quant_table()。
# ---------------------------------------------------------------------------
STD_LUM_QUANT: list[int] = [
    16,  11,  10,  16,  24,  40,  51,  61,
    12,  12,  14,  19,  26,  58,  60,  55,
    14,  13,  16,  24,  40,  57,  69,  56,
    14,  17,  22,  29,  51,  87,  80,  62,
    18,  22,  37,  56,  68, 109, 103,  77,
    24,  35,  55,  64,  81, 104, 113,  92,
    49,  64,  78,  87, 103, 121, 120, 101,
    72,  92,  95,  98, 112, 100, 103,  99,
]

STD_CHROMA_QUANT: list[int] = [
    17,  18,  24,  47,  99,  99,  99,  99,
    18,  21,  26,  66,  99,  99,  99,  99,
    24,  26,  56,  99,  99,  99,  99,  99,
    47,  66,  99,  99,  99,  99,  99,  99,
    99,  99,  99,  99,  99,  99,  99,  99,
    99,  99,  99,  99,  99,  99,  99,  99,
    99,  99,  99,  99,  99,  99,  99,  99,
    99,  99,  99,  99,  99,  99,  99,  99,
]


def _quality_scaling(quality: int) -> int:
    """jcparam.c:105-128 ``jpeg_quality_scaling``。

    C 源码先把 quality 钳到 1..100（0 变 1 防止除零），然后：
    quality < 50 -> 5000 / quality（C 整数除法，正数下等价于 Python //）；
    否则          -> 200 - 2*quality。
    """
    if quality <= 0:
        quality = 1
    if quality > 100:
        quality = 100
    if quality < 50:
        return 5000 // quality
    return 200 - quality * 2


def _add_quant_table(basic_table: list[int], scale_factor: int,
                     force_baseline: bool) -> list[int]:
    """jcparam.c:22-60 ``jpeg_add_quant_table`` 的纯 Python 等价实现。

    temp = ((long) basic_table[i] * scale_factor + 50L) / 100L;   C 整数除法
    if (temp <= 0L)   temp = 1L;
    if (temp > 32767L) temp = 32767L;      /* 12-bit 所需的最大量化器 */
    if (force_baseline && temp > 255L) temp = 255L;
    (*qtblptr)->quantval[i] = (UINT16) temp;

    注意：写入用下标 i 本身，basic_table[i] -> quantval[i]，没有
    ``quantval[jpeg_natural_order[i]]`` 这类重排；重排只发生在
    jcmarker.c/jdmarker.c 读写 DQT 时。因此本函数输入、输出都是自然顺序。
    由于这里所有中间量非负，C 的向零取整除法与 Python 的 ``//`` 完全一致。
    """
    quantval: list[int] = []
    for basic in basic_table:
        temp = (basic * scale_factor + 50) // 100
        if temp <= 0:
            temp = 1
        if temp > 32767:
            temp = 32767
        if force_baseline and temp > 255:
            temp = 255
        quantval.append(temp)
    return quantval


def quality_tables(quality: int,
                   force_baseline: bool = True) -> tuple[list[int], list[int]]:
    """等价于 ``jpeg_set_quality(&cinfo, quality, TRUE)`` 后的量化表。

    jcparam.c:131-144 ``jpeg_set_quality`` 先调 ``jpeg_quality_scaling``，
    把结果作为 scale_factor 传给 ``jpeg_set_linear_quality``（:63-102），
    后者对表 0/1 分别以 STD_LUM_QUANT / STD_CHROMA_QUANT 为 basic_table
    调用 ``jpeg_add_quant_table``。

    返回 ``(luma, chroma)``，各为长度 64 的**自然顺序**列表，对应
    ``cinfo.quant_tbl_ptrs[0]->quantval`` 与 ``[1]->quantval``。
    """
    scale_factor = _quality_scaling(quality)
    luma = _add_quant_table(STD_LUM_QUANT, scale_factor, force_baseline)
    chroma = _add_quant_table(STD_CHROMA_QUANT, scale_factor, force_baseline)
    return luma, chroma


# ---------------------------------------------------------------------------
# jcparam.c:181-254  std_huff_tables() 中的 4 张标准 Huffman 表（JPEG K.3）
#
# C 里的 bits_*[17] 下标 0 是占位 0（"/* 0-base */"），这里按要求去掉，
# 只存码长 1..16 的计数，共 16 个元素。
# 键: ("dc"|"ac", 表号)，表号 0 = 亮度、1 = 色度。
# ---------------------------------------------------------------------------
STD_HUFF_TABLES: dict = {
    ("dc", 0): {
        "bits": [0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0],
        "values": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    },
    ("ac", 0): {
        "bits": [0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7d],
        "values": [
            0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12,
            0x21, 0x31, 0x41, 0x06, 0x13, 0x51, 0x61, 0x07,
            0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xa1, 0x08,
            0x23, 0x42, 0xb1, 0xc1, 0x15, 0x52, 0xd1, 0xf0,
            0x24, 0x33, 0x62, 0x72, 0x82, 0x09, 0x0a, 0x16,
            0x17, 0x18, 0x19, 0x1a, 0x25, 0x26, 0x27, 0x28,
            0x29, 0x2a, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39,
            0x3a, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49,
            0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
            0x5a, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69,
            0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79,
            0x7a, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
            0x8a, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98,
            0x99, 0x9a, 0xa2, 0xa3, 0xa4, 0xa5, 0xa6, 0xa7,
            0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6,
            0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3, 0xc4, 0xc5,
            0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2, 0xd3, 0xd4,
            0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda, 0xe1, 0xe2,
            0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0xe9, 0xea,
            0xf1, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8,
            0xf9, 0xfa,
        ],
    },
    ("dc", 1): {
        "bits": [0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0],
        "values": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    },
    ("ac", 1): {
        "bits": [0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77],
        "values": [
            0x00, 0x01, 0x02, 0x03, 0x11, 0x04, 0x05, 0x21,
            0x31, 0x06, 0x12, 0x41, 0x51, 0x07, 0x61, 0x71,
            0x13, 0x22, 0x32, 0x81, 0x08, 0x14, 0x42, 0x91,
            0xa1, 0xb1, 0xc1, 0x09, 0x23, 0x33, 0x52, 0xf0,
            0x15, 0x62, 0x72, 0xd1, 0x0a, 0x16, 0x24, 0x34,
            0xe1, 0x25, 0xf1, 0x17, 0x18, 0x19, 0x1a, 0x26,
            0x27, 0x28, 0x29, 0x2a, 0x35, 0x36, 0x37, 0x38,
            0x39, 0x3a, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48,
            0x49, 0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58,
            0x59, 0x5a, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68,
            0x69, 0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78,
            0x79, 0x7a, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87,
            0x88, 0x89, 0x8a, 0x92, 0x93, 0x94, 0x95, 0x96,
            0x97, 0x98, 0x99, 0x9a, 0xa2, 0xa3, 0xa4, 0xa5,
            0xa6, 0xa7, 0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4,
            0xb5, 0xb6, 0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3,
            0xc4, 0xc5, 0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2,
            0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda,
            0xe2, 0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0xe9,
            0xea, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8,
            0xf9, 0xfa,
        ],
    },
}


class HuffmanTable:
    """一张 JPEG Huffman 表及其规范（canonical）码字。

    码字生成逐行照抄 jchuff.c:208-239 ``jpeg_make_c_derived_tbl`` 的
    Figure C.1/C.2：先按 bits[] 展开每个符号的码长 huffsize[]，然后

        code = 0; si = huffsize[0];
        while (huffsize[p]) {
            while (huffsize[p] == si) { huffcode[p++] = code; code++; }
            if (code >= 1 << si) ERREXIT(...);   /* 不允许全 1 码 */
            code <<= 1; si++;
        }

    即：code 从 0 起，同一码长的符号依次 code += 1；每上升一个码长
    code <<= 1（空码长也要左移，因为 si 每轮都 +1）。随后 Figure C.3 把
    ``huffcode[p] / huffsize[p]`` 按 ``huffval[p]``（符号值）建索引，得到
    ``ehufco[符号] / ehufsi[符号]``，也就是这里的 ``codes``。

    属性
    ----
    codes  : dict[int, tuple[int, int]]   symbol -> (code, length)，用于编码
    lookup : dict[tuple[int, int], int]   (length, code) -> symbol，用于解码
    """

    def __init__(self, bits: list[int], values: list[int]) -> None:
        if len(bits) != 16:
            raise ValueError("bits 必须是长度 16 的列表（码长 1..16）")
        if any(n < 0 for n in bits):
            raise ValueError("bits 不能含负数")
        if sum(bits) != len(values):
            raise ValueError("bits 之和必须等于 values 的长度")

        self.bits: list[int] = list(bits)
        self.values: list[int] = list(values)
        self.codes: dict[int, tuple[int, int]] = {}
        self.lookup: dict[tuple[int, int], int] = {}

        # huffsize[] 中第一个非零码长，对应 C 的 si = huffsize[0]。
        nonempty = [length for length in range(1, 17) if self.bits[length - 1]]
        if not nonempty:
            raise ValueError("空 Huffman 表")
        first, last = nonempty[0], nonempty[-1]

        code = 0
        p = 0
        for length in range(first, last + 1):
            for _ in range(self.bits[length - 1]):
                symbol = self.values[p]
                if symbol in self.codes:
                    raise ValueError(f"重复的符号值: {symbol}")
                self.codes[symbol] = (code, length)
                self.lookup[(length, code)] = symbol
                p += 1
                code += 1
            # C 中 "no code is allowed to be all ones" 的合法性检查
            if code >= (1 << length):
                raise ValueError("非法的 Huffman 码长计数")
            code <<= 1
        if p != len(self.values):
            raise ValueError("values 长度与 bits 不匹配")

    def encode_symbol(self, symbol: int) -> tuple[int, int]:
        """返回该符号的 ``(code, length)``；无此符号时抛 KeyError。"""
        return self.codes[symbol]

    def decode(self, length: int, code: int) -> int:
        """按 ``(length, code)`` 反查符号。"""
        return self.lookup[(length, code)]

    def decode_bits(self, bits: object) -> tuple[int, int]:
        """按位流式解码，返回 ``(symbol, 消耗的比特数)``。

        ``bits`` 为 0/1 的可迭代对象；逐位累加
        ``code = (code << 1) | bit``，在 ``lookup`` 中命中即返回。
        """
        bit_iter = iter(bits)  # type: ignore[arg-type]
        code = 0
        for length in range(1, 17):
            try:
                bit = next(bit_iter)
            except StopIteration:
                break
            code = (code << 1) | (int(bit) & 1)
            key = (length, code)
            if key in self.lookup:
                return self.lookup[key], length
        raise KeyError("比特流不匹配任何 Huffman 码字")

    def __repr__(self) -> str:
        return (f"<HuffmanTable symbols={len(self.codes)} "
                f"maxlen={max((n for _, n in self.codes.values()), default=0)}>")


def standard_huffman() -> dict:
    """构造 4 张标准 Huffman 表，键同 :data:`STD_HUFF_TABLES`。"""
    return {
        key: HuffmanTable(spec["bits"], spec["values"])
        for key, spec in STD_HUFF_TABLES.items()
    }


if __name__ == "__main__":
    # ---- 自检：数值核对 -------------------------------------------------
    assert len(NATURAL_ORDER) == 80, "jpeg_natural_order 长度应为 DCTSIZE2+16=80"
    assert len(NATURAL_TO_ZIGZAG) == 64
    assert all(NATURAL_TO_ZIGZAG[NATURAL_ORDER[k]] == k for k in range(64)), \
        "正/反查表必须互逆"
    assert len(STD_LUM_QUANT) == 64 and len(STD_CHROMA_QUANT) == 64

    expected_counts = {
        ("dc", 0): ("DC 亮度", 12),
        ("ac", 0): ("AC 亮度", 162),
        ("dc", 1): ("DC 色度", 12),
        ("ac", 1): ("AC 色度", 162),
    }

    print("数据来源: IJG libjpeg 6b (jutils.c / jcparam.c / jchuff.c)")
    print()
    print(f"NATURAL_ORDER 长度: {len(NATURAL_ORDER)}")
    print("NATURAL_ORDER 前 10 个值:", " ".join(map(str, NATURAL_ORDER[:10])))
    print("NATURAL_TO_ZIGZAG 前 10 个值:",
          " ".join(map(str, NATURAL_TO_ZIGZAG[:10])))
    print()

    tables = standard_huffman()
    print("标准 Huffman 表符号总数:")
    for key, (label, expected) in expected_counts.items():
        spec = STD_HUFF_TABLES[key]
        ht = tables[key]
        total = sum(spec["bits"])
        assert total == expected == len(ht.codes) == len(ht.lookup) == len(spec["values"]), \
            f"{key} 符号数不符"
        # 编码/解码往返检查
        for symbol in spec["values"]:
            code, length = ht.encode_symbol(symbol)
            assert ht.decode(length, code) == symbol
            stream = [(code >> shift) & 1 for shift in range(length - 1, -1, -1)]
            assert ht.decode_bits(stream) == (symbol, length)
        print(f"  {key!s:>10} {label}: {total}")
    print()

    # quality=75 -> jpeg_quality_scaling: 200 - 2*75 = 50
    luma75, chroma75 = quality_tables(75)
    assert len(luma75) == len(chroma75) == 64
    assert _quality_scaling(75) == 50

    # 按 C 的整数除法 (basic*50 + 50)//100 计算，前 8 个自然序值：
    # 16,11,10,16,24,40,51,61 -> 8,6,5,8,12,20,26,31
    first8 = [8, 6, 5, 8, 12, 20, 26, 31]
    first16 = [8, 6, 5, 8, 12, 20, 26, 31, 6, 6, 7, 10, 13, 29, 30, 28]
    assert luma75[:8] == first8, luma75[:8]
    assert luma75[:16] == first16, luma75[:16]
    assert chroma75[:8] == [9, 9, 12, 24, 50, 50, 50, 50]

    print("quality=75  scale_factor = 200 - 2*75 = 50")
    print("quality_tables(75) 亮度表前 8 个自然序值:",
          " ".join(map(str, luma75[:8])))
    print("quality_tables(75) 亮度表前 16 个自然序值:",
          " ".join(map(str, luma75[:16])))
    print("quality_tables(75) 色度表前 8 个自然序值:",
          " ".join(map(str, chroma75[:8])))
    print()
    print("自检通过")
