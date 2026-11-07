"""Command line front-end behaviour."""

from __future__ import annotations

import os
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest

from outguess.cli import extract_main, main

DATA = Path(__file__).resolve().parent / "data"


@contextmanager
def _cwd(path: Path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def test_usage_exits_with_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 1
    err = capsys.readouterr().err
    assert "OutGuess 0.4" in err
    assert "-[kK] <key>" in err


def test_help_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["-h"]) == 0
    assert "usage" in capsys.readouterr().err.lower()


def test_embed_and_retrieve(tmp_path: Path) -> None:
    shutil.copy(DATA / "sample.ppm", tmp_path / "in.ppm")
    shutil.copy(DATA / "message.txt", tmp_path / "msg.txt")
    with _cwd(tmp_path):
        assert main(["-k", "cli-key", "-d", "msg.txt", "in.ppm", "out.ppm"]) == 0
        assert main(["-k", "cli-key", "-r", "out.ppm", "back.txt"]) == 0
    assert (tmp_path / "back.txt").read_bytes() == (DATA / "message.txt").read_bytes()


def test_default_key_is_accepted(tmp_path: Path) -> None:
    shutil.copy(DATA / "sample.ppm", tmp_path / "in.ppm")
    shutil.copy(DATA / "message.txt", tmp_path / "msg.txt")
    with _cwd(tmp_path):
        assert main(["-d", "msg.txt", "in.ppm", "out.ppm"]) == 0
        assert main(["-r", "out.ppm", "back.txt"]) == 0
    assert (tmp_path / "back.txt").read_bytes() == (DATA / "message.txt").read_bytes()


def test_extract_mode_writes_bitmap(tmp_path: Path) -> None:
    shutil.copy(DATA / "sample.ppm", tmp_path / "in.ppm")
    with _cwd(tmp_path):
        # ``outguess-extract`` mirrors the reference, which exits with 1.
        assert extract_main(["in.ppm", "map.bin"]) == 1
    raw = (tmp_path / "map.bin").read_bytes()
    assert int.from_bytes(raw[:4], "big") == 64 * 64 * 3
    assert len(raw) == 4 + (64 * 64 * 3 + 7) // 8


def test_extract_mode_matches_reference_bitmap(tmp_path: Path) -> None:
    shutil.copy(DATA / "sample.ppm", tmp_path / "in.ppm")
    with _cwd(tmp_path):
        # ``outguess-extract`` mirrors the reference, which exits with 1.
        assert extract_main(["in.ppm", "map.bin"]) == 1
    assert (tmp_path / "map.bin").read_bytes() == (DATA / "map_sample_ppm.bin").read_bytes()


def test_unknown_option_fails(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["-Q"]) != 0
    assert "option" in capsys.readouterr().err.lower()


def test_two_datasets(tmp_path: Path) -> None:
    shutil.copy(DATA / "sample.ppm", tmp_path / "in.ppm")
    (tmp_path / "a.txt").write_bytes(b"first dataset")
    (tmp_path / "b.txt").write_bytes(b"second dataset")
    with _cwd(tmp_path):
        assert (
            main(
                [
                    "-k", "k1", "-d", "a.txt",
                    "-K", "k2", "-D", "b.txt",
                    "in.ppm", "out.ppm",
                ]
            )
            == 0
        )
        assert main(["-k", "k1", "-r", "out.ppm", "r1.txt"]) == 0
        assert main(["-k", "k2", "-r", "out.ppm", "r2.txt"]) == 0
    assert (tmp_path / "r1.txt").read_bytes() == b"first dataset"
    assert (tmp_path / "r2.txt").read_bytes() == b"second dataset"

