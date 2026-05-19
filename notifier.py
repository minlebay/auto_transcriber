"""
D-Bus notification wrapper for the MANUAL processing mode.

Architecture:
- A GLib daemon thread owns the dbus.SessionBus() and runs GLib.MainLoop.
  It receives ActionInvoked / NotificationClosed signals and puts them into
  a thread-safe queue.Queue.
- The Qt main thread drains that queue every 200 ms via a QTimer.

IMPORTANT: dbus.mainloop.glib.DBusGMainLoop(set_as_default=True) must be
called in main.py before any dbus.SessionBus() is instantiated anywhere.
"""

import logging
import queue
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._pending: dict[int, str] = {}  # notif_id → file_path
        self._bus = None
        self._start_glib_thread()

    # ------------------------------------------------------------------
    # GLib daemon thread
    # ------------------------------------------------------------------

    def _start_glib_thread(self) -> None:
        t = threading.Thread(target=self._glib_run, daemon=True, name='dbus-glib')
        t.start()

    def _glib_run(self) -> None:
        try:
            import dbus
            import dbus.mainloop.glib
            from gi.repository import GLib

            self._bus = dbus.SessionBus()
            self._bus.add_signal_receiver(
                self._on_action_invoked,
                signal_name='ActionInvoked',
                dbus_interface='org.freedesktop.Notifications',
                path='/org/freedesktop/Notifications',
            )
            self._bus.add_signal_receiver(
                self._on_notification_closed,
                signal_name='NotificationClosed',
                dbus_interface='org.freedesktop.Notifications',
                path='/org/freedesktop/Notifications',
            )
            loop = GLib.MainLoop()
            loop.run()
        except Exception:
            log.exception('D-Bus GLib thread failed — MANUAL mode notifications disabled')

    def _on_action_invoked(self, notif_id: int, action_key: str) -> None:
        self._queue.put(('action', int(notif_id), str(action_key)))

    def _on_notification_closed(self, notif_id: int, reason: int) -> None:
        # reason: 1=expired, 2=dismissed, 3=action invoked, 4=other
        self._queue.put(('closed', int(notif_id), int(reason)))

    # ------------------------------------------------------------------
    # Called from Qt main thread
    # ------------------------------------------------------------------

    def notify_new_file(self, file_path: str) -> int:
        """Send a KDE notification with a 'Transcribe' action button."""
        try:
            import dbus

            bus = dbus.SessionBus()
            obj = bus.get_object(
                'org.freedesktop.Notifications',
                '/org/freedesktop/Notifications',
            )
            iface = dbus.Interface(obj, 'org.freedesktop.Notifications')

            filename = Path(file_path).name
            notif_id = int(iface.Notify(
                'auto-transcriber',
                dbus.UInt32(0),
                'auto-transcriber',
                'Auto Transcriber: new files found',
                f'Transcribe "{filename}"?',
                dbus.Array(['transcribe', 'Transcribe'], signature='s'),
                dbus.Dictionary({}, signature='sv'),
                dbus.Int32(30_000),
            ))
            self._pending[notif_id] = file_path
            log.debug('Sent notification %d for %s', notif_id, file_path)
            return notif_id
        except Exception:
            log.exception('Failed to send D-Bus notification for %s', file_path)
            return -1

    def drain(self) -> list[tuple]:
        """Non-blocking drain of the inter-thread queue. Call from Qt main thread."""
        events: list[tuple] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events

    def get_file_for_notif(self, notif_id: int) -> Optional[str]:
        return self._pending.pop(notif_id, None)
