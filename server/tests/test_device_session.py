"""Contract for the device session: one socket, one in-flight message."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from device_session import SessionHub, parse_frame


def test_parse_session_frames():
    hello = parse_frame('{"type":"hello","token":"odt_x","fw":"agent-runtime"}')
    assert hello is not None and hello["type"] == "hello"
    ack = parse_frame('{"type":"ack","message_id":"abc","ok":true,"ms":12}')
    assert ack is not None and ack["message_id"] == "abc"
    assert parse_frame('{"type":"status","rssi":-40}')["type"] == "status"
    assert parse_frame('{"type":"heartbeat"}')["type"] == "heartbeat"
    assert parse_frame('{"type":"event","name":"hit"}')["name"] == "hit"
    assert parse_frame('{"type":"shell"}') is None
    assert parse_frame("not-json") is None
    assert parse_frame("[1,2]") is None


def test_one_message_in_flight():
    hub = SessionHub()
    hub.attach("dev", "sock")
    assert hub.claim("dev", "m1")
    assert not hub.claim("dev", "m2")
    assert hub.inflight("dev") == "m1"
    assert hub.release("dev", "m1")
    assert hub.inflight("dev") is None
    assert hub.claim("dev", "m2")


def test_claim_requires_a_socket():
    hub = SessionHub()
    assert not hub.claim("dev", "m1")


def test_detach_returns_the_unacked_message():
    hub = SessionHub()
    hub.attach("dev", "sock")
    hub.claim("dev", "m1")
    assert hub.detach("dev", "other") is None
    assert hub.socket("dev") == "sock"
    assert hub.detach("dev", "sock") == "m1"
    assert hub.socket("dev") is None
    assert hub.inflight("dev") is None


def test_a_new_socket_takes_the_unacked_message_back():
    hub = SessionHub()
    hub.attach("dev", "old")
    hub.claim("dev", "m1")
    assert hub.attach("dev", "new") == "m1"
    assert hub.socket("dev") == "new"
    assert hub.inflight("dev") is None
    assert hub.claim("dev", "m1")


if __name__ == "__main__":
    test_parse_session_frames()
    test_one_message_in_flight()
    test_claim_requires_a_socket()
    test_detach_returns_the_unacked_message()
    test_a_new_socket_takes_the_unacked_message_back()
    print("ok")
