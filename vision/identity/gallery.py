"""Persistent face gallery: integer IDs + SFace embeddings on disk."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

_DEFAULT_DIR = Path(__file__).resolve().parents[2] / "jev_servo" / "runs" / "face_gallery"


@dataclass
class FaceRecord:
    face_id: int
    name: str = ""
    embedding: list[float] = field(default_factory=list)
    enrolled_at: float = 0.0
    seen_n: int = 0
    last_seen_at: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class FaceGallery:
    """Match / enroll faces. Cosine similarity (higher = closer)."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        match_thresh: float = 0.36,
        auto_save: bool = True,
    ) -> None:
        self.root = Path(root) if root else _DEFAULT_DIR
        self.match_thresh = float(match_thresh)
        self.auto_save = auto_save
        self.records: dict[int, FaceRecord] = {}
        self._next_id = 1
        self.load()

    @property
    def json_path(self) -> Path:
        return self.root / "gallery.json"

    def load(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        p = self.json_path
        if not p.is_file():
            self.records = {}
            self._next_id = 1
            return
        payload = json.loads(p.read_text(encoding="utf-8"))
        self.records = {}
        for row in payload.get("faces") or []:
            rec = FaceRecord(
                face_id=int(row["face_id"]),
                name=str(row.get("name") or ""),
                embedding=[float(x) for x in (row.get("embedding") or [])],
                enrolled_at=float(row.get("enrolled_at") or 0.0),
                seen_n=int(row.get("seen_n") or 0),
                last_seen_at=float(row.get("last_seen_at") or 0.0),
            )
            self.records[rec.face_id] = rec
        self._next_id = int(payload.get("next_id") or (max(self.records, default=0) + 1))

    def save(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "next_id": self._next_id,
            "match_thresh": self.match_thresh,
            "faces": [r.as_dict() for r in sorted(self.records.values(), key=lambda r: r.face_id)],
            "saved_at": time.time(),
        }
        self.json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.json_path

    @staticmethod
    def cosine(a: np.ndarray, b: np.ndarray) -> float:
        a = np.asarray(a, dtype=np.float64).ravel()
        b = np.asarray(b, dtype=np.float64).ravel()
        na = float(np.linalg.norm(a))
        nb = float(np.linalg.norm(b))
        if na < 1e-12 or nb < 1e-12:
            return -1.0
        return float(np.dot(a, b) / (na * nb))

    def match(self, embedding: np.ndarray) -> tuple[int | None, float]:
        """Return (face_id, score) or (None, best_score)."""
        best_id: int | None = None
        best = -1.0
        for rec in self.records.values():
            if not rec.embedding:
                continue
            s = self.cosine(embedding, np.asarray(rec.embedding, dtype=np.float64))
            if s > best:
                best = s
                best_id = rec.face_id
        if best_id is not None and best >= self.match_thresh:
            return best_id, best
        return None, best

    def enroll(self, embedding: np.ndarray, *, name: str = "") -> FaceRecord:
        fid = self._next_id
        self._next_id += 1
        now = time.time()
        rec = FaceRecord(
            face_id=fid,
            name=name.strip(),
            embedding=[float(x) for x in np.asarray(embedding, dtype=np.float64).ravel().tolist()],
            enrolled_at=now,
            seen_n=1,
            last_seen_at=now,
        )
        self.records[fid] = rec
        if self.auto_save:
            self.save()
        return rec

    def touch(self, face_id: int, *, embedding: np.ndarray | None = None) -> None:
        rec = self.records.get(face_id)
        if rec is None:
            return
        rec.seen_n += 1
        rec.last_seen_at = time.time()
        # Optional EMA update of embedding for mild adaptation
        if embedding is not None and rec.embedding:
            old = np.asarray(rec.embedding, dtype=np.float64)
            new = np.asarray(embedding, dtype=np.float64).ravel()
            if old.shape == new.shape:
                blended = 0.9 * old + 0.1 * new
                n = float(np.linalg.norm(blended))
                if n > 1e-12:
                    blended = blended / n
                rec.embedding = [float(x) for x in blended.tolist()]
        if self.auto_save:
            self.save()

    def rename(self, face_id: int, name: str) -> FaceRecord | None:
        rec = self.records.get(face_id)
        if rec is None:
            return None
        rec.name = name.strip()
        if self.auto_save:
            self.save()
        return rec

    def identify_or_enroll(self, embedding: np.ndarray, *, name: str = "") -> tuple[FaceRecord, float, bool]:
        """Return (record, score, is_new)."""
        fid, score = self.match(embedding)
        if fid is not None:
            self.touch(fid, embedding=embedding)
            return self.records[fid], score, False
        rec = self.enroll(embedding, name=name)
        return rec, 1.0, True

    def list_faces(self) -> list[dict[str, Any]]:
        out = []
        for rec in sorted(self.records.values(), key=lambda r: r.face_id):
            out.append(
                {
                    "face_id": rec.face_id,
                    "name": rec.name,
                    "seen_n": rec.seen_n,
                    "enrolled_at": rec.enrolled_at,
                    "last_seen_at": rec.last_seen_at,
                }
            )
        return out
