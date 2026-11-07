#!/bin/sh
# Build the OutGuess 0.4 reference (C) binaries used for cross-validation.
#
#   tools/build_reference.sh [output-dir]
#
# The upstream tree is expected at ../_upstream (or $OUTGUESS_UPSTREAM); the
# built binaries default to ../_reference.  A C compiler is taken from $CC,
# then `cc`, then `python -m ziglang cc` -- the last one installs with
# `pip install ziglang` and needs no system toolchain, which is how the
# reference binaries for this port were produced on Windows.
#
# Two intentional deviations from upstream's own build:
#
#   * the bundled libjpeg 6b needs <netinet/in.h>, <err.h> and <sys/mman.h>,
#     which are missing on Windows; tiny shims live in tools/refbuild/compat
#     and are added to the include path.
#   * src/histogram.c opens the bitmap dump with fopen(path, "r").  On Windows
#     that is text mode, so any dump containing 0x1A (or 0x0D) is truncated.
#     We build it with "rb" so the reference output is well defined; POSIX
#     systems behave identically either way.
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(dirname "$HERE")
UP=${OUTGUESS_UPSTREAM:-$ROOT/_upstream}
OUT=${1:-$ROOT/_reference}
SRC=$UP/src
JPEG=$SRC/jpeg-6b-steg
SHIM=$ROOT/tools/refbuild
COMPAT=$SHIM/compat

[ -d "$SRC" ] || { echo "upstream sources not found: $SRC" >&2; exit 1; }
[ -d "$JPEG" ] || { echo "bundled libjpeg not found: $JPEG" >&2; exit 1; }
mkdir -p "$OUT"

# zig cc cross-compiles to PE, but only appends an extension when asked; a
# bare PE file is awkward to launch, so name it *.exe on Windows shells.
EXE=
case "$(uname -s 2>/dev/null)" in
MINGW*|MSYS*|CYGWIN*) EXE=.exe ;;
esac

if [ -n "$CC" ]; then
	:
elif command -v cc >/dev/null 2>&1; then
	CC=cc
elif command -v gcc >/dev/null 2>&1; then
	CC=gcc
else
	CC="python -m ziglang cc"
fi

CFLAGS="-O2 -std=gnu11 -w -DHAVE_STDC_HEADERS -DHAVE_CONFIG_H=0"
INCLUDES="-I$SHIM -I$SRC -I$JPEG"
# The compat headers only stand in for <err.h>, <netinet/in.h> and <sys/mman.h>,
# which Windows lacks; putting them on the include path elsewhere would shadow
# the real system headers.
case "$(uname -s 2>/dev/null)" in
MINGW*|MSYS*|CYGWIN*) INCLUDES="-I$SHIM -I$COMPAT -I$SRC -I$JPEG" ;;
esac

LIBJPEG="jcapimin.c jcapistd.c jccoefct.c jccolor.c jcdctmgr.c jchuff.c
jcinit.c jcmainct.c jcmarker.c jcmaster.c jcomapi.c jcparam.c jcphuff.c
jcprepct.c jcsample.c jctrans.c jdapimin.c jdapistd.c jdatadst.c jdatasrc.c
jdcoefct.c jdcolor.c jddctmgr.c jdhuff.c jdinput.c jdmainct.c jdmarker.c
jdmaster.c jdmerge.c jdphuff.c jdpostct.c jdsample.c jdtrans.c jerror.c
jfdctflt.c jfdctfst.c jfdctint.c jidctflt.c jidctfst.c jidctint.c jidctred.c
jquant1.c jquant2.c jutils.c jmemmgr.c jmemansi.c"

Jpeg_sources=""
for f in $LIBJPEG; do
	Jpeg_sources="$Jpeg_sources $JPEG/$f"
done

Outguess_sources=""
for f in outguess.c golay.c arc.c pnm.c jpg.c iterator.c md5.c err.c; do
	Outguess_sources="$Outguess_sources $SRC/$f"
done

echo "CC = $CC"
echo "upstream = $UP"
echo "output   = $OUT"

build() { # build <output-name> <sources...>
	name=$1
	shift
	# shellcheck disable=SC2086
	$CC $CFLAGS $INCLUDES "$@" -lm -o "$OUT/$name$EXE"
	echo "  built $OUT/$name$EXE"
}

build outguess $Jpeg_sources $Outguess_sources
build outguess-extract $Jpeg_sources $Outguess_sources
build histogram "$SRC/histogram.c" "$SRC/err.c"

# Bitmap dumper: upstream outguess.c with a -DEXTRACT dump path and options.
if [ -f "$SHIM/outguess_dump.c" ]; then
	build outguess-dump "$SHIM/outguess_dump.c" \
		"$SRC/golay.c" "$SRC/arc.c" "$SRC/pnm.c" "$SRC/jpg.c" \
		"$SRC/iterator.c" "$SRC/md5.c" "$SRC/err.c" $Jpeg_sources
fi

# Vector generators -- they only need the primitive they exercise.
build golaytest "$SHIM/golaytest.c" "$SRC/golay.c"
build arc4test "$SHIM/arc4test.c" "$SRC/arc.c"
build itertest "$SHIM/itertest.c" "$SRC/iterator.c" \
	"$SRC/arc.c" "$SRC/md5.c"

# histogram.c reads the dump in text mode; patch it to binary for the oracle.
sed 's/fopen(argv\[0\], "r")/fopen(argv[0], "rb")/' \
	"$SRC/histogram.c" > "$OUT/histogram_bin.c"
build histogram_bin "$OUT/histogram_bin.c" "$SRC/err.c"

# Carrier generators: they drive the bundled libjpeg directly so we can build
# 4:4:4 / 4:2:2 / greyscale / progressive fixtures, none of which OutGuess's
# own compressor emits.  tools/refbuild/steg_stub.c neutralises the steg patch.
for helper in mk_jpeg mk_jpeg_gray mk_jpeg_prog; do
	[ -f "$SHIM/$helper.c" ] || continue
	build "$helper" "$SHIM/$helper.c" "$SHIM/steg_stub.c" \
		"$JPEG/jdatadst.c" $Jpeg_sources
done

echo "done"
