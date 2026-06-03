"""
store.py — LanceDB-backed command store.

Owns the table handle, the embedder, and the four operations the rest of
the system needs: lookup, insert, teach, update_trust.

v0.2 — per-chat isolation. Each Telegram chat (or CLI --chat-id) gets
its own table named `commands_<chat_id>`. The seed pack from init_db.py
is imported into the table on first use, so a new chat starts with the
same 66 commands as everyone else but can /teach its own without
affecting (or being affected by) other chats.
"""

from __future__ import annotations

import os
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

import lancedb
from dotenv import load_dotenv

load_dotenv()

LANCEDB_PATH = os.getenv("LANCEDB_PATH", "./data/lever.lancedb")
LANCEDB_TABLE_PREFIX = os.getenv("LANCEDB_TABLE_PREFIX", "commands")
# Legacy support: the v0.1.x single-table layout used the literal name
# "commands" with no suffix. We keep that as the "default" chat's table
# so existing data survives the upgrade.
LEGACY_TABLE = "commands"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_DIM = 384

TRUST_NEW = float(os.getenv("TRUST_NEW_COMMAND", "50"))
TRUST_REWRITTEN = float(os.getenv("TRUST_REWRITTEN_COMMAND", "40"))

# Chat IDs in Telegram are integers. CLI may pass anything. We sanitize
# to a safe subset for use as a LanceDB table name (alphanumerics +
# underscore). Falls back to "default" if the input sanitizes to empty.
_TABLE_NAME_RE = re.compile(r"[^A-Za-z0-9_]")


def _table_name_for(chat_id: str) -> str:
    """Return a safe LanceDB table name for the given chat id.

    The legacy single-table layout used the bare name 'commands' with
    no suffix, so we treat chat_id == 'default' (or the empty string)
    as a request for the legacy table to preserve data across upgrades.
    """
    if chat_id in ("", "default"):
        return LEGACY_TABLE
    sanitized = _TABLE_NAME_RE.sub("_", str(chat_id))
    if not sanitized:
        return LEGACY_TABLE
    return f"{LANCEDB_TABLE_PREFIX}_{sanitized}"


