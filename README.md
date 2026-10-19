# motion-carousel-engine (Phase 2)

Turns a script or topic into an animated carousel: one 1080×1350, 30 fps MP4 per slide.
Every slide is a standalone HTML page driven by `window.seek(t)`, rendered frame by frame,
and checked by a QA gate before any video is encoded.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

FFmpeg must be on your PATH. `generate` needs `GEMINI_API_KEY` set (a key from Google AI Studio).

## Website

```bash
APP_PASSWORD=choose-a-password GEMINI_API_KEY=... python -m webapp
```

Open http://localhost:8000 and sign in with any username and that password. The site creates carousels,
shows live slide previews, edits slide text with the schema's character limits, runs the QA gate on every save,
renders the MP4s and downloads them one by one or as a zip. Only one job (writing or rendering) runs at a time;
others wait their turn.

Carousels live in `output/<id>/` (`carousel.json`, `request.json` for "Rewrite all", `qa.json`, `slides/`, `mp4/`),
so keep that folder when you move or redeploy. Job progress is kept in memory: a restart during a job loses that
job, but not the files already written.

With Docker (FFmpeg and Chromium included):

```bash
docker build -t carousel-studio .
docker run -p 8000:8000 -e APP_PASSWORD=... -e GEMINI_API_KEY=... -v carousel-output:/app/output carousel-studio
```

## Commands

```bash
# Write a carousel with Gemini, compile it, and QA it (retries once with the QA findings)
python -m engine generate --brand brands/simplescale.json --script my_script.md --slides 6 --out output/my-carousel
python -m engine generate --brand brands/simplescale.json --topic "Why cold email volume backfires" --out output/volume

# Check a hand-edited spec (exit code 1 if QA finds problems)
python -m engine verify output/my-carousel/carousel.json

# Compile, QA, and render MP4s into <spec folder>/mp4
python -m engine render output/my-carousel/carousel.json --parallel 4
```

Open any file in `<spec folder>/slides/` in a browser to preview it; it plays on a loop.
`examples/outbound.json` is a complete spec you can render without an API key.

## Slide types

| `type` | Use it for | Fields |
| --- | --- | --- |
| `cover_hero` | The opening hook (dark) | `badge`, `headline`, `headline_accent`, `subline?` |
| `word_stagger` | One sharp statement, revealed word by word | `lines` (1–4, the last becomes a serif accent), `body?` |
| `comparison_split` | Before/after contrast | `title`, `old_label`, `new_label`, `old_points`, `new_points` (1–3 each) |
| `outro_cta` | The closing call to action (dark) | `headline`, `headline_accent`, `cta`, `note?` |

Every field has a character limit enforced by `engine/schema.py`. `duration` defaults to 8 s
(3–15 s) and must leave at least 0.5 s after the animation settles.

## The seek contract

A slide's `window.seek(t)` must set every animated property from `t` alone, synchronously.
CSS animations and transitions are disabled; nothing may read the clock or `Math.random`.
The renderer waits until every font face reports `loaded` before frame 0, and fails if any don't.

## QA gate

From the moment a slide's animation settles until its last frame, every 0.5 s the gate checks:

- **Overflow**: text wider than its box, or content clipped by the slide's stage.
- **Bounds**: anything outside the 1080×1350 canvas.
- **Overlap**: two text elements intersecting.
- **Contrast**: WCAG ratio below 3:1 for text 24 px and up, 4.5:1 below that.
- **Determinism**: the same `t` must produce the same pixels after seeking elsewhere.

## Layout

```
engine/
  cli.py          generate / verify / render
  pipeline.py     generate-with-retries and compile+QA, shared by the CLI and the website
  schema.py       Pydantic models, one per slide type, with timing schedules
  synthesizer.py  Gemini call with structured JSON output (schema converted to Gemini's supported subset)
  compiler.py     Jinja2 → standalone slide HTML (fonts inlined)
  verifier.py     QA gate
  renderer.py     Playwright frames → FFmpeg H.264
  browser.py      shared page setup: font lock, error capture, seek
templates/        base slide + one partial per slide type
assets/fonts/     Plus Jakarta Sans and Instrument Serif (SIL OFL)
brands/           brand presets (name, handle, voice, palette)
examples/         a ready-to-render spec
webapp/
  server.py       FastAPI: password check, job runner, carousel API, file downloads
  static/         the single-page website
tests/            pytest suite, including real browser and FFmpeg runs
```

## Not built yet

Reference-style analysis, freeform slides, audio, 9:16 and PDF export.
