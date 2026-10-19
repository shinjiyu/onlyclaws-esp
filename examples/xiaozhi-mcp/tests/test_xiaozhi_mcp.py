"""Unit tests with mocked HTTP and websocket. Run: python -m unittest discover -s tests -v"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import onlyclaws_mcp as oc  # noqa: E402

TOKEN = "oct_test_token"


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class HttpRecorder:
    """Stands in for urllib.request.urlopen and records requests."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode()) if req.data else None
        self.requests.append({"method": req.get_method(), "url": req.full_url,
                              "auth": req.get_header("Authorization"), "body": body})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return FakeResp(json.dumps(r).encode())


def cfg(**extra):
    env = {"ONLYCLAWS_TOKEN": TOKEN, "ONLYCLAWS_BASE_URL": "https://oc.example/",
           "ONLYCLAWS_DEVICE_ID": "A4CB8FDF8440"}
    env.update(extra)
    return oc.Config(env)


def call(c, name, args=None, responses=()):
    rec = HttpRecorder(responses)
    with mock.patch.object(oc.urllib.request, "urlopen", rec):
        res = oc.call_tool(c, name, args or {})
    text = res["content"][0]["text"]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = text
    return res["isError"], data, rec.requests


class ToolTests(unittest.TestCase):
    def test_tools_list_hides_lua_by_default(self):
        names = [t["name"] for t in oc.list_tools(cfg())]
        self.assertNotIn("onlyclaws_deploy_lua", names)
        self.assertIn("onlyclaws_show_text", names)
        names = [t["name"] for t in oc.list_tools(cfg(ONLYCLAWS_ALLOW_LUA="1"))]
        self.assertIn("onlyclaws_deploy_lua", names)

    def test_show_text_posts_push_with_bearer(self):
        err, data, reqs = call(cfg(), "onlyclaws_show_text", {"title": "Hi", "body": "开会了"},
                               [{"success": True, "message": {"id": "m1", "device_id": "a4cb8fdf8440"}}])
        self.assertFalse(err)
        self.assertEqual(data["message_id"], "m1")
        r = reqs[0]
        self.assertEqual((r["method"], r["url"]), ("POST", "https://oc.example/api/push"))
        self.assertEqual(r["auth"], f"Bearer {TOKEN}")
        self.assertEqual(r["body"], {"title": "Hi", "body": "开会了", "beep": True, "device_id": "a4cb8fdf8440"})

    def test_show_text_requires_text(self):
        err, _, reqs = call(cfg(), "onlyclaws_show_text", {"body": "  "})
        self.assertTrue(err)
        self.assertEqual(reqs, [])

    def test_devices_summarizes_sensor_meta(self):
        resp = {"success": True, "devices": [{
            "id": "a4cb8fdf8440", "name": "RLCD", "online": True, "last_seen": "t", "fw": "0.18.0",
            "ip": "10.0.0.2", "owner_email": "me@example.com",
            "meta": {"temp_c": 23.5, "humidity": 40, "battery_pct": 87, "capabilities": ["core", "panel"],
                     "api_host": "secret-ish"},
        }]}
        err, data, reqs = call(cfg(), "onlyclaws_devices", {}, [resp])
        self.assertFalse(err)
        dev = data["devices"][0]
        self.assertEqual(dev["temp_c"], 23.5)
        self.assertEqual(dev["capabilities"], ["core", "panel"])
        self.assertNotIn("owner_email", dev)
        self.assertNotIn("api_host", dev)
        self.assertEqual(reqs[0]["url"], "https://oc.example/api/devices")

    def test_beep_uses_action(self):
        err, _, reqs = call(cfg(), "onlyclaws_beep", {"device_id": "441bf6923320"},
                            [{"success": True, "message": {"id": "m2"}}])
        self.assertFalse(err)
        self.assertEqual(reqs[0]["url"], "https://oc.example/api/action")
        self.assertEqual(reqs[0]["body"], {"beep": True, "device_id": "441bf6923320"})

    def test_recent_events_clamps_limit(self):
        err, data, reqs = call(cfg(), "onlyclaws_recent_events", {"limit": 999},
                               [{"success": True, "events": [{"id": 1, "name": "heard", "data": {"word": "yes"},
                                                              "created_at": "t", "device_id": "a4cb8fdf8440"}]}])
        self.assertFalse(err)
        self.assertEqual(data["events"][0]["data"], {"word": "yes"})
        self.assertEqual(reqs[0]["url"], "https://oc.example/api/events?device_id=a4cb8fdf8440&limit=50")

    def test_script_status_and_stop(self):
        err, data, reqs = call(cfg(), "onlyclaws_script_status", {},
                               [{"success": True, "device_id": "a4cb8fdf8440", "script_state": "running"}])
        self.assertFalse(err)
        self.assertEqual(data["script_state"], "running")
        self.assertEqual(reqs[0]["url"], "https://oc.example/api/script/status?device_id=a4cb8fdf8440")
        err, _, reqs = call(cfg(), "onlyclaws_stop_script", {}, [{"success": True, "device_id": "a4cb8fdf8440"}])
        self.assertFalse(err)
        self.assertEqual(reqs[0]["url"], "https://oc.example/api/script/stop")

    def test_deploy_lua_disabled_by_default(self):
        err, data, reqs = call(cfg(), "onlyclaws_deploy_lua", {"name": "x", "source": "function on_start() end"})
        self.assertTrue(err)
        self.assertIn("ONLYCLAWS_ALLOW_LUA", data)
        self.assertEqual(reqs, [])

    def test_deploy_lua_posts_scripts_with_device(self):
        c = cfg(ONLYCLAWS_ALLOW_LUA="1")
        resp = {"success": True, "script": {"id": "s1"}, "deploy": {"success": True}}
        err, data, reqs = call(c, "onlyclaws_deploy_lua", {"name": "clock", "source": "function on_start() end",
                                                           "mode": "loop", "every_ms": 500}, [resp])
        self.assertFalse(err)
        self.assertEqual(data["script_id"], "s1")
        b = reqs[0]["body"]
        self.assertEqual(reqs[0]["url"], "https://oc.example/api/scripts")
        self.assertEqual((b["language"], b["mode"], b["every_ms"], b["device_id"]), ("lua", "loop", 500, "a4cb8fdf8440"))

    def test_deploy_lua_rejects_oversize_and_missing_device(self):
        c = cfg(ONLYCLAWS_ALLOW_LUA="1")
        err, _, reqs = call(c, "onlyclaws_deploy_lua", {"name": "x", "source": "-" * 24001})
        self.assertTrue(err)
        self.assertEqual(reqs, [])
        c2 = oc.Config({"ONLYCLAWS_TOKEN": TOKEN, "ONLYCLAWS_ALLOW_LUA": "1"})
        err, data, _ = call(c2, "onlyclaws_deploy_lua", {"name": "x", "source": "x=1"})
        self.assertTrue(err)
        self.assertIn("device_id", data)

    def test_rejects_non_agent_token_without_http(self):
        c = oc.Config({"ONLYCLAWS_TOKEN": "devtoken123"})
        err, data, reqs = call(c, "onlyclaws_devices")
        self.assertTrue(err)
        self.assertIn("oct_", data)
        self.assertEqual(reqs, [])

    def test_http_401_is_tool_error(self):
        e = urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b'{"detail":"bad"}'))
        err, data, _ = call(cfg(), "onlyclaws_devices", {}, [e])
        self.assertTrue(err)
        self.assertIn("401", data)
        self.assertNotIn(TOKEN, data)

    def test_unknown_tool(self):
        err, data, _ = call(cfg(), "nope")
        self.assertTrue(err)


