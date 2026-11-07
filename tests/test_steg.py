"""End-to-end steganography against golden carriers produced by the C build."""

from __future__ import annotations

import os
import shutil
from contextlib import contextmanager
from pathlib import Path

from outguess.cli import main

DATA = Path(__file__).resolve().parent / "data"


@contextmanager
def _cwd(path: Path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _run(tmp_path: Path, *args: str) -> int:
    with _cwd(tmp_path):
        return main(list(args))


def test_ppm_embed_matches_golden(tmp_path: Path) -> None:
    shutil.copy(DATA / "sample.ppm", tmp_path / "in.ppm")
    shutil.copy(DATA / "message.txt", tmp_path / "msg.txt")
    assert _run(tmp_path, "-k", "fixture-key", "-d", "msg.txt", "in.ppm", "out.ppm") == 0
    assert (tmp_path / "out.ppm").read_bytes() == (DATA / "sample_golden.ppm").read_bytes()


def test_ppm_retrieve_roundtrip(tmp_path: Path) -> None:
    shutil.copy(DATA / "sample_golden.ppm", tmp_path / "carrier.ppm")
    assert _run(tmp_path, "-k", "fixture-key", "-r", "carrier.ppm", "msg.txt") == 0
    assert (tmp_path / "msg.txt").read_bytes() == (DATA / "message.txt").read_bytes()


def test_ppm_seed_matches_golden(tmp_path: Path) -> None:
    shutil.copy(DATA / "sample.ppm", tmp_path / "in.ppm")
    shutil.copy(DATA / "message.txt", tmp_path / "msg.txt")
    assert _run(tmp_path, "-s", "5", "-k", "fixture-key", "-d", "msg.txt", "in.ppm", "o.ppm") == 0
    assert (tmp_path / "o.ppm").read_bytes() == (DATA / "sample_seed5_golden.ppm").read_bytes()


def test_ppm_ecc_roundtrip(tmp_path: Path) -> None:
    shutil.copy(DATA / "sample.ppm", tmp_path / "in.ppm")
    shutil.copy(DATA / "message.txt", tmp_path / "msg.txt")
    assert _run(tmp_path, "-e", "-k", "fixture-key", "-d", "msg.txt", "in.ppm", "e.ppm") == 0
    assert _run(tmp_path, "-e", "-k", "fixture-key", "-r", "e.ppm", "back.txt") == 0
    assert (tmp_path / "back.txt").read_bytes() == (DATA / "message.txt").read_bytes()


def test_wrong_key_is_rejected(tmp_path: Path) -> None:
    """A bogus key yields a nonsense length, which the reference rejects."""
    shutil.copy(DATA / "sample_golden.ppm", tmp_path / "carrier.ppm")
    assert _run(tmp_path, "-k", "wrong-key", "-r", "carrier.ppm", "out.bin") != 0


def test_no_foiling_option_matches_golden_baseline(tmp_path: Path) -> None:
    shutil.copy(DATA / "sample.ppm", tmp_path / "in.ppm")
    shutil.copy(DATA / "message.txt", tmp_path / "msg.txt")
    assert _run(tmp_path, "-F-", "-k", "fixture-key", "-d", "msg.txt", "in.ppm", "o.ppm") == 0
    assert _run(tmp_path, "-k", "fixture-key", "-r", "o.ppm", "back.txt") == 0
    assert (tmp_path / "back.txt").read_bytes() == (DATA / "message.txt").read_bytes()


def test_statistics_mode_still_embeds(tmp_path: Path) -> None:
    shutil.copy(DATA / "sample.ppm", tmp_path / "in.ppm")
    shutil.copy(DATA / "message.txt", tmp_path / "msg.txt")
    assert _run(tmp_path, "-t", "-k", "fixture-key", "-d", "msg.txt", "in.ppm", "o.ppm") == 0
    assert _run(tmp_path, "-k", "fixture-key", "-r", "o.ppm", "back.txt") == 0
    assert (tmp_path / "back.txt").read_bytes() == (DATA / "message.txt").read_bytes()


def test_message_too_long_is_rejected(tmp_path: Path) -> None:
    shutil.copy(DATA / "gradient.ppm", tmp_path / "small.ppm")
    (tmp_path / "big.txt").write_bytes(b"x" * 5000)
    assert _run(tmp_path, "-k", "k", "-d", "big.txt", "small.ppm", "o.ppm") != 0


def test_missing_message_file_errors(tmp_path: Path) -> None:
    shutil.copy(DATA / "sample.ppm", tmp_path / "in.ppm")
    assert _run(tmp_path, "-k", "k", "-d", "nope.txt", "in.ppm", "o.ppm") != 0


def test_jpeg_embed_matches_golden(tmp_path: Path) -> None:
    shutil.copy(DATA / "sample.jpg", tmp_path / "in.jpg")
    shutil.copy(DATA / "message.txt", tmp_path / "msg.txt")
    assert _run(tmp_path, "-k", "fixture-key", "-d", "msg.txt", "in.jpg", "out.jpg") == 0
    assert (tmp_path / "out.jpg").read_bytes() == (DATA / "sample_jpeg_golden.jpg").read_bytes()


def test_jpeg_retrieve_roundtrip(tmp_path: Path) -> None:
    shutil.copy(DATA / "sample_jpeg_golden.jpg", tmp_path / "carrier.jpg")
    assert _run(tmp_path, "-k", "fixture-key", "-r", "carrier.jpg", "msg.txt") == 0
    assert (tmp_path / "msg.txt").read_bytes() == (DATA / "message.txt").read_bytes()
