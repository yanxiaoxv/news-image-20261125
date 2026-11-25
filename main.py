#!/usr/bin/env python3
"""Deliver the finished front-page image for news-image-20261125.

The picture itself ships in this directory as ``entry.png``.  What this
program adds is a guard rail: before anything is delivered it proves
that the shipped file is a complete image the contest will accept, and
afterwards it proves the delivered copy is the very same bytes.

    mkdir -p out
    MAKEFUN_OUTPUT_DIR=out python3 main.py

``MAKEFUN_OUTPUT_DIR`` picks the destination directory; when it is
missing or empty the destination is ``/output``.  Only the Python
standard library is used and nothing here touches the network, so the
delivered file is identical on every run.
"""

import hashlib
import os
import struct
import sys
import zlib

MAX_FILE_BYTES = 1024 * 1024   # contest cap: 1 MiB
MAX_EDGE = 1024                # contest cap: 1024 px per side

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"

# JPEG markers that carry no payload and no length field.
_JPEG_BARE = {0x01, 0xD8} | set(range(0xD0, 0xD8))
# Start-of-frame markers whose segment holds the picture dimensions.
_JPEG_SOF = {0xC0, 0xC1, 0xC2}


class Reject(Exception):
    """The shipped image failed a check; the run must stop."""


def jpeg_dimensions(blob):
    """Return (width, height) if blob is a JPEG, else None.

    A blob that starts like a JPEG but is malformed raises Reject: a
    truncated or corrupt file must fail loudly, not fall through to
    some other interpretation.
    """
    if len(blob) < 4 or not blob.startswith(JPEG_SOI):
        return None
    if not blob.endswith(JPEG_EOI):
        raise Reject("JPEG is missing its end-of-image marker")
    cursor = 2
    while cursor + 1 < len(blob):
        if blob[cursor] != 0xFF:
            raise Reject(f"JPEG marker missing at byte {cursor}")
        marker = blob[cursor + 1]
        if marker == 0xD9:
            break  # reached EOI without ever seeing a frame header
        if marker in _JPEG_BARE:
            cursor += 2
            continue
        if cursor + 4 > len(blob):
            raise Reject("JPEG segment header runs past the file end")
        (span,) = struct.unpack_from(">H", blob, cursor + 2)
        if span < 2 or cursor + 2 + span > len(blob):
            raise Reject("JPEG segment length runs past the file end")
        if marker in _JPEG_SOF:
            height, width = struct.unpack_from(">HH", blob, cursor + 5)
            return width, height
        cursor += 2 + span
    raise Reject("JPEG contains no start-of-frame segment")


def png_dimensions(blob):
    """Return (width, height) if blob is a PNG, else None.

    The chunk list is walked end to end: each chunk's stored CRC must
    match a fresh CRC over its type and data, the first chunk must be
    IHDR, and IEND must finish exactly at the end of the file.
    """
    if len(blob) < 8 or not blob.startswith(PNG_MAGIC):
        return None
    cursor = len(PNG_MAGIC)
    dimensions = None
    first = True
    while cursor < len(blob):
        if cursor + 8 > len(blob):
            raise Reject("PNG chunk header runs past the file end")
        (payload_len,) = struct.unpack_from(">I", blob, cursor)
        kind = blob[cursor + 4:cursor + 8]
        chunk_end = cursor + 12 + payload_len
        if chunk_end > len(blob):
            raise Reject(f"PNG {kind!r} chunk runs past the file end")
        payload = blob[cursor + 8:cursor + 8 + payload_len]
        (stored_crc,) = struct.unpack_from(">I", blob, cursor + 8 + payload_len)
        actual_crc = zlib.crc32(payload, zlib.crc32(kind)) & 0xFFFFFFFF
        if actual_crc != stored_crc:
            raise Reject(f"PNG {kind!r} chunk has a bad CRC")
        if first and kind != b"IHDR":
            raise Reject("PNG does not begin with an IHDR chunk")
        first = False
        if kind == b"IHDR":
            if payload_len != 13:
                raise Reject("PNG IHDR chunk is not 13 bytes")
            dimensions = struct.unpack_from(">II", payload, 0)
        elif kind == b"IEND":
            if chunk_end != len(blob):
                raise Reject("trailing bytes after the PNG IEND chunk")
            if dimensions is None:
                raise Reject("PNG has an IEND but no IHDR")
            return dimensions
        cursor = chunk_end
    raise Reject("PNG ends without an IEND chunk")


def inspect_image(blob):
    """Identify the image format and return (format, width, height)."""
    for probe in (jpeg_dimensions, png_dimensions):
        found = probe(blob)
        if found is not None:
            name = "JPEG" if probe is jpeg_dimensions else "PNG"
            return name, found[0], found[1]
    raise Reject("entry.png is neither a complete JPEG nor a complete PNG")


def run():
    base = os.path.dirname(os.path.abspath(__file__))
    source = os.path.join(base, "entry.png")
    if not os.path.isfile(source):
        raise Reject(f"shipped image is missing: {source}")
    with open(source, "rb") as fh:
        blob = fh.read()
    if len(blob) > MAX_FILE_BYTES:
        raise Reject(f"image weighs {len(blob)} bytes; the cap is {MAX_FILE_BYTES}")
    fmt, width, height = inspect_image(blob)
    if width > MAX_EDGE or height > MAX_EDGE:
        raise Reject(f"image measures {width}x{height}; the cap is {MAX_EDGE}x{MAX_EDGE}")

    target_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, "entry.png")
    expected = hashlib.sha256(blob).hexdigest()
    with open(target, "wb") as fh:
        written_count = fh.write(blob)
    if written_count != len(blob):
        raise Reject(f"short write to {target}: "
                     f"{written_count} of {len(blob)} bytes landed")
    # Read the delivered file back: a short write or a flipped byte on
    # disk must turn into a failed run, never into a silent bad entry.
    with open(target, "rb") as fh:
        delivered = fh.read()
    if delivered != blob or hashlib.sha256(delivered).hexdigest() != expected:
        raise Reject(f"delivered file {target} differs from the shipped image")
    print(f"delivered {target}: {fmt} {width}x{height}, "
          f"{len(blob)} bytes, sha256 {expected}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Reject as problem:
        print(f"main.py: {problem}", file=sys.stderr)
        sys.exit(1)
