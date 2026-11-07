"""Command line interface -- option-for-option equivalent of ``outguess`` 0.4."""

from __future__ import annotations

import getopt
import os
import struct
import sys
from typing import BinaryIO, Optional, Sequence

from ._compat import f32, f32_div, f32_mul
from .arc4 import ARC4Stream
from .handlers import get_handler
from .iterator import Iterator
from .steg import (
    STEG_ERROR,
    STEG_MARK,
    STEG_RETRIEVE,
    Config,
    StegResult,
    StegState,
    decode_data,
    do_embed,
    foil_statistics,
    steg_retrieve,
)

VERSION = "OutGuess 0.4 Universal Stego 1999-2021 Niels Provos and others"

USAGE = """{version}

{prog} [options] [<input file> [<output file>]]
\t-h           print this usage help text and exit
\t-[sS] <n>    iteration start, capital letter for 2nd dataset
\t-[iI] <n>    iteration limit
\t-[kK] <key>  key
\t-[dD] <name> filename of dataset
\t-[eE]        use error correcting encoding
\t-p <param>   parameter passed to destination data handler
\t-r           retrieve message from data
\t-x <n>       number of key derivations to be tried
\t-m           mark pixels that have been modified
\t-t           collect statistic information
\t-F[+-]       turns statistical steganalysis foiling on/off.
\t             The default is on.
"""

OPTSTRING = "heErmtp:s:S:i:I:k:d:D:K:x:F:"


class UsageError(Exception):
    pass


def _usage(prog: str, version: str = VERSION) -> None:
    print(USAGE.format(version=version, prog=prog), file=sys.stderr)


def _encode(s: str) -> bytes:
    """Encode a C ``char *`` argument the way a UTF-8/ASCII argv does."""
    return os.fsencode(s) if any(ord(c) > 127 for c in s) else s.encode("ascii")


