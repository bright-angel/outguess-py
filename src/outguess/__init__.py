"""OutGuess 0.4 reimplemented in pure Python.

This package is a bit-compatible port of the C OutGuess 0.4 steganography
tool: it reads and writes carriers produced by the original program and vice
versa.  It has no third-party runtime dependencies.

Distributed under the same BSD-style licence as the original OutGuess; see
``LICENSE`` in the source distribution, which also carries the Independent
JPEG Group acknowledgement for the reimplemented libjpeg codec.
"""

from __future__ import annotations

__version__ = "0.4.0"
__all__ = ["__version__"]


def get_version() -> str:
    return f"OutGuess {__version__} (Python port of 0.4, 1999-2021 Niels Provos and others)"
