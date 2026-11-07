# Reference-build notes

This file records the undefined behaviour in upstream OutGuess 0.4 that the
Python port has to model (or deliberately does not model), together with the
measurements that back every claim.  Everything below was measured on the
reference build produced by `tools/build_reference.sh` (zig cc,
`-target x86_64-windows-gnu -O2`) from the unmodified upstream sources in
`_upstream/`.

---

## 1. `dctadjust[-1]` is alignment padding, not `dctmax`

`src/jpg.c` keeps two adjacent tables and indexes them with a plain `char`
coefficient:

```c
static int dctadjust[DCTENTRIES];   /* DCTENTRIES == 256 */
static int dctfreq[DCTENTRIES];
...
coeff = data[off] ^ 0x01;
if (dctadjust[data[off] + 127]) { ... }
if (dctadjust[coeff + 127] < dctfreq[coeff + 127]) { ... }
```

`data` is `char *`, so a stored coefficient of `0x80` reads back as `-128` and
both `data[off] + 127` and `coeff + 127` can be `-1`.  Two different cells are
reached:

* `dctfreq[-1]` **does** alias a live variable.  The two arrays are contiguous,
  so `dctfreq - 1` is the last element of `dctadjust`:

  ```
  LAYOUT dctadjust=00007FF6C7279300 dctfreq=00007FF6C7279700 ...
  ```

  `0x9700 - 0x9300 == 0x400 == 256 * sizeof(int)`, hence
  `dctfreq[-1] == dctadjust[255]`.  This matters twice: the frequency
  histogram loop `dctfreq[data[i] + 127]++` dumps every `-128` coefficient into
  `dctadjust[255]`, and the flush loop later drains that slot with
  `coeff = (char)(255 - 127)`, which is `128` in C and therefore `-128` once
  narrowed to `char`.

* `dctadjust[-1]` **does not** alias anything.  It lands in the alignment
  padding between `dctmax` and the array:

  ```
  LAYOUT dctmin=00007FF6C72792AC dctmax=00007FF6C72792B0 dctadjust=00007FF6C7279300
  LAYOUT before0=0 after_last=0
  ```

  `dctadjust[-1]` is at `0x9300 - 4 == 0x92FC`, i.e. inside the 76-byte gap
  `0x92B4..0x92FF`.  It is writable `.bss`, it starts at `0`, and
  `memset(dctadjust, 0, sizeof(dctadjust))` (which starts at `&dctadjust[0]`)
  never clears it.  The flush loop iterates `0..255`, so it is never drained
  either: it behaves like a 257th counter that starts at zero and can be
  incremented or decremented.

The port therefore stores `dctadjust` shifted by one
(`src/outguess/jpeg/codec.py`, `preserve_jpg`): `adjust[i + 1]` mirrors C's
`dctadjust[i]` and `adjust[0]` mirrors C's `dctadjust[-1]`.  `dctfreq[-1]` is
resolved through `adjust[DCTENTRIES]`.

Failing to model the padding cell is not cosmetic: for
`tests/data/photo_odd.jpg` at `-p 90`, C reaches `off = 5942` with
`data[off] == -127`, so `coeff == -128`, and `dctadjust[-1] (=0) < dctfreq[-1]`
is true.  C increments the padding cell and returns `0`; a port that skips the
branch instead falls through to `preserve_single`, which rewrites an earlier
coefficient.  The carrier bytes still match (the output LSBs come from
`bitmap.bitmap`, not from `data[]`), but the reported foiling statistics
diverge:

| build | foiling statistics line |
| --- | --- |
| C (reference) | `corrections: 138, failed: 0, offset: 134.112903 +- 248.805152` |
| port before the fix | `corrections: 138, failed: 1, offset: 137.380952 +- 248.149957` |
| port after the fix | `corrections: 138, failed: 0, offset: 134.112903 +- 248.805152` |

The addresses above come from the PE binary that `tools/build_reference.sh`
produces on Windows.  Where exactly the linker puts the padding is not
guaranteed: a binary built by a different toolchain may place some other
variable (or nothing writable) at `dctadjust[-1]`, and then the same C source
produces different statistics.  The port models the layout that was measured
here, which is the one every number in this directory was recorded against.
That is also why the cross-validation job in CI is informative rather than
blocking when it runs on Linux — see the comment in `.github/workflows/ci.yml`.

The instrumentation behind this section is reproducible: `tools/build_debug.sh`
builds `outguess-pj` from `tools/refbuild/jpg_dbg.c`, which prints the `LAYOUT`
line above, the `PSLOG` trace of every `preserve_single` call and the `INCA`
trace of every `dctadjust` increment.

---

## 2. `steg_adjust_errors` writes past two fixed-size arrays

`src/outguess.c`:

```c
int priority[ERRORBITS], detect[ERRORBITS];   /* ERRORBITS == 3 */
...
for (i = j; i < steg_err_cnt; i++) {
    for (n = 0; n < j; n++)
        if (detect[n] < bitmap->detect[steg_err_buf[i]])
            break;
    if (n < j - 1) {
        memmove(detect + n + 1, detect + n, (j - n) * sizeof(int));
        memmove(priority + n + 1, priority + n, (j - n) * sizeof(int));
    }
    ...
}
```