def run(
    argv: Optional[Sequence[str]] = None,
    *,
    extract_only: bool = False,
    argv0: Optional[str] = None,
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    prog = argv0 or (sys.argv[0] if argv is None else "outguess")
    # The C binary switches mode when invoked as "outguess-extract".
    if os.path.basename(prog).lower().startswith("outguess-extract"):
        extract_only = True

    key = "Default key"
    key2: Optional[str] = None
    param: Optional[str] = None
    derive = 0
    data: Optional[str] = None
    data2: Optional[str] = None
    mark = 0
    doretrieve = 0
    doerror = 0
    doerror2 = 0
    foil = 1
    state = StegState()
    cfg1 = Config()
    cfg2 = Config()

    try:
        opts, rest = getopt.gnu_getopt(args, OPTSTRING)
    except getopt.GetoptError:
        _usage(prog)
        return 1

    for opt, value in opts:
        if opt == "-h":
            _usage(prog)
            return 0
        elif opt == "-F":
            if value.startswith("-"):
                foil = 0
        elif opt == "-k":
            key = value
        elif opt == "-K":
            key2 = value
        elif opt == "-p":
            param = value
        elif opt == "-x":
            derive = _atoi(value)
        elif opt == "-i":
            cfg1.siter = _atoi(value)
        elif opt == "-I":
            cfg2.siter = _atoi(value)
        elif opt == "-s":
            cfg1.siterstart = _atoi(value)
        elif opt == "-S":
            cfg2.siterstart = _atoi(value)
        elif opt == "-r":
            doretrieve = 1
        elif opt == "-t":
            state.stat += 1
        elif opt == "-m":
            mark = 1
        elif opt == "-d":
            data = value
        elif opt == "-D":
            data2 = value
        elif opt == "-e":
            doerror = 1
        elif opt == "-E":
            doerror2 = 1
        else:
            _usage(prog)
            return 1

    if extract_only:
        doretrieve = 1

    if (
        (len(rest) != 2 and len(rest) != 0)
        or (extract_only and len(rest) != 2)
        or (not doretrieve and not extract_only and data is None)
    ):
        _usage(prog)
        return 1

    fin: BinaryIO
    fout: BinaryIO
    close_in = close_out = False
    if len(rest) == 2:
        src_name, dst_name = rest
        srch = get_handler(src_name)
        if srch is None:
            print(f"Unknown data type of {src_name}", file=sys.stderr)
            return 1
        dsth = None
        if not doretrieve:
            dsth = get_handler(dst_name)
            if dsth is None:
                print(f"Unknown data type of {dst_name}", file=sys.stderr)
                return 1
        try:
            fin = open(src_name, "rb")
            close_in = True
        except OSError as exc:
            print(f"Can't open input file '{src_name}': {exc}", file=sys.stderr)
            return 1
        try:
            fout = open(dst_name, "wb")
            close_out = True
        except OSError as exc:
            print(f"Can't open output file '{dst_name}': {exc}", file=sys.stderr)
            return 1
        reading_name, writing_name = src_name, dst_name
    else:
        fin = sys.stdin.buffer
        fout = sys.stdout.buffer
        srch = get_handler(".ppm")
        dsth = srch
        assert srch is not None
        reading_name, writing_name = "<stdin>", "<stdout>"

    try:
        return _execute(
            fin=fin,
            fout=fout,
            srch=srch,
            dsth=dsth,
            reading_name=reading_name,
            writing_name=writing_name,
            extract_only=extract_only,
            doretrieve=doretrieve,
            data=data,
            data2=data2,
            key=key,
            key2=key2,
            derive=derive,
            param=param,
            mark=mark,
            doerror=doerror,
            doerror2=doerror2,
            foil=foil,
            cfg1=cfg1,
            cfg2=cfg2,
            state=state,
        )
    finally:
        if close_in:
            fin.close()
        if close_out:
            fout.close()


def _atoi(value: str) -> int:
    """``atoi`` -- leading integer only, 0 when absent."""
    text = value.lstrip()
    sign = 1
    if text.startswith(("-", "+")):
        sign = -1 if text[0] == "-" else 1
        text = text[1:]
    digits = ""
    for ch in text:
        if ch.isdigit():
            digits += ch
        else:
            break
    return sign * int(digits) if digits else 0


def _execute(
    *,
    fin: BinaryIO,
    fout: BinaryIO,
    srch,
    dsth,
    reading_name: str,
    writing_name: str,
    extract_only: bool,
    doretrieve: int,
    data: Optional[str],
    data2: Optional[str],
    key: str,
    key2: Optional[str],
    derive: int,
    param: Optional[str],
    mark: int,
    doerror: int,
    doerror2: int,
    foil: int,
    cfg1: Config,
    cfg2: Config,
    state: StegState,
) -> int:
    if doerror or doerror2:
        print("Initialize encoding/decoding tables", file=sys.stderr)

    print(f"Reading {reading_name}....", file=sys.stderr)
    image = srch.read(fin)

    if extract_only:
        bitmap = srch.get_bitmap(image, STEG_RETRIEVE)
        print(f"Writing {bitmap.bits} bits", file=sys.stderr)
        fout.write(struct.pack(">I", bitmap.bits))
        fout.write(bitmap.bitmap.to_bytes(bitmap.bytes))
        return 1  # the C program exits(1) in this mode

    if doretrieve:
        bitmap = srch.get_bitmap(image, STEG_RETRIEVE)
    else:
        assert dsth is not None
        dsth.init(param)
        bitmap = dsth.get_bitmap(image, 0)

    print(f"Extracting usable bits:   {bitmap.bits} bits", file=sys.stderr)

    if doerror:
        cfg1.flags |= STEG_ERROR

    if not doretrieve:
        assert dsth is not None
        if mark:
            cfg1.flags |= STEG_MARK
        if foil:
            dsth.preserve(bitmap, -1)
            if bitmap.extra.get("estimate_error"):
                print("Can not calculate estimate", file=sys.stderr)
            if bitmap.maxcorrect:
                # C computes this in single precision:
                #   (float)100 * maxcorrect / bitmap.bits
                pct = f32_div(
                    f32_mul(f32(100.0), f32(float(bitmap.maxcorrect))),
                    f32(float(bitmap.bits)),
                )
                print(
                    f"Correctable message size: {bitmap.maxcorrect} bits, "
                    f"{pct:0.2f}%",
                    file=sys.stderr,
                )

        assert data is not None
        _, cumres = do_embed(bitmap, data, _encode(key), cfg1, state)
        cumres = cumres or StegResult()

        if key2 and data2:
            cfg2.flags = cfg1.flags
            if doerror2:
                cfg2.flags |= STEG_ERROR
            else:
                cfg2.flags &= ~STEG_ERROR
            j = -1
            tmpres: Optional[StegResult] = None
            for i in range(0, derive + 1):
                if j >= 0:
                    break
                derived = key2 if i == 0 else f"{key2}{i}"
                j, tmpres = do_embed(bitmap, data2, _encode(derived), cfg2, state)
            if j < 0:
                print("Failed to find embedding.", file=sys.stderr)
                return 1
            cumres.changed += (tmpres or StegResult()).changed
            cumres.bias += (tmpres or StegResult()).bias

        if foil:
            foil_statistics(bitmap, state)

        print(
            f"Total bits changed: {cumres.changed + cumres.bias} "
            f"(change {cumres.changed} + bias {cumres.bias})",
            file=sys.stderr,
        )
        print("Storing bitmap into data...", file=sys.stderr)
        dsth.put_bitmap(image, bitmap, cfg1.flags)
        print(f"Writing {writing_name}....", file=sys.stderr)
        dsth.write(fout, image)
    else:
        keybytes = _encode(key)
        stream = ARC4Stream.from_key("Encryption", keybytes)
        tas = stream.copy()
        it = Iterator(keybytes)
        encdata = steg_retrieve(bitmap, it, stream, cfg1.flags)
        plain, length = decode_data(bytearray(encdata), len(encdata), tas, cfg1.flags)
        fout.write(plain[:length])
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        return run(argv)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def extract_main(argv: Optional[Sequence[str]] = None) -> int:
    """``outguess-extract``: dump the redundant-bit bitmap for ``histogram``."""
    try:
        return run(argv, extract_only=True)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
