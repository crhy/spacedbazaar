"""crhy/spacedbazaar#15: the screenshots SpacedBazaar publishes must be at least half dark.

The fixtures below are written with `zlib` and `struct` and read back through
`scripts/png_luminance.py`, so the decoder is tested rather than assumed: PIL is
not a dependency of this repository and is not used here.
"""

from __future__ import annotations

import importlib.util
import pathlib
import struct
import tempfile
import unittest
import zlib

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


png_luminance = load_module("png_luminance", REPOSITORY_ROOT / "scripts" / "png_luminance.py")
screenshot_mix = load_module(
    "check_screenshot_mix", REPOSITORY_ROOT / "scripts" / "check-screenshot-mix.py"
)


def encode_row(pixels, previous, filter_type: int) -> bytes:
    """Filter one scanline the way PNG says, so the decoder gets real input."""

    line = bytearray()
    for index, pixel in enumerate(pixels):
        for channel in range(3):
            value = pixel[channel]
            left = pixels[index - 1][channel] if index else 0
            above = previous[index][channel] if previous else 0
            above_left = (previous[index - 1][channel]
                          if previous and index else 0)
            if filter_type == 0:
                predicted = 0
            elif filter_type == 1:
                predicted = left
            elif filter_type == 2:
                predicted = above
            elif filter_type == 3:
                predicted = (left + above) >> 1
            else:
                estimate = left + above - above_left
                predicted = left
                distance = abs(left - estimate)
                if abs(above - estimate) < distance:
                    predicted = above
                if abs(above_left - estimate) < distance:
                    predicted = above_left
            line.append((value - predicted) % 256)
    return bytes([filter_type]) + bytes(line)


def filtered_rows(pixels, filter_type: int) -> list[bytes]:
    rows = []
    previous = None
    for row in pixels:
        rows.append(encode_row(row, previous, filter_type))
        previous = row
    return rows


