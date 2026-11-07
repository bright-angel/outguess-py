"""Baseline JPEG entropy bit I/O and Huffman block coding.

Mirrors ``jchuff.c`` (``emit_bits`` / ``flush_bits`` / ``encode_one_block``)
and ``jdhuff.c`` (``decode_mcu`` / ``HUFF_EXTEND``), including byte stuffing
and restart markers.
"""

from __future__ import annotations

from .tables import NATURAL_ORDER, HuffmanTable


class BitReader:
    """MSB-first bit reader with 0xFF00 un-stuffing."""

    __slots__ = ("data", "pos", "bitbuf", "bits_left", "restart_interval", "mcus_left")

    def __init__(self, data: bytes, pos: int, restart_interval: int = 0) -> None:
        self.data = data
        self.pos = pos
        self.bitbuf = 0
        self.bits_left = 0
        self.restart_interval = restart_interval
        self.mcus_left = restart_interval

    def read_byte(self) -> int:
        if self.pos >= len(self.data):
            return 0
        byte = self.data[self.pos]
        self.pos += 1
        if byte == 0xFF and self.pos < len(self.data):
            following = self.data[self.pos]
            if following == 0x00:
                self.pos += 1  # stuffed zero byte
            # A marker (FF D0-D7 / FF D9) is left in place.
        return byte

    def get_bits(self, count: int) -> int:
        if count == 0:
            return 0
        while self.bits_left < count:
            self.bitbuf = ((self.bitbuf << 8) | self.read_byte()) & 0xFFFFFFFF
            self.bits_left += 8
        self.bits_left -= count
        return (self.bitbuf >> self.bits_left) & ((1 << count) - 1)

    def mcu_done(self) -> bool:
        """Handle a restart marker between MCUs; returns True when one occurred."""
        if not self.restart_interval:
            return False
        self.mcus_left -= 1
        if self.mcus_left:
            return False
        self.bitbuf = 0
        self.bits_left = 0
        while self.pos < len(self.data) and self.data[self.pos] != 0xFF:
            self.pos += 1
        if self.pos + 1 < len(self.data) and 0xD0 <= self.data[self.pos + 1] <= 0xD7:
            self.pos += 2
        self.mcus_left = self.restart_interval
        return True


class BitWriter:
    """MSB-first bit writer with 0xFF00 stuffing (jchuff.c emit_bits)."""

    __slots__ = ("out", "acc", "nbits")

    def __init__(self) -> None:
        self.out = bytearray()
        self.acc = 0
        self.nbits = 0

    def put(self, code: int, size: int) -> None:
        if size == 0:
            raise ValueError("Huffman table produced a zero-length code")
        self.acc = (self.acc << size) | (code & ((1 << size) - 1))
        self.nbits += size
        while self.nbits >= 8:
            self.nbits -= 8
            byte = (self.acc >> self.nbits) & 0xFF
            self.out.append(byte)
            if byte == 0xFF:
                self.out.append(0x00)
            self.acc &= (1 << self.nbits) - 1

    def flush(self) -> bytes:
        """jchuff.c flush_bits: pad the final byte with ones."""
        if self.nbits:
            self.put(0x7F, 7)
            self.acc = 0
            self.nbits = 0
        return bytes(self.out)


def huff_extend(value: int, size: int) -> int:
    """``HUFF_EXTEND`` -- convert an ``size``-bit magnitude to a signed value."""
    if value < (1 << (size - 1)):
        return value - (1 << size) + 1
    return value


def huff_decode(reader: BitReader, table: HuffmanTable) -> int:
    code = 0
    for length in range(1, 17):
        code = (code << 1) | reader.get_bits(1)
        symbol = table.lookup.get((length, code))
        if symbol is not None:
            return symbol
    raise ValueError("invalid Huffman code in entropy stream")


def encode_block(writer: BitWriter, block: list[int], last_dc: int,
                 dc_table: HuffmanTable, ac_table: HuffmanTable) -> int:
    """``encode_one_block``; returns the new DC predictor value."""
    temp = temp2 = block[0] - last_dc
    if temp < 0:
        temp = -temp
        temp2 -= 1
    nbits = temp.bit_length()
    code, size = dc_table.codes[nbits]
    writer.put(code, size)
    if nbits:
        writer.put(temp2, nbits)

    run = 0
    for k in range(1, 64):
        temp = block[NATURAL_ORDER[k]]
        if temp == 0:
            run += 1
            continue
        while run > 15:
            code, size = ac_table.codes[0xF0]
            writer.put(code, size)
            run -= 16
        temp2 = temp
        if temp < 0:
            temp = -temp
            temp2 -= 1
        nbits = temp.bit_length()
        symbol = (run << 4) + nbits
        code, size = ac_table.codes[symbol]
        writer.put(code, size)
        writer.put(temp2, nbits)
        run = 0

    if run > 0:
        code, size = ac_table.codes[0]
        writer.put(code, size)
    return block[0]


def decode_block(reader: BitReader, dc_table: HuffmanTable,
                 ac_table: HuffmanTable, last_dc: int) -> tuple[list[int], int]:
    """``decode_mcu`` for one block; returns (natural-order coefficients, DC)."""
    block = [0] * 64
    s = huff_decode(reader, dc_table)
    if s:
        bits = reader.get_bits(s)
        s = huff_extend(bits, s)
    s += last_dc
    last_dc = s
    block[0] = s

    k = 1
    while k < 64:
        s = huff_decode(reader, ac_table)
        r = s >> 4
        s &= 15
        if s:
            k += r
            bits = reader.get_bits(s)
            s = huff_extend(bits, s)
            if k < 64:
                block[NATURAL_ORDER[k]] = s
        else:
            if r != 15:
                break
            k += 15
        k += 1
    return block, last_dc
