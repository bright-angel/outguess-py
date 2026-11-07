# Contributing

Thanks for taking a look. This project has an unusual constraint that shapes
everything else: **the output must stay byte-for-byte identical to the C
program**, including its diagnostics. That goal is what the tests and the
validation harness exist to protect.

## Getting set up

```console
$ python -m pip install -e '.[dev]'
$ pytest                      # 98 tests, no C toolchain needed
$ python -m ruff check src tests validation tools
```

The test suite compares against recorded fixtures, so you can work on the port
without building anything in C.

## Working on bit-exactness

To change anything that touches the steganography path, you need the reference
implementation:

```console
$ tools/fetch_upstream.sh     # clones OutGuess 0.4 into _upstream/
$ tools/build_reference.sh    # builds the oracle binaries into _reference/
$ outguess-validate           # writes validation/REPORT.md and report.json
```

`build_reference.sh` uses `$CC`, then `cc`, then `python -m ziglang cc` — the
last one installs with `pip install ziglang` and needs no system toolchain, so
a reference build is possible even on a machine without a C compiler.

`tools/build_debug.sh` additionally builds the instrumented binaries
(`outguess-pj`, `outguess-smp`, `outguess-dct`, `jdec`) that were used to
measure the internals described in `validation/NOTES.md`. They are only needed
to reproduce those measurements.

## Ground rules

1. **Never "fix" an upstream quirk.** Some behaviours look like bugs and are
   bugs — `histogram_runlen` compares masked bits, `preserve_jpg` writes to an
   alignment cell — but reproducing them is the point. If a quirk has to be
   modelled, document *why* and *how it was measured* in `validation/NOTES.md`
   and add a test that would fail if the quirk were silently corrected.
2. **Keep the C shape.** Modules mirror translation units, and function names
   mirror C function names, so that a reader can diff the two side by side.
   `outguess._compat` exists to make C integer and float semantics explicit
   (`i8`, `u32`, `f32_div`, `BitArray`); use it instead of `ctypes` tricks.
3. **No new runtime dependencies.** The JPEG codec, the cipher and the error
   correcting code are part of the deliverable.
4. **Fixtures are recorded, not generated at test time.** `tests/data` holds
   carriers, golden carriers and vectors dumped from C. Regenerating them by
   hand is documented in `validation/NOTES.md`; always state in the pull
   request how a regenerated fixture was produced.

## Pull requests

- `pytest` and `ruff check src tests validation tools` must pass.
- If you touched an embedding path, run `outguess-validate` and include the
  summary line (`pass=…, known=…, edge=0, fail=0`) in the description.
- New behaviour needs a test; changed behaviour needs a line in `CHANGELOG.md`.
- Keep commits focused: a fix, its test and its documentation belong together.

## Licensing

By contributing you agree that your changes are distributed under the same
BSD-style licence as the rest of the project (see `LICENSE`), which is also the
licence of the original OutGuess.
