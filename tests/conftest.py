"""Shared fixtures for the OutGuess Python port test-suite.

The golden files under ``tests/data`` were produced by the reference C
implementation (OutGuess 0.4 built from the upstream tarball) and act as the
oracle for bit-exactness.  Regenerating them requires the C binary; see
``tools/build_reference.sh``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent / "data"
VECTORS = DATA / "vectors"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return DATA


@pytest.fixture(scope="session")
def vectors_dir() -> Path:
    return VECTORS


def read_bitmap_dump(path: Path) -> tuple[int, bytes]:
    """Parse the ``bits`` + payload layout written by ``outguess-extract``."""
    raw = path.read_bytes()
    bits = int.from_bytes(raw[:4], "big")
    return bits, raw[4 : 4 + (bits + 7) // 8]
