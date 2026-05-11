#!/usr/bin/env bash
set -euo pipefail

# Ion - Docker Entrypoint Script
# Usage: docker run <image> [web|cli|shell] [args...]

MODE="${1:-web}"
shift || true

# Pre-flight: if `./ion.db` was missing on the host when `docker compose up` ran,
# Docker creates it as an empty directory at the bind-mount target. SQLite then
# fails with an obscure "unable to open database" error. Detect this early and
# surface a fix instead. Only check when the app will touch the DB.
ensure_db_file() {
    local db_file="/opt/ion/ion.db"
    if [ -d "${db_file}" ]; then
        echo "[!] ${db_file} is a directory, not a file." >&2
        echo "[!] Docker auto-created it because the host bind source './ion.db' was missing." >&2
        echo "[!] On the host (next to docker-compose.yaml), run:" >&2
        echo "[!]     docker compose down && rm -rf ion.db && touch ion.db && docker compose up -d" >&2
        exit 1
    fi
}

case "${MODE}" in
    web)
        ensure_db_file
        PORT="${ION_PORT:-8000}"
        echo "[+] Starting Ion Web API on 0.0.0.0:${PORT} ..."
        exec uvicorn Ion.web.app:app --host 0.0.0.0 --port "${PORT}" "$@"
        ;;
    cli)
        ensure_db_file
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
  docker run -p \${ION_PORT:-8000}:\${ION_PORT:-8000} -e OPENAI_API_KEY=xxx ion
  docker run -it ion cli --interactive
  docker run -it ion shell
EOF
        exit 1
        ;;
esac
