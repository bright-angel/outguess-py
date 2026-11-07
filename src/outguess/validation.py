"""``outguess-validate`` -- run the C cross-validation harness.

The harness itself lives in ``validation/cross_validate.py`` at the root of the
source checkout, because it needs the upstream C tree, the reference binaries
and the fixture carriers in ``tests/data``.  None of that belongs in a wheel,
so this entry point locates the checkout and delegates to the script instead of
duplicating it.

Resolution order:

1. ``$OUTGUESS_VALIDATION`` -- explicit path to ``cross_validate.py``.
2. The nearest ``validation/cross_validate.py`` walking up from this package
   (which finds it when running from a source checkout or an editable install).

All arguments are forwarded, so ``outguess-validate --reference DIR/outguess``
works exactly like the standalone script.  See ``tools/build_reference.sh`` for
building the reference binary.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path
from typing import Optional, Sequence

SCRIPT = "cross_validate.py"


def find_harness(start: Optional[Path] = None) -> Optional[Path]:
    """Return the path to ``validation/cross_validate.py``, if it exists."""
    override = os.environ.get("OUTGUESS_VALIDATION")
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None

    here = (start or Path(__file__)).resolve()
    for directory in [here, *here.parents]:
        candidate = directory / "validation" / SCRIPT
        if candidate.is_file():
            return candidate
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    harness = find_harness()

    if harness is None:
        print(
            "outguess-validate: could not find validation/cross_validate.py\n"
            "Cross-validation needs a source checkout (upstream C tree, "
            "reference binaries and tests/data).\n"
            "Point OUTGUESS_VALIDATION at the script if it lives elsewhere.",
            file=sys.stderr,
        )
        return 2

    # The harness imports nothing from the installed package, but it does want
    # the checkout's src/ on the path for the Python side of every comparison.
    root = harness.parent.parent
    src = root / "src"
    if src.is_dir():
        existing = os.environ.get("PYTHONPATH", "")
        parts = [str(src), *[p for p in existing.split(os.pathsep) if p]]
        os.environ["PYTHONPATH"] = os.pathsep.join(parts)

    sys.argv = [str(harness), *args]
    try:
        runpy.run_path(str(harness), run_name="__main__")
    except SystemExit as exc:  # the harness returns its verdict via exit code
        code = exc.code
        return 0 if code is None else int(code)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