def _migrate_legacy_table_if_needed(db: lancedb.DBConnection) -> None:
    """If a v0.1.x 'commands' table exists with real data and no
    'commands_default' table yet, rename it. Idempotent.
    """
    tables = set(db.list_tables().tables)
    if LEGACY_TABLE in tables and f"{LANCEDB_TABLE_PREFIX}_default" not in tables:
        # Check that legacy has at least one non-schema-seed row.
        legacy = db.open_table(LEGACY_TABLE)
        non_schema = [
            r for r in legacy.search().limit(1000).to_list()
            if r["id"] != "__schema_seed__"
        ]
        if non_schema:
            # LanceDB doesn't have a rename primitive; create the new
            # table with the same rows and drop the legacy.
            db.create_table(
                f"{LANCEDB_TABLE_PREFIX}_default",
                data=non_schema,
                mode="create",
            )
            db.drop_table(LEGACY_TABLE)


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
    """Thin wrapper around a per-chat command table. Lazy-loads the embedder.

    Each chat_id gets its own LanceDB table; the seed pack from
    `init_db.py` is bulk-imported into the table on first use, so a
    new chat starts with the same commands as everyone else but can
    /teach its own without affecting (or being affected by) other
    chats.
    """

    def __init__(self, chat_id: str = "default") -> None:
        self.chat_id = str(chat_id)
        self.table_name = _table_name_for(self.chat_id)
        Path(LANCEDB_PATH).mkdir(parents=True, exist_ok=True)
        # read_consistency_interval=0: force every read to see the latest
        # writes. Cheap on a small table, and means /teach followed
        # immediately by /do will find the newly-inserted command.
        # Override with READ_CONSISTENCY_INTERVAL_SEC in .env if profiling
        # shows a hot-path cost.
        from datetime import timedelta

        rc_interval = timedelta(seconds=float(os.getenv("READ_CONSISTENCY_INTERVAL_SEC", "0")))
        self.db = lancedb.connect(LANCEDB_PATH, read_consistency_interval=rc_interval)
        self._lock = threading.Lock()

        # One-time migration: rename the v0.1.x 'commands' table to
        # 'commands_default' if it has real data.
        _migrate_legacy_table_if_needed(self.db)

        if self.table_name not in self.db.list_tables().tables:
            # Bootstrap an empty table with a schema sample row, then
            # bulk-import the seed pack from init_db.py so this chat
            # starts with the same commands as everyone else.
            self.db.create_table(
                self.table_name,
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
            # Seed only on first creation of a chat's table. Subsequent
            # constructions for the same chat_id find the table exists
            # and skip this branch entirely.
            self.table = self.db.open_table(self.table_name)
            self._embedder = None
            self._seed_from_init_db()
        self.table = self.db.open_table(self.table_name)
        self._embedder = None

    def _seed_from_init_db(self) -> None:
        """Bulk-import SEED_COMMANDS into this chat's table.

        Called once per chat, on first construction. Encodes all intent
        phrases in a single batch for speed (~0.5s for 66 phrases vs
        ~3s one-at-a-time).
        """
        try:
            from init_db import SEED_COMMANDS
        except ImportError:
            # init_db.py may not be on the import path (e.g. when the
            # package is installed as a wheel). Fall back to a no-op;
            # the chat will start empty and the user can /teach.
            return
        if not SEED_COMMANDS:
            return
        phrases = [c["intent"] for c in SEED_COMMANDS]
        vectors = self.embedder.encode(phrases, normalize_embeddings=True, show_progress_bar=False)
        rows = []
        for c, v in zip(SEED_COMMANDS, vectors):
            rows.append({
                "id": str(uuid.uuid4()),
                "intent_phrase": c["intent"],
                "command": c["command"],
                "trust_score": TRUST_NEW,
                "success_count": 0,
                "failure_count": 0,
                "embedding": v.tolist(),
            })
        self.table.add(rows)

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

    def list_all(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        min_trust: float = 0.0,
        only_active: bool = True,
    ) -> list[dict]:
        """Return up to `limit` commands, skipping soft-deleted rows and the
        schema seed. `min_trust` filters out low-trust entries. Sorted by
        `trust_score` descending so the most-trusted commands come first.

        `offset` is implemented as a Python-side slice because lancedb's
        .to_pandas() / .search() pagination semantics vary by version; the
        tables we're listing from are O(hundreds) rows so this is fine.
        """
        # ``only_active`` filters out rows with trust_score < 1, which
        # catches any legacy zeroed-trust rows from before delete_command()
        # was renamed. For current data, delete_command() removes rows outright.
        trust_floor = max(min_trust, 1.0) if only_active else min_trust
        df = self.table.to_pandas()
        df = df[df["id"] != "__schema_seed__"]
        df = df[df["trust_score"] >= trust_floor]
        df = df.sort_values("trust_score", ascending=False)
        df = df.iloc[offset : offset + limit]
        return df.to_dict(orient="records")

    def get_by_id(self, row_id: str) -> dict | None:
        """Return one row by id, or None. Includes all metadata fields."""
        df = self.table.to_pandas()
        df = df[df["id"] == row_id]
        if df.empty:
            return None
        return df.iloc[0].to_dict()

    def find_best(self, intent_phrase: str, top_k: int = 3) -> list[Match]:
        """Return top-k matches sorted by ascending L2 distance (best first),
        dropping the schema seed.

        For template commands with {{param}} placeholders, the intent_phrase
        column stores the template (e.g. "show logs for {{container}}"), but
        the embedding is computed on the stripped version ("show logs for")
        so the search works correctly regardless of the actual argument value.
        """
        # Strip any placeholders from the query phrase for embedding
        query_phrase = strip_placeholders(intent_phrase) or intent_phrase
        vec = self._embed(query_phrase)
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
        """Insert a new command. Returns its id.

        For parameterized commands (containing {{param}} placeholders),
        the intent_phrase is stored as-is but the embedding is computed
        from the stripped version so matching works correctly.
        """
        # For template commands, embed the stripped phrase so matching works
        embed_phrase = strip_placeholders(intent_phrase) or intent_phrase
        row = {
            "id": str(uuid.uuid4()),
            "intent_phrase": intent_phrase.strip(),
            "command": command.strip(),
            "trust_score": float(trust if trust is not None else TRUST_NEW),
            "success_count": 0,
            "failure_count": 0,
            "embedding": self._embed(embed_phrase),
        }
        self.table.add([row])
        return row["id"]

    def update_trust(
        self, row_id: str, *, success: bool, trust_bump: float = 1.5, trust_penalty: float = 4.0
    ) -> None:
        """Apply a small trust adjustment + bump the appropriate counter.

        Uses a per-store lock to serialize concurrent updates to the same
        row, preventing lost updates when two requests race on the same
        command (classic TOCTOU on the read-modify-write cycle).
        """
        with self._lock:
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

    def delete_command(self, row_id: str) -> None:
        """Permanently remove a command from the table by id."""
        self.table.delete(f"id = '{row_id}'")


# ---------------------------------------------------------------------------
# Parameterized command support ({{param}} placeholders)
# ---------------------------------------------------------------------------

# Matches {{param_name}} in intent phrases and commands
_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")

# Only allow safe characters in extracted args to prevent injection
_SAFE_ARG_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def has_placeholders(text: str) -> bool:
    """True if the text contains {{param}} placeholders."""
    return bool(_PLACEHOLDER_RE.search(text))


def get_placeholders(text: str) -> list[str]:
    """Return a list of unique placeholder names in order of appearance."""
    return list(dict.fromkeys(_PLACEHOLDER_RE.findall(text)))


def strip_placeholders(text: str) -> str:
    """Remove {{param}} placeholders for embedding/matching purposes.

    This produces a clean phrase suitable for embedding without the
    template syntax, e.g. "show logs for {{container}}" → "show logs for".
    """
    return _PLACEHOLDER_RE.sub("", text).strip()


def validate_arg(name: str, value: str) -> str:
    """Validate a single argument value. Only allows alphanumeric, dash,
    underscore, and dot. Returns the value if valid, raises ValueError otherwise.

    This prevents shell injection through parameterized commands.
    """
    if not value:
        raise ValueError(f"argument {name!r} must not be empty")
    if not _SAFE_ARG_RE.match(value):
        raise ValueError(
            f"argument {name!r} contains disallowed characters: {value!r}. "
            f"Only alphanumeric, dash, underscore, and dot are allowed."
        )
    return value


def substitute_args(template: str, args: dict[str, str]) -> str:
    """Substitute {{param}} placeholders in a template with validated args.

    All placeholders in the template must have a corresponding arg value.
    All arg values are validated against the safe-character set.

    Returns the substituted string.
    """
    placeholders = get_placeholders(template)
    missing = [p for p in placeholders if p not in args]
    if missing:
        raise ValueError(f"missing arguments: {', '.join(missing)}")
    for name, value in args.items():
        validate_arg(name, value)
    result = template
    for name, value in args.items():
        result = result.replace("{{" + name + "}}", value)
    return result
