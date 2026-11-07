"""JPEG marker parsing and libjpeg-6b-compatible header emission."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .tables import NATURAL_ORDER, STD_HUFF_TABLES, HuffmanTable, quality_tables

M_SOI = 0xD8
M_EOI = 0xD9
M_SOS = 0xDA
M_DQT = 0xDB
M_DHT = 0xC4
M_DRI = 0xDD
M_SOF0 = 0xC0
M_SOF1 = 0xC1
M_SOF2 = 0xC2
M_APP0 = 0xE0


@dataclass
class Component:
    cid: int
    h: int
    v: int
    tq: int
    td: int = 0
    ta: int = 0


@dataclass
class JPEGInfo:
    width: int = 0
    height: int = 0
    precision: int = 8
    components: list[Component] = field(default_factory=list)
    quant: dict[int, list[int]] = field(default_factory=dict)
    dc_tables: dict[int, HuffmanTable] = field(default_factory=dict)
    ac_tables: dict[int, HuffmanTable] = field(default_factory=dict)
    scan: list[int] = field(default_factory=list)  # component indices in SOS order
    restart_interval: int = 0
    entropy_pos: int = 0
    progressive: bool = False

    @property
    def max_h(self) -> int:
        return max(c.h for c in self.components)

    @property
    def max_v(self) -> int:
        return max(c.v for c in self.components)


def parse(data: bytes) -> JPEGInfo:
    """Parse all markers up to (and including) SOS; return entropy start."""
    info = JPEGInfo()
    if len(data) < 2 or data[0] != 0xFF or data[1] != M_SOI:
        raise ValueError("Empty input file" if len(data) < 2 else "Not a JPEG file")
    pos = 2
    while pos + 1 < len(data):
        if data[pos] != 0xFF:
            raise ValueError(f"corrupt JPEG stream at offset {pos}")
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        marker = data[pos]
        pos += 1
        if marker == M_EOI:
            break
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            continue
        length = struct.unpack_from(">H", data, pos)[0]
        segment = data[pos + 2 : pos + length]
        pos += length

        if marker == M_DQT:
            off = 0
            while off < len(segment):
                spec = segment[off]
                off += 1
                precision, index = spec >> 4, spec & 15
                table = [0] * 64
                for i in range(64):
                    if precision:
                        value = struct.unpack_from(">H", segment, off)[0]
                        off += 2
                    else:
                        value = segment[off]
                        off += 1
                    table[NATURAL_ORDER[i]] = value
                info.quant[index] = table

        elif marker == M_DHT:
            off = 0
            while off < len(segment):
                spec = segment[off]
                off += 1
                kind, index = spec >> 4, spec & 15
                counts = list(segment[off : off + 16])
                off += 16
                total = sum(counts)
                values = list(segment[off : off + total])
                off += total
                table = HuffmanTable(counts, values)
                if kind == 0:
                    info.dc_tables[index] = table
                else:
                    info.ac_tables[index] = table

        elif marker in (M_SOF0, M_SOF1, M_SOF2):
            info.progressive = marker == M_SOF2
            info.precision = segment[0]
            info.height, info.width = struct.unpack_from(">HH", segment, 1)
            count = segment[5]
            for i in range(count):
                cid, hv, tq = segment[6 + i * 3 : 9 + i * 3]
                info.components.append(Component(cid, hv >> 4, hv & 15, tq))

        elif marker == M_DRI:
            info.restart_interval = struct.unpack_from(">H", segment, 0)[0]

        elif marker == M_SOS:
            count = segment[0]
            by_id = {comp.cid: idx for idx, comp in enumerate(info.components)}
            for i in range(count):
                cid, selectors = segment[1 + i * 2 : 3 + i * 2]
                idx = by_id.get(cid)
                if idx is None:
                    raise ValueError(f"unknown component id {cid} in SOS")
                info.components[idx].td = selectors >> 4
                info.components[idx].ta = selectors & 15
                info.scan.append(idx)
            info.entropy_pos = pos
            break
        # APPn / COM and everything else: ignored
    return info


def _marker(code: int, payload: bytes) -> bytes:
    return bytes((0xFF, code)) + struct.pack(">H", len(payload) + 2) + payload


def jfif_app0() -> bytes:
    return _marker(
        M_APP0,
        b"JFIF\x00\x01\x01\x00" + struct.pack(">HH", 1, 1) + b"\x00\x00",
    )


def write_header(width: int, height: int, quality: int
                 ) -> tuple[bytes, list[list[int]], dict[tuple[str, int], HuffmanTable]]:
    """Emit the exact header libjpeg 6b writes for a default RGB baseline JPEG.

    Returns ``(header_bytes, [luma_quant, chroma_quant], huffman_tables)``
    where the quant tables are in natural order.
    """
    luma, chroma = quality_tables(quality)
    quants = [luma, chroma]
    huff = {
        key: HuffmanTable(spec["bits"], spec["values"])
        for key, spec in STD_HUFF_TABLES.items()
    }

    out = bytearray(b"\xff\xd8")
    out += jfif_app0()

    for index, table in enumerate(quants):
        payload = bytes((index,)) + bytes(table[NATURAL_ORDER[i]] for i in range(64))
        out += _marker(M_DQT, payload)

    # SOF0: 3 components, Y = 2x2 sampling, Cb/Cr = 1x1, ids 1/2/3.
    sof = bytearray((8,))
    sof += struct.pack(">HH", height, width)
    sof.append(3)
    sof += bytes((1, 0x22, 0))
    sof += bytes((2, 0x11, 1))
    sof += bytes((3, 0x11, 1))
    out += _marker(M_SOF0, bytes(sof))

    # DHT in the order emit_dht() is called: DC0, AC0, DC1, AC1.
    for kind, index in (("dc", 0), ("ac", 0), ("dc", 1), ("ac", 1)):
        table = huff[(kind, index)]
        payload = bytes(((0x10 if kind == "ac" else 0) | index,))
        payload += bytes(table.bits)
        payload += bytes(table.values)
        out += _marker(M_DHT, payload)

    # SOS: comp 1 -> DC0/AC0, comps 2/3 -> DC1/AC1.
    sos = bytearray((3,))
    sos += bytes((1, 0x00, 2, 0x11, 3, 0x11))
    sos += bytes((0, 63, 0))
    out += _marker(M_SOS, bytes(sos))
    return bytes(out), quants, huff
