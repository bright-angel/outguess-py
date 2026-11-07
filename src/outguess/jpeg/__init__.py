"""Dependency-free baseline JPEG codec tuned for OutGuess coefficient access.

The codec implements the integer algorithms of IJG libjpeg 6b (the library
embedded in OutGuess 0.4): slow integer FDCT/IDCT, fixed-point colour
conversion, 2x2 downsampling / fancy upsampling, quantization and baseline
Huffman coding.  It also exposes the quantized DCT coefficients in exactly the
order used by ``steg_use_bit`` in the patched ``jcdctmgr.c`` / ``jdcoefct.c``.
"""

from __future__ import annotations

__all__ = ["codec", "tables", "dct"]
