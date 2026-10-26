"""Tiny valid-enough image bytes for tests."""

import struct


def make_jpeg(width: int, height: int = 90) -> bytes:
    """A JPEG header (SOI + SOF0) that declares the given size, padded so parsers can read it."""
    sof = (
        b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, height, width, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    )
    return b"\xff\xd8" + sof + b"\x00" * 64 + f"w{width}".encode()


def make_png(width: int, height: int = 90) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x02\x00\x00\x00"
    )
