import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

log = logging.getLogger(__name__)


class ProcessorWorker(QObject):
    """
    Long-running worker that lives in a QThread.
    Converts media to WAV via ffmpeg, then transcribes with Gemini.
    """

    finished      = Signal(str, str)  # (source_path, output_txt_path)
    failed        = Signal(str, str)  # (source_path, error_message)
    status_changed = Signal(str)      # human-readable status for tray tooltip

    # Set by TrayApp on the main thread immediately before emitting _do_process.
    # Safe to read in process() because the queued signal delivery ensures
    # this attribute is visible when the slot executes.
    settings_snapshot: dict = {}

    @Slot(str)
    def process(self, file_path: str) -> None:
        snap = dict(self.settings_snapshot)
        src  = Path(file_path)
        stem = src.stem

        dest_root = Path(snap.get('dest_dir', ''))
        if snap.get('create_per_file_dir'):
            file_dest = dest_root / stem
        else:
            file_dest = dest_root
        file_dest.mkdir(parents=True, exist_ok=True)

        fd, wav = tempfile.mkstemp(suffix='.wav', prefix='at_')
        os.close(fd)
        try:
            name = src.name
            self.status_changed.emit(f'Converting {name}…')
            self._convert_to_wav(file_path, wav)

            self.status_changed.emit(f'Transcribing {name}…')
            text = self._transcribe(wav, snap)

            out = self._save_transcript(src, file_dest, text)

            if snap.get('make_keynotes'):
                self.status_changed.emit(f'Generating keynotes for {name}…')
                self._save_keynotes(src, file_dest, text, snap)

            if snap.get('move_source'):
                self._move_source(src, file_dest)

            self.finished.emit(file_path, out)
        except Exception as exc:
            log.exception('Processing failed for %s', file_path)
            self.failed.emit(file_path, str(exc))
        finally:
            Path(wav).unlink(missing_ok=True)

    def _convert_to_wav(self, input_path: str, wav_path: str) -> None:
        cmd = [
            'ffmpeg', '-y', '-i', input_path,
            '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1',
            wav_path,
        ]
        # Strip API key from child process environment to avoid leaking credentials.
        safe_env = {k: v for k, v in os.environ.items() if k != 'AUTO_TRANSCRIBER_GEMINI_KEY'}
        result = subprocess.run(cmd, capture_output=True, timeout=300, env=safe_env)
        if result.returncode != 0:
            stderr = result.stderr.decode(errors='replace')[-600:]
            raise RuntimeError(f'ffmpeg error (rc={result.returncode}): {stderr}')

    def _transcribe(self, wav_path: str, snap: dict) -> str:
        import google.generativeai as genai
        try:
            from google.api_core.exceptions import ResourceExhausted
        except ImportError:
            ResourceExhausted = Exception  # type: ignore[assignment,misc]

        api_key = os.environ.get('AUTO_TRANSCRIBER_GEMINI_KEY', '') or snap.get('gemini_api_key', '')
        if not api_key:
            raise RuntimeError(
                'Gemini API key is not set.\n'
                'Add it in Settings or set AUTO_TRANSCRIBER_GEMINI_KEY in your environment.'
            )

        genai.configure(api_key=api_key)

        log.debug('Uploading %s to Gemini File API', wav_path)
        audio_file = genai.upload_file(path=wav_path, mime_type='audio/wav')

        try:
            for _ in range(90):
                state = audio_file.state.name
                if state == 'ACTIVE':
                    break
                if state == 'FAILED':
                    raise RuntimeError('Gemini file upload failed (state=FAILED)')
                time.sleep(1)
                audio_file = genai.get_file(audio_file.name)
            else:
                raise RuntimeError('Gemini file upload timed out (90 s)')

            lang_clause = ''
            raw_hint = snap.get('language_hint', '')
            if raw_hint:
                # Sanitize: strip control characters and limit length to prevent prompt injection.
                safe_hint = ''.join(c for c in raw_hint if c.isprintable())[:40]
                lang_clause = f' The audio language is {safe_hint}.'

            if snap.get('diarize_speakers'):
                prompt = (
                    'Transcribe this audio accurately. '
                    'Identify each speaker and label them consistently as "Speaker 1:", "Speaker 2:", etc. '
                    'Mark every speaker change throughout the transcript. '
                    f'Return plain text with speaker labels only.{lang_clause}'
                )
            else:
                prompt = (
                    'Transcribe this audio accurately. '
                    'Preserve speaker changes if detectable. '
                    f'Return plain text only.{lang_clause}'
                )

            model = genai.GenerativeModel('gemini-2.5-flash')
            try:
                response = model.generate_content([audio_file, prompt])
            except ResourceExhausted:
                raise RuntimeError('Gemini quota exceeded — try again later')

            return response.text.strip()
        finally:
            try:
                genai.delete_file(audio_file.name)
            except Exception:
                pass

    def _save_transcript(self, src: Path, dest: Path, text: str) -> str:
        out = dest / f'{src.stem}.txt'
        counter = 1
        while out.exists():
            out = dest / f'{src.stem}_{counter}.txt'
            counter += 1
        out.write_text(text, encoding='utf-8')
        log.info('Saved transcript: %s', out)
        return str(out)

    def _save_keynotes(self, src: Path, dest: Path, transcript: str, snap: dict) -> None:
        import google.generativeai as genai
        try:
            from google.api_core.exceptions import ResourceExhausted
        except ImportError:
            ResourceExhausted = Exception  # type: ignore[assignment,misc]

        api_key = os.environ.get('AUTO_TRANSCRIBER_GEMINI_KEY', '') or snap.get('gemini_api_key', '')
        genai.configure(api_key=api_key)

        lang_clause = ''
        raw_hint = snap.get('language_hint', '')
        if raw_hint:
            safe_hint = ''.join(c for c in raw_hint if c.isprintable())[:40]
            lang_clause = f'\nRespond in {safe_hint}.'

        prompt = (
            'Based on the following transcript, provide a structured meeting summary '
            'with exactly these four sections in Markdown:\n\n'
            '## Participants\n'
            'List all identified speakers or participants.\n\n'
            '## Main Topic\n'
            'Describe the primary subject of the conversation.\n\n'
            '## Agreements & Decisions\n'
            'List every decision made or agreement reached. If none, write "None".\n\n'
            '## Summary\n'
            'A concise overall summary (3–5 sentences).\n'
            f'{lang_clause}\n\n'
            'Transcript:\n'
            f'{transcript[:30000]}'
        )

        model = genai.GenerativeModel('gemini-2.5-flash')
        try:
            response = model.generate_content(prompt)
        except ResourceExhausted:
            raise RuntimeError('Gemini quota exceeded — try again later')

        keynotes_text = response.text.strip()
        out = dest / f'{src.stem}_keynotes.md'
        counter = 1
        while out.exists():
            out = dest / f'{src.stem}_keynotes_{counter}.md'
            counter += 1
        out.write_text(keynotes_text, encoding='utf-8')
        log.info('Saved keynotes: %s', out)

    def _move_source(self, src: Path, dest: Path) -> None:
        target = dest / src.name
        if target.resolve() == src.resolve():
            return
        if target.exists():
            counter = 1
            while target.exists():
                target = dest / f'{src.stem}_{counter}{src.suffix}'
                counter += 1
        shutil.move(str(src), str(target))
        log.info('Moved source to %s', target)