`j == 3` and `n == 1` is reachable (`steg_err_cnt` grows to `CODEBITS == 23`
inside one codeword and `j` is capped at `ERRORBITS - steg_errors`).  The
`memmove` then copies `j - n == 2` ints to `detect + 2`, writing `detect[2]`
and `detect[3]`; `detect[3]` and the matching `priority[3]` are one past the
end of both arrays.

Consequences measured on the reference build with `-e`:

```
6, -258078: Embedding data: 1288 in 12288
Bits embedded: 1384, changed: 517(37.4%)[79.8%], bias: -231460, tot: 12243, skip: 10859
Total bits changed: -230943 (change 517 + bias -231460)
```

`bias` is `steg_mod`, which is decremented by `detect[i]`; once the stack slot
holding `detect`/`priority` has been overwritten, `steg_mod` accumulates
garbage and both the chosen embedding offset and the statistics become
meaningless (note the negative "Total bits changed").  The `-O0` build of
upstream crashes outright in this path.

**This is a genuine upstream bug, and the port does not reproduce it.**  The
Python implementation keeps the same algorithm but bounds every array access,
so it produces the sane numbers instead:

```
176, 448: Embedding data: 1288 in 12288
Bits embedded: 1384, changed: 470(34.0%)[72.5%], bias: -22, tot: 12254, skip: 10870
Total bits changed: 448 (change 470 + bias -22)
```

