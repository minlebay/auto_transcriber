import json
import logging
import logging.handlers
import os
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path

CONFIG_DIR    = Path.home() / '.config' / 'auto_transcriber'
CONFIG_FILE   = CONFIG_DIR / 'config.json'
LOG_DIR       = Path.home() / '.local' / 'share' / 'auto_transcriber'
LOG_FILE      = LOG_DIR / 'app.log'
DB_FILE       = CONFIG_DIR / 'processed.db'
AUTOSTART_DST = Path.home() / '.config' / 'autostart' / 'auto-transcriber.desktop'
AUTOSTART_SRC = Path('/usr/share/auto-transcriber/autostart/auto-transcriber-autostart.desktop')

DEFAULTS = {
    'source_dir':          str(Path.home() / 'Videos'),
    'dest_dir':            str(Path.home() / 'Videos' / 'transcripts'),
    'interval_minutes':    5,
    'mode':                'AUTO',
    'language_hint':       '',
    'start_on_login':      False,
    'gemini_api_key':      '',
    'move_source':         False,
    'create_per_file_dir': False,
    'make_keynotes':       False,
    'diarize_speakers':    False,
}

AUTOSTART_DESKTOP = """\
[Desktop Entry]
Name=Auto Transcriber
Comment=Automatic media file transcriber
Exec=/usr/bin/auto-transcriber
Icon=auto-transcriber
Type=Application
Categories=Utility;AudioVideo;
StartupNotify=false
X-GNOME-Autostart-enabled=true
X-KDE-autostart-phase=2
X-KDE-autostart-after=panel
Hidden=false
"""


@dataclass
class Settings:
    source_dir:          str
    dest_dir:            str
    interval_minutes:    int
    mode:                str   # 'AUTO' | 'MANUAL'
    language_hint:       str
    start_on_login:      bool
    gemini_api_key:      str   # stored in config; env var AUTO_TRANSCRIBER_GEMINI_KEY takes precedence
    move_source:         bool  # move original file to dest dir after processing
    create_per_file_dir: bool  # put artifacts in dest_dir/<stem>/ subdir
    make_keynotes:       bool  # generate summary (participants, topic, agreements)
    diarize_speakers:    bool  # label speakers in transcript

    @classmethod
    def load(cls) -> 'Settings':
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = dict(DEFAULTS)
        if CONFIG_FILE.exists():
            try:
                data.update(json.loads(CONFIG_FILE.read_text(encoding='utf-8')))
            except Exception:
                pass
        return cls(
            source_dir=str(data['source_dir']),
            dest_dir=str(data['dest_dir']),
            interval_minutes=max(1, int(data['interval_minutes'])),
            mode=str(data['mode']).upper() if str(data['mode']).upper() in ('AUTO', 'MANUAL') else 'AUTO',
            language_hint=str(data['language_hint']),
            start_on_login=bool(data['start_on_login']),
            gemini_api_key=str(data.get('gemini_api_key', '')),
            move_source=bool(data.get('move_source', False)),
            create_per_file_dir=bool(data.get('create_per_file_dir', False)),
            make_keynotes=bool(data.get('make_keynotes', False)),
            diarize_speakers=bool(data.get('diarize_speakers', False)),
        )

    def effective_api_key(self) -> str:
        """Env var overrides stored key."""
        return os.environ.get('AUTO_TRANSCRIBER_GEMINI_KEY', '') or self.gemini_api_key

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding='utf-8',
        )
        os.chmod(CONFIG_FILE, 0o600)

    def apply_autostart(self) -> None:
        AUTOSTART_DST.parent.mkdir(parents=True, exist_ok=True)
        if self.start_on_login:
            if AUTOSTART_SRC.exists():
                shutil.copy2(AUTOSTART_SRC, AUTOSTART_DST)
            else:
                AUTOSTART_DST.write_text(AUTOSTART_DESKTOP, encoding='utf-8')
        else:
            AUTOSTART_DST.unlink(missing_ok=True)


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8'
    )
    handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)-8s %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    ))
    root.addHandler(handler)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter('%(levelname)-8s %(message)s'))
    root.addHandler(console)
