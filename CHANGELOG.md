# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The version number tracks the upstream release this port reproduces.

## [0.4.0] - 2026-11-07

First public release: a complete port of OutGuess 0.4 to Python 3, with no
third-party runtime dependencies.

### Added

- `outguess` — embed and retrieve, with the full upstream option set
  (`-h -s/S -i/I -k/K -d/D -e/E -p -r -x -m -t -F[+-]`), including the
  two-dataset and key-derivation modes.
- `outguess-extract` — dump the raw bit plane of a carrier.
- `outguess-histogram` — run-length and bias statistics over a bit plane.
- `outguess-seek` — try every carrier matching a glob, keep the cheapest
  embedding (a port of upstream's `seek_script`).
- `outguess-validate` — run the C cross-validation harness from a checkout.
- Pure-Python JPEG codec reproducing the bundled libjpeg 6b path used by
  OutGuess: integer ISLOW DCT, quality-scaled quantisation tables, standard
  Huffman tables, 4:2:0 / 4:2:2 / 4:4:4 sampling with libjpeg's fancy
  upsampling, and the `steg_use_bit` coefficient filter.
- Pure-Python ARC4, (23,12,7) Golay code and adaptive bit iterator, each
  checked against vectors dumped from the C implementation.
- `validation/` — a harness that compares the port against the C program over
  eight carriers and ten option sets, plus `validation/NOTES.md`, which records
  the upstream undefined behaviour the port has to model.

### Compatibility

- PNM carriers: byte-identical output and identical diagnostics for every
  option combination in the matrix.
- JPEG carriers: byte-identical re-compression at quality 75, 90 and 100 for
  4:2:0, 4:2:2 and 4:4:4 sources, including odd image dimensions.
- Carriers written by either implementation can be read by the other.

### Known limitations

- `-e` / `-E` (Golay error-correcting encoding) cannot be byte-identical:
  upstream's `steg_adjust_errors()` writes past two stack arrays, so the C
  statistics are undefined behaviour. The port keeps the algorithm with bounds
  checking; the carriers remain interoperable in all four directions.
- Progressive JPEG carriers are not supported yet, although the C tool decodes
  them through libjpeg.

[0.4.0]: https://github.com/OWNER/outguess-py/releases/tag/v0.4.0
