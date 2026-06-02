"""Allow `python -m lever_runner ...` to default to the CLI.
Also exposes a `main()` function so pyproject.toml entry points can
call into it with the right argv (the entry point does NOT pass argv
itself, so we read sys.argv here)."""

import sys

from .cli import main as _cli_main


def main():
    """Entry point for `lever-runner` console script."""
    raise SystemExit(_cli_main(sys.argv[1:]))


if __name__ == "__main__":
    main()
