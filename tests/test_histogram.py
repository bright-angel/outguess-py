"""``histogram`` helper: statistical readout of an extracted bitmap."""

from __future__ import annotations

from pathlib import Path

import pytest

from outguess import histogram

DATA = Path(__file__).resolve().parent / "data"


def test_analyze_matches_c_reference_output() -> None:
    """Byte-for-byte parity with the output of the reference ``histogram``."""
    expected = (DATA / "hist_sample_ppm.txt").read_text(encoding="utf-8")
    assert histogram.analyze(str(DATA / "map_sample_ppm.bin")) == expected


def test_simple_histogram_counts() -> None:
    # 0b1010_0110 -> four ones out of eight bits.
    text = histogram.histogram_simple(bytes([0b10100110]), 8)
    assert "Bits:      8" in text
    assert "One:       4" in text
    assert "Zero:      4" in text


def test_runlen_keeps_upstream_masking_quirk() -> None:
    """Runs only continue while the bit is 0 (see the module docstring)."""
    # Bits 1,1,1,1 followed by 0: the three leading 1s each end a run.
    buckets = histogram.histogram_runlen(bytes([0b00001111]), 8).splitlines()
    one = int(buckets[0].split(",")[0].split(":")[1])
    assert one == 4, buckets


def test_missing_file_raises() -> None:
    with pytest.raises(OSError):
        histogram.analyze("does-not-exist.bin")


def test_truncated_bitmap_raises() -> None:
    with pytest.raises(ValueError):
        histogram.analyze(str(DATA / "message.txt"))


def test_main_requires_one_argument(capsys: pytest.CaptureFixture[str]) -> None:
    assert histogram.main([]) == 1
    assert capsys.readouterr().err


def test_main_prints_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    assert histogram.main([str(DATA / "map_sample_ppm.bin")]) == 0
    assert "Bits:" in capsys.readouterr().out
