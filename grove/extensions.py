import os

from flask_socketio import SocketIO as _SocketIO
from grove.services.system.emit import emit
from grove.services.system.log import Log


class SocketIO(_SocketIO):
    def init_app(self, app, **kwargs):
        super().init_app(app, **kwargs)
        from functools import partial

        from grove import events

        self.on("request_log")(partial(events.request_log, self))
        self.on("subscribe_log")(events.subscribe_log)
        self.on("unsubscribe_log")(events.unsubscribe_log)
        emit.set_socketio(self)


# message_queue lets Celery workers (other processes) emit via redis pubsub.
# Falls back to in-process queue when REDIS_URL is unset (dev without redis).
_message_queue = os.getenv("SOCKETIO_MESSAGE_QUEUE") or os.getenv("REDIS_URL")
socketio = SocketIO(async_mode="threading", message_queue=_message_queue)
logger = Log()
