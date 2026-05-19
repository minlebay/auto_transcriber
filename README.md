# Auto Transcriber

A KUbuntu system tray application that watches a directory for audio and video files, transcribes them using the [Google Gemini API](https://ai.google.dev/), and saves the results as plain-text files.

## Features

- Runs silently in the system tray (KDE / any freedesktop-compatible desktop)
- Watches a source directory and transcribes new files automatically
- Two processing modes: **AUTO** (immediate) and **MANUAL** (KDE notification with action button)
- Extracts audio from video files via `ffmpeg`
- Transcribes with `gemini-2.5-flash` via the Gemini File API
- Skips files that are still being written (size-stability check)
- Tracks processed files in SQLite — no duplicate work on restart
- Rotating log file, configurable poll interval, optional language hint

## Supported formats

| Type  | Extensions                                    |
| ----- | --------------------------------------------- |
| Video | `.mp4` `.mkv` `.avi` `.mov` `.webm` `.ts`     |
| Audio | `.mp3` `.wav` `.ogg` `.flac` `.m4a` `.opus`   |

## Requirements

- Python 3.10+
- `ffmpeg` in `PATH`
- `python3-dbus`, `python3-gi` (system packages — for MANUAL mode notifications)
- A valid [Gemini API key](https://aistudio.google.com/app/apikey)

## Installation

### From source

```bash
# 1. Clone / download the project
cd auto_transcriber

# 2. Create a virtual environment
python3 -m venv --system-site-packages venv
venv/bin/pip install -r requirements.txt

# 3. Set your API key
export AUTO_TRANSCRIBER_GEMINI_KEY=your_key_here

# 4. Run
make run
# or directly:
PYTHONPATH=. python3 main.py
```

### Debian package (KUbuntu / Ubuntu 22.04+)

```bash
# Install build tools (once)
make build-deps

# Build the .deb
make deb

# Install (resolves dependencies automatically)
make install
# or:
sudo apt install -y ./auto-transcriber_1.0.0_amd64.deb
```

After installation the app is available from the application menu and at `/usr/bin/auto-transcriber`.  
Set `AUTO_TRANSCRIBER_GEMINI_KEY` in your shell profile (`.bashrc`, `.profile`, etc.) before launching.

## Usage

Right-click the tray icon to access the menu:

| Item            | Action                                      |
| --------------- | ------------------------------------------- |
| **Settings**    | Open the configuration dialog               |
| **Process Now** | Trigger an immediate directory scan         |
| **Show Log**    | Open the log file with the default viewer   |
| **Quit**        | Exit the application                        |

### Icon colors

| Color  | Meaning                                              |
| ------ | ---------------------------------------------------- |
| Blue   | Idle — waiting for the next poll                     |
| Amber  | Processing a file                                    |
| Red    | Last file failed (resets to blue after a few seconds)|

## Configuration

Settings are stored in `~/.config/auto_transcriber/config.json`.

| Field               | Default                   | Description                                                      |
| ------------------- | ------------------------- | ---------------------------------------------------------------- |
| `source_dir`        | `~/Videos`                | Directory to watch                                               |
| `dest_dir`          | `~/Videos/transcripts`    | Where to save `.txt` transcripts                                 |
| `interval_minutes`  | `5`                       | Poll interval (min 1, max 1440)                                  |
| `mode`              | `AUTO`                    | `AUTO` — transcribe on detection; `MANUAL` — show notification   |
| `language_hint`     | _(empty)_                 | Optional language passed to Gemini (e.g. `Russian`)              |
| `start_on_login`    | `false`                   | Copy autostart entry to `~/.config/autostart/`                   |

## Processing modes

**AUTO** — any stable new file is queued and transcribed immediately.

**MANUAL** — a KDE desktop notification appears with a **Transcribe** button.  
Clicking it starts transcription; dismissing it leaves the file unprocessed until the next scan.

## File output

Transcripts are saved as `<original_stem>.txt` in the destination directory.  
If the file already exists a numeric suffix is added: `meeting_1.txt`, `meeting_2.txt`, …

The source file is never moved, renamed, or deleted.

## Logging

Logs are written to `~/.local/share/auto_transcriber/app.log` (rotating, max 5 MB, 3 backups).  
Use **Show Log** from the tray menu to open the file.

## Project structure

```text
auto_transcriber/
├── main.py              # TrayApp — Qt event loop, orchestration
├── watcher.py           # Directory scanner with stability check
├── processor.py         # ffmpeg + Gemini API worker (QThread)
├── settings.py          # Config load/save, logging setup, autostart
├── settings_dialog.py   # QDialog for the Settings menu item
├── db.py                # SQLite tracker (processed files)
├── notifier.py          # D-Bus notification wrapper (MANUAL mode)
├── icons/
│   ├── generate.py      # Generates idle/processing/error PNGs
│   ├── idle.png
│   ├── processing.png
│   └── error.png
├── requirements.txt
├── Makefile
└── packaging/
    └── debian/          # Debian package metadata and scripts
```

## Makefile targets

| Target              | Description                                |
| ------------------- | ------------------------------------------ |
| `make build-deps`   | Install `debhelper` (needed once for .deb) |
| `make gen-icons`    | Generate PNG icons                         |
| `make run`          | Run from source (creates venv if needed)   |
| `make deb`          | Build `auto-transcriber_1.0.0_amd64.deb`   |
| `make install`      | `sudo apt install` the built package       |
| `make clean`        | Remove build artifacts and icons           |
| `make distclean`    | `clean` + remove venv and debian symlink   |

## Dependencies (pip)

| Package                      | Purpose                                     |
| ---------------------------- | ------------------------------------------- |
| `PySide6 >= 6.6`             | Qt bindings — tray icon, dialogs, threading |
| `google-generativeai >= 0.7` | Gemini API client                           |

`dbus-python` and `python3-gi` are expected as system packages and are not installed via pip.
