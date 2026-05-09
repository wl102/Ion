#!/usr/bin/env bash
set -euo pipefail

# Ion - Docker Entrypoint Script
# Usage: docker run <image> [web|cli|shell] [args...]

MODE="${1:-web}"
shift || true

case "${MODE}" in
    web)
        echo "[+] Starting Ion Web API on 0.0.0.0:8000 ..."
        exec uvicorn Ion.web.app:app --host 0.0.0.0 --port 8000 "$@"
        ;;
    cli)
        echo "[+] Starting Ion CLI ..."
        exec ion "$@"
        ;;
    shell)
        echo "[+] Dropping into container shell ..."
        exec /bin/bash "$@"
        ;;
    *)
        cat <<EOF
Usage: docker run <image> <mode> [args...]

Modes:
  web   [uvicorn args...]   Start Web API server (default)
  cli   [ion args...]       Run Ion CLI
  shell [bash args...]      Open a bash shell inside the container

Examples:
  docker run -p 8000:8000 -e OPENAI_API_KEY=xxx ion
  docker run -it ion cli --interactive
  docker run -it ion shell
EOF
        exit 1
        ;;
esac
