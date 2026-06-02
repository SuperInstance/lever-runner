"""
cli.py — `python -m lever_runner "check disk usage"`.

Prints the orchestrator result in plain text. Useful for cron jobs and
quick tests from the shell.
"""

from __future__ import annotations

import sys

from .orchestrator import do, teach, status


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m lever_runner <request>")
        print("       python -m lever_runner teach \"phrase\" | <cmd>")
        print("       python -m lever_runner status")
        return 2

    sub = argv[0]
    if sub == "teach":
        raw = " ".join(argv[1:])
        if "|" not in raw:
            print('usage: python -m lever_runner teach "phrase" | <cmd>')
            return 2
        phrase, _, cmd = raw.partition("|")
        row_id = teach(phrase.strip().strip('"'), cmd.strip())
        print(f"taught: {row_id}")
        return 0
    if sub == "status":
        s = status()
        print(f"commands: {s['command_count']}")
        return 0

    request = " ".join(argv)
    r = do(request, source="cli")
    print(f"intent:   {r.intent!r}")
    if r.match:
        print(f"matched:  {r.match.intent_phrase!r}  trust={r.match.trust_score:.1f}")
        print(f"command:  {r.match.command}")
    if r.error:
        print(f"error:    {r.error}")
    if r.run:
        print(f"exit:     {r.run.exit_code}  ({'ok' if r.run.ok else 'fail'}, {r.run.duration_sec:.2f}s)")
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
