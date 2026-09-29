"""Initialize the canonical database from numbered SQL migrations."""

import sys

from structural_break.services.foundation import main

if __name__ == "__main__":
    raise SystemExit(main(["init-db", *sys.argv[1:]]))
