"""``seek_script`` equivalent: pick the carrier with the cheapest embedding."""

from __future__ import annotations

import glob
import io
import os
import re
import sys
from contextlib import redirect_stderr
from typing import Optional, Sequence

_TOTAL = re.compile(r"^Total bits changed:\s+(-?\d+)", re.MULTILINE)


def seek(
    pattern: str = "*.jpg",
    message: str = "message.txt",
    output: str = "out.jpg",
    *,
    key: Optional[str] = None,
    extra_args: Sequence[str] = (),
    directory: str = ".",
) -> tuple[str, int, int]:
    """Embed ``message`` into every matching carrier, keep the best result."""
    from .cli import run

    names = sorted(
        os.path.basename(p)
        for p in glob.glob(os.path.join(directory, pattern))
    )
    best = 0
    worst = 0
    best_name = "no name"

    for name in names:
        src = os.path.join(directory, name)
        tmp = os.path.join(directory, f"out.{os.getpid()}.{os.path.splitext(name)[1] or 'jpg'}")
        args = []
        if key:
            args += ["-k", key]
        args += ["-d", message, src, tmp]
        args += list(extra_args)
        buffer = io.StringIO()
        text = ""
        try:
            with redirect_stderr(buffer):
                run(args)
            text = buffer.getvalue()
        except (ValueError, OSError):
            # The shell script only looks at "Total bits changed" in the
            # output, so any failure counts as "not possible".
            text = ""
        match = _TOTAL.search(text)
        if not match:
            print(f"{name} not possible to embed data")
            if os.path.exists(tmp):
                os.unlink(tmp)
            continue

        result = int(match.group(1))
        print(f"{name} Bits changed {result}")
        if worst == 0 or result > worst:
            worst = result
        if best == 0 or result < best:
            best = result
            best_name = name
            if os.path.exists(output):
                os.unlink(output)
            os.replace(tmp, output)
            print(f"NEW best image: {name}")
        elif os.path.exists(tmp):
            os.unlink(tmp)

    print(f"Best data object was {best_name} with {best}. Worst result was {worst}.")
    return best_name, best, worst


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    directory = "."
    pattern = "*.jpg"
    message = "message.txt"
    output = "out.jpg"
    if args:
        pattern = args[0]
    if len(args) > 1:
        message = args[1]
    if len(args) > 2:
        output = args[2]
    if not os.path.exists(message):
        print(f"The file {message} does not exist")
        return 0
    seek(pattern, message, output, directory=directory)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
