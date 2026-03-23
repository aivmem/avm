"""Allow running as `python -m fileorg`."""

from .fileorg import main
import sys

if __name__ == "__main__":
    sys.exit(main())
