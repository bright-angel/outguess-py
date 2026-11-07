#!/usr/bin/env python3
"""Cross-validate the Python port against the reference C implementation.

The harness drives both binaries over a matrix of carriers, options and keys
and compares

* the produced carrier bytes (bit-exactness),
* the diagnostic output on stderr (after normalising the program name), and
* mutual extractability in both directions (C -> Python, Python -> C).

Usage::

    python validation/cross_validate.py [--reference PATH] [--report FILE]

The reference binary defaults to ``$OUTGUESS_REF`` or ``_reference/outguess``
(``.exe`` on Windows).  Building it is described in ``tools/build_reference.sh``.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
DATA = ROOT / "tests" / "data"

#: Cases where the reference binary itself has undefined behaviour and can
#: therefore not be matched bit for bit.  They are reported separately.
KNOWN_DEVIATIONS = {
    "ecc": "upstream steg_adjust_errors() writes past `priority[]`/`detect[]`",
}

EDGE_CASES = {
    "tail": "message reaches the last bitmap bit; C reads past the buffer",
}


@dataclass
class Case:
    """One embedding scenario."""

    name: str
    args: list[str]
    message: str = "message.txt"


@dataclass
class Outcome:
    carrier: str
    case: str
    bytes_equal: bool | None = None
    stderr_equal: bool | None = None
    c_to_py: bool | None = None
    py_to_c: bool | None = None
    note: str = ""
    stderr_diff: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.bytes_equal and self.c_to_py and self.py_to_c:
            return "pass"
        if self.case in KNOWN_DEVIATIONS and self.c_to_py and self.py_to_c:
            return "known"
        if self.note in EDGE_CASES.values():
            return "edge"
        return "fail"


def _norm_stderr(text: str, prog: str, other: str) -> list[str]:
    """Normalise the diagnostics so two different binaries compare equal."""
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        line = line.replace(str(prog), "PROG").replace(str(other), "PROG")
        line = line.replace("-nan(ind)", "nan").replace("-nan", "nan")
        line = line.replace("  ", " ")
        lines.append(line.rstrip())
    return [line for line in lines if line]


def _run(cmd: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, env=env)


def _prepare(work: Path, carrier: Path, message: Path) -> tuple[Path, Path]:
    for sub in ("c", "p"):
        target = work / sub
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(carrier, target / carrier.name)
        shutil.copy(message, target / "message.txt")
    return work / "c", work / "p"


def _compare_case(
    ref: Path,
    work: Path,
    carrier: Path,
    case: Case,
    env: dict[str, str],
) -> Outcome:
    cdir, pdir = _prepare(work, carrier, DATA / case.message)
    out_name = carrier.stem + "_out" + carrier.suffix
    base = case.args + ["-d", "message.txt", carrier.name, out_name]

    c_run = _run([str(ref)] + base, cdir, env)
    p_run = _run([sys.executable, "-m", "outguess"] + base, pdir, env)

    outcome = Outcome(carrier=carrier.name, case=case.name)
    c_out, p_out = cdir / out_name, pdir / out_name

    if c_run.returncode != p_run.returncode:
        outcome.note = f"exit {c_run.returncode} vs {p_run.returncode}"

    if c_out.exists() and p_out.exists():
        outcome.bytes_equal = filecmp.cmp(c_out, p_out, shallow=False)
    else:
        outcome.bytes_equal = None

    c_err = _norm_stderr(c_run.stderr.decode("utf-8", "replace"), ref, "outguess")
    p_err = _norm_stderr(p_run.stderr.decode("utf-8", "replace"), ref, "outguess")
    outcome.stderr_equal = c_err == p_err
    if not outcome.stderr_equal:
        outcome.stderr_diff = [
            f"C: {a!r} != PY: {b!r}"
            for a, b in zip(c_err, p_err)
            if a != b
        ][:4]

    # Mutual extraction, using the very same option set.
    if c_out.exists():
        _run(
            [sys.executable, "-m", "outguess"] + case.args + ["-r", out_name, "back.txt"],
            cdir,
            env,
        )
        back = cdir / "back.txt"
        outcome.c_to_py = back.exists() and filecmp.cmp(back, DATA / case.message, shallow=False)
    if p_out.exists():
        _run([str(ref)] + case.args + ["-r", out_name, "back.txt"], pdir, env)
        back = pdir / "back.txt"
        outcome.py_to_c = back.exists() and filecmp.cmp(back, DATA / case.message, shallow=False)

    return outcome


def _build_carriers(work: Path, env: dict[str, str], ref: Path) -> list[Path]:
    """Create the carrier set: PPM/PGM inputs plus JPEGs of every sampling."""
    carriers: list[Path] = []
    for name in (
        "sample.ppm",
        "large.pnm",
        "sample.jpg",
        "photo_odd.jpg",
        "photo_large.jpg",
        "photo_422.jpg",
        "photo_444.jpg",
        "gradient.ppm",
    ):
        shutil.copy(DATA / name, work / name)
        carriers.append(work / name)
    return carriers


# ---------------------------------------------------------------------------
# Auxiliary tools: outguess-extract bitmap dumps and the histogram readout
# ---------------------------------------------------------------------------


def _sibling(ref: Path, name: str) -> Path | None:
    """Locate a reference binary that sits next to ``outguess``."""
    suffix = ".exe" if ref.suffix.lower() == ".exe" else ""
    candidate = ref.parent / (name + suffix)
    return candidate if candidate.exists() else None


def _dump_via_c(extract: Path, src: Path, dst: Path, cwd: Path, env: dict[str, str]) -> bool:
    # ``outguess-extract`` is selected by argv[0], so force the basename: the
    # upstream check splits on '/' only and never fires for a Windows path.
    cmd = ["outguess-extract", str(src), str(dst)]
    proc = subprocess.run(cmd, executable=str(extract), cwd=str(cwd), capture_output=True, env=env)
    return proc.returncode in (0, 1) and dst.exists()


def _dump_via_py(src: Path, dst: Path, cwd: Path, env: dict[str, str]) -> bool:
    code = (
        "import sys;from outguess.cli import run;"
        f"sys.exit(run([{str(src)!r},{str(dst)!r}], extract_only=True))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=str(cwd), capture_output=True, env=env
    )
    return proc.returncode in (0, 1) and dst.exists()


def _same_bits(a: bytes, b: bytes) -> tuple[bool, str]:
    """Compare two bitmap dumps bit by bit, ignoring the padding bits."""
    if len(a) != len(b):
        return False, f"size {len(a)} vs {len(b)}"
    bits = int.from_bytes(a[:4], "big")
    if a[:4] != b[:4]:
        return False, f"bit count {bits} vs {int.from_bytes(b[:4], 'big')}"
    whole, rem = divmod(bits, 8)
    if a[4 : 4 + whole] != b[4 : 4 + whole]:
        return False, "payload bytes differ"
    if rem:
        mask = (1 << rem) - 1
        if (a[4 + whole] & mask) != (b[4 + whole] & mask):
            return False, "trailing bits differ"
        if a[4 + whole] != b[4 + whole]:
            return True, "trailing padding bits differ"
    return True, ""


def _check_aux_tools(
    ref: Path, work: Path, carriers: list[Path], env: dict[str, str]
) -> list[dict[str, object]]:
    """Cross-check ``outguess-extract`` and ``histogram`` carrier by carrier."""
    extract = _sibling(ref, "outguess-extract")
    # Prefer the binary-mode histogram build; text mode truncates dumps on
    # Windows (see validation/NOTES.md).
    hist = _sibling(ref, "histogram_bin") or _sibling(ref, "histogram")
    results: list[dict[str, object]] = []
    if extract is None:
        return results

    probes = work / "aux"
    probes.mkdir(parents=True, exist_ok=True)
    for carrier in carriers:
        src = probes / carrier.name
        shutil.copy(carrier, src)
        c_dump = probes / (carrier.stem + ".c.bin")
        p_dump = probes / (carrier.stem + ".p.bin")
        entry: dict[str, object] = {"carrier": carrier.name}

        if not _dump_via_c(extract, src, c_dump, probes, env):
            entry["dump"] = "c-failed"
            results.append(entry)
            continue
        if not _dump_via_py(src, p_dump, probes, env):
            entry["dump"] = "py-failed"
            results.append(entry)
            continue

        same, note = _same_bits(c_dump.read_bytes(), p_dump.read_bytes())
        entry["dump"] = "same" if same else "diff"
        if note:
            entry["dump_note"] = note

        if hist is not None:
            c_hist = subprocess.run(
                [str(hist), str(c_dump)], cwd=str(probes), capture_output=True, env=env
            ).stdout
            p_hist = subprocess.run(
                [sys.executable, "-m", "outguess.histogram", str(c_dump)],
                cwd=str(probes),
                capture_output=True,
                env=env,
            ).stdout
            entry["histogram"] = "same" if c_hist == p_hist else "diff"
        results.append(entry)
    return results


CASES = [
    Case("default", ["-k", "matrix-key"]),
    Case("ecc", ["-e", "-k", "matrix-key"]),
    Case("seed7", ["-s", "7", "-k", "matrix-key"]),
    Case("iter8", ["-i", "8", "-k", "matrix-key"]),
    Case("no-foil", ["-F-", "-k", "matrix-key"]),
    Case("mark", ["-m", "-k", "matrix-key"]),
    Case("stats", ["-t", "-k", "matrix-key"]),
    Case("derive", ["-x", "3", "-k", "matrix-key"]),
    Case("quality90", ["-p", "90", "-k", "matrix-key"]),
    Case("quality100", ["-p", "100", "-k", "matrix-key"]),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--reference",
        default=os.environ.get(
            "OUTGUESS_REF",
            str(ROOT / "_reference" / ("outguess.exe" if os.name == "nt" else "outguess")),
        ),
    )
    parser.add_argument("--report", default=str(ROOT / "validation" / "REPORT.md"))
    parser.add_argument("--json", default=str(ROOT / "validation" / "report.json"))
    parser.add_argument("--keep", action="store_true", help="keep the scratch tree")
    args = parser.parse_args(argv)

    ref = Path(args.reference)
    if not ref.exists():
        print(f"reference binary not found: {ref}", file=sys.stderr)
        print("build it with tools/build_reference.sh", file=sys.stderr)
        return 2

    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env["PYTHONIOENCODING"] = "utf-8"

    scratch = Path(tempfile.mkdtemp(prefix="outguess-xval-"))
    aux: list[dict[str, object]] = []
    try:
        carriers = _build_carriers(scratch, env, ref)
        outcomes: list[Outcome] = []
        for carrier in carriers:
            for case in CASES:
                work = scratch / "runs" / f"{carrier.name}-{case.name}"
                work.mkdir(parents=True, exist_ok=True)
                outcomes.append(_compare_case(ref, work, carrier, case, env))
                last = outcomes[-1]
                print(
                    f"{last.carrier:14s} {last.case:11s} "
                    f"bytes={'same' if last.bytes_equal else 'diff'!s:4s} "
                    f"stderr={'same' if last.stderr_equal else 'diff'!s:4s} "
                    f"C->PY={'ok' if last.c_to_py else 'bad'!s:3s} "
                    f"PY->C={'ok' if last.py_to_c else 'bad'!s:3s} "
                    f"{'- ' + last.status}"
                )

        print()
        aux = _check_aux_tools(ref, scratch, carriers, env)
        for entry in aux:
            print(
                f"{entry['carrier']:14s} extract={'same' if entry.get('dump') == 'same' else str(entry.get('dump'))!s:11s} "
                f"histogram={entry.get('histogram', 'n/a')!s:5s}"
            )
    finally:
        if not args.keep:
            shutil.rmtree(scratch, ignore_errors=True)

    counts = {"pass": 0, "known": 0, "edge": 0, "fail": 0}
    for outcome in outcomes:
        counts[outcome.status] += 1

    Path(args.json).write_text(
        json.dumps(
            {
                "reference": _display_path(ref),
                "counts": counts,
                "outcomes": [o.__dict__ for o in outcomes],
                "auxiliary": aux,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    _write_report(Path(args.report), ref, outcomes, counts, aux)
    print()
    print("summary:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    aux_ok = True
    if aux:
        dump_ok = sum(1 for e in aux if e.get("dump") == "same")
        hist_ok = sum(1 for e in aux if e.get("histogram") == "same")
        aux_ok = dump_ok == len(aux) and hist_ok in (len(aux), 0)
        print(f"auxiliary: extract={dump_ok}/{len(aux)} histogram={hist_ok}/{len(aux)}")
    print(f"report: {args.report}")
    return 0 if counts["fail"] == 0 and aux_ok else 1


def _display_path(path: Path) -> str:
    """Render *path* relative to the checkout when it lives inside it.

    Keeps the committed report free of the absolute path of whoever ran it.
    """
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _write_report(
    path: Path,
    ref: Path,
    outcomes: list[Outcome],
    counts: dict[str, int],
    aux: list[dict[str, object]] | None = None,
) -> None:
    shown = _display_path(ref)
    lines = [
        "# OutGuess Python port — cross-validation report",
        "",
        f"Reference binary: `{shown}`",
        "",
        "| carrier | case | bytes | stderr | C→PY | PY→C | status |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for o in outcomes:
        lines.append(
            "| {carrier} | {case} | {b} | {s} | {c} | {p} | {st} |".format(
                carrier=o.carrier,
                case=o.case,
                b="same" if o.bytes_equal else "diff",
                s="same" if o.stderr_equal else "diff",
                c="ok" if o.c_to_py else "bad",
                p="ok" if o.py_to_c else "bad",
                st=o.status,
            )
        )
    lines += [
        "",
        "## Summary",
        "",
        *[f"- {key}: {value}" for key, value in counts.items()],
    ]
    if aux:
        lines += [
            "",
            "## Auxiliary tools",
            "",
            "`outguess-extract` bitmap dumps and the `histogram` readout of the",
            "reference dump, compared bit for bit.",
            "",
            "| carrier | bitmap dump | histogram |",
            "| --- | --- | --- |",
        ]
        for entry in aux:
            note = entry.get("dump_note") or entry.get("dump") or ""
            lines.append(
                f"| {entry['carrier']} | "
                f"{entry.get('dump', 'n/a')}"
                f"{' (' + str(note) + ')' if note and note != entry.get('dump') else ''} | "
                f"{entry.get('histogram', 'n/a')} |"
            )
    lines += [
        "",
        "## Notes",
        "",
        "- `known`: the reference implementation has undefined behaviour in this",
        "  mode (out-of-bounds writes in `steg_adjust_errors`), so byte equality is",
        "  not achievable.  Mutual extraction is verified instead.",
        "- `edge`: the message occupies the very last bitmap bit; the reference",
        "  reads past the end of its bitmap buffer there, so the final byte is",
        "  undefined in C as well.",
        "- Bitmap dumps can differ in the unused high bits of their final byte:",
        "  the C dumper writes into a `malloc`'d buffer whose tail is never",
        "  initialised.  Only the significant bits are compared.",
        "",
        "See `validation/NOTES.md` for the measurements behind each quirk.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
