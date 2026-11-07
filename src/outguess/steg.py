"""Steganographic core: message coding, embedding and retrieval.

Faithful port of ``src/outguess.c`` (``encode_data``, ``decode_data``,
``steg_embed``, ``steg_find``, ``steg_retrieve``, ``do_embed`` and the
statistical-foiling loop in ``main``).  All integer widths, array indices and
even the original's quirks are preserved so that generated carriers are
byte-compatible with the C implementation.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ._compat import U32, U64, c_div
from .arc4 import ARC4Stream
from .bitmap import Bitmap
from .golay import CODEBITS, CODEMASK, DATABITS, DATAMASK, ERRORBITS
from .golay import decode as golay_decode
from .golay import encode as golay_encode
from .iterator import DEFAULT_ITER, Iterator

STEG_EMBED = 0x01
STEG_MARK = 0x02
STEG_ERROR = 0x08
STEG_RETRIEVE = 0x10
STEG_STATS = 0x20

STEG_ERR_HEADER = 1
STEG_ERR_BODY = 2
STEG_ERR_PERM = 3

MAX_SEEK = 1024
DCTENTRIES = 256
DCTFREQRANGE = 5000
DCTFREQREDUCE = 33
DCTFREQMIN = 2


@dataclass
class StegResult:
    error: int = 0
    changed: int = 0
    bias: int = 0


@dataclass
class Config:
    flags: int = 0
    siter: int = 0
    siterstart: int = 0


@dataclass
class StegState:
    """Module-level variables of the C program, scoped per invocation."""

    stat: int = 0
    steg_data: int = 0
    steg_count: int = 0
    steg_mis: int = 0
    steg_mod: int = 0
    steg_encoded: int = 0
    steg_err_cnt: int = 0
    steg_err_buf: list[int] = field(default_factory=lambda: [0] * CODEBITS)
    steg_errors: int = 0
    steg_foil: int = 0
    steg_foilfail: int = 0
    steg_offset: list[int] = field(default_factory=lambda: [0] * MAX_SEEK)
    # JPEG statistical foiling scratch state
    dctadjust: list[int] = field(default_factory=lambda: [0] * DCTENTRIES)
    dctfreq: list[int] = field(default_factory=lambda: [0] * DCTENTRIES)
    dctpending: int = 0
    jpeg_eval: int = 0


def _err(message: str) -> None:
    print(message, file=sys.stderr)


# ---------------------------------------------------------------------------
# Message coding (Golay ECC + ARC4 stream cipher)
# ---------------------------------------------------------------------------


def encoded_length(length: int, flags: int) -> int:
    """Size of the encoded payload for a message of ``length`` bytes."""
    if flags & STEG_ERROR:
        datalen = length + (3 - (length % 3))
        return (datalen * 8 // DATABITS * CODEBITS + 7) // 8
    return length


def encode_data(
    data: Optional[bytes], length: int, stream: Optional[ARC4Stream], flags: int
) -> tuple[Optional[bytes], int]:
    """``encode_data`` -- optional Golay encoding followed by XOR encryption.

    ``data is None`` is the C "sizing" call: it returns ``(None, encoded_len)``.
    """
    datalen = length
    if flags & STEG_ERROR:
        datalen = datalen + (3 - (datalen % 3))
        eclen = (datalen * 8 // DATABITS * CODEBITS + 7) // 8
        if data is None:
            return None, eclen

        encdata = bytearray(3 * eclen)
        code = 0
        bitlength = 0
        out = 0
        pos = 0
        original_len = length
        while datalen > 0:
            if datalen > 3:
                edata = [data[pos], data[pos + 1], data[pos + 2]]
            else:
                adj = original_len % 3
                edata = [0, 0, 0]
                for k in range(adj):
                    edata[k] = data[pos + k]
                for j in range(2, adj - 1, -1):
                    edata[j] = j - adj
            tmp = edata[0] | (edata[1] << 8) | (edata[2] << 16)
            pos += 3
            datalen -= 3
            for _ in range(2):
                code |= golay_encode(tmp & DATAMASK) << bitlength
                bitlength += CODEBITS
                while bitlength >= 8:
                    encdata[out] = code & 0xFF
                    out += 1
                    code >>= 8
                    bitlength -= 8
                tmp >>= DATABITS
            code &= U64
        if bitlength > 0:
            encdata[out] = code & 0xFF
            out += 1
        datalen = eclen
        payload = encdata[:datalen]
    else:
        if data is None:
            return None, datalen
        payload = bytearray(data[:datalen])

    if datalen > 0 and stream is None:
        return None, datalen

    assert stream is not None
    result = bytearray(datalen)
    for j in range(datalen):
        result[j] = payload[j] ^ stream.get_byte()
    return bytes(result), datalen


def decode_data(
    encdata: bytearray, length: int, stream: ARC4Stream, flags: int
) -> tuple[bytes, int]:
    """``decode_data`` -- XOR decrypt in place, then Golay decode and unpad."""
    enclen = length
    for j in range(enclen):
        encdata[j] ^= stream.get_byte()

    if flags & STEG_ERROR:
        declen = enclen * DATABITS // CODEBITS
        data = bytearray(declen)
        inbits = outbits = 0
        etmp = dtmp = 0
        i = j = 0
        while i < enclen and j < declen:
            while outbits < CODEBITS:
                if i < enclen:
                    etmp |= encdata[i] << outbits
                i += 1
                outbits += 8
            dtmp |= (golay_decode(etmp & CODEMASK) >> (CODEBITS - DATABITS)) << inbits
            inbits += DATABITS
            etmp >>= CODEBITS
            etmp &= U32
            outbits -= CODEBITS
            while inbits >= 8:
                if j < declen:
                    data[j] = dtmp & 0xFF
                j += 1
                dtmp >>= 8
                inbits -= 8

        pad = data[declen - 1] if declen else 0
        bad = pad > 2
        if not bad:
            k = pad
            while k >= 0:
                if data[declen - 1 - pad + k] != k:
                    break
                k -= 1
            bad = k >= 0
        if bad:
            _err(f"decode_data: padding is incorrect: {pad}")
            return bytes(data), 0
        declen -= pad + 1
        _err(f"Decode: {enclen} data after ECC: {declen}")
        return bytes(data[:declen]), declen

    return bytes(encdata[:enclen]), enclen


# ---------------------------------------------------------------------------
# Error-correction bookkeeping
# ---------------------------------------------------------------------------


def _steg_adjust_errors(bitmap: Bitmap, flags: int, state: StegState) -> None:
    """``steg_adjust_errors`` -- sacrifice up to 3 bits with the highest bias."""
    many = ERRORBITS - state.steg_errors
    priority: list[int] = []
    detect: list[int] = []
    j = 0
    while j < many and j < state.steg_err_cnt:
        priority.append(state.steg_err_buf[j])
        detect.append(bitmap.detect[state.steg_err_buf[j]])
        j += 1

    # Simple bubble sort, descending by detectability.
    while True:
        swapped = False
        for i in range(j - 1):
            if detect[i] < detect[i + 1]:
                detect[i], detect[i + 1] = detect[i + 1], detect[i]
                priority[i], priority[i + 1] = priority[i + 1], priority[i]
                swapped = True
        if not swapped:
            break

    for idx in range(j, state.steg_err_cnt):
        n = 0
        while n < j:
            if detect[n] < bitmap.detect[state.steg_err_buf[idx]]:
                break
            n += 1
        if n < j - 1:
            detect[n + 1 : j + 1] = detect[n:j]
            priority[n + 1 : j + 1] = priority[n:j]
            del detect[j:]
            del priority[j:]
        if n < j:
            priority[n] = state.steg_err_buf[idx]
            detect[n] = bitmap.detect[state.steg_err_buf[idx]]

    for i in range(j):
        if flags & STEG_EMBED:
            # The C code indexes with `i` here (not `priority[i]`); preserved.
            bitmap.locked.set(i, 0)
            bitmap.set_bit(i, 0 if bitmap.get_bit(priority[i]) else 1)
        state.steg_mis -= 1
        state.steg_mod -= detect[i]


def _steg_embedchunk(
    bitmap: Bitmap,
    it: Iterator,
    data: int,
    bits: int,
    embed: int,
    state: StegState,
) -> int:
    """``steg_embedchunk`` -- embed one byte (LSB first)."""
    i = it.current
    nbits = bitmap.bits
    while i < nbits and bits:
        if (embed & STEG_ERROR) and not state.steg_encoded:
            if state.steg_err_cnt > 0:
                _steg_adjust_errors(bitmap, embed, state)
            state.steg_encoded = CODEBITS
            state.steg_errors = 0
            state.steg_err_cnt = 0
            state.steg_err_buf = [0] * CODEBITS
        state.steg_encoded -= 1

        bit = bitmap.get_bit(i)
        val = bit ^ (data & 1)
        state.steg_count += 1
        if val == 1:
            state.steg_mod += bitmap.detect[i]
            state.steg_mis += 1

        if val == 1 and bitmap.is_locked(i):
            if not (embed & STEG_ERROR):
                return 0
            state.steg_errors += 1
            if state.steg_errors > 3:
                return 0
            val = 2

        if (embed & STEG_ERROR) and val == 1:
            state.steg_err_buf[state.steg_err_cnt] = i
            state.steg_err_cnt += 1

        if val != 2 and (embed & STEG_EMBED):
            bitmap.lock(i)
            bitmap.set_bit(i, data & 1)

        data >>= 1
        bits -= 1
        i = it.next()
    return 1


def steg_embed(
    bitmap: Bitmap,
    it: Iterator,
    stream: ARC4Stream,
    data: bytes,
    datalen: int,
    seed: int,
    embed: int,
    state: StegState,
) -> StegResult:
    """``steg_embed`` -- dry-run (no STEG_EMBED) or real embedding."""
    state.steg_count = state.steg_mis = state.steg_mod = 0
    result = StegResult()

    if bitmap.bits // (datalen * 8) < 2:
        raise ValueError(
            f"steg_embed: not enough bits in bitmap for embedding: "
            f"{datalen * 8} > {bitmap.bits}/2"
        )

    if embed & STEG_EMBED:
        _err(f"Embedding data: {datalen * 8} in {bitmap.bits}")

    state.steg_encoded = 0
    state.steg_err_cnt = 0

    tmpbuf = bytes((seed & 0xFF, (seed >> 8) & 0xFF, datalen & 0xFF, (datalen >> 8) & 0xFF))
    length = 4
    encbuf, length = encode_data(tmpbuf, length, stream, embed)
    assert encbuf is not None
    for i in range(length):
        if not _steg_embedchunk(bitmap, it, encbuf[i], 8, embed, state):
            if (embed & STEG_ERROR) or state.steg_count < 16:
                result.error = STEG_ERR_HEADER
            else:
                result.error = STEG_ERR_PERM
            return result

    state.steg_encoded = 0
    it.seed(seed)

    pos = 0
    remaining = datalen
    while it.current < bitmap.bits and remaining > 0:
        it.adapt(bitmap.bits, remaining)
        tmp = data[pos]
        pos += 1
        remaining -= 1
        if not _steg_embedchunk(bitmap, it, tmp, 8, embed, state):
            result.error = STEG_ERR_BODY
            return result

    if (embed & STEG_ERROR) and state.steg_err_cnt > 0:
        _steg_adjust_errors(bitmap, embed, state)

    if embed & STEG_EMBED:
        count = state.steg_count
        mis = state.steg_mis
        _err(
            f"Bits embedded: {count}, changed: {mis}"
            f"({100 * mis / count if count else 0:2.1f}%)"
            f"[{100 * mis / state.steg_data if state.steg_data else 0:2.1f}%], "
            f"bias: {state.steg_mod}, tot: {it.current}, "
            f"skip: {it.current - count}"
        )

    result.changed = state.steg_mis
    result.bias = state.steg_mod
    return result


def steg_find(
    bitmap: Bitmap,
    it: Iterator,
    stream: ARC4Stream,
    siter: int,
    siterstart: int,
    data: bytes,
    datalen: int,
    flags: int,
    state: StegState,
) -> int:
    """``steg_find`` -- search the seed giving the least detectable embedding."""
    import math

    half = datalen * 8 // 2
    if not siter and not siterstart:
        siter = DEFAULT_ITER

    if siter and siterstart < siter:
        size = siter - siterstart
        chstats = [0] * size if state.stat else None
        _err("Finding best embedding...")
        changed = -1
        chmin = -1
        chmax = -1
        j = -STEG_ERR_HEADER

        for i in range(siterstart, siter):
            titer = it.copy()
            tas = stream.copy()
            result = steg_embed(bitmap, titer, tas, data, datalen, i, flags, state)
            if result.error == STEG_ERR_PERM:
                return -result.error
            if result.error:
                continue

            tch = result.changed + result.bias
            if chstats is not None:
                chstats[i - siterstart] = result.changed
            if chmax == -1 or result.changed > chmax:
                chmax = result.changed
            if chmin == -1 or result.changed < chmin:
                chmin = result.changed
            if changed == -1 or tch < changed:
                changed = tch
                j = i
                count = state.steg_count or 1
                _err(
                    f"{j:5d}: {result.changed:5d}"
                    f"({100 * state.steg_mis / count:3.1f}%)"
                    f"[{100 * state.steg_mis / state.steg_data if state.steg_data else 0:3.1f}%], "
                    f"bias {result.bias:5d}"
                    f"({result.bias / state.steg_mis if state.steg_mis else 0:1.2f}), "
                    f"saved: {c_div(half - result.changed, 8): 5d}, "
                    f"total: {100 * state.steg_mis / bitmap.bits:5.2f}%"
                )

        if chstats is not None and (chmax - chmin > 1):
            mean = 0.0
            dev = 0.0
            cnt = 0
            count = chmax - chmin + 1
            chtab = [0] * count
            chtabcnt = 0
            for i in range(size):
                if chstats[i] > 0:
                    mean += chstats[i]
                    cnt += 1
                    chtab[chstats[i] - chmin] += 1
                    chtabcnt += 1
            if cnt:
                mean /= cnt
            for i in range(size):
                if chstats[i] > 0:
                    sq = chstats[i] - mean
                    dev += sq * sq
            deviation = math.sqrt(dev / (cnt - 1)) if cnt > 1 else 0.0
            _err(
                f"Changed bits. Min: {chmin}, Mean: {mean:f}, "
                f"+- {deviation:f}, Max: {chmax}"
            )
            if state.stat > 1:
                for i in range(count):
                    if chtab[i]:
                        _err(f"{chmin + i}: {chtab[i] / chtabcnt:.9f}")

        _err_prefix = f"{j}, {changed}: "
        print(_err_prefix, end="", file=sys.stderr)
    else:
        j = siterstart
    return j


def steg_retrbyte(bitmap: Bitmap, bits: int, it: Iterator) -> int:
    """``steg_retrbyte`` -- read ``bits`` bits, LSB first."""
    i = it.current
    tmp = 0
    for where in range(bits):
        tmp |= bitmap.get_bit(i) << where
        i = it.next()
    return tmp


def steg_retrieve(
    bitmap: Bitmap, it: Iterator, stream: ARC4Stream, flags: int
) -> bytes:
    """``steg_retrieve`` -- read and decrypt the header, then the raw body."""
    datalen = 4
    _, datalen = encode_data(None, datalen, None, flags)
    tmpbuf = bytearray(datalen)
    for i in range(datalen):
        tmpbuf[i] = steg_retrbyte(bitmap, 8, it)

    header, datalen = decode_data(tmpbuf, datalen, stream, flags)
    if datalen != 4:
        raise ValueError(f"Steg retrieve: wrong data len: {datalen}")

    seed = header[0] | (header[1] << 8)
    datalen = header[2] | (header[3] << 8)
    _err(f"Steg retrieve: seed: {seed}, len: {datalen}")
    if datalen > bitmap.bytes:
        raise ValueError(f"Extracted datalen is too long: {datalen} > {bitmap.bytes}")

    buf = bytearray(datalen)
    it.seed(seed)
    n = 0
    remaining = datalen
    while remaining > 0:
        it.adapt(bitmap.bits, remaining)
        buf[n] = steg_retrbyte(bitmap, 8, it)
        n += 1
        remaining -= 1
    return bytes(buf)


def do_embed(
    bitmap: Bitmap,
    filename: str,
    key: bytes,
    cfg: Config,
    state: StegState,
) -> tuple[int, Optional[StegResult]]:
    """``do_embed`` -- encode one dataset and write it into the bitmap."""
    stream = ARC4Stream.from_key("Encryption", key)
    tas = stream.copy()
    it = Iterator(key)

    data = Path(filename).read_bytes()
    state.steg_data = len(data) * 8
    enclen = len(data)
    encdata, enclen = encode_data(data, enclen, tas, cfg.flags)
    assert encdata is not None
    if cfg.flags & STEG_ERROR:
        _err(f"Encoded '{filename}' with ECC: {enclen * 8} bits, {enclen} bytes")
        correctlen = enclen // 2 * 8
    else:
        _err(f"Encoded '{filename}': {enclen * 8} bits, {enclen} bytes")
        correctlen = enclen * 8
    if bitmap.maxcorrect and correctlen > bitmap.maxcorrect:
        raise ValueError(
            f"steg_embed: message larger than correctable size "
            f"{correctlen} > {bitmap.maxcorrect}"
        )

    j = steg_find(
        bitmap, it, stream, cfg.siter, cfg.siterstart,
        encdata, enclen, cfg.flags, state,
    )
    if j < 0:
        _err("Failed to find embedding.")
        return j, None

    result = steg_embed(
        bitmap, it, stream, encdata, enclen, j,
        cfg.flags | STEG_EMBED, state,
    )
    return j, result


# ---------------------------------------------------------------------------
# Statistical foiling performed by main() after embedding
# ---------------------------------------------------------------------------


def foil_statistics(bitmap: Bitmap, state: StegState) -> None:
    """Rebalance DCT coefficient frequencies (the OutGuess "foil" step)."""
    import math

    state.steg_offset = [0] * MAX_SEEK
    bitmap.foil = bitmap.foilfail = 0
    if bitmap.preserve is None:
        return

    for i in range(bitmap.bits):
        if not bitmap.is_locked(i):
            continue
        cbit = bitmap.get_bit(i)
        if cbit == (bitmap.data[i] & 0x01):
            continue
        n = bitmap.preserve(bitmap, i)
        if n > 0:
            n = abs(n - i)
            if n > MAX_SEEK:
                n = MAX_SEEK
            state.steg_offset[n - 1] += 1

    bitmap.preserve(bitmap, bitmap.bits)

    count = 0
    mean = 0.0
    for i in range(MAX_SEEK):
        count += state.steg_offset[i]
        mean += state.steg_offset[i] * (i + 1)
    mean = mean / count if count else float("nan")
    dev = 0.0
    for i in range(MAX_SEEK):
        sq = (i + 1 - mean) * (i + 1 - mean)
        dev += state.steg_offset[i] * sq
    deviation = math.sqrt(dev / (count - 1)) if count > 1 else float("nan")
    if count <= 1:
        # MinGW's printf renders 0/0 as "-nan(ind)"; match the C reference.
        offset = "-nan(ind) +- -nan(ind)"
    else:
        offset = f"{mean:f} +- {deviation:f}"
    _err(
        f"Foiling statistics: corrections: {bitmap.foil}, "
        f"failed: {bitmap.foilfail}, offset: {offset}"
    )
