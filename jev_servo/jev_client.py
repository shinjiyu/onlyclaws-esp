"""Thin TypeSafe JEV system-one client."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://api.typesafe.ai/v1/systemone"
_ROOT = Path(__file__).resolve().parents[1]
_LOCAL_KEY = _ROOT / ".local" / "jev_key"


class JevError(RuntimeError):
    pass


def _load_token(explicit: str | None) -> str | None:
    if explicit:
        return explicit.strip()
    env = os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_KEY")
    if env:
        return env.strip()
    if _LOCAL_KEY.is_file():
        return _LOCAL_KEY.read_text(encoding="utf-8").strip() or None
    return None


class JevClient:
    def __init__(
        self,
        token: str | None = None,
        model: str = "jev-latest",
        timeout: float = 60.0,
    ):
        self.token = _load_token(token)
        if not self.token:
            raise JevError(
                "missing TYPESAFE_API_KEY / JEV_KEY / onlyclaws-esp/.local/jev_key"
            )
        self.model = model
        self.timeout = timeout

    def choose(
        self,
        state: str,
        question_id: str,
        instructions: str,
        criteria: dict[str, str],
    ) -> dict:
        body = {
            "model": self.model,
            "state": state,
            "questions": {
                question_id: {
                    "type": "choice",
                    "instructions": instructions,
                    "criteria": criteria,
                }
            },
        }
        payload, latency_ms = self._post(body)
        answer = payload.get("answers", {}).get(question_id) or {}
        choice = answer.get("choice")
        probabilities = answer.get("probabilities") or {}
        if choice not in criteria:
            ranked = sorted(
                ((float(probabilities.get(key, 0.0)), key) for key in criteria),
                reverse=True,
            )
            choice = ranked[0][1] if ranked else "stay"
            answer = {**answer, "choice": choice, "invalid_choice": True}
        return {
            "choice": choice,
            "probabilities": {key: probabilities.get(key) for key in criteria},
            "confidence": answer.get("confidence"),
            "invalid_choice": bool(answer.get("invalid_choice")),
            "latency_ms": round(latency_ms, 1),
            "model": payload.get("model"),
        }

    def _post(self, body: dict) -> tuple[dict, float]:
        data = json.dumps(body).encode()
        request = urllib.request.Request(
            API_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        last_error: Exception | None = None
        for _ in range(2):
            started = time.perf_counter()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode()
                    status = response.status
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode()
                status = exc.code
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(1.0)
                continue
            latency_ms = (time.perf_counter() - started) * 1000
            if status != 200:
                last_error = JevError(f"HTTP {status}: {raw[:400]}")
                time.sleep(1.0)
                continue
            return json.loads(raw), latency_ms
        raise JevError(str(last_error))
