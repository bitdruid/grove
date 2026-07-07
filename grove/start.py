import os

from flask import Flask
from flask_minify import Minify
from werkzeug.middleware.proxy_fix import ProxyFix

from grove.api import a
from grove.db import database
from grove.extensions import logger, socketio
from grove.routes import r
from grove.services.system.emit import emit
from grove.services.system.workflow.jobmaster import jm as jobmaster

app = Flask(__name__)

# Reverse-proxy support. When behind nginx, send these headers from the proxy:
# X-Forwarded-For, X-Forwarded-Proto, X-Forwarded-Host, X-Forwarded-Prefix
# X-Forwarded-Prefix lets the app live under a sub-path (e.g. /thisapp/here/).
# Or set SCRIPT_NAME=/thisapp/here in the environment instead.
if os.getenv("ENABLE_PROXY_FIX", "1") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

Minify(app=app, html=True, js=True, cssless=True)

app.register_blueprint(r)
app.register_blueprint(a)

socketio.init_app(app)

database.init_app(app)
logger.init_app(app)

emit.init_app()
jobmaster.init_app(app)  # binds Celery's task base to this Flask app context

if __name__ == "__main__":
    socketio.run(app, debug=True)
