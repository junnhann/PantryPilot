"""Fridge scan tests: image prep, normalising AI output, demo mode, route. No network."""
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import ai, config
from app.imaging import prepare_image
from app.main import app
from app.models import FridgeItem, FridgeScan

NAMES = ["plain flour", "milk", "egg", "butter", "baking powder"]


def make_png(width=3000, height=2000, mode="RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_image_resized_to_1000_wide_jpeg():
    out = Image.open(io.BytesIO(prepare_image(make_png())))
    assert out.format == "JPEG" and out.width == 1000 and out.height == 667


def test_small_image_not_upscaled_and_rgba_ok():
    out = Image.open(io.BytesIO(prepare_image(make_png(400, 300, "RGBA"))))
    assert out.width == 400


def test_bad_image_gives_friendly_400():
    with pytest.raises(ai.AIError) as e:
        prepare_image(b"not an image")
    assert e.value.status == 400


def test_normalise_drops_extras_and_fills_missing():
    raw = FridgeScan(items=[
        FridgeItem(name="MILK", have=True, confidence="high"),
        FridgeItem(name="ketchup", have=True, confidence="high"),  # not in recipe -> dropped
    ])
    out = ai._normalise_scan(raw, NAMES)
    assert [i.name for i in out.items] == NAMES
    assert out.items[1].have is True  # case-insensitive match kept
    assert out.items[0].have is False and out.items[0].confidence == "low"  # missing -> check me


async def test_demo_scan(monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", True)
    res = await ai.scan_fridge(make_png(), NAMES)
    by = {i.name: i for i in res.items}
    assert by["milk"].have and by["milk"].confidence == "high"
    assert by["baking powder"].confidence == "low"
    assert not by["plain flour"].have


def test_route_ok_and_bad_input(monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", True)
    c = TestClient(app)
    ok = c.post("/api/fridge-scan", files={"image": ("f.png", make_png(), "image/png")},
                data={"ingredients": json.dumps(NAMES)})
    assert ok.status_code == 200 and len(ok.json()["items"]) == len(NAMES)
    bad_img = c.post("/api/fridge-scan", files={"image": ("f.txt", b"hello", "text/plain")},
                     data={"ingredients": json.dumps(NAMES)})
    assert bad_img.status_code == 400
    bad_list = c.post("/api/fridge-scan", files={"image": ("f.png", make_png(), "image/png")},
                      data={"ingredients": "nope"})
    assert bad_list.status_code == 400
