# outguess-py

A pure-Python, bit-compatible reimplementation of [OutGuess 0.4][upstream], the
universal steganography tool by Niels Provos.

Files produced by this package are byte-for-byte identical to the ones the C
program produces, and the two implementations can read each other's output.
There are no third-party runtime dependencies: the JPEG codec (quantisation,
Huffman coding, integer DCT, chroma subsampling), the ARC4 keystream, the
(23,12,7) Golay code and the adaptive bit iterator are all implemented here.

```
$ outguess -k "my secret" -d message.txt sample.jpg stego.jpg
Reading sample.jpg....
JPEG compression quality set to 75
Extracting usable bits:   5114 bits
Correctable message size: 1968 bits, 38.48%
Encoded 'message.txt': 648 bits, 81 bytes
Finding best embedding...
    0:   328(48.2%)[50.6%], bias   345(1.05), saved:     0, total:  6.41%
    ...
   93:   313(46.0%)[48.3%], bias   296(0.95), saved:     1, total:  6.12%
93, 609: Embedding data: 648 in 5114
Bits embedded: 680, changed: 313(46.0%)[48.3%], bias: 296, tot: 5097, skip: 4417
Foiling statistics: corrections: 149, failed: 2, offset: 35.819277 +- 82.508410
Total bits changed: 609 (change 313 + bias 296)
Storing bitmap into data...
Writing stego.jpg....

$ outguess -k "my secret" -r stego.jpg recovered.txt
Reading stego.jpg....
Extracting usable bits:   5114 bits
Steg retrieve: seed: 93, len: 81
```

## Installation

```console
$ pip install .            # or: pip install -e '.[dev]'
```

Python 3.9 or newer. `pip` installs five console scripts:

