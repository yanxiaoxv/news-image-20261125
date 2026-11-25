#!/usr/bin/env python3
"""news-image-20261125 entry point.

The repository ships a finished front-page image as ``entry.png`` (JPEG
bytes under a .png name, which the contest rules allow). This program
checks that image against the contest limits — a whole PNG or JPEG, at
most 1 MiB, at most 1024x1024 pixels — and then copies it unchanged to
``entry.png`` in the output directory:

    mkdir -p out
    MAKEFUN_OUTPUT_DIR=out python3 main.py    # writes out/entry.png

With MAKEFUN_OUTPUT_DIR unset, or set to an empty string, the output
directory is /output (an empty value counts as unset).

Standard library only, no network. The output is a byte-for-byte copy of
the shipped image, so every run writes exactly the same bytes.
"""

import hashlib
import os
import shutil
import struct
import sys
import zlib

LIMIT_BYTES = 1024 * 1024
LIMIT_SIDE = 1024


def die(message):
    print(f"main.py: error: {message}", file=sys.stderr)
    raise SystemExit(1)


def jpeg_size(data):
    """(width, height) of a JPEG, or None if data does not start as one.

    Walks marker segments from the SOI marker to the first start-of-frame
    segment. The file must end with the EOI marker.
    """
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    if data[-2:] != b"\xff\xd9":
        die("JPEG does not end with the end-of-image marker")
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            die(f"JPEG: marker expected at offset {pos}")
        marker = data[pos + 1]
        if marker == 0xD9:  # EOI before any frame header
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            pos += 2  # standalone markers carry no length field
            continue
        (seg_len,) = struct.unpack(">H", data[pos + 2:pos + 4])
        if seg_len < 2 or pos + 2 + seg_len > len(data):
            die("JPEG: segment runs past the end of the file")
        if marker in (0xC0, 0xC1, 0xC2):  # SOF0, SOF1, SOF2
            height, width = struct.unpack(">HH", data[pos + 5:pos + 9])
            return width, height
        pos += 2 + seg_len
    die("JPEG: no start-of-frame segment found")


def png_size(data):
    """(width, height) of a PNG, or None if data does not start as one.

    Every chunk's CRC is verified; IHDR must be present and IEND must be
    the final chunk with nothing after it.
    """
    if len(data) < 8 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos = 8
    size = None
    seen_iend = False
    while pos + 12 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        end = pos + 12 + length
        if end > len(data):
            die("PNG: chunk runs past the end of the file")
        body = data[pos + 8:pos + 8 + length]
        (crc_seen,) = struct.unpack(">I", data[pos + 8 + length:end])
        crc_real = zlib.crc32(body, zlib.crc32(ctype)) & 0xFFFFFFFF
        if crc_real != crc_seen:
            die(f"PNG: CRC mismatch in {ctype!r} chunk")
        if ctype == b"IHDR":
            if length != 13:
                die("PNG: IHDR chunk has the wrong length")
            size = struct.unpack(">II", body[:8])
        elif ctype == b"IEND":
            seen_iend = True
            if end != len(data):
                die("PNG: bytes follow the IEND chunk")
            break
        pos = end
    if size is None:
        die("PNG: no IHDR chunk")
    if not seen_iend:
        die("PNG: no IEND chunk")
    return size


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(here, "entry.png")
    if not os.path.isfile(src):
        die(f"shipped image not found: {src}")
    with open(src, "rb") as fh:
        data = fh.read()
    if len(data) > LIMIT_BYTES:
        die(f"image is {len(data)} bytes, over the 1 MiB limit")
    dims = jpeg_size(data)
    kind = "JPEG"
    if dims is None:
        dims = png_size(data)
        kind = "PNG"
    if dims is None:
        die("entry.png is neither a whole JPEG nor a whole PNG")
    width, height = dims
    if width > LIMIT_SIDE or height > LIMIT_SIDE:
        die(f"image is {width}x{height}, over the 1024x1024 limit")
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, "entry.png")
    digest = hashlib.sha256(data).hexdigest()
    shutil.copyfile(src, dst)
    # Read the copy back and check it: a short or corrupted write (full
    # disk, interrupted copy) must fail the run, not pass silently.
    with open(dst, "rb") as fh:
        written = fh.read()
    if len(written) != len(data) or hashlib.sha256(written).hexdigest() != digest:
        die(f"written file {dst} does not match the shipped image")
    print(f"main.py: wrote {dst} ({kind} {width}x{height}, "
          f"{len(data)} bytes, sha256 {digest})")


if __name__ == "__main__":
    main()
