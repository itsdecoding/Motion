import copy

from typer.testing import CliRunner

from engine import cli, pipeline
from engine.config import ROOT
from engine.schema import SlideDeck

runner = CliRunner()


def test_generate_retries_with_qa_feedback(spec, tmp_path, monkeypatch):
    broken = copy.deepcopy(spec)
    broken["slides"][1]["lines"] = ["Antidisestablishmentarians"]
    decks = [SlideDeck.model_validate({k: d[k] for k in ("title", "slides")}) for d in (broken, spec)]
    feedback = []

    def fake_write_deck(source, brand, slide_count, model, fb=None):
        feedback.append(fb)
        return decks[len(feedback) - 1]

    monkeypatch.setattr(pipeline, "write_deck", fake_write_deck)
    result = runner.invoke(cli.app, [
        "generate", "--brand", str(ROOT / "brands" / "simplescale.json"),
        "--topic", "outbound", "--slides", "4", "--out", str(tmp_path),
    ])

    assert result.exit_code == 0, result.output
    assert feedback[0] is None and "overflow on line-1" in feedback[1]
    assert (tmp_path / "carousel.json").exists()


def test_generate_requires_one_source(tmp_path):
    result = runner.invoke(cli.app, ["generate", "--brand", str(ROOT / "brands" / "simplescale.json")])
    assert result.exit_code == 1
    assert "exactly one of --script or --topic" in result.output
