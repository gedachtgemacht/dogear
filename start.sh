#!/usr/bin/env bash
# Starts dogear on http://127.0.0.1:7870 (pass --port, --root, --open, see python -m dogear --help)
cd "$(dirname "$0")"
exec uv run python -m dogear "$@"
