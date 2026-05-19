"""
Auto Transcriber — KUbuntu system tray application.
Watches a directory for audio/video files and transcribes them via Gemini API.
"""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

# D-Bus GLib main loop must be set as default before any dbus.SessionBus() call.
# This is a process-wide setting; do it unconditionally at import time.
try:
    import dbus.mainloop.glib
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
except Exception:
    pass  # dbus not available; MANUAL mode will degrade gracefully

from PySide6.QtCore import QObject, QRect, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QSystemTrayIcon

import settings as settings_module
from db import Database
from notifier import Notifier
from processor import ProcessorWorker
from settings import Settings, setup_logging
from settings_dialog import SettingsDialog
from watcher import Watcher

log = logging.getLogger(__name__)

# Equalizer-bar icon specs: (color_hex, bar_heights_from_bottom)
_ICON_SPECS: dict[str, tuple[str, list[int]]] = {
    'idle':       ('#4A90D9', [6, 10, 14, 10, 6]),   # bell curve, blue — resting
    'processing': ('#F5A623', [14, 7, 17, 5, 12]),   # irregular, amber — active
    'error':      ('#E74C3C', [3, 3, 3, 3, 3]),      # flatline, red — failed
}

_BAR_W  = 3
_GAP    = 1
_N_BARS = 5
_SIZE   = 22
_BOTTOM = _SIZE - 3   # bottom edge row


def _make_icon(state: str) -> QIcon:
    color_hex, heights = _ICON_SPECS[state]
    total_w = _N_BARS * _BAR_W + (_N_BARS - 1) * _GAP
    left = (_SIZE - total_w) // 2

    pix = QPixmap(_SIZE, _SIZE)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color_hex))
    p.setPen(QColor(0, 0, 0, 0))

    for i, h in enumerate(heights):
        x = left + i * (_BAR_W + _GAP)
        y = _BOTTOM - h + 1
        p.drawRoundedRect(QRect(x, y, _BAR_W, h), 1, 1)

    p.end()
    return QIcon(pix)


