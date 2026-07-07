"""
Celery worker entrypoint.

Run with:  celery -A worker.celery_app worker --loglevel=info --concurrency=1

We import grove.start so the Flask app is built and Celery's task base is bound
to its app context (DB, extensions, etc. all become available inside tasks).
"""

from grove.start import app  # noqa: F401  — side-effect: init_celery(app)
from grove.celery_app import celery_app  # noqa: F401  — exposed for `-A worker.celery_app`
