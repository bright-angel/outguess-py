#!/bin/sh
# Build the *instrumented* reference binaries used while reverse-engineering
# the parts of OutGuess/libjpeg that the port has to reproduce bit for bit
# (see validation/NOTES.md).
#
#   tools/build_debug.sh [output-dir]
#
# These binaries are not needed for the test suite or for cross-validation --
# they only exist so the measurements quoted in validation/NOTES.md can be
# reproduced.  Each one swaps an instrumented copy of a single translation unit
# into an otherwise normal build:
#
#   outguess-pj    tools/refbuild/jpg_dbg.c       instead of src/jpg.c
#                  PJ_DEBUG/PJ_DUMPDATA/PJ_DUMPFINAL trace preserve_jpg,
#                  WR_DEBUG traces the writer, LAYOUT prints the addresses of
#                  dctmin/dctmax/dctadjust/dctfreq.
#   outguess-smp   tools/refbuild/jcsample_dbg.c  instead of jcsample.c
#                  dumps the chroma planes before/after h2v2_downsample.
#   outguess-dct   tools/refbuild/jcdctmgr_dbg.c  instead of jcdctmgr.c
#                  dumps quantized coefficients before steg_use_bit runs.
#
# The trace switches are environment variables read at run time, so a single
# binary covers every measurement.
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(dirname "$HERE")
UP=${OUTGUESS_UPSTREAM:-$ROOT/_upstream}
OUT=${1:-$ROOT/_reference/debug}
SRC=$UP/src
JPEG=$SRC/jpeg-6b-steg
SHIM=$ROOT/tools/refbuild
COMPAT=$SHIM/compat

[ -d "$SRC" ] || { echo "upstream sources not found: $SRC" >&2; exit 1; }
mkdir -p "$OUT"

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

# build_variant <variant-name> <upstream-basename> <instrumented-source>
build_variant() {
	variant=$1
	replacing=$2
	instrumented=$3

	sources=""
	for f in $LIBJPEG; do
		if [ "$f" = "$replacing" ]; then
			sources="$sources $instrumented"
		else
			sources="$sources $JPEG/$f"
		fi
	done
	for f in outguess.c golay.c arc.c pnm.c jpg.c iterator.c md5.c err.c; do
		# The instrumented jpg.c is the steganography side, so keep upstream's.
		sources="$sources $SRC/$f"
	done

	# shellcheck disable=SC2086
	$CC $CFLAGS $INCLUDES $sources -lm -o "$OUT/$variant$EXE"
	echo "  built $OUT/$variant$EXE"
}

echo "CC = $CC"
echo "upstream = $UP"
echo "output   = $OUT"

build_variant outguess-pj  jpg.c      "$SHIM/jpg_dbg.c"
build_variant outguess-smp jcsample.c "$SHIM/jcsample_dbg.c"
build_variant outguess-dct jcdctmgr.c "$SHIM/jcdctmgr_dbg.c"

# Raw pixel dump of the decode path, for comparing libjpeg's output against
# the port's decoder (supports 4:2:0, 4:2:2 and 4:4:4).  read_JPEG_file()
# lives in src/jpg.c, which in turn calls into the bit iterator and ARC4, so
# the helper links those as well (src/jpg.c carries the reading half of
# steg_use_bit, so no stub is needed here).
decoder_sources=""
for f in $LIBJPEG; do
	decoder_sources="$decoder_sources $JPEG/$f"
done
# shellcheck disable=SC2086
$CC $CFLAGS $INCLUDES "$SHIM/jdec.c" \
	"$SRC/jpg.c" "$SRC/iterator.c" "$SRC/arc.c" "$SRC/md5.c" "$SRC/golay.c" \
	$decoder_sources -lm -o "$OUT/jdec$EXE"
echo "  built $OUT/jdec$EXE"

echo "done"
