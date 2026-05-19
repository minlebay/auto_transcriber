from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)
from PySide6.QtGui import QIcon
from PySide6.QtCore import QSize

from settings import Settings


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Auto Transcriber — Settings')
        self.setMinimumWidth(480)
        self._settings = settings
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 12)

        # Source directory
        self._source_dir = QLineEdit(self._settings.source_dir)
        src_row = self._dir_row(self._source_dir)
        form.addRow('Source directory:', src_row)

        # Destination directory
        self._dest_dir = QLineEdit(self._settings.dest_dir)
        dst_row = self._dir_row(self._dest_dir)
        form.addRow('Output directory:', dst_row)

        # Poll interval
        self._interval = QSpinBox()
        self._interval.setRange(1, 1440)
        self._interval.setValue(self._settings.interval_minutes)
        self._interval.setSuffix(' minutes')
        form.addRow('Check interval:', self._interval)

        # Mode
        self._mode = QComboBox()
        self._mode.addItems(['AUTO', 'MANUAL'])
        self._mode.setCurrentText(self._settings.mode)
        mode_hint = QLabel(
            '<small>AUTO: transcribe immediately · '
            'MANUAL: show notification with action button</small>'
        )
        mode_hint.setWordWrap(True)
        form.addRow('Processing mode:', self._mode)
        form.addRow('', mode_hint)

        # Gemini API key
        import os
        env_key = os.environ.get('AUTO_TRANSCRIBER_GEMINI_KEY', '')
        self._api_key = QLineEdit(self._settings.gemini_api_key)
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText('Paste your Gemini API key here')
        if env_key:
            self._api_key.setPlaceholderText(f'Set via env var (AUTO_TRANSCRIBER_GEMINI_KEY)')
            self._api_key.setEnabled(False)
        toggle_btn = QPushButton('Show')
        toggle_btn.setFixedWidth(52)
        toggle_btn.setCheckable(True)
        toggle_btn.toggled.connect(self._toggle_key_visibility)
        api_row = QHBoxLayout()
        api_row.setContentsMargins(0, 0, 0, 0)
        api_row.addWidget(self._api_key)
        api_row.addWidget(toggle_btn)
        self._toggle_btn = toggle_btn
        form.addRow('Gemini API key:', api_row)

        # Language hint
        self._lang = QLineEdit(self._settings.language_hint)
        self._lang.setPlaceholderText('e.g. English, Russian  (optional)')
        form.addRow('Language hint:', self._lang)

        # Start on login
        self._autostart = QCheckBox('Start on login (KDE / GNOME autostart)')
        self._autostart.setChecked(self._settings.start_on_login)
        form.addRow('', self._autostart)

        # Output options
        from PySide6.QtWidgets import QFrame
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        form.addRow(sep)
        form.addRow(QLabel('<b>Output options</b>'))

        self._move_source = QCheckBox('Move source file to output directory after processing')
        self._move_source.setChecked(self._settings.move_source)
        form.addRow('', self._move_source)

        self._create_per_file_dir = QCheckBox('Create a subdirectory per file (place all artifacts inside it)')
        self._create_per_file_dir.setChecked(self._settings.create_per_file_dir)
        form.addRow('', self._create_per_file_dir)

        # Analysis options
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        form.addRow(sep2)
        form.addRow(QLabel('<b>Analysis options</b>'))

        self._make_keynotes = QCheckBox('Generate keynotes: participants, main topic, agreements, summary')
        self._make_keynotes.setChecked(self._settings.make_keynotes)
        form.addRow('', self._make_keynotes)

        self._diarize_speakers = QCheckBox('Identify and label speakers in transcript (Speaker 1, Speaker 2, …)')
        self._diarize_speakers.setChecked(self._settings.diarize_speakers)
        form.addRow('', self._diarize_speakers)

        layout.addLayout(form)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _dir_row(self, line_edit: QLineEdit) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(line_edit)
        btn = QPushButton('Browse…')
        btn.setFixedWidth(80)
        btn.clicked.connect(lambda: self._browse(line_edit))
        row.addWidget(btn)
        return row

    def _toggle_key_visibility(self, checked: bool) -> None:
        self._api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )
        self._toggle_btn.setText('Hide' if checked else 'Show')

    def _browse(self, line_edit: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(
            self, 'Select Directory', line_edit.text() or str(Path.home())
        )
        if path:
            line_edit.setText(path)

    def _on_accept(self) -> None:
        src = self._source_dir.text().strip()
        if not src:
            QMessageBox.warning(self, 'Validation', 'Source directory cannot be empty.')
            return
        if not Path(src).is_dir():
            QMessageBox.warning(self, 'Validation', f'Source directory does not exist:\n{src}')
            return
        self.accept()

    def get_updated_settings(self) -> Settings:
        import os
        return Settings(
            source_dir=self._source_dir.text().strip(),
            dest_dir=self._dest_dir.text().strip(),
            interval_minutes=self._interval.value(),
            mode=self._mode.currentText(),
            language_hint=self._lang.text().strip(),
            start_on_login=self._autostart.isChecked(),
            gemini_api_key='' if os.environ.get('AUTO_TRANSCRIBER_GEMINI_KEY') else self._api_key.text().strip(),
            move_source=self._move_source.isChecked(),
            create_per_file_dir=self._create_per_file_dir.isChecked(),
            make_keynotes=self._make_keynotes.isChecked(),
            diarize_speakers=self._diarize_speakers.isChecked(),
        )
