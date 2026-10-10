import unittest

from teachmechat.desktop.theme import COLORS, STYLE


def luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
    return sum(a * b for a, b in zip(linear, (.2126, .7152, .0722)))


def contrast(a, b):
    bright, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (bright + .05) / (dark + .05)


class ThemeTests(unittest.TestCase):
    def test_text_pairs_meet_normal_text_contrast(self):
        pairs = [(foreground, background) for foreground in ("text", "muted")
                 for background in ("canvas", "surface", "card", "input", "incoming", "outgoing", "sidebar", "selected")]
        pairs += [("on_accent", "accent"), ("on_accent", "accent_hover"), ("error", "surface"),
                  ("error", "card"), ("busy", "card"), ("paused", "card")]
        for foreground, background in pairs:
            with self.subTest(foreground=foreground, background=background):
                self.assertGreaterEqual(contrast(COLORS[foreground], COLORS[background]), 4.5)

    def test_surface_luminance_is_lower_without_becoming_dark(self):
        for token in ("canvas", "surface", "card", "input"):
            self.assertLess(luminance(COLORS[token]), .8)
            self.assertGreater(luminance(COLORS[token]), .4)
        self.assertLess(luminance(COLORS["canvas"]), luminance(COLORS["surface"]))
        self.assertLess(luminance(COLORS["surface"]), luminance(COLORS["card"]))

    def test_all_style_tokens_are_resolved_no_pure_white_panels(self):
        self.assertNotIn("@", STYLE)
        self.assertNotIn("#ffffff", STYLE.lower())
        self.assertNotIn("background: white", STYLE.lower())
