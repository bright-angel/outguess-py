"""(23,12,7) binary Golay code, ported from ``src/golay.c``.

OutGuess uses systematic encoding: 12 data bits are shifted left by 11 and
the remainder modulo the generator polynomial ``g(x) = 0xC75`` is appended.
The decoder uses a 2048-entry syndrome table generated from all error
patterns of Hamming weight <= 3.
"""

from __future__ import annotations

X22 = 0x00400000
X11 = 0x00000800
MASK12 = 0xFFFFF800
GENPOL = 0x00000C75

DATAMASK = 0x000FFF
CODEMASK = 0x7FFFFF
DATABITS = 12
CODEBITS = 23
ERRORBITS = 3


def get_syndrome(pattern: int) -> int:
    """Remainder of ``pattern`` divided by the generator polynomial."""
    if pattern >= X11:
        aux = X22
        while pattern & MASK12:
            while not (aux & pattern):
                aux >>= 1
            pattern ^= (aux // X11) * GENPOL
    return pattern


def _arr2int(a: list[int], r: int) -> int:
    result = 0
    for i in range(1, r + 1):
        result += 1 << (a[i] - 1)
    return result


def _nextcomb(n: int, r: int, a: list[int]) -> None:
    a[r] += 1
    if a[r] <= n:
        return
    j = r - 1
    while a[j] == n - r + j:
        j -= 1
    for i in range(r, j - 1, -1):
        a[i] = a[j] + i - j + 1


def _build_tables() -> tuple[list[int], list[int]]:
    encoding = [0] * 4096
    decoding = [0] * 2048

    for pattern in range(4096):
        temp = pattern << 11
        encoding[pattern] = temp + get_syndrome(temp)

    decoding[0] = 0
    decoding[1] = 1
    temp = 1
    for i in range(2, 24):
        temp *= 2
        decoding[get_syndrome(temp)] = temp

    a = [0, 1, 2, 0]
    decoding[get_syndrome(_arr2int(a, 2))] = _arr2int(a, 2)
    for _ in range(1, 253):
        _nextcomb(23, 2, a)
        temp = _arr2int(a, 2)
        decoding[get_syndrome(temp)] = temp

    a = [0, 1, 2, 3]
    decoding[get_syndrome(_arr2int(a, 3))] = _arr2int(a, 3)
    for _ in range(1, 1771):
        _nextcomb(23, 3, a)
        temp = _arr2int(a, 3)
        decoding[get_syndrome(temp)] = temp

    return encoding, decoding


ENCODING_TABLE, DECODING_TABLE = _build_tables()


def encode(value: int) -> int:
    """``ENCODE(x)`` for a 12-bit information vector."""
    return ENCODING_TABLE[value]


def decode(value: int) -> int:
    """``DECODE(x)`` -- correct up to three bit errors in a 23-bit word."""
    return value ^ DECODING_TABLE[get_syndrome(value)]
