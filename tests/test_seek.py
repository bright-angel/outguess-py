"""``seek_script``: pick the carrier in a directory with the cheapest embedding."""

from __future__ import annotations

import filecmp
import shutil
from pathlib import Path

import pytest

from outguess import seek as seek_mod
from outguess.cli import run

DATA = Path(__file__).resolve().parent / "data"


@pytest.fixture()
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in ("sample.jpg", "photo_odd.jpg", "photo_large.jpg", "message.txt"):
        shutil.copy(DATA / name, tmp_path / name)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_seek_picks_the_cheapest_carrier(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    best_name, best, worst = seek_mod.seek("*.jpg", "message.txt", "out.jpg", key="k")

    out = capsys.readouterr().out
    assert best_name in {"sample.jpg", "photo_odd.jpg", "photo_large.jpg"}
    assert 0 < best <= worst
    assert f"Best data object was {best_name} with {best}." in out
    assert f"Worst result was {worst}." in out
    # Every carrier was tried and reported.
    for name in ("sample.jpg", "photo_odd.jpg", "photo_large.jpg"):
        assert f"{name} Bits changed" in out

    # ``out.jpg`` must be the embedding of exactly the winning carrier.
    assert (workdir / "out.jpg").exists()
    run(["-k", "k", "-d", "message.txt", best_name, "expected.jpg"])
    assert filecmp.cmp(workdir / "out.jpg", workdir / "expected.jpg", shallow=False)

    # No temporary files survive.
    assert not list(workdir.glob("out.*.jpg"))


def test_seek_keeps_the_previous_best(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A worse second candidate must not overwrite ``out.jpg``."""
    names = sorted(p.name for p in workdir.glob("*.jpg"))
    first = names[0]
    _, first_bits, _ = seek_mod.seek(first, "message.txt", "a.jpg", key="k")
    capsys.readouterr()
    first_copy = workdir / "first.jpg"
    shutil.copy(workdir / "a.jpg", first_copy)

    _, best, _ = seek_mod.seek("*.jpg", "message.txt", "b.jpg", key="k")
    capsys.readouterr()
    assert best <= first_bits
    if abs(best) != first_bits:
        assert (workdir / "b.jpg").exists()


def test_seek_reports_carriers_that_cannot_hold_the_data(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A truncated JPEG makes the decoder fail; seek must skip it quietly.
    (workdir / "tiny.jpg").write_bytes((DATA / "sample.jpg").read_bytes()[:300])
    best_name, best, worst = seek_mod.seek("tiny.jpg", "message.txt", "out.jpg", key="k")
    out = capsys.readouterr().out
    assert "not possible to embed data" in out
    assert best_name == "no name" and best == 0 and worst == 0
    assert not (workdir / "out.jpg").exists()


def test_seek_skips_carriers_too_small_for_the_message(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # sample.jpg holds 5114 bits; 4000 bytes of message need far more.
    (workdir / "big.txt").write_bytes(b"x" * 4000)
    best_name, best, worst = seek_mod.seek("sample.jpg", "big.txt", "out.jpg", key="k")
    out = capsys.readouterr().out
    assert "not possible to embed data" in out
    assert best_name == "no name"
    assert not list(workdir.glob("out.*.jpg"))


def test_main_reports_missing_message(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert seek_mod.main(["*.jpg", "absent.txt"]) == 0
    assert "does not exist" in capsys.readouterr().out


def test_main_runs_with_defaults(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert seek_mod.main([]) == 0
    out = capsys.readouterr().out
    assert "Best data object was" in out