class JsonRpcTests(unittest.TestCase):
    def test_initialize_list_and_notifications(self):
        c = cfg()
        init = json.loads(oc.handle_line(c, json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                                         "params": {"protocolVersion": "2024-11-05"}})))
        self.assertEqual(init["result"]["serverInfo"]["name"], "onlyclaws-xiaozhi")
        self.assertIn("tools", init["result"]["capabilities"])
        self.assertIsNone(oc.handle_line(c, '{"jsonrpc":"2.0","method":"notifications/initialized"}'))
        lst = json.loads(oc.handle_line(c, '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{"cursor":""}}'))
        self.assertEqual(len(lst["result"]["tools"]), 6)
        for t in lst["result"]["tools"]:
            self.assertEqual(t["inputSchema"]["type"], "object")

    def test_unknown_method_and_bad_json(self):
        c = cfg()
        r = json.loads(oc.handle_line(c, '{"jsonrpc":"2.0","id":3,"method":"resources/list"}'))
        self.assertEqual(r["error"]["code"], -32601)
        r = json.loads(oc.handle_line(c, "{not json"))
        self.assertEqual(r["error"]["code"], -32700)


class FakeWebSocket:
    """Async-iterable websocket double: yields queued frames, records sends."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.frames:
            raise StopAsyncIteration
        return self.frames.pop(0)

    async def send(self, data):
        self.sent.append(json.loads(data))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class BridgeTests(unittest.TestCase):
    def setUp(self):
        import xiaozhi_bridge  # needs websockets installed
        self.bridge = xiaozhi_bridge

    def test_redact_hides_token(self):
        url = "wss://api.xiaozhi.me/mcp/?token=eyJhbGciOi.secret"
        self.assertEqual(self.bridge.redact(url), "wss://api.xiaozhi.me/mcp/?token=***")
        self.assertEqual(self.bridge.redact("refused token=abc def"), "refused token=*** def")

    def test_serve_connection_roundtrip_with_mocked_http(self):
        frames = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode(),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "onlyclaws_show_text", "arguments": {"body": "你好"}}}),
        ]
        ws = FakeWebSocket(frames)
        rec = HttpRecorder([{"success": True, "message": {"id": "m9", "device_id": "a4cb8fdf8440"}}])
        with mock.patch.object(oc.urllib.request, "urlopen", rec):
            asyncio.run(self.bridge.serve_connection(ws, cfg()))
        self.assertEqual([m["id"] for m in ws.sent], [1, 2, 3])
        result = ws.sent[2]["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(json.loads(result["content"][0]["text"])["message_id"], "m9")
        self.assertEqual(rec.requests[0]["url"], "https://oc.example/api/push")

    def test_run_reconnects_after_failure(self):
        attempts = []

        def connect(url):
            attempts.append(url)
            if len(attempts) == 1:
                raise OSError("refused token=abc")
            return FakeWebSocket([json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"})])

        async def no_sleep(_):
            return None

        with mock.patch.object(self.bridge.asyncio, "sleep", no_sleep):
            asyncio.run(self.bridge.run("wss://x/mcp/?token=abc", cfg(), connect=connect, max_attempts=2))
        self.assertEqual(len(attempts), 2)

    def test_real_websocket_server_roundtrip(self):
        """Spin up a local websockets server playing the Xiaozhi endpoint."""
        import websockets

        got = []

        async def endpoint(conn):
            await conn.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}))
            got.append(json.loads(await conn.recv()))
            await conn.send(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                        "params": {"name": "onlyclaws_beep", "arguments": {}}}))
            got.append(json.loads(await conn.recv()))
            await conn.close()

        rec = HttpRecorder([{"success": True, "message": {"id": "m3"}}])

        async def main():
            async with websockets.serve(endpoint, "127.0.0.1", 0) as server:
                port = list(server.sockets)[0].getsockname()[1]
                await self.bridge.run(f"ws://127.0.0.1:{port}/mcp/?token=t", cfg(), max_attempts=1)

        with mock.patch.object(oc.urllib.request, "urlopen", rec):
            asyncio.run(asyncio.wait_for(main(), 10))
        self.assertEqual(len(got[0]["result"]["tools"]), 6)
        self.assertFalse(got[1]["result"]["isError"])
        self.assertEqual(rec.requests[0]["url"], "https://oc.example/api/action")


if __name__ == "__main__":
    unittest.main()
