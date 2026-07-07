#!/bin/bash
# single-container launcher: redis + celery worker + web
# tini PID 1 (set in dockerfile) handles signal forwarding / zombie reaping.

set -e

# redis embedded; skipped if external
# - bind 127.0.0.1: not exposed outside the container
# - save "": disable RDB snapshots (broker + transient task results only)
# - appendonly no: same reason
REDIS_PID=""
BROKER_URL="${CELERY_BROKER_URL:-redis://127.0.0.1:6379/0}"
if echo "$BROKER_URL" | grep -qE '127\.0\.0\.1|localhost'; then
    echo "[entrypoint] starting embedded redis-server ..."
    redis-server \
        --bind 127.0.0.1 \
        --port 6379 \
        --save "" \
        --appendonly no \
        --daemonize no \
        --loglevel notice \
        &
    REDIS_PID=$!

    # wait for redis to accept connections
    for i in $(seq 1 20); do
        if redis-cli -h 127.0.0.1 ping >/dev/null 2>&1; then
            echo "[entrypoint] redis ready"
            break
        fi
        sleep 0.2
    done
else
    echo "[entrypoint] external broker configured ($BROKER_URL), skipping embedded redis"
fi

# celery worker
echo "[entrypoint] starting celery worker ..."
celery -A worker.celery_app worker --loglevel=info --concurrency=1 &
WORKER_PID=$!

# propagate SIGTERM/SIGINT to children, then wait
shutdown() {
    echo "[entrypoint] shutting down ..."
    kill -TERM "$WEB_PID"    2>/dev/null || true
    kill -TERM "$WORKER_PID" 2>/dev/null || true
    kill -TERM "$REDIS_PID"  2>/dev/null || true
    wait
    exit 0
}
trap shutdown TERM INT

# web (foreground)
echo "[entrypoint] starting web ..."
python3 /app/entry.py &
WEB_PID=$!

# if any of the running processes exits, tear the rest down
# (REDIS_PID is empty when an external broker is used)
wait -n $REDIS_PID "$WORKER_PID" "$WEB_PID"
shutdown
