"""Validate migration history and apply unapplied migrations."""

import sys

from structural_break.services.foundation import main

if __name__ == "__main__":
    raise SystemExit(main(["migrate-db", *sys.argv[1:]]))
