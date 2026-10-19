import copy
import time

import pytest
from fastapi.testclient import TestClient

from engine import pipeline
from engine.schema import SlideDeck
from webapp import server

AUTH = ("me", "secret")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setattr(server, "CAROUSELS_DIR", tmp_path)
    with TestClient(server.app) as c:
        c.auth = AUTH
        yield c


def _fake_writer(monkeypatch, *decks):
    calls = []

    def write_deck(source, brand, slide_count, model, feedback=None):
        calls.append(feedback)
        return decks[min(len(calls), len(decks)) - 1]

    monkeypatch.setattr(pipeline, "write_deck", write_deck)
    return calls


def _deck(spec):
    return SlideDeck.model_validate({k: spec[k] for k in ("title", "slides")})


def _wait(client, carousel_id):
    for _ in range(300):
        data = client.get(f"/api/carousels/{carousel_id}").json()
        if data["job"]["status"] in ("done", "failed"):
            return data
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def _create(client):
    response = client.post("/api/carousels", json={"brand": "simplescale", "source": "outbound", "slides": 4})
    assert response.status_code == 202, response.text
    return response.json()["id"]


def test_requires_password(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    with TestClient(server.app) as anonymous:
        assert anonymous.get("/").status_code == 401
        assert anonymous.get("/api/brands", auth=("me", "wrong")).status_code == 401


def test_lists_brands_and_slide_types(client):
    assert [b["id"] for b in client.get("/api/brands").json()] == ["simplescale"]
    assert set(client.get("/api/slide-types").json()) == {"cover_hero", "word_stagger", "comparison_split", "outro_cta"}


def test_create_review_edit_and_render(client, spec, monkeypatch):
    _fake_writer(monkeypatch, _deck(spec))
    carousel_id = _create(client)
    data = _wait(client, carousel_id)
    assert data["job"]["status"] == "done", data["job"]
    assert data["issues"] == [] and len(data["slides"]) == 4
    assert client.get(data["slides"][0]["html"]).status_code == 200
    assert client.get("/api/carousels").json()[0]["title"] == spec["title"]

    broken = copy.deepcopy(data["carousel"])
    broken["slides"][1]["lines"] = ["Antidisestablishmentarians"]
    issues = client.put(f"/api/carousels/{carousel_id}", json=broken).json()["issues"]
    assert any(i["check"] == "overflow" and i["slide"] == 2 for i in issues)
    assert client.post(f"/api/carousels/{carousel_id}/render").status_code == 202
    assert "quality problems" in _wait(client, carousel_id)["job"]["error"]

    too_long = copy.deepcopy(data["carousel"])
    too_long["slides"][0]["headline"] = "x" * 49
    assert client.put(f"/api/carousels/{carousel_id}", json=too_long).status_code == 422

    assert client.put(f"/api/carousels/{carousel_id}", json=data["carousel"]).json()["issues"] == []

    async def fake_render(carousel, html_paths, out_dir, parallel):
        out_dir.mkdir(parents=True)
        for html in html_paths:
            (out_dir / f"{html.stem}.mp4").write_bytes(b"video")

    monkeypatch.setattr(server.renderer, "render", fake_render)
    client.post(f"/api/carousels/{carousel_id}/render")
    data = _wait(client, carousel_id)
    assert data["job"]["status"] == "done" and all(s["video"] for s in data["slides"])
    archive = client.get(f"/api/carousels/{carousel_id}/videos.zip")
    assert archive.status_code == 200 and archive.headers["content-type"] == "application/zip"


def test_generate_failure_keeps_issues_for_review(client, spec, monkeypatch):
    broken = copy.deepcopy(spec)
    broken["slides"][1]["lines"] = ["Antidisestablishmentarians"]
    calls = _fake_writer(monkeypatch, _deck(broken))
    data = _wait(client, _create(client))
    assert data["job"]["status"] == "failed" and len(calls) == server.ATTEMPTS
    assert data["carousel"] is not None and any(i["check"] == "overflow" for i in data["issues"])


def test_rejects_unknown_brand_and_bad_paths(client):
    assert client.post("/api/carousels", json={"brand": "nope", "source": "x"}).status_code == 400
    assert client.get("/api/carousels/..%2Fbrands").status_code == 404
    assert client.get("/api/carousels/missing").status_code == 404