Because the C output in this mode is not reproducible (it depends on the
compiler's stack layout), `-e` is listed in `KNOWN_DEVIATIONS` in
`validation/cross_validate.py` and validated by *interoperability* instead:
C→Python, Python→C and Python→Python all recover the original message, and
`tests/test_steg.py` covers the error-correction round trip.

One further quirk of the same function is preserved verbatim, because it is
deterministic: the embed branch indexes `bitmap->locked` and `bitmap->bitmap`
with the loop counter `i` instead of `priority[i]`.

### The second dataset inherits the same damage

`steg_adjust_errors()` touches `bitmap->locked` and `bitmap->bitmap` at indices
`0 .. j-1`, i.e. the *first* bits of the carrier — which is exactly where the
first dataset's header lives.  With `-E` the second dataset is therefore able
to clobber the first one, and whether it does depends on how far the corrupted
`detect[]` sort got.  Measured on `tests/data/photo_large.jpg` with a 13-byte
first and a 14-byte second dataset:

* the reference binary embeds the first dataset at seed 185 in both
  implementations (identical, 97 bits changed);
* for the second dataset the reference emits `219, -110694` with
  `bias: -100492` and `Total bits changed: -100270`, while the port reports
  `125, 148` / `bias: 45`;
* reading the reference carrier back returns both datasets; reading the port's
  carrier returns the second dataset but garbage for the first, because the
  bounded implementation happens to clear one header bit the C build did not.

This is the same upstream overflow, so it is covered by the same
`KNOWN_DEVIATIONS` entry; there is no way to make the first dataset survive
reliably, in C or in Python.  The plain (non-ECC) two-dataset flow, which the
man page's `-K`/`-D` example uses by default, is byte-identical and covered by
`tests/test_cli.py::test_two_datasets`.

---

## 3. `TEST_BIT` returns a mask, and `histogram_runlen` compares masks

`src/outguess.h`:

```c
#define TEST_BIT(x,y)  ((x)[(y) / 8] & (1 << ((y) & 7)))
```

The value is `0` or `1 << (y & 7)` — not `0`/`1`.  `histogram_simple()` only
tests truthiness, so it is unaffected, but `src/histogram.c`'s
`histogram_runlen()` compares the raw values:

```c
what = TEST_BIT(data, 0);
for (i = 1; i < bits; i++) {
    if (TEST_BIT(data, i) != what) { ... }
}
```

`what` was captured at index `i - 1` and carries the mask `1 << ((i-1) & 7)`,
while the new value carries `1 << (i & 7)`; the masks differ for every
consecutive pair of indices.  The comparison therefore reports "no change"
only when the current bit is `0` *and* the previous bit was `0`.  Every `1`
terminates a run.

For `tests/data/map_sample_ppm.bin` (a 12288-bit dump with the period-6
pattern `000111`):

| bucket | C reference | naive normalised port |
| --- | --- | --- |
| run length 1 | 6176 | 32 |
| run length 3 | 1985 | 4033 |

`src/outguess/histogram.py` reproduces the masking behaviour on purpose so the
readout matches the C tool byte for byte; `tests/data/hist_sample_ppm.txt` is
the recorded reference output and `tests/test_histogram.py` asserts equality.

Note also that `histogram.c` opens the dump with `fopen(argv[0], "r")` — no
`b`.  On Windows the C tool is therefore unusable for dumps that contain
`0x1A` or `0x0D`; the reference binary used for the golden file is built with
`"rb"` (`tools/build_reference.sh` applies that one-line change).  On POSIX
systems there is no difference, and the Python port always reads binary.

---

## 4. `outguess-extract` is selected by `argv[0]`

```c
if (strchr(argv[0], '/'))
        cp = strrchr(argv[0], '/') + 1;
else
        cp = argv[0];
if (!strcmp("outguess-extract", cp)) { extractonly = 1; ... }
```

The basename is split on a forward slash only.  On Windows `argv[0]` is a
backslash path such as `C:\...\outguess-extract.exe`, so the check never fires
and the binary refuses to run in extraction mode.  The port detects the mode
from the entry point (`outguess.cli:extract_main`) rather than from `argv[0]`,
which is the intended behaviour on POSIX and also works on Windows.  For the
cross-checks the reference binary is invoked with `argv[0]` forced to
`outguess-extract` (`subprocess.run([...], executable=...)`); the dumps are
identical, including for JPEG carriers.

Extraction mode writes `htonl(bits)` followed by `(bits + 7) / 8` bytes, and
then calls `exit(1)` — an upstream oddity that the port mirrors.

One residual difference is unavoidable: the unused high bits of the final dump
byte.  C writes bit by bit into a `malloc`'d buffer that grows 256 bytes at a
time, and `WRITE_BIT` preserves the rest of the byte, so the padding bits come
from uninitialised heap.  For `tests/data/sample.jpg` (5286 bits, 6 significant
bits in the last byte) C emits `0x76` where the port emits `0x36`; the six
significant bits agree.  `tests/test_cli.py` compares the dump bit by bit for
that reason.

---

## 5. Chroma sampling: which upsampler libjpeg picks

`jdmaster.c` (`jinit_upsampler`) selects the method from the sampling factors:

```c
} else if (compptr->h_samp_factor * 2 == cinfo->max_h_samp_factor &&
           compptr->v_samp_factor == cinfo->max_v_samp_factor) {
  if (cinfo->do_fancy_upsampling)
    upsample->methods[ci] = h2v1_fancy_upsample;
```

so a 4:2:2 carrier needs `h2v1_fancy_upsample` and a 4:4:4 carrier needs no
upsampling at all.  Both were confirmed against the reference on 320x240
carriers produced with `tools/refbuild/mk_jpeg.c` (a helper that drives the bundled
libjpeg with explicit `h_samp_factor`/`v_samp_factor`):

| carrier | sampling | result at `-p 75` and `-p 90` |
| --- | --- | --- |
| `tests/data/photo_422.jpg` | 2x1 | byte-identical |
| `tests/data/photo_444.jpg` | 1x1 | byte-identical |
| `tests/data/photo_large.jpg` | 2x2 | byte-identical |

Getting this wrong does not corrupt extraction (retrieval reads the coefficient
bitmap, never the pixels) but it does change the re-compressed carrier, so both
variants are part of the validation matrix.

The fixtures are reproducible from `tests/data/photo_large.jpg`:

```console
$ python -c "from outguess.jpeg.codec import read_jpeg; \
    i = read_jpeg(open('tests/data/photo_large.jpg','rb')); \
    open('photo.ppm','wb').write(b'P6\n%d %d\n255\n' % (i.x, i.y) + bytes(i.img))"
$ tools/build_reference.sh            # also builds _reference/mk_jpeg*.exe
$ _reference/mk_jpeg.exe      photo.ppm photo_422.jpg 88 2 1
$ _reference/mk_jpeg.exe      photo.ppm photo_444.jpg 88 1 1
$ _reference/mk_jpeg_gray.exe photo.ppm photo_gray.jpg 88
```

Single-component carriers are a dead end in upstream as well: the compressor
always declares `JCS_YCbCr` with three components, so libjpeg aborts with
`Bogus input colorspace` for a greyscale JPEG or a PGM destination.  The port
raises `ValueError("Bogus input colorspace")` from
`codec._build_planes_from_rgb` so the diagnostic matches.

Progressive JPEG is the one thing that is **not** ported yet.  libjpeg 6b
decodes it (note `jdphuff.c` in the file list), and the reference binary
embeds into `photo_prog.jpg` without complaint, so this is a real gap in the
port rather than an upstream restriction.  `codec.read_jpeg` raises
`ValueError("progressive JPEG is not supported by OutGuess")` instead of
silently producing wrong coefficients.

---

## 6. Numeric details worth knowing

* `maxcorrect` is declared `size_t` but assigned the `int` result of
  `preserve_jpg()`.  A `-1` return ("can not calculate estimate") becomes
  `SIZE_MAX`, which is truthy, so the "Correctable message size" line is
  printed with `18446744073709551615` — the port reproduces that via
  `res & ((1 << 64) - 1)`.
* Both the percentage on that line and the coefficient-frequency scaling in
  `preserve_jpg` are computed in **single precision**
  (`(float)100 * maxcorrect / bits` and
  `dctfreq[i] / ((float)bits / DCTFREQRANGE)`).  `src/outguess/_compat.py`
  provides `f32`, `f32_add/sub/mul/div` and `c_div` for exactly this reason.
* MinGW prints a NaN as `-nan(ind)`; the port prints `nan` and
  `validation/cross_validate.py` normalises the two before comparing.
