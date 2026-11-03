"""Preset catalog: copies match origins, public list/download, kind-checked deploy (ADR 0009)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import presets  # noqa: E402


def test_catalog_files_exist_and_ids_unique():
    ids = [p["id"] for p in presets.PRESETS]
    assert len(ids) == len(set(ids))
    for p in presets.PRESETS:
        assert p["kind"] in presets.KINDS
        assert presets.path_of(p).is_file(), p["file"]
        assert p["title"]["zh"] and p["title"]["en"]
        if p["kind"] == "esp32":
            assert p["file"].endswith(".lua")
            assert p["mode"] in ("once", "loop") and p["every_ms"] >= 50
        else:
            assert p["file"].endswith(".js")


def test_copies_match_origins():
    assert presets.drift() == [], "run: python server/presets.py sync"


def test_bilibili_play_is_an_oca_preset():
    oca = {p["id"]: p for p in presets.list_presets("oca")}
    assert "bilibili-play" in oca
    assert oca["bilibili-play"]["language"] == "js"
    src = presets.source(presets.get("bilibili-play"))
    assert "function onStart" in src
    assert all(p["kind"] == "esp32" for p in presets.list_presets("esp32"))


def test_sizes_fit_their_channels(oc_app):
    for p in presets.PRESETS:
        size = len(presets.source(p))
        limit = oc_app.SCRIPT_SOURCE_MAX if p["kind"] == "esp32" else oc_app.INVOKE_CONTAINER_MAX - 1024
        assert size <= limit, (p["id"], size)


# ---- routes ----


def test_public_list_and_download(client):
    r = client.get("/api/presets?kind=oca")
    assert r.status_code == 200
    assert {p["id"] for p in r.json()["presets"]} == {"bilibili-play", "oca-empty"}
    assert client.get("/api/presets?kind=phone").status_code == 400
    src = client.get("/api/presets/bilibili-play/source")
    assert src.status_code == 200
    assert 'filename="bilibili-play.js"' in src.headers["content-disposition"]
    assert src.content == presets.path_of(presets.get("bilibili-play")).read_bytes()
    inline = client.get("/api/presets/snake-lan/source?inline=1")
    assert "content-disposition" not in inline.headers
    assert client.get("/api/presets/nope/source").status_code == 404


def test_pages_served(client):
    for kind in presets.KINDS:
        r = client.get(f"/presets/{kind}/")
        assert r.status_code == 200 and "<html" in r.text.lower()
    assert client.get("/presets/phone/").status_code == 404


def test_deploy_needs_login(client):
    r = client.post("/api/presets/bilibili-play/deploy", json={"device_id": "oca000000000"})
    assert r.status_code == 401


def test_deploy_js_to_oca_enqueues_invoke(oc_app, client, login):
    login(client, "preset-oca@example.com")
    did = client.post("/api/oca/devices", json={}).json()["device"]["id"]
    r = client.post("/api/presets/bilibili-play/deploy", json={"device_id": did})
    assert r.status_code == 200, r.text
    msg_id = r.json()["message"]["id"]
    assert "body" not in r.json()["message"]
    with oc_app.db() as conn:
        row = conn.execute("SELECT type, body FROM messages WHERE id=?", (msg_id,)).fetchone()
    assert row["type"] == "invoke"
    tools = json.loads(row["body"])["tools"]
    assert tools == [{"tool": "js", "source": presets.source(presets.get("bilibili-play"))}]


def test_deploy_kind_mismatch(client, login):
    login(client, "preset-mix@example.com")
    did = client.post("/api/oca/devices", json={}).json()["device"]["id"]
    assert client.post("/api/presets/snake-lan/deploy", json={"device_id": did}).status_code == 400
    client.post("/api/devices/register", json={"device_id": "b1b2c3d4e5f6"})
    r = client.post("/api/presets/bilibili-play/deploy", json={"device_id": "b1b2c3d4e5f6"})
    assert r.status_code == 400


def test_deploy_lua_reaches_signing(client, login):
    login(client, "preset-esp@example.com")
    client.post("/api/devices/register", json={"device_id": "c1b2c3d4e5f6"})
    r = client.post("/api/presets/snake-lan/deploy", json={"device_id": "c1b2c3d4e5f6"})
    assert r.status_code == 503
    assert "signing key" in r.json()["message"]


def test_deploy_respects_reported_capabilities(oc_app, client, login):
    login(client, "preset-caps@example.com")
    client.post("/api/devices/register", json={"device_id": "d1b2c3d4e5f6"})
    with oc_app.db() as conn:
        conn.execute(
            "UPDATE devices SET meta=? WHERE id=?",
            (json.dumps({"capabilities": ["core", "panel"]}), "d1b2c3d4e5f6"),
        )
    r = client.post("/api/presets/arm-hold/deploy", json={"device_id": "d1b2c3d4e5f6"})
    assert r.status_code == 400
    assert r.json()["message"]["missing"] == ["arm"]


def test_lua_deploy_to_oca_rejected(client, login):
    login(client, "lua-oca@example.com")
    did = client.post("/api/oca/devices", json={}).json()["device"]["id"]
    r = client.post(
        "/api/scripts",
        json={"name": "x", "source": "function on_start() end", "device_id": did},
    )
    assert r.status_code == 400
