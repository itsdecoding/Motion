import json
from types import SimpleNamespace

import pytest

from engine import synthesizer
from engine.errors import EngineError
from engine.schema import Brand


def _walk(node):
    yield node
    for child in [*node.get("properties", {}).values(), *node.get("anyOf", []), *([node["items"]] if "items" in node else [])]:
        yield from _walk(child)


def _fake_gemini(monkeypatch, text):
    calls = []

    class Models:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(text=text)

    monkeypatch.setenv(synthesizer.API_KEY_VAR, "test-key")
    monkeypatch.setattr(synthesizer.genai, "Client", lambda api_key: SimpleNamespace(models=Models()))
    return calls


def _deck_json(spec):
    return json.dumps({k: spec[k] for k in ("title", "slides")})


def test_schema_uses_only_documented_keywords():
    allowed = synthesizer.SCHEMA_KEYS
    for node in _walk(synthesizer.response_schema()):
        assert set(node) <= allowed, set(node) - allowed
    assert "At most 48 characters." in json.dumps(synthesizer.response_schema())


def test_returns_valid_deck(monkeypatch, spec):
    calls = _fake_gemini(monkeypatch, _deck_json(spec))
    deck = synthesizer.write_deck("outbound", Brand.model_validate(spec["brand"]), 4, "gemini-test", "fix overflow")
    assert deck.title == spec["title"] and len(deck.slides) == 4
    assert calls[0]["model"] == "gemini-test" and "fix overflow" in calls[0]["contents"]


@pytest.mark.parametrize("text", ["not json", json.dumps({"title": "x", "slides": [{"type": "spinning_cube"}]})])
def test_rejects_output_that_breaks_the_schema(monkeypatch, spec, text):
    _fake_gemini(monkeypatch, text)
    with pytest.raises(synthesizer.DeckRejected):
        synthesizer.write_deck("outbound", Brand.model_validate(spec["brand"]), 4, "gemini-test")


def test_rejects_wrong_slide_count(monkeypatch, spec):
    _fake_gemini(monkeypatch, _deck_json(spec))
    with pytest.raises(synthesizer.DeckRejected, match="exactly 6"):
        synthesizer.write_deck("outbound", Brand.model_validate(spec["brand"]), 6, "gemini-test")


def test_requires_api_key(monkeypatch, spec):
    monkeypatch.delenv(synthesizer.API_KEY_VAR, raising=False)
    with pytest.raises(EngineError, match="GEMINI_API_KEY"):
        synthesizer.write_deck("outbound", Brand.model_validate(spec["brand"]), 4, "gemini-test")