def write_png(path: pathlib.Path, rows: list[bytes], width: int, colour_type: int,
              bit_depth: int = 8, palette: bytes | None = None) -> None:
    """Write a minimal PNG: IHDR, optional PLTE, one IDAT, IEND."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(
            ">I", zlib.crc32(body)
        )

    data = b"\x89PNG\r\n\x1a\n"
    data += chunk(b"IHDR", struct.pack(">IIBBBBB", width, len(rows), bit_depth,
                                       colour_type, 0, 0, 0))
    if palette is not None:
        data += chunk(b"PLTE", palette)
    data += chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
    data += chunk(b"IEND", b"")
    path.write_bytes(data)


def dark_pixels(width: int, height: int):
    """A near-black desktop: dark chrome, slightly lighter content area."""

    return [[(8 + 6 * x + y, 10 + 5 * x + y, 20 + 4 * x + y)
             for x in range(width)] for y in range(height)]


def light_pixels(width: int, height: int):
    """A near-white desktop: the same layout pushed up to white."""

    return [[(250 - 2 * x, 252 - 2 * x - y, 254 - 2 * x)
             for x in range(width)] for y in range(height)]


def expected_planes(pixels):
    """The channel planes `iter_row_channels` is expected to yield."""

    return [tuple(bytes(pixel[channel] for pixel in row) for channel in range(3))
            for row in pixels]


def reference_luminance(pixels) -> float:
    """Rec.709 luminance computed straight from the fixture pixels."""

    flat = [pixel for row in pixels for pixel in row]
    weights = png_luminance.REC709
    total = sum(weights[0] * pixel[0] + weights[1] * pixel[1] + weights[2] * pixel[2]
                for pixel in flat)
    return total / len(flat) / 255.0


class DecoderFixtureTests(unittest.TestCase):
    def test_a_dark_capture_round_trips_and_measures_dark(self):
        pixels = dark_pixels(12, 9)
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "dark.png"
            write_png(path, filtered_rows(pixels, 4), 12, 2)
            planes = list(png_luminance.iter_row_channels(path))
            luminance = png_luminance.mean_luminance(path)

        self.assertEqual(planes, expected_planes(pixels))
        self.assertAlmostEqual(luminance, reference_luminance(pixels), places=9)
        self.assertLess(luminance, png_luminance.DARK_THRESHOLD)
        self.assertTrue(png_luminance.is_dark(luminance))

    def test_a_light_capture_round_trips_and_measures_light(self):
        pixels = light_pixels(12, 9)
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "light.png"
            write_png(path, filtered_rows(pixels, 2), 12, 2)
            planes = list(png_luminance.iter_row_channels(path))
            luminance = png_luminance.mean_luminance(path)

        self.assertEqual(planes, expected_planes(pixels))
        self.assertAlmostEqual(luminance, reference_luminance(pixels), places=9)
        self.assertGreater(luminance, png_luminance.DARK_THRESHOLD)
        self.assertFalse(png_luminance.is_dark(luminance))

    def test_every_png_filter_type_decodes_to_the_same_pixels(self):
        pixels = dark_pixels(10, 6)
        expected = expected_planes(pixels)
        with tempfile.TemporaryDirectory() as temporary:
            for filter_type in range(5):
                path = pathlib.Path(temporary) / f"filter-{filter_type}.png"
                write_png(path, filtered_rows(pixels, filter_type), 10, 2)
                self.assertEqual(list(png_luminance.iter_row_channels(path)),
                                 expected,
                                 f"filter type {filter_type} did not round-trip")
                self.assertAlmostEqual(png_luminance.mean_luminance(path),
                                       reference_luminance(pixels),
                                       places=9)

    def test_the_threshold_is_one_documented_value(self):
        self.assertEqual(png_luminance.DARK_THRESHOLD, 0.50)
        self.assertTrue(png_luminance.is_dark(0.499))
        self.assertFalse(png_luminance.is_dark(0.50))
        self.assertFalse(png_luminance.is_dark(0.501))

    def test_uniform_grey_straddles_the_threshold(self):
        for grey, expected_dark in ((127, True), (128, False)):
            pixels = [[(grey, grey, grey) for _ in range(8)] for _ in range(8)]
            with tempfile.TemporaryDirectory() as temporary:
                path = pathlib.Path(temporary) / "grey.png"
                write_png(path, filtered_rows(pixels, 1), 8, 2)
                luminance = png_luminance.mean_luminance(path)
            self.assertAlmostEqual(luminance,
                                   grey * sum(png_luminance.REC709) / 255.0,
                                   places=9)
            self.assertEqual(png_luminance.is_dark(luminance), expected_dark)

    def test_alpha_is_composited_over_black(self):
        rows = [b"\x00" + bytes(v for _ in range(4) for v in (255, 255, 255, 0))
                for _ in range(4)]
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "clear.png"
            write_png(path, rows, 4, 6)
            luminance = png_luminance.mean_luminance(path)
        self.assertEqual(luminance, 0.0)

    def test_greyscale_and_palette_captures_measure_too(self):
        grey_rows = [b"\x00" + bytes(range(0, 256, 32)) for _ in range(2)]
        palette = bytes(value for value in (0, 0, 0, 255, 255, 255))
        with tempfile.TemporaryDirectory() as temporary:
            grey_path = pathlib.Path(temporary) / "grey.png"
            write_png(grey_path, grey_rows, 8, 0)
            grey_luminance = png_luminance.mean_luminance(grey_path)

            indexed_rows = [b"\x00" + bytes([0, 1, 0, 1]) for _ in range(2)]
            palette_path = pathlib.Path(temporary) / "palette.png"
            write_png(palette_path, indexed_rows, 4, 3, palette=palette)
            palette_planes = list(png_luminance.iter_row_channels(palette_path))
            palette_luminance = png_luminance.mean_luminance(palette_path)

        self.assertAlmostEqual(grey_luminance,
                               sum(range(0, 256, 32)) * sum(png_luminance.REC709) / 8 / 255.0,
                               places=9)
        self.assertEqual(palette_planes,
                         expected_planes([[(0, 0, 0), (255, 255, 255),
                                          (0, 0, 0), (255, 255, 255)]
                                         for _ in range(2)]))
        self.assertAlmostEqual(palette_luminance, 0.5 * sum(png_luminance.REC709), places=9)

    def test_the_decoder_refuses_what_it_cannot_measure(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "not-a-png.png"
            path.write_bytes(b"definitely not a png")
            with self.assertRaises(png_luminance.PNGError):
                png_luminance.mean_luminance(path)


class PublishedScreenshotMixTests(unittest.TestCase):
    def test_every_published_screenshot_is_committed(self):
        for name in screenshot_mix.published_set():
            self.assertTrue((REPOSITORY_ROOT / name).is_file(), f"missing {name}")

    def test_no_capture_is_published_twice_under_two_names(self):
        captures = {}
        for name in screenshot_mix.published_set():
            digest = png_luminance.measure(REPOSITORY_ROOT / name)[1]
            self.assertNotIn(digest, captures,
                             f"{name} duplicates another published capture")
            captures[digest] = name

    def test_the_published_set_is_at_least_half_dark(self):
        published = screenshot_mix.published_set()
        measured = [(name, png_luminance.mean_luminance(REPOSITORY_ROOT / name))
                    for name in published]
        dark = [name for name, luminance in measured
                if png_luminance.is_dark(luminance)]
        self.assertGreaterEqual(
            2 * len(dark),
            len(measured),
            "published screenshots are not at least half dark: "
            + ", ".join(f"{name} {luminance:.3f}" for name, luminance in measured),
        )

    def test_the_readme_gallery_and_the_flathub_pin_are_both_measured(self):
        published = screenshot_mix.published_set()
        self.assertIn("screenshots/spaced-bazaar-explore-2026-09.png", published)
        self.assertEqual(
            published["screenshots/spaced-bazaar-explore-dark-9.26.1.png"],
            ["README", "metainfo"],
            "the dark capture Flathub shows must also be in the README gallery",
        )


if __name__ == "__main__":
    unittest.main()
