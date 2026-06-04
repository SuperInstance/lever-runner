"""
cli.py — Production CLI for lever-runner.

Subcommands:
    lever-runner <request>        Execute a natural-language request
    lever-runner teach            Teach a new command
    lever-runner status           Show store status
    lever-runner doctor           Health check
    lever-runner stats            Usage statistics
    lever-runner export           Export commands
    lever-runner import           Import commands
    lever-runner --version        Show version
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import __version__


def _get_version() -> str:
    """Get version from package metadata, falling back to hardcoded."""
    return __version__


def _cmd_do(ns: argparse.Namespace) -> int:
    """Execute a natural-language command request."""
    from .orchestrator import do

    request = " ".join(ns.request)
    r = do(request, source="cli", chat_id=ns.chat_id)
    print(f"intent:   {r.intent!r}")
    if r.match:
        print(f"matched:  {r.match.intent_phrase!r}  trust={r.match.trust_score:.1f}")
        print(f"command:  {r.match.command}")
    if r.error:
        print(f"error:    {r.error}")
    if r.run:
        print(
            f"exit:     {r.run.exit_code}  ({'ok' if r.run.ok else 'fail'}, {r.run.duration_sec:.2f}s)"
        )
        if r.run.stdout.strip():
            print("--- stdout ---")
            print(r.run.stdout.rstrip())
        if r.run.stderr.strip():
            print("--- stderr ---")
            print(r.run.stderr.rstrip())
    print(f"tokens:   in={r.tokens_in}  out={r.tokens_out}  total={r.total_tokens}")
    return 0 if r.ok else 1


def _cmd_teach(ns: argparse.Namespace) -> int:
    """Teach a new command: phrase | command."""
    from .orchestrator import teach

    raw = ns.teach_args
    if "|" not in raw:
        print('usage: lever-runner teach "phrase" | "command"')
        print('  e.g: lever-runner teach "show my ip" | "curl ifconfig.me"')
        return 2

    phrase, _, cmd = raw.partition("|")
    row_id = teach(
        phrase.strip().strip('"'),
        cmd.strip().strip('"'),
        chat_id=ns.chat_id,
        trust=ns.trust,
    )
    suffix = f" trust={ns.trust:.0f}" if ns.trust is not None else ""
    print(f"✓ taught (chat={ns.chat_id}){suffix}: {row_id}")
    return 0


def _cmd_status(ns: argparse.Namespace) -> int:
    """Show store status."""
    from .orchestrator import status

    s = status(chat_id=ns.chat_id)
    print(f"chat: {s['chat_id']}  commands: {s['command_count']}")
    return 0


def _cmd_doctor(ns: argparse.Namespace) -> int:
    """Run health diagnostics."""
    from .doctor import main as doctor_main

    return doctor_main()


def _cmd_stats(ns: argparse.Namespace) -> int:
    """Show usage statistics."""
    from .store import CommandStore

    store = CommandStore(chat_id=ns.chat_id)
    count = store.count()

    # Read token logs if available
    tok_path = os.getenv("TOKEN_LOG_PATH", "./data/token_usage.jsonl")
    embed_path = os.getenv("EMBED_LOG_PATH", "./data/embed_usage.jsonl")

    total_tokens_in = 0
    total_tokens_out = 0
    total_requests = 0
    cache_hits = 0

    for path in [tok_path, embed_path]:
        if not os.path.exists(path):
            continue
        try:
            with open(path) as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("type") == "llm_call":
                            total_requests += 1
                            total_tokens_in += entry.get("tokens_in", 0)
                            total_tokens_out += entry.get("tokens_out", 0)
                        elif entry.get("type") == "cache_hit":
                            cache_hits += 1
                    except (json.JSONDecodeError, KeyError):
                        continue
        except OSError:
            continue

    print(f"lever-runner stats (chat={ns.chat_id})")
    print(f"{'=' * 45}")
    print(f"  Commands taught:    {count}")

    if total_requests > 0:
        print(f"  Commands run:       {total_requests}")
        print(f"  Cache hits:         {cache_hits}")
        hit_rate = cache_hits / (total_requests + cache_hits) * 100 if (total_requests + cache_hits) > 0 else 0
        print(f"  Cache hit rate:     {hit_rate:.1f}%")
        print(f"  Tokens consumed:    {total_tokens_in + total_tokens_out}")
        print(f"    (in={total_tokens_in}, out={total_tokens_out})")

        # Estimate savings vs raw LLM
        # Raw LLM would need ~500 tokens per request for tool schema + prompt
        raw_cost = total_requests * 500 + cache_hits * 500
        actual_cost = total_tokens_in + total_tokens_out
        if raw_cost > 0:
            savings = (1 - actual_cost / raw_cost) * 100
            print(f"  Token savings:      ~{savings:.0f}% vs raw LLM")
            print(f"    (raw would use ~{raw_cost} tokens)")

    # Most-used commands
    if count > 0:
        try:
            import lancedb
            db_path = os.getenv("LANCEDB_PATH", "./data/lever.lancedb")
            db = lancedb.connect(db_path)
            table_name = f"commands_{ns.chat_id}" if ns.chat_id != "default" else "commands"
            if table_name in [t.name for t in db.list_tables().tables]:
                tbl = db.open_table(table_name)
                df = tbl.to_pandas()
                if "run_count" in df.columns:
                    top = df.nlargest(5, "run_count")[["intent_phrase", "command", "run_count"]]
                    if not top.empty:
                        print(f"\n  Top commands:")
                        for _, row in top.iterrows():
                            rc = row.get("run_count", 0)
                            print(f"    {rc:>4d}x  {row['intent_phrase'][:40]:<40s}  →  {row['command'][:50]}")
        except Exception:
            pass

    print()
    return 0


def _cmd_export(ns: argparse.Namespace) -> int:
    """Export commands in various formats."""
    from .store import CommandStore

    store = CommandStore(chat_id=ns.chat_id)
    commands = store.list_all()

    if not commands:
        print(f"No commands found for chat={ns.chat_id}")
        return 1

    fmt = ns.format
    output = ns.output

    if fmt == "json":
        data = {
            "version": _get_version(),
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "chat_id": ns.chat_id,
            "commands": [],
        }
        for cmd in commands:
            entry = {
                "intent_phrase": cmd.get("intent_phrase", ""),
                "command": cmd.get("command", ""),
                "trust_score": cmd.get("trust_score", 0.5),
            }
            if "run_count" in cmd:
                entry["run_count"] = cmd["run_count"]
            data["commands"].append(entry)

        out = json.dumps(data, indent=2)
        if output:
            Path(output).write_text(out)
            print(f"✓ Exported {len(commands)} commands to {output}")
        else:
            print(out)

    elif fmt == "aliases":
        lines = ["#!/bin/bash", "# lever-runner shell aliases", f"# Exported {len(commands)} commands", ""]
        for cmd in commands:
            intent = cmd.get("intent_phrase", "")
            command = cmd.get("command", "")
            # Convert intent to alias name
            alias = intent.lower().replace(" ", "_").replace("-", "_")
            alias = "".join(c for c in alias if c.isalnum() or c == "_")[:30]
            if alias:
                lines.append(f"alias {alias}='{command}'  # {intent}")
        out = "\n".join(lines) + "\n"
        if output:
            Path(output).write_text(out)
            os.chmod(output, 0o755)
            print(f"✓ Exported {len(commands)} aliases to {output}")
        else:
            print(out)

    elif fmt == "nail":
        # Delegate to existing export_nail module
        from .export_nail import export_to_nail
        if not output:
            print("usage: lever-runner export --format nail --output <file.nail>")
            return 2
        export_to_nail(ns.chat_id, output, pack_name=ns.pack)
        print(f"✓ Exported .nail pack to {output}")

    else:
        print(f"Unknown format: {fmt}. Use: json, aliases, nail")
        return 2

    return 0


def _cmd_import(ns: argparse.Namespace) -> int:
    """Import commands from various sources."""
    source = ns.source
    fmt = ns.format

    if not os.path.exists(source):
        print(f"File not found: {source}")
        return 1

    from .store import CommandStore

    store = CommandStore(chat_id=ns.chat_id)
    imported = 0

    if fmt == "json":
        with open(source) as f:
            data = json.load(f)

        commands = data.get("commands", [])
        for cmd in commands:
            phrase = cmd.get("intent_phrase", "")
            command = cmd.get("command", "")
            trust = cmd.get("trust_score", 0.5)
            if phrase and command:
                store.teach(phrase, command, trust=trust)
                imported += 1
        print(f"✓ Imported {imported}/{len(commands)} commands from {source}")

    elif fmt == "skillpack":
        # Import from directory of .md files with command templates
        skill_dir = Path(source)
        if not skill_dir.is_dir():
            print(f"Not a directory: {source}")
            return 1

        for md_file in sorted(skill_dir.glob("*.md")):
            content = md_file.read_text()
            # Parse markdown skill packs: ## command\n phrase | command
            for line in content.split("\n"):
                line = line.strip()
                if "|" in line and not line.startswith("#"):
                    parts = line.split("|", 1)
                    if len(parts) == 2:
                        phrase = parts[0].strip().strip("- ")
                        command = parts[1].strip()
                        if phrase and command:
                            store.teach(phrase, command)
                            imported += 1
        print(f"✓ Imported {imported} commands from skill pack {source}")

    elif fmt == "history":
        # Parse bash/zsh history for common patterns
        with open(source) as f:
            lines = f.readlines()

        # Extract commands (strip line numbers from history format)
        commands_seen: dict[str, int] = {}
        for line in lines:
            line = line.strip()
            # Skip empty, comments, history prefixes
            if not line or line.startswith("#"):
                continue
            # Strip leading line number from bash history
            if line[0:1].isdigit() and " " in line:
                _, _, cmd = line.partition(" ")
            else:
                cmd = line
            cmd = cmd.strip()
            if cmd and len(cmd) > 3 and not cmd.startswith("lever"):
                commands_seen[cmd] = commands_seen.get(cmd, 0) + 1

        # Import top commands by frequency
        sorted_cmds = sorted(commands_seen.items(), key=lambda x: -x[1])
        imported = 0
        for cmd, freq in sorted_cmds[:ns.limit]:
            # Generate intent from command
            intent = cmd.split()[0] + " " + " ".join(cmd.split()[1:3])
            intent = intent.strip()[:60]
            store.teach(intent, cmd)
            imported += 1
        print(f"✓ Imported top {imported} commands from history ({len(commands_seen)} unique)")
        print(f"  Most common: {sorted_cmds[0][0]} ({sorted_cmds[0][1]}x)" if sorted_cmds else "")

    else:
        print(f"Unknown format: {fmt}. Use: json, skillpack, history")
        return 2

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="lever-runner",
        description="Post-inference command execution. The LLM never sees your shell.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  lever-runner "check disk usage"           # execute a command
  lever-runner teach "show ip" | "curl ifconfig.me"  # teach a command
  lever-runner doctor                       # health check
  lever-runner stats                        # usage statistics
  lever-runner export --format json         # export as JSON
  lever-runner import commands.json         # import from another instance
""",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"lever-runner {_get_version()}",
    )
    parser.add_argument(
        "--chat-id", default="default",
        help="scope commands to a per-chat table (default: %(default)s)",
    )

    sub = parser.add_subparsers(dest="command", help="sub-command help")

    # teach
    p_teach = sub.add_parser("teach", help="teach a new command (phrase | command)")
    p_teach.add_argument("teach_args", nargs="+", help='"phrase" | "command"')
    p_teach.add_argument("--trust", type=float, default=None, help="trust score 0-100 (default: auto)")

    # status
    sub.add_parser("status", help="show store status")

    # doctor
    sub.add_parser("doctor", help="run health diagnostics")

    # stats
    sub.add_parser("stats", help="show usage statistics")

    # export
    p_export = sub.add_parser("export", help="export taught commands")
    p_export.add_argument("--format", "-f", choices=["json", "aliases", "nail"],
                          default="json", help="export format (default: %(default)s)")
    p_export.add_argument("--output", "-o", help="output file path")
    p_export.add_argument("--pack", help="pack name for .nail format")

    # import
    p_import = sub.add_parser("import", help="import commands")
    p_import.add_argument("source", help="source file or directory")
    p_import.add_argument("--format", "-f", choices=["json", "skillpack", "history"],
                          default="json", help="import format (default: %(default)s)")
    p_import.add_argument("--limit", type=int, default=50,
                          help="max commands to import from history (default: %(default)s)")

    return parser


