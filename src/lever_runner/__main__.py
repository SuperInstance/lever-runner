"""Allow `python -m lever_runner ...` to default to the CLI."""
from .cli import main
import sys

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
