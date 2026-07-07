from grove.start import app, socketio
from grove.services.system.workflow._health import start_monitor
from grove.services.system.workflow._maintenance import start_maintenance

if __name__ == "__main__":
    # Web-only entrypoint (worker imports grove.start, not this), so these run in exactly one process.
    start_monitor(app)
    start_maintenance(app)
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
