from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "templates"
FONTS_DIR = ROOT / "assets" / "fonts"

WIDTH = 1080
HEIGHT = 1350
FPS = 30

SPRING_SETTLE = 0.6
QA_STEP = 0.5

DEFAULT_MODEL = "gemini-3.8-flash"

FONT_FACES = [
    ("Jakarta", "plus-jakarta-sans-latin-400-normal.woff2", 400, "normal"),
    ("Jakarta", "plus-jakarta-sans-latin-600-normal.woff2", 600, "normal"),
    ("Jakarta", "plus-jakarta-sans-latin-800-normal.woff2", 800, "normal"),
    ("Instrument Serif", "instrument-serif-latin-400-normal.woff2", 400, "normal"),
    ("Instrument Serif", "instrument-serif-latin-400-italic.woff2", 400, "italic"),
]
