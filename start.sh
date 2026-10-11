#!/usr/bin/env bash
cd "$(dirname "$0")"
exec uv run uvicorn dogear.server:app --host 127.0.0.1 --port 7870
