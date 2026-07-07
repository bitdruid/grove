FROM python:3.13-slim

RUN apt-get -qq update && apt-get -qq --yes install --no-install-recommends \
    # build wheels without manylinux binaries (pdftotext, cffi); git fetches sublist3r
    gcc g++ libffi-dev libpoppler-cpp-dev git \
    # pipeline tools
    wget whois libimage-exiftool-perl \
    # ocr engines (tesseract also does page orientation) + libmagic for python-magic
    ghostscript tesseract-ocr tesseract-ocr-eng tesseract-ocr-deu libmagic1 \
    # embedded broker + tiny init that reaps zombies and forwards signals
    redis-server tini \
    && apt-get autoremove --yes \
    && rm -rf /var/lib/apt/lists/*

# requirements.lock = frozen exact versions for reproducible builds.
COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r /app/requirements.lock

# playwright headless browser (+ system libs)
RUN playwright install --with-deps firefox \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# requirements.txt is copied for pyproject.toml's hatch-requirements-txt hook,
# which reads it for the editable install's metadata
# --no-deps: everything is installed from lock, only registers the local package
COPY grove/ /app/grove
COPY entry.py worker.py docker-entrypoint.sh pyproject.toml requirements.txt /app/
RUN chmod +x /app/docker-entrypoint.sh \
    && pip install --no-cache-dir --no-deps -e /app

ENV REDIS_URL=redis://127.0.0.1:6379/0 \
    CELERY_BROKER_URL=redis://127.0.0.1:6379/0 \
    CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0 \
    SOCKETIO_MESSAGE_QUEUE=redis://127.0.0.1:6379/0

# Runtime state dirs, so the container is self-contained without a host mount.
RUN mkdir -p /app/jobs /app/instance

ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker-entrypoint.sh"]
