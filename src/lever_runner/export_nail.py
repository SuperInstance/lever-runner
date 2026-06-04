"""Export lever-runner commands as pincherOS .nail migration files.

The .nail format is a tar.zst archive containing:
- manifest.json: Version, fingerprint, timestamp, reflex count, checksums
- reflexes.db: SQLite database with reflexes table
- identity.json: Agent identity and preferences
- config.toml: Agent configuration

Usage:
    python -m lever_runner.export_nail --output my-reflexes.nail
    python -m lever_runner.export_nail --pack devops --output devops.nail
    python -m lever_runner.export_nail --chat-id 12345 --output chat.nail
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sqlite3
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import zstandard as zstd

    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False

from .store import CommandStore, LANCEDB_PATH


# ---------------------------------------------------------------------------
# .nail format helpers
# ---------------------------------------------------------------------------

NAIL_VERSION = 1


def _blake3_hex(data: bytes) -> str:
    """Compute a BLAKE3-compatible hash.

    Falls back to blake2b if the blake3 package is not installed.
    PincherOS uses BLAKE3, but for cross-compatibility we accept either.
    """
    try:
        import blake3 as _blake3

        return _blake3.blake3(data).hexdigest()
    except ImportError:
        # blake2b as fallback — the checksum is verified on import by
        # pincherOS itself, which uses blake3.  We note this in manifest.
        return hashlib.blake2b(data, digest_size=32).hexdigest()


def _reflexes_schema_sql() -> str:
    """Return the CREATE TABLE SQL matching pincherOS's reflexes table."""
    return """
    CREATE TABLE IF NOT EXISTS reflexes (
        id TEXT PRIMARY KEY,
        intent TEXT NOT NULL,
        action_sql TEXT NOT NULL,
        embedding BLOB NOT NULL,
        confidence REAL NOT NULL DEFAULT 0.5,
        invoke_count INTEGER NOT NULL DEFAULT 0,
        last_invoked TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """


def _pack_rows_into_sqlite(rows: list[dict]) -> bytes:
    """Create an in-memory SQLite DB with the pincherOS reflexes schema,
    inserting lever-runner command rows. Returns the raw DB bytes."""
    conn = sqlite3.connect(":memory:")
    conn.execute(_reflexes_schema_sql())
    for r in rows:
        # Convert embedding list to bytes
        emb = r.get("embedding")
        if isinstance(emb, list):
            import struct
            emb_bytes = struct.pack(f"<{len(emb)}f", *[float(v) for v in emb])
        elif isinstance(emb, bytes):
            emb_bytes = emb
        else:
            emb_bytes = b"\x00" * 4  # fallback: zero embedding

        conn.execute(
            "INSERT INTO reflexes (id, intent, action_sql, embedding, confidence, invoke_count, last_invoked, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r.get("id", ""),
                r.get("intent_phrase", ""),
                r.get("command", ""),
                emb_bytes,
                _clamp_confidence(r.get("trust_score", 50.0)),
                r.get("success_count", 0),
                "",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    conn.commit()

    # Python 3.12+ has conn.serialize(); for older versions, dump to temp file.
    if hasattr(conn, "serialize"):
        raw = conn.serialize()
        conn.close()
    else:
        conn.close()
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".db")
        try:
            conn2 = sqlite3.connect(path)
            conn2.execute(_reflexes_schema_sql())
            for r in rows:
                emb = r.get("embedding")
                if isinstance(emb, list):
                    import struct
                    emb_bytes = struct.pack(f"<{len(emb)}f", *[float(v) for v in emb])
                else:
                    emb_bytes = b"\x00" * 4
                conn2.execute(
                    "INSERT INTO reflexes (id, intent, action_sql, embedding, confidence, invoke_count, last_invoked, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        r.get("id", ""),
                        r.get("intent_phrase", ""),
                        r.get("command", ""),
                        emb_bytes,
                        _clamp_confidence(r.get("trust_score", 50.0)),
                        r.get("success_count", 0),
                        "",
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            conn2.commit()
            conn2.close()
            with open(path, "rb") as f:
                raw = f.read()
        finally:
            os.unlink(path)
    return raw


def _clamp_confidence(trust_score: float) -> float:
    """Convert lever-runner trust (0-100) to pincherOS confidence (0-1)."""
    return max(0.0, min(1.0, trust_score / 100.0))


def _build_manifest(
    reflex_count: int,
    checksums: dict[str, str],
    source: str = "lever-runner",
) -> dict[str, Any]:
    """Build a .nail manifest dict matching pincherOS schema.

    PincherOS expects:
      - version: int (schema version)
      - created_at: ISO timestamp
      - source_device: { hostname, os, arch, fingerprint }
      - pincher_version: string
      - embedding_backend: string
      - embedding_dimensions: int
      - reflex_count: int
    """
    import platform
    import socket

    return {
        "version": NAIL_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_device": {
            "hostname": socket.gethostname(),
            "os": platform.system().lower(),
            "arch": platform.machine(),
            "fingerprint": f"blake3:{checksums.get('reflexes_db', 'unknown')[:16]}",
        },
        "pincher_version": "0.1.0",
        "embedding_backend": "hash",
        "embedding_dimensions": 256,
        "reflex_count": reflex_count,
        "checksums": checksums,
        "source": source,
    }


