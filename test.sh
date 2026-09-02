#!/usr/bin/env bash
set -euo pipefail

export FX_UPSTREAM_BASE="http://127.0.0.1:54321"

exec pytest -v tests/
