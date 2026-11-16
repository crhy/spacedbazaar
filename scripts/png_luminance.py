#!/usr/bin/env python3
"""Measure how light or dark a PNG screenshot is, without an imaging dependency.

Spaced Bazaar publishes screenshots in three places: the README gallery, the
AppStream metainfo and the signed application catalog.  Issue
crhy/spacedbazaar#15 asks that the published mix be at least half dark, because
Spaced Linux ships a dark desktop by default.  That claim is only worth keeping
if it is measured, so this module decodes the committed PNGs itself: PIL is
*not* a dependency of this repository, so the decoder below uses nothing but
`zlib`, `struct` and `hashlib`.

Supported: non-interlaced PNGs with colour type 0 (greyscale), 2 (truecolour),
3 (palette), 4 (greyscale + alpha) or 6 (truecolour + alpha), at 8 or 16 bits
per sample, with PNG filter types 0-4 on every scanline.  16-bit samples keep
their most significant byte, and alpha is composited over black so a transparent
corner counts as black.  Anything else raises PNGError instead of guessing.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from pathlib import Path

# A screenshot counts as dark when its mean luminance is below this value.
# One threshold, shared by scripts/check-screenshot-mix.py and the tests, so
# the two can never disagree about what "dark" means.
DARK_THRESHOLD = 0.50

# Rec.709 weights, applied to 8-bit samples in the 0.0-1.0 range.
REC709 = (0.2127, 0.7152, 0.0722)

SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


class PNGError(ValueError):
    """The file is not a PNG this module can decode."""


def _chunks(data: bytes):
    """Yield (type, payload) for every chunk after the PNG signature."""

    position = len(SIGNATURE)
    while position + 8 <= len(data):
        length = struct.unpack(">I", data[position:position + 4])[0]
        kind = data[position + 4:position + 8]
        payload = data[position + 8:position + 8 + length]
        if len(payload) != length:
            raise PNGError("truncated PNG chunk")
        yield kind, payload
        position += 12 + length


def _unfilter(filter_type: int, line: bytearray, above: bytes, bpp: int) -> None:
    """Undo the PNG scanline filter in place.

    Each channel is an independent byte sequence strided by `bpp` (bytes per
    pixel), so the reconstruction walks one channel at a time and keeps the
    already-decoded neighbours in local variables.
    """

    width = len(line)

    if filter_type == 0:  # None
        return

    if filter_type == 1:  # Sub: add the reconstructed sample to the left
        for start in range(bpp):
            running = 0
            for position in range(start, width, bpp):
                running = (line[position] + running) & 0xFF
                line[position] = running
        return

    if filter_type == 2:  # Up: add the sample above
        for position in range(width):
            line[position] = (line[position] + above[position]) & 0xFF
        return

    if filter_type == 3:  # Average: half of (left + above), rounded down
        for start in range(bpp):
            left = 0
            for position in range(start, width, bpp):
                left = (line[position] + ((left + above[position]) >> 1)) & 0xFF
                line[position] = left
        return

    if filter_type == 4:  # Paeth: the neighbour closest to left + above - above_left
        for start in range(bpp):
            left = 0
            above_left = 0
            for position in range(start, width, bpp):
                up = above[position]
                estimate = left + up - above_left
                best = left
                distance = abs(left - estimate)
                candidate_distance = abs(up - estimate)
                if candidate_distance < distance:
                    best = up
                    distance = candidate_distance
                if abs(above_left - estimate) < distance:
                    best = above_left
                line[position] = (line[position] + best) & 0xFF
                left = line[position]
                above_left = up
        return

    raise PNGError(f"unknown PNG filter type {filter_type}")


def _palette_tables(palette: bytes, palette_alpha: bytes | None) -> list[bytes]:
    """Translation tables mapping a palette index to its composited 8-bit sample."""

    tables = []
    for channel in range(3):
        table = bytearray(256)
        for index in range(256):
            offset = index * 3 + channel
            value = palette[offset] if offset < len(palette) else 0
            alpha = 255
            if palette_alpha is not None and index < len(palette_alpha):
                alpha = palette_alpha[index]
            table[index] = (value * alpha) // 255
        tables.append(bytes(table))
    return tables


def _composited(samples, alpha) -> bytes:
    """Composite 8-bit samples over black: a fully transparent sample is black."""

    if min(alpha) == 255:
        return bytes(samples)
    return bytes((value * mask) // 255 for value, mask in zip(samples, alpha))


def iter_row_channels(path):
    """Yield each scanline of `path` as its 8-bit red, green and blue samples.

    Rows come back as three `bytes` objects of length `width` rather than
    interleaved pixels: PNG samples are already laid out per channel, and
    `zip(*row)` recovers the pixels when a caller wants them.
    """

    data = Path(path).read_bytes()
    if not data.startswith(SIGNATURE):
        raise PNGError(f"not a PNG: {path}")

    header = None
    palette = None
    palette_alpha = None
    compressed = []

    for kind, payload in _chunks(data):
        if kind == b"IHDR":
            if header is not None:
                raise PNGError(f"more than one IHDR: {path}")
            header = struct.unpack(">IIBBBBB", payload)
        elif kind == b"PLTE":
            palette = payload
        elif kind == b"tRNS":
            palette_alpha = payload
        elif kind == b"IDAT":
            compressed.append(payload)
        elif kind == b"IEND":
            break

    if header is None:
        raise PNGError(f"no IHDR chunk: {path}")

    width, height, bit_depth, colour_type, compression, filter_method, interlace = header

    if compression != 0 or filter_method != 0:
        raise PNGError(f"unsupported compression or filter method in {path}")
    if interlace != 0:
        raise PNGError(f"Adam7 interlacing is not supported: {path}")
    if bit_depth not in (8, 16):
        raise PNGError(f"only 8 and 16-bit PNGs are supported: {path}")
    if colour_type not in CHANNELS:
        raise PNGError(f"unsupported PNG colour type {colour_type}: {path}")
    if colour_type == 3 and bit_depth != 8:
        raise PNGError(f"only 8-bit palettes are supported: {path}")
    if colour_type == 3 and palette is None:
        raise PNGError(f"palette PNG without a PLTE chunk: {path}")
    if width == 0 or height == 0:
        raise PNGError(f"PNG has no pixels: {path}")

    channels = CHANNELS[colour_type]
    sample_bytes = bit_depth // 8
    stride = width * channels * sample_bytes
    raw = zlib.decompress(b"".join(compressed))
    if len(raw) != height * (stride + 1):
        raise PNGError(f"IDAT does not hold {height} rows of {stride} bytes: {path}")

    tables = _palette_tables(palette, palette_alpha) if colour_type == 3 else None
    bpp = max(1, channels * sample_bytes)
    above = bytes(stride)

    for row in range(height):
        offset = row * (stride + 1)
        line = bytearray(raw[offset + 1:offset + 1 + stride])
        _unfilter(raw[offset], line, above, bpp)
        above = bytes(line)

        if sample_bytes == 2:  # keep the most significant byte of each sample
            line = bytes(line[0::2])

        if colour_type == 2:
            yield (line[0::3], line[1::3], line[2::3])
        elif colour_type == 6:
            alpha = line[3::4]
            yield (_composited(line[0::4], alpha),
                   _composited(line[1::4], alpha),
                   _composited(line[2::4], alpha))
        elif colour_type == 4:
            grey = _composited(line[0::2], line[1::2])
            yield (grey, grey, grey)
        elif colour_type == 3:
            yield (line.translate(tables[0]),
                   line.translate(tables[1]),
                   line.translate(tables[2]))
        else:  # colour_type == 0, plain greyscale
            grey = bytes(line)
            yield (grey, grey, grey)


def measure(path) -> tuple[float, str]:
    """Return the mean Rec.709 luminance of `path` and a capture digest.

    The digest identifies the decoded pixels, not the file bytes, so the same
    capture committed twice under different names is still recognised as one
    capture.
    """

    digest = hashlib.sha256()
    total = 0.0
    pixels = 0

    for red, green, blue in iter_row_channels(path):
        digest.update(red)
        digest.update(green)
        digest.update(blue)
        pixels += len(red)
        total += (REC709[0] * sum(red)
                  + REC709[1] * sum(green)
                  + REC709[2] * sum(blue))

    if pixels == 0:
        raise PNGError(f"PNG has no pixels: {path}")

    return total / pixels / 255.0, digest.hexdigest()


def mean_luminance(path) -> float:
    """Mean Rec.709 luminance of `path`, from 0.0 (black) to 1.0 (white)."""

    return measure(path)[0]


def is_dark(luminance: float) -> bool:
    """True when a capture counts as a dark-mode screenshot."""

    return luminance < DARK_THRESHOLD
