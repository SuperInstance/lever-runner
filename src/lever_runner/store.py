"""
store.py — LanceDB-backed command store.

Owns the table handle, the embedder, and the four operations the rest of
the system needs: lookup, insert, teach, update_trust.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import lancedb
from dotenv import load_dotenv

load_dotenv()

LANCEDB_PATH = os.getenv("LANCEDB_PATH", "./data/lever.lancedb")
LANCEDB_TABLE = os.getenv("LANCEDB_TABLE", "commands")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_DIM = 384

TRUST_NEW = float(os.getenv("TRUST_NEW_COMMAND", "50"))
TRUST_REWRITTEN = float(os.getenv("TRUST_REWRITTEN_COMMAND", "40"))


@dataclass
class Match:
    id: str
    intent_phrase: str
    command: str
    trust_score: float
    success_count: int
    failure_count: int
    score: float  # L2 distance — LOWER is better
    similarity: float  # convenience: 1 - score (clamped)


def _get_embedder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL)


class CommandStore:
    """Thin wrapper around the `commands` table. Lazy-loads the embedder."""

    def __init__(self) -> None:
        Path(LANCEDB_PATH).mkdir(parents=True, exist_ok=True)
        # read_consistency_interval=0: force every read to see the latest
        # writes. Cheap on a small table, and means /teach followed
        # immediately by /do will find the newly-inserted command.
        # Override with READ_CONSISTENCY_INTERVAL_SEC in .env if profiling
        # shows a hot-path cost.
        from datetime import timedelta

        rc_interval = timedelta(seconds=float(os.getenv("READ_CONSISTENCY_INTERVAL_SEC", "0")))
        self.db = lancedb.connect(LANCEDB_PATH, read_consistency_interval=rc_interval)
        if LANCEDB_TABLE not in self.db.list_tables().tables:
            # Bootstrap an empty table with a schema sample row.
            self.db.create_table(
                LANCEDB_TABLE,
                data=[
                    {
                        "id": "__schema_seed__",
                        "intent_phrase": "",
                        "command": "",
                        "trust_score": 0.0,
                        "success_count": 0,
                        "failure_count": 0,
                        "embedding": [0.0] * EMBEDDING_DIM,
                    }
                ],
                mode="create",
            )
        self.table = self.db.open_table(LANCEDB_TABLE)
        self._embedder = None

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = _get_embedder()
        return self._embedder

    def _embed(self, phrase: str) -> list[float]:
        v = self.embedder.encode(phrase, normalize_embeddings=True, show_progress_bar=False)
        return v.tolist()

    def count(self) -> int:
        n = self.table.count_rows()
        rows = self.table.search().limit(1).where("id = '__schema_seed__'").to_list()
        return n - len(rows)

    def find_best(self, intent_phrase: str, top_k: int = 3) -> list[Match]:
        """Return top-k matches sorted by ascending L2 distance (best first),
        dropping the schema seed."""
        vec = self._embed(intent_phrase)
        raw = self.table.search(vec).limit(top_k + 1).to_list()
        out: list[Match] = []
        for r in raw:
            if r["id"] == "__schema_seed__":
                continue
            dist = float(r.get("_distance", 0.0) or 0.0)
            out.append(
                Match(
                    id=r["id"],
                    intent_phrase=r["intent_phrase"],
                    command=r["command"],
                    trust_score=r["trust_score"],
                    success_count=r["success_count"],
                    failure_count=r["failure_count"],
                    score=dist,
                    similarity=max(0.0, 1.0 - dist),
                )
            )
            if len(out) >= top_k:
                break
        # LanceDB returns ascending by distance, but be defensive.
        out.sort(key=lambda m: m.score)
        return out

    def teach(self, intent_phrase: str, command: str, trust: float | None = None) -> str:
        """Insert a new command. Returns its id."""
        row = {
            "id": str(uuid.uuid4()),
            "intent_phrase": intent_phrase.strip(),
            "command": command.strip(),
            "trust_score": float(trust if trust is not None else TRUST_NEW),
            "success_count": 0,
            "failure_count": 0,
            "embedding": self._embed(intent_phrase),
        }
        self.table.add([row])
        return row["id"]

    def update_trust(
        self, row_id: str, *, success: bool, trust_bump: float = 1.5, trust_penalty: float = 4.0
    ) -> None:
        """Apply a small trust adjustment + bump the appropriate counter."""
        rows = self.table.search().limit(1).where(f"id = '{row_id}'").to_list()
        if not rows:
            return
        r = rows[0]
        new_trust = float(r["trust_score"])
        if success:
            new_trust = min(100.0, new_trust + trust_bump)
        else:
            new_trust = max(0.0, new_trust - trust_penalty)
        new_success = int(r["success_count"]) + (1 if success else 0)
        new_failure = int(r["failure_count"]) + (0 if success else 1)
        self.table.update(
            where=f"id = '{row_id}'",
            values={
                "trust_score": new_trust,
                "success_count": new_success,
                "failure_count": new_failure,
            },
        )

    def soft_delete(self, row_id: str) -> None:
        self.table.delete(f"id = '{row_id}'")