| script | purpose |
| --- | --- |
| `outguess` | embed / retrieve, the main tool |
| `outguess-extract` | dump the raw bit plane of a carrier (upstream's `outguess-extract` mode) |
| `outguess-histogram` | statistics over an extracted bit plane |
| `outguess-seek` | try every carrier in a directory, keep the cheapest embedding |
| `outguess-validate` | run the C cross-validation harness from a source checkout |

`python -m outguess` is equivalent to `outguess`.

## Command line

The option set is the one from the man page, including the two-dataset
(`-K`/`-D`/`-E`) and key-derivation (`-x`) modes:

```
outguess [options] [<input file> [<output file>]]

  -h           print this usage help text and exit
  -[sS] <n>    iteration start, capital letter for 2nd dataset
  -[iI] <n>    iteration limit
  -[kK] <key>  key
  -[dD] <name> filename of dataset
  -[eE]        use error correcting encoding
  -p <param>   parameter passed to destination data handler
  -r           retrieve message from data
  -x <n>       number of key derivations to be tried
  -m           mark pixels that have been modified
  -t           collect statistic information
  -F[+-]       turns statistical steganalysis foiling on/off (default on)
```

`-p` is the JPEG quality used when re-compressing a JPEG carrier (clamped to
75..100, default 75). For PNM carriers it is ignored, as upstream does.

## Supported carriers

* **PNM** — binary `P5` (grey) and `P6` (RGB). Every sample LSB is a usable
  bit; `preserve_pnm` is a no-op, so no statistical foiling is applied.
* **JPEG** — 3-component YCbCr at 4:4:4, 4:2:2 or 4:2:0 sampling. The carrier
  is always re-compressed at the requested quality with libjpeg's default 4:2:0
  settings; coefficients whose magnitude is 0 or 1 are skipped, exactly like the
  reference `steg_use_bit`. Chroma is upsampled with libjpeg's fancy (triangle)
  filters, including the horizontal-only variant that 4:2:2 needs.

  Two limits apply. **Greyscale** (single-component) carriers are rejected for
  embedding with libjpeg's own message, `Bogus input colorspace` — the C tool
  fails identically at compression time, because its compressor always declares
  YCbCr. **Progressive** JPEG is *not* supported yet: `read_jpeg` raises
  `ValueError("progressive JPEG is not supported by OutGuess")`. This is the one
  remaining functional gap, since libjpeg 6b does decode progressive files and
  the C tool therefore handles them; baseline (SOF0/SOF1) carriers, which is
  what virtually every encoder emits by default, are fully supported.

## Python API

The CLI is a thin layer over the same functions you can call directly. For
carrier-independent work, drive the handlers — `get_bitmap()` builds the bit
plane from the decoded image, `do_embed()` fills it, `put_bitmap()` maps it back
and `write()` serialises:

```python
from outguess.handlers.pnm import PNMHandler
from outguess.steg import Config, StegState, do_embed

handler = PNMHandler()
with open("cover.ppm", "rb") as fh:
    image = handler.read(fh)

bitmap = handler.get_bitmap(image, 0)          # usable bits + detectability
offset, result = do_embed(bitmap, "message.txt", b"my secret", Config(), StegState())
print(offset, result.changed, result.bias)     # 67 305 16

handler.put_bitmap(image, bitmap, 0)
with open("stego.ppm", "wb") as fh:
    handler.write(fh, image)
```

For anything that involves option handling, seeding or extraction, call the
program entry point instead — it takes the same argv list as the script:

```python
from outguess.cli import run

run(["-k", "my secret", "-r", "stego.jpg", "recovered.txt"])
run(["-p", "90", "-e", "-k", "other", "-d", "msg.txt", "in.jpg", "out.jpg"])
```

`run()` returns the process exit code and never calls `sys.exit()`, so it is
safe inside a larger program; `main()` is the console-script wrapper that
converts exceptions into diagnostics plus a non-zero exit.

`outguess.jpeg.codec` exposes the lower layer — `read_jpeg`, `write_jpeg`,
`encode_coefficients`, `decode_coefficients`, `preserve_jpg` — if you need to
work on coefficients rather than pixels.

The modules mirror the C translation units one to one:

| module | upstream |
| --- | --- |
| `outguess.cli` | `src/outguess.c` (option parsing, embedding driver) |
| `outguess.steg` | `src/outguess.c` (`steg_embed`, `steg_retrieve`, `do_embed`) |
| `outguess.arc4` | `src/arc.c` |
| `outguess.golay` | `src/golay.c` |
| `outguess.iterator` | `src/iterator.c` |
| `outguess.handlers.pnm` | `src/pnm.c` |
| `outguess.handlers.jpeg` | `src/jpg.c` |
| `outguess.histogram` | `src/histogram.c` |
| `outguess.seek` | `src/seek_script` |
| `outguess.jpeg.*` | the bundled `jpeg-6b-steg` codec |

`outguess._compat` holds the helpers that keep C semantics: fixed-width integer
wrapping (`i8`, `u16`, `u32`), single-precision arithmetic (`f32`, `f32_div`,
…) and a `BitArray` with the same LSB-first `TEST_BIT`/`WRITE_BIT` behaviour.

## Cross-validation

`validation/` contains a harness that drives the C binary and this port over
eight carriers and ten option sets and compares the produced carrier bytes, the
diagnostics on stderr, mutual extraction in both directions, the
`outguess-extract` bitmap dumps and the `histogram` readout.

```console
$ tools/fetch_upstream.sh           # clone OutGuess 0.4 into _upstream/
$ tools/build_reference.sh          # build the C oracle into _reference/
$ outguess-validate                 # or: python validation/cross_validate.py
```

`_upstream/` is fetched rather than vendored, and is pinned to the 0.4 release
commit so the comparison stays reproducible. The build script takes a C
compiler from `$CC`, then `cc`, then `python -m ziglang cc` — that last option
installs with `pip install ziglang` and needs no system toolchain, which is how
the reference binaries for this port were produced on Windows.

Current result — `validation/REPORT.md` is regenerated on every run:

```
pass=72, known=8, edge=0, fail=0
auxiliary: extract=8/8 histogram=8/8
```

The carriers are two PPM/PGM images, a 160x120 and a 320x240 4:2:0 JPEG, an
odd-geometry 133x201 JPEG, and 320x240 JPEGs at 4:2:2 and 4:4:4 sampling. The
eight `known` entries are the `-e` (Golay ECC) cases; see below.

## Known deviations

**`-e` / `-E` (error-correcting encoding) does not match the C output.** This
is a bug in upstream, not in the port: `steg_adjust_errors()` copies
`(j - n) * sizeof(int)` bytes to `detect + n + 1` with `j == ERRORBITS == 3` and
`n == 1`, writing `detect[3]` and `priority[3]` one past the end of two
three-element stack arrays. The `-O2` build silently corrupts its own stack (the
reported `bias` becomes garbage such as `-231460` and "Total bits changed" goes
negative); the `-O0` build crashes. The port keeps the same algorithm but
bounds every access, so its statistics are sane and the carriers it produces are
interoperable in all four directions (C→Py, Py→C, Py→Py, C→C). Every other
mode is byte-identical, including `-K`/`-D` two-dataset embedding and `-x` key
derivation. (`-E` combined with a second dataset has the same overflow — C
clears bits 0..j-1 of the carrier, where the first dataset's header lives — so
the survival of the first dataset is luck in both implementations; see
`validation/NOTES.md`.)

Two smaller, documented differences:

* Extraction dumps can differ in the *unused* high bits of their final byte.
  C writes into a `malloc`'d buffer that it never initialises past the last
  significant bit; the port emits zeroes.
* `outguess-extract` selects its mode from `argv[0]` after splitting on `/`,
  so the upstream binary cannot enter that mode on Windows. The port detects it
  from the entry point instead.

**Progressive JPEG carriers are not supported yet** (see "Supported carriers").
Baseline carriers — 4:4:4, 4:2:2 and 4:2:0, all byte-identical to the C output —
are covered by the validation matrix and the test-suite.

`validation/NOTES.md` documents every quirk that had to be reproduced — the
`dctadjust[-1]` padding cell that C really does increment, the `dctfreq[-1]`
alias onto `dctadjust[255]`, the masking bug in `histogram_runlen`, and the
single-precision arithmetic in the foiling statistics — with the measured
addresses and before/after numbers.

## Layout

```
pyproject.toml          setuptools, src layout, console scripts
.github/workflows/      CI: test matrix, lint + packaging, cross-validation
src/outguess/           the package
tests/                  pytest suite plus fixture carriers and C-generated vectors
  data/                 PPM/PNM/JPEG carriers, golden outputs, ARC4/Golay/iterator vectors
  data/vectors/         vectors dumped from the C implementation
validation/             cross_validate.py, REPORT.md, NOTES.md
tools/
  fetch_upstream.sh     clone the pinned OutGuess 0.4 tree into _upstream/
  build_reference.sh    build the C oracle into _reference/
  build_debug.sh        build the instrumented binaries used for NOTES.md
  refbuild/             config.h, Windows compat headers, probe and fixture
                        generators -- the sources the build scripts compile
```

Two directories appear after the first build and are never committed:

```
_upstream/              unmodified upstream sources (fetched)
_reference/             the binaries produced by the build scripts
```

Both are development-only. The package itself builds and runs without them;
only `outguess-validate` needs a checkout.

## Tests

```console
$ pip install -e '.[test]'
$ pytest
```

The suite covers the primitives against C-generated vectors (`tests/data/vectors`),
PNM and JPEG round trips, golden carriers for every sampling layout, the CLI
surface, `seek` and the histogram readout. Every expected value is a recorded
file, so the tests run without the C binary — the oracle is only needed to
regenerate `tests/data` (`validation/NOTES.md` documents how).

See `CONTRIBUTING.md` for the workflow, and for the one rule that governs
everything else: an upstream quirk is never "fixed", it is modelled and
documented.

## Licence

OutGuess is distributed under a BSD-style licence; the original copyright
notice is preserved in `LICENSE`, together with the bundled libjpeg notice. This
port keeps the same terms.

[upstream]: https://github.com/resurrecting-open-source-projects/outguess
