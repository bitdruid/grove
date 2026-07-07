#!/bin/bash
set -e

# system deps
MISSING=""
command -v whois     >/dev/null 2>&1 || MISSING="$MISSING whois"
command -v tesseract >/dev/null 2>&1 || MISSING="$MISSING tesseract"
command -v gs        >/dev/null 2>&1 || MISSING="$MISSING ghostscript"
command -v exiftool  >/dev/null 2>&1 || MISSING="$MISSING exiftool"
command -v redis-server >/dev/null 2>&1 || MISSING="$MISSING redis"

if [ -n "$MISSING" ]; then
    echo "Missing system dependencies:$MISSING"
    read -p "Install them now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if command -v pacman >/dev/null 2>&1; then
            sudo pacman -S --needed whois tesseract tesseract-data-eng tesseract-data-deu ghostscript perl-image-exiftool redis
        elif command -v apt >/dev/null 2>&1; then
            sudo apt install -y whois tesseract-ocr tesseract-ocr-eng tesseract-ocr-deu ghostscript libimage-exiftool-perl redis-server
        else
            echo "Unsupported package manager. Please install manually:$MISSING"
            exit 1
        fi
    else
        echo "Cannot continue without:$MISSING"
        exit 1
    fi
fi

# python env
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python 3.13 virtual environment..."
    python3.13 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

echo "Installing dependencies..."
pip install -r requirements.txt
pip install -e .

echo "Installing Playwright Firefox..."
playwright install firefox

# redis
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-$REDIS_URL}"
export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-$REDIS_URL}"
export SOCKETIO_MESSAGE_QUEUE="${SOCKETIO_MESSAGE_QUEUE:-$REDIS_URL}"

if ! pgrep -x redis-server >/dev/null; then
    echo "Starting redis-server..."
    redis-server --daemonize yes
fi

# celery worker
echo "Starting Celery worker..."
celery -A worker.celery_app worker --loglevel=info --concurrency=1 &
WORKER_PID=$!
trap "echo 'Stopping worker [$WORKER_PID]'; kill $WORKER_PID 2>/dev/null || true" EXIT

# web
echo "Starting application..."
python3 entry.py
