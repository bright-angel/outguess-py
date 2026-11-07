# OutGuess Python port — cross-validation report

Reference binary: `_reference/outguess.exe`

| carrier | case | bytes | stderr | C→PY | PY→C | status |
| --- | --- | --- | --- | --- | --- | --- |
| sample.ppm | default | same | same | ok | ok | pass |
| sample.ppm | ecc | diff | diff | ok | ok | known |
| sample.ppm | seed7 | same | same | ok | ok | pass |
| sample.ppm | iter8 | same | same | ok | ok | pass |
| sample.ppm | no-foil | same | same | ok | ok | pass |
| sample.ppm | mark | same | same | ok | ok | pass |
| sample.ppm | stats | same | same | ok | ok | pass |
| sample.ppm | derive | same | same | ok | ok | pass |
| sample.ppm | quality90 | same | same | ok | ok | pass |
| sample.ppm | quality100 | same | same | ok | ok | pass |
| large.pnm | default | same | same | ok | ok | pass |
| large.pnm | ecc | diff | diff | ok | ok | known |
| large.pnm | seed7 | same | same | ok | ok | pass |
| large.pnm | iter8 | same | same | ok | ok | pass |
| large.pnm | no-foil | same | same | ok | ok | pass |
| large.pnm | mark | same | same | ok | ok | pass |
| large.pnm | stats | same | same | ok | ok | pass |
| large.pnm | derive | same | same | ok | ok | pass |
| large.pnm | quality90 | same | same | ok | ok | pass |
| large.pnm | quality100 | same | same | ok | ok | pass |
| sample.jpg | default | same | same | ok | ok | pass |
| sample.jpg | ecc | diff | diff | ok | ok | known |
| sample.jpg | seed7 | same | same | ok | ok | pass |
| sample.jpg | iter8 | same | same | ok | ok | pass |
| sample.jpg | no-foil | same | same | ok | ok | pass |
| sample.jpg | mark | same | same | ok | ok | pass |
| sample.jpg | stats | same | same | ok | ok | pass |
| sample.jpg | derive | same | same | ok | ok | pass |
| sample.jpg | quality90 | same | same | ok | ok | pass |
| sample.jpg | quality100 | same | same | ok | ok | pass |
| photo_odd.jpg | default | same | same | ok | ok | pass |
| photo_odd.jpg | ecc | diff | diff | ok | ok | known |
| photo_odd.jpg | seed7 | same | same | ok | ok | pass |
| photo_odd.jpg | iter8 | same | same | ok | ok | pass |
| photo_odd.jpg | no-foil | same | same | ok | ok | pass |
| photo_odd.jpg | mark | same | same | ok | ok | pass |
| photo_odd.jpg | stats | same | same | ok | ok | pass |
| photo_odd.jpg | derive | same | same | ok | ok | pass |
| photo_odd.jpg | quality90 | same | same | ok | ok | pass |
| photo_odd.jpg | quality100 | same | same | ok | ok | pass |
| photo_large.jpg | default | same | same | ok | ok | pass |
| photo_large.jpg | ecc | diff | diff | ok | ok | known |
| photo_large.jpg | seed7 | same | same | ok | ok | pass |
| photo_large.jpg | iter8 | same | same | ok | ok | pass |
| photo_large.jpg | no-foil | same | same | ok | ok | pass |
| photo_large.jpg | mark | same | same | ok | ok | pass |
| photo_large.jpg | stats | same | same | ok | ok | pass |
| photo_large.jpg | derive | same | same | ok | ok | pass |
| photo_large.jpg | quality90 | same | same | ok | ok | pass |
| photo_large.jpg | quality100 | same | same | ok | ok | pass |
| photo_422.jpg | default | same | same | ok | ok | pass |
| photo_422.jpg | ecc | diff | diff | ok | ok | known |
| photo_422.jpg | seed7 | same | same | ok | ok | pass |
| photo_422.jpg | iter8 | same | same | ok | ok | pass |
| photo_422.jpg | no-foil | same | same | ok | ok | pass |
| photo_422.jpg | mark | same | same | ok | ok | pass |
| photo_422.jpg | stats | same | same | ok | ok | pass |
| photo_422.jpg | derive | same | same | ok | ok | pass |
| photo_422.jpg | quality90 | same | same | ok | ok | pass |
| photo_422.jpg | quality100 | same | same | ok | ok | pass |
| photo_444.jpg | default | same | same | ok | ok | pass |
| photo_444.jpg | ecc | diff | diff | ok | ok | known |
| photo_444.jpg | seed7 | same | same | ok | ok | pass |
| photo_444.jpg | iter8 | same | same | ok | ok | pass |
| photo_444.jpg | no-foil | same | same | ok | ok | pass |
| photo_444.jpg | mark | same | same | ok | ok | pass |
| photo_444.jpg | stats | same | same | ok | ok | pass |
| photo_444.jpg | derive | same | same | ok | ok | pass |
| photo_444.jpg | quality90 | same | same | ok | ok | pass |
| photo_444.jpg | quality100 | same | same | ok | ok | pass |
| gradient.ppm | default | same | same | ok | ok | pass |
| gradient.ppm | ecc | diff | diff | ok | ok | known |
| gradient.ppm | seed7 | same | same | ok | ok | pass |
| gradient.ppm | iter8 | same | same | ok | ok | pass |
| gradient.ppm | no-foil | same | same | ok | ok | pass |
| gradient.ppm | mark | same | same | ok | ok | pass |
| gradient.ppm | stats | same | same | ok | ok | pass |
| gradient.ppm | derive | same | same | ok | ok | pass |
| gradient.ppm | quality90 | same | same | ok | ok | pass |
| gradient.ppm | quality100 | same | same | ok | ok | pass |

## Summary

- pass: 72
- known: 8
- edge: 0
- fail: 0

## Auxiliary tools

`outguess-extract` bitmap dumps and the `histogram` readout of the
reference dump, compared bit for bit.

| carrier | bitmap dump | histogram |
| --- | --- | --- |
| sample.ppm | same | same |
| large.pnm | same | same |
| sample.jpg | same (trailing padding bits differ) | same |
| photo_odd.jpg | same | same |
| photo_large.jpg | same | same |
| photo_422.jpg | same (trailing padding bits differ) | same |
| photo_444.jpg | same | same |
| gradient.ppm | same | same |

## Notes

- `known`: the reference implementation has undefined behaviour in this
  mode (out-of-bounds writes in `steg_adjust_errors`), so byte equality is
  not achievable.  Mutual extraction is verified instead.
- `edge`: the message occupies the very last bitmap bit; the reference
  reads past the end of its bitmap buffer there, so the final byte is
  undefined in C as well.
- Bitmap dumps can differ in the unused high bits of their final byte:
  the C dumper writes into a `malloc`'d buffer whose tail is never
  initialised.  Only the significant bits are compared.

See `validation/NOTES.md` for the measurements behind each quirk.