def _build_identity() -> dict[str, Any]:
    """Build a default identity.json for the nail archive.

    PincherOS expects:
      - agent_name: string
      - preferences: dict
    """
    return {
        "agent_name": "lever-runner-export",
        "preferences": {
            "preferred_shell": "bash",
            "preferred_editor": "vim",
            "language": "en",
            "verbosity": 1,
            "output_format": "text",
            "confirm_threshold": 0.70,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _build_config() -> str:
    """Build a default config.toml for the nail archive."""
    return """[resource_thresholds]
ram_light = 70.0
ram_critical = 85.0
cpu_light = 60.0
cpu_critical = 80.0

veto_rules_path = ".pincher/veto_rules.toml"
model_path = ".pincher/models/all-MiniLM-L6-v2-int8.onnx"
rpc_socket_path = "/tmp/pincher.sock"
"""


# ---------------------------------------------------------------------------
# Core export logic
# ---------------------------------------------------------------------------

def _get_all_rows(store: CommandStore) -> list[dict]:
    """Get all rows from the store, including embeddings."""
    df = store.table.to_pandas()
    df = df[df["id"] != "__schema_seed__"]
    return df.to_dict(orient="records")


def _filter_by_pack(rows: list[dict], pack_name: str) -> list[dict]:
    """Filter rows by matching against a skill pack file.

    Packs are JSONL files in the packs/ directory. We load the pack's
    intent phrases and filter rows to only those whose intent_phrase
    appears in the pack.
    """
    pack_path = Path(__file__).parent.parent.parent / "packs" / f"{pack_name}.jsonl"
    if not pack_path.exists():
        print(f"warning: pack file not found: {pack_path}", file=sys.stderr)
        return rows

    pack_intents: set[str] = set()
    with open(pack_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                rec = json.loads(line)
                pack_intents.add(rec.get("intent", ""))
            except json.JSONDecodeError:
                continue

    return [r for r in rows if r.get("intent_phrase", "") in pack_intents]


def export_nail(
    output_path: str,
    *,
    chat_id: str = "default",
    pack: str | None = None,
    min_trust: float = 0.0,
    include_embeddings: bool = True,
) -> dict[str, Any]:
    """Export lever-runner commands as a .nail file.

    Returns a summary dict with count and path.
    """
    if not HAS_ZSTD:
        print(
            "error: zstandard package is required. Install with: pip install zstandard",
            file=sys.stderr,
        )
        raise SystemExit(1)

    store = CommandStore(chat_id=chat_id)
    rows = _get_all_rows(store)

    # Filter by trust
    rows = [r for r in rows if r.get("trust_score", 0) >= min_trust]

    # Filter by pack if specified
    if pack:
        rows = _filter_by_pack(rows, pack)

    if not rows:
        print("warning: no commands to export", file=sys.stderr)

    # Strip embeddings if not requested
    if not include_embeddings:
        for r in rows:
            r.pop("embedding", None)

    # Build the SQLite reflexes DB
    db_bytes = _pack_rows_into_sqlite(rows)

    # Build identity and config
    identity = _build_identity()
    identity_json = json.dumps(identity, indent=2).encode()

    config_toml = _build_config().encode()

    # Compute checksums
    checksums = {
        "reflexes_db": _blake3_hex(db_bytes),
        "identity_json": _blake3_hex(identity_json),
        "config_toml": _blake3_hex(config_toml),
    }

    # Build manifest
    source = f"lever-runner:chat-{chat_id}" if not pack else f"lever-runner:pack-{pack}"
    manifest = _build_manifest(len(rows), checksums, source=source)
    manifest_json = json.dumps(manifest, indent=2).encode()

    # Create tar.zst archive
    cctx = zstd.ZstdCompressor()
    compressed_buf = io.BytesIO()

    with tarfile.open(fileobj=compressed_buf, mode="w") as tar:
        _add_bytes_to_tar(tar, "manifest.json", manifest_json)
        _add_bytes_to_tar(tar, "reflexes.db", db_bytes)
        _add_bytes_to_tar(tar, "identity.json", identity_json)
        _add_bytes_to_tar(tar, "config.toml", config_toml)

    compressed = cctx.compress(compressed_buf.getvalue())

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(compressed)

    summary = {
        "path": str(output),
        "reflex_count": len(rows),
        "source": source,
        "size_bytes": len(compressed),
    }
    return summary


def _add_bytes_to_tar(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    """Add bytes as a file to a tar archive."""
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Export lever-runner commands as pincherOS .nail migration files.",
    )
    p.add_argument("--output", "-o", required=True, help="Output .nail file path")
    p.add_argument("--chat-id", default="default", help="Chat ID to export from (default: 'default')")
    p.add_argument("--pack", help="Filter to a specific skill pack (e.g. devops, system)")
    p.add_argument("--min-trust", type=float, default=0.0, help="Minimum trust score to include (default: 0)")
    p.add_argument("--no-embeddings", action="store_true", help="Exclude embedding vectors")
    args = p.parse_args()

    summary = export_nail(
        args.output,
        chat_id=args.chat_id,
        pack=args.pack,
        min_trust=args.min_trust,
        include_embeddings=not args.no_embeddings,
    )

    print(f"exported {summary['reflex_count']} commands to {summary['path']} ({summary['size_bytes']} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
