#!/usr/bin/env bash
# Refresh requirements.lock via pip freeze, from a container or a venv.
# Preserves leading pip directives already in the lock (e.g. --extra-index-url).
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  ./lock_new_requirements.sh --container <name>   freeze inside a running container
  ./lock_new_requirements.sh --venv <path>        freeze from a local virtualenv
EOF
    exit "${1:-0}"
}

write_lock() {
    # $@ = command that prints a `pip freeze` listing on stdout
    local header body
    header=$([[ -f requirements.lock ]] && grep -E '^[[:space:]]*(#|--)' requirements.lock || true)
    body=$("$@")
    { [[ -n "$header" ]] && printf '%s\n\n' "$header"; printf '%s\n' "$body"; } > requirements.lock
    echo "wrote requirements.lock ($(wc -l < requirements.lock) lines)"
}

case "${1:-}" in
    --container)
        name="${2:?--container requires a container name}"
        docker ps --format '{{.Names}}' | grep -qx "$name" || { echo "container '$name' not running"; exit 1; }
        write_lock docker exec "$name" pip freeze --exclude-editable
        ;;
    --venv)
        venv="${2:?--venv requires a venv path}"
        [[ -x "$venv/bin/pip" ]] || { echo "no venv at '$venv'"; exit 1; }
        write_lock "$venv/bin/pip" freeze --exclude-editable
        ;;
    -h | --help) usage 0 ;;
    *) usage 1 ;;
esac
