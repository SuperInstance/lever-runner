"""
cli.py — `python -m lever_runner "check disk usage"`.

Prints the orchestrator result in plain text. Useful for cron jobs and
quick tests from the shell.

Use --chat-id to scope the store to a per-chat table (matches the
Telegram bot's chat_id handling). Default is "default".
"""

from __future__ import annotations

import argparse
import sys

from .orchestrator import do, status, teach


def main(argv: list[str]) -> int:
    # Manual arg parse: support --chat-id in front or after the subcommand.
    chat_id = "default"
    args = list(argv)
    if args and args[0] == "--chat-id":
        if len(args) < 2:
            print("--chat-id requires a value")
            return 2
        chat_id = args[1]
        args = args[2:]
    if not args:
        print("usage: python -m lever_runner [--chat-id ID] <request>")
        print('       python -m lever_runner [--chat-id ID] teach "phrase" | <cmd>')
        print("       python -m lever_runner [--chat-id ID] status")
        return 2

    sub = args[0]
    if sub == "teach":
        # Parse optional --trust=N from anywhere in the teach arg list
        trust: float | None = None
        teach_args: list[str] = []
        for a in args[1:]:
            if a.startswith("--trust="):
                try:
                    trust = float(a.split("=", 1)[1])
                except ValueError:
                    print("--trust must be a number")
                    return 2
            elif a.startswith("--trust"):
                # handled below; skip the value
                continue
            else:
                teach_args.append(a)
        raw = " ".join(teach_args)
        if "|" not in raw:
            print('usage: python -m lever_runner teach [--trust=N] "phrase" | <cmd>')
            return 2
        phrase, _, cmd = raw.partition("|")
        row_id = teach(phrase.strip().strip('"'), cmd.strip(), chat_id=chat_id, trust=trust)
        suffix = f" trust={trust:.0f}" if trust is not None else ""
        print(f"taught (chat={chat_id}){suffix}: {row_id}")
        return 0
    if sub == "status":
        s = status(chat_id=chat_id)
        print(f"chat: {s['chat_id']}  commands: {s['command_count']}")
        return 0

    request = " ".join(args)
    r = do(request, source="cli", chat_id=chat_id)
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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
