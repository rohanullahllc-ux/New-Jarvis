"""A small message box between the assistant (which runs on a background thread) and the window.

A command such as "open the admin panel" is understood on the session thread, but a window can only be opened by the window's own
thread. The window registers a handler here (one that just emits a Qt signal, which is safe from any thread); the command calls
request("admin"). With no window (the terminal), request() returns False and the caller does something else.
"""
import threading

_handlers = {}
_lock = threading.Lock()


def register(name, handler):
    with _lock:
        _handlers[name] = handler


def unregister(name, handler=None):
    with _lock:
        if handler is None or _handlers.get(name) is handler:
            _handlers.pop(name, None)


def request(name, *arguments):
    """Ask the window to do ``name``. True if a window took the request."""
    with _lock:
        handler = _handlers.get(name)
    if handler is None:
        return False
    try:
        handler(*arguments)
        return True
    except Exception:                                   # noqa: BLE001 - a window that cannot do it is the same as no window
        return False