def main(argv: list[str] | None = None) -> int:
    # Manual parse to handle no-subcommand case (argparse subparsers
    # don't play well with free-form positional args as the default)
    raw_args = argv if argv is not None else sys.argv[1:]

    SUBCOMMANDS = {"teach", "status", "doctor", "stats", "export", "import"}

    if not raw_args:
        parser.print_help()
        return 2

    # Handle --version early
    if "--version" in raw_args or "-V" in raw_args:
        print(f"lever-runner {_get_version()}")
        return 0

    # Extract --chat-id from anywhere
    chat_id = "default"
    filtered = []
    skip_next = False
    for i, a in enumerate(raw_args):
        if skip_next:
            skip_next = False
            continue
        if a == "--chat-id" and i + 1 < len(raw_args):
            chat_id = raw_args[i + 1]
            skip_next = True
            continue
        if a.startswith("--chat-id="):
            chat_id = a.split("=", 1)[1]
            continue
        filtered.append(a)

    if not filtered:
        parser.print_help()
        return 2

    if filtered[0] in SUBCOMMANDS:
        # Use argparse for subcommands
        ns = parser.parse_args(raw_args)
        ns.chat_id = chat_id

        if ns.command == "teach":
            ns.teach_args = " ".join(ns.teach_args)
            return _cmd_teach(ns)
        elif ns.command == "status":
            return _cmd_status(ns)
        elif ns.command == "doctor":
            return _cmd_doctor(ns)
        elif ns.command == "stats":
            return _cmd_stats(ns)
        elif ns.command == "export":
            return _cmd_export(ns)
        elif ns.command == "import":
            return _cmd_import(ns)
        else:
            parser.print_help()
            return 2
    else:
        # No subcommand — treat everything as a request
        ns = argparse.Namespace(chat_id=chat_id, request=filtered)
        return _cmd_do(ns)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