class TrayApp(QSystemTrayIcon):
    # Signal used to send work to the ProcessorWorker (lives in a QThread).
    # Using a signal guarantees queued (thread-safe) delivery.
    _do_process = Signal(str)

    def __init__(self, cfg: Settings, db: Database, notifier: Notifier) -> None:
        super().__init__()
        self._cfg      = cfg
        self._db       = db
        self._notifier = notifier
        self._watcher  = Watcher(db)
        self._queue: list[str] = []
        self._is_processing    = False

        self._ffmpeg_ok  = shutil.which('ffmpeg') is not None
        self._api_key_ok = bool(cfg.effective_api_key())

        # Worker thread setup
        self._worker_thread = QThread(self)
        self._worker = ProcessorWorker()
        self._worker.moveToThread(self._worker_thread)
        self._do_process.connect(self._worker.process)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.status_changed.connect(self._on_status)
        self._worker_thread.start()

        self._set_state('idle')
        self._build_menu()
        self.show()

        # Warn about missing dependencies
        if not self._ffmpeg_ok:
            self.showMessage(
                'Auto Transcriber',
                'ffmpeg not found in PATH — processing is disabled.',
                QSystemTrayIcon.MessageIcon.Warning, 6000,
            )
            log.error('ffmpeg not found in PATH')
        if not self._api_key_ok:
            self.showMessage(
                'Auto Transcriber',
                'Gemini API key is not set — open Settings to add it.',
                QSystemTrayIcon.MessageIcon.Warning, 6000,
            )
            log.error('Gemini API key not set (no env var or config value)')

        # Polling timer
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._apply_interval()

        # Immediate first scan once the event loop starts, so files already
        # present in the source dir are picked up without waiting the full interval.
        QTimer.singleShot(0, self._poll)
        # Second pass after a short delay to complete the two-scan stability
        # check for files that existed before this process started.
        QTimer.singleShot(15_000, self._poll)

        # Notification drain timer (Qt main thread, 200 ms)
        self._notif_timer = QTimer(self)
        self._notif_timer.setInterval(200)
        self._notif_timer.timeout.connect(self._drain_notifications)
        self._notif_timer.start()

        log.info('Auto Transcriber started (source=%s, mode=%s, interval=%dm)',
                 self._cfg.source_dir, self._cfg.mode, self._cfg.interval_minutes)

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menu = QMenu()
        menu.addAction('Settings').triggered.connect(self._open_settings)
        menu.addAction('Process Now').triggered.connect(self._process_now)
        menu.addSeparator()
        menu.addAction('Show Log').triggered.connect(self._show_log)
        menu.addSeparator()
        menu.addAction('Quit').triggered.connect(self._quit)
        self.setContextMenu(menu)

    # ------------------------------------------------------------------
    # Icon state
    # ------------------------------------------------------------------

    def _set_state(self, state: str) -> None:
        self.setIcon(_make_icon(state))
        labels = {
            'idle':       'Auto Transcriber — Idle',
            'processing': 'Auto Transcriber — Processing…',
            'error':      'Auto Transcriber — Error',
        }
        self.setToolTip(labels[state])

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _apply_interval(self) -> None:
        ms = max(1, self._cfg.interval_minutes) * 60_000
        self._poll_timer.start(ms)

    def _poll(self) -> None:
        if self._is_processing or not self._ffmpeg_ok or not self._api_key_ok:
            return
        new_files = self._watcher.scan(self._cfg.source_dir)
        if new_files:
            log.info('Found %d new file(s): %s', len(new_files),
                     ', '.join(Path(f).name for f in new_files))
        self._queue.extend(new_files)
        self._process_next()

    def _process_now(self) -> None:
        """Triggered by "Process Now" menu item — immediate poll."""
        self._poll_timer.stop()
        self._poll()
        self._apply_interval()

    # ------------------------------------------------------------------
    # Processing pipeline
    # ------------------------------------------------------------------

    def _process_next(self) -> None:
        if self._is_processing or not self._queue:
            return
        path = self._queue.pop(0)
        if self._cfg.mode == 'MANUAL':
            self._notifier.notify_new_file(path)
        else:
            self._start_processing(path)

    def _start_processing(self, path: str) -> None:
        self._is_processing = True
        self._set_state('processing')
        self._worker.settings_snapshot = {
            'dest_dir':            self._cfg.dest_dir,
            'language_hint':       self._cfg.language_hint,
            'gemini_api_key':      self._cfg.effective_api_key(),
            'move_source':         self._cfg.move_source,
            'create_per_file_dir': self._cfg.create_per_file_dir,
            'make_keynotes':       self._cfg.make_keynotes,
            'diarize_speakers':    self._cfg.diarize_speakers,
        }
        self._do_process.emit(path)
        log.info('Started processing: %s', path)

    @Slot(str, str)
    def _on_finished(self, source_path: str, output_path: str) -> None:
        self._is_processing = False
        try:
            mtime = Path(source_path).stat().st_mtime
            self._db.mark_done(source_path, mtime)
        except OSError:
            pass
        self._set_state('idle')
        self.showMessage(
            'Auto Transcriber',
            f'Saved: {Path(output_path).name}',
            QSystemTrayIcon.MessageIcon.Information, 4000,
        )
        log.info('Finished: %s → %s', source_path, output_path)
        self._process_next()

    @Slot(str, str)
    def _on_failed(self, source_path: str, error_msg: str) -> None:
        self._is_processing = False
        try:
            mtime = Path(source_path).stat().st_mtime
        except OSError:
            mtime = 0.0
        self._db.mark_failed(source_path, mtime, error_msg)
        self._set_state('error')
        self.showMessage(
            'Auto Transcriber',
            f'Error: {error_msg[:120]}',
            QSystemTrayIcon.MessageIcon.Critical, 7000,
        )
        log.error('Failed: %s — %s', source_path, error_msg)
        QTimer.singleShot(6000, lambda: self._set_state('idle'))
        self._process_next()

    @Slot(str)
    def _on_status(self, msg: str) -> None:
        self.setToolTip(f'Auto Transcriber — {msg}')

    # ------------------------------------------------------------------
    # Notification drain (MANUAL mode)
    # ------------------------------------------------------------------

    def _drain_notifications(self) -> None:
        for event in self._notifier.drain():
            kind = event[0]
            notif_id = event[1]
            if kind == 'action' and event[2] == 'transcribe':
                file_path = self._notifier.get_file_for_notif(notif_id)
                if file_path:
                    log.info('User clicked Transcribe for %s', file_path)
                    self._start_processing(file_path)
            elif kind == 'closed':
                # User dismissed or notification expired — clean up
                self._notifier.get_file_for_notif(notif_id)

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._cfg)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            old_interval   = self._cfg.interval_minutes
            old_autostart  = self._cfg.start_on_login
            self._cfg = dlg.get_updated_settings()
            self._cfg.save()
            self._api_key_ok = bool(self._cfg.effective_api_key())
            log.info('Settings saved: %s', self._cfg)
            if self._cfg.start_on_login != old_autostart:
                self._cfg.apply_autostart()
            if self._cfg.interval_minutes != old_interval:
                self._apply_interval()

    def _show_log(self) -> None:
        log_path = settings_module.LOG_FILE
        if log_path.exists():
            subprocess.Popen(['xdg-open', str(log_path)])
        else:
            self.showMessage(
                'Auto Transcriber', 'Log file not found yet.',
                QSystemTrayIcon.MessageIcon.Information, 3000,
            )

    def _quit(self) -> None:
        log.info('Quitting')
        self._worker_thread.quit()
        self._worker_thread.wait(3000)
        QApplication.quit()


def main() -> None:
    setup_logging()
    log.info('--- Auto Transcriber starting ---')

    app = QApplication(sys.argv)
    app.setApplicationName('auto-transcriber')
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.critical('No system tray available')
        sys.exit(1)

    cfg      = Settings.load()
    db       = Database(settings_module.DB_FILE)
    notifier = Notifier()
    tray     = TrayApp(cfg, db, notifier)  # noqa: F841 — kept alive by Qt parent chain

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
