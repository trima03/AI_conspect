"""Record/import a lesson and transcribe in a background thread."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QTextEdit, QVBoxLayout,
    QTabWidget, QWidget, QCheckBox,
)

from .. import lesson_audio, storage, library
from ..pipeline import transcribe_lesson, summarize_lesson
from ..notes import NotesCancelled
from ..recording import RecordingError, list_input_devices, record_audio
from ..transcription import MAX_FILE_BYTES, TranscriptionCancelled


class AudioJob(QThread):
    message = Signal(str)
    meter = Signal(float, float)

    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.action = action
        self.stop_event = threading.Event()
        self.result = None
        self.error = None
        self.lesson_id = None

    def run(self):
        try:
            self.result = self.action(self)
        except Exception as error:
            self.error = error
            if not isinstance(error, (TranscriptionCancelled, NotesCancelled)):
                logging.getLogger(__name__).exception("Ошибка обработки аудио")


class AudioDialog(QDialog):
    lesson_changed = Signal()

    def __init__(self, lesson_id: int | None = None, parent=None, *, subject_id=None, source_path=None):
        super().__init__(parent)
        self.setWindowTitle("Лекция: аудио, расшифровка и конспект")
        self.resize(780, 720)
        self.lesson_id = lesson_id
        self.source = None
        self.job = None
        self.mode = None
        self._auto_transcribe = False
        self._replace_audio = False
        self._loaded_transcript = ""
        self._notes_source = ""
        root = QVBoxLayout(self)
        self.audio_panel = QWidget()
        audio_root = QVBoxLayout(self.audio_panel)
        audio_root.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.subjects = QComboBox()
        self.add_subject = QPushButton("+ Предмет")
        self.add_subject.clicked.connect(self._add_subject)
        subject_row = QHBoxLayout()
        subject_row.addWidget(self.subjects, 1)
        subject_row.addWidget(self.add_subject)
        form.addRow("Предмет", subject_row)
        self.title = QLineEdit()
        self.title.setPlaceholderText("Например, Производные — 13 октября")
        form.addRow("Название лекции", self.title)
        self.models = QComboBox()
        self.models.addItem("Точное распознавание — Large v3 Turbo", "turbo")
        self.models.addItem("Экономия памяти — Small", "small")
        self.models.addItem("Tiny — только для проверки запуска", "tiny")
        form.addRow("Модель", self.models)
        self.context = QLineEdit()
        self.context.setPlaceholderText("Необязательно: фамилии, термины, тема")
        form.addRow("Подсказка", self.context)
        audio_root.addLayout(form)
        self.reduce_noise = QCheckBox("Шумная аудитория: снизить фоновый шум")
        self.reduce_noise.setToolTip("Уменьшает постоянный гул и шипение во временной копии. Исходная запись сохраняется. Голоса других людей надёжно не отделяет; сравните результат с обычным режимом.")
        audio_root.addWidget(self.reduce_noise)
        hint = QLabel("Аудио обрабатывается на компьютере бесплатно. При первом запуске выбранная модель скачивается из интернета. До 4 часов и 2 ГБ.")
        hint.setWordWrap(True)
        audio_root.addWidget(hint)
        self.devices = QComboBox()
        self.devices.addItem("Микрофон по умолчанию", None)
        try:
            for index, name in list_input_devices():
                self.devices.addItem(name, index)
        except RecordingError as error:
            self.devices.setToolTip(str(error))
        audio_root.addWidget(self.devices)
        actions = QHBoxLayout()
        self.choose = QPushButton("Загрузить аудиофайл")
        self.choose.clicked.connect(self._choose_file)
        self.record = QPushButton("Записать с микрофона")
        self.record.clicked.connect(self._record)
        self.stop = QPushButton("Остановить и распознать")
        self.stop.clicked.connect(self._stop)
        self.stop.hide()
        for widget in (self.choose, self.record, self.stop):
            actions.addWidget(widget)
        audio_root.addLayout(actions)
        self.source_label = QLabel("Аудио ещё не выбрано")
        self.source_label.setTextFormat(Qt.TextFormat.PlainText)
        self.source_label.setWordWrap(True)
        audio_root.addWidget(self.source_label)
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setValue(0)
        self.level.setFormat("Уровень микрофона: %p%")
        audio_root.addWidget(self.level)
        root.addWidget(self.audio_panel)
        self.state = QLabel("")
        self.state.setTextFormat(Qt.TextFormat.PlainText)
        self.state.setWordWrap(True)
        root.addWidget(self.state)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        root.addWidget(self.progress)
        controls = QHBoxLayout()
        self.transcribe = QPushButton("Распознать")
        self.transcribe.setObjectName("PrimaryButton")
        self.transcribe.clicked.connect(self._transcribe)
        self.cancel = QPushButton("Отменить обработку")
        self.cancel.clicked.connect(self._cancel)
        self.cancel.hide()
        controls.addWidget(self.transcribe)
        controls.addWidget(self.cancel)
        self.reset = QPushButton("Сбросить зависшую обработку")
        self.reset.hide()
        self.reset.clicked.connect(self._reset_processing)
        controls.addWidget(self.reset)
        root.addLayout(controls)
        self.import_text = QPushButton("Импорт расшифровки TXT")
        self.import_text.clicked.connect(self._import_transcript)
        controls.addWidget(self.import_text)
        self.text = QTextEdit()
        self.text.setPlaceholderText("Здесь появится расшифровка. Её можно будет исправить и сохранить.")
        self.tabs = QTabWidget()
        self.tabs.addTab(self.text, "Расшифровка")
        notes_tab = QWidget()
        notes_layout = QVBoxLayout(notes_tab)
        notes_controls = QHBoxLayout()
        self.notes_style = QComboBox()
        self.notes_style.addItem("Подробный конспект", "detailed")
        self.notes_style.addItem("Краткий конспект", "short")
        self.make_notes = QPushButton("Создать ИИ-конспект")
        self.make_notes.setObjectName("PrimaryButton")
        self.make_notes.clicked.connect(self._generate_notes)
        self.save_notes = QPushButton("Сохранить конспект")
        self.save_notes.clicked.connect(self._save_notes)
        for widget in (self.notes_style, self.make_notes, self.save_notes):
            notes_controls.addWidget(widget)
        notes_layout.addLayout(notes_controls)
        self.notes_hint = QLabel("Локальная модель Qwen3 4B. Конспект создаётся по расшифровке; факты и формулы стоит сверить с записью.")
        self.notes_hint.setWordWrap(True)
        notes_layout.addWidget(self.notes_hint)
        self.notes = QTextEdit()
        self.notes.setAcceptRichText(False)
        self.notes.setPlaceholderText("Получите расшифровку, затем нажмите «Создать ИИ-конспект». Здесь можно исправить результат.")
        notes_layout.addWidget(self.notes, 1)
        self.tabs.addTab(notes_tab, "Конспект")
        self.lesson_heading = QLabel()
        self.lesson_heading.setTextFormat(Qt.TextFormat.PlainText)
        self.lesson_heading.setObjectName("PageTitle")
        self.lesson_heading.setWordWrap(True)
        root.addWidget(self.lesson_heading)
        root.addWidget(self.tabs, 1)
        self.auto_notes = QCheckBox("Создать ИИ-конспект после распознавания")
        root.addWidget(self.auto_notes)
        footer = QHBoxLayout()
        deletion_row = QHBoxLayout()
        self.play = QPushButton("Прослушать запись")
        self.play.clicked.connect(self._play)
        self.delete_audio = QPushButton("Удалить аудио")
        self.delete_audio.clicked.connect(self._delete_audio)
        self.delete_lesson = QPushButton("Удалить лекцию")
        self.delete_lesson.clicked.connect(self._delete_lesson)
        for button in (self.play, self.delete_audio, self.delete_lesson):
            deletion_row.addWidget(button)
        root.addLayout(deletion_row)
        self.save = QPushButton("Сохранить лекцию")
        self.save.clicked.connect(self._save)
        self.export = QPushButton("Экспорт текста / конспекта")
        self.export.clicked.connect(self._export)
        self.close_button = QPushButton("Закрыть")
        self.close_button.clicked.connect(self.reject)
        for widget in (self.save, self.export, self.close_button):
            footer.addWidget(widget)
        root.addLayout(footer)
        self._load_subjects(subject_id)
        if lesson_id is not None:
            lesson = storage.get_lesson(lesson_id)
            self.title.setText(lesson.title)
            self.subjects.setCurrentIndex(self.subjects.findData(lesson.subject_id))
            self._set_source(Path(lesson.audio_path) if lesson.audio_path else None)
            self._replace_audio = not lesson.audio_path or not Path(lesson.audio_path).is_file()
            self.text.setPlainText(lesson.transcript or "")
            self._loaded_transcript = lesson.transcript or ""
            self._notes_source = lesson.transcript or ""
            self.notes.setMarkdown(lesson.summary or "")
            notes_state = storage.get_notes_state(lesson.id)
            if notes_state.error_message:
                self.notes_hint.setText(notes_state.error_message)
            self.reset.setVisible(lesson.status == storage.STATUS_PROCESSING)
            self.state.setText(lesson.error_message or (
                "Аудиозапись сохранена." if self.source else "Лекция сохранена без аудио."
            ))
        if lesson_id is None and source_path:
            self._set_source(Path(source_path))
        self._busy(False)
        self.text.textChanged.connect(self._update_note_buttons)
        self.notes.textChanged.connect(self._update_note_buttons)
        self.tabs.currentChanged.connect(self._update_note_buttons)
        self._update_note_buttons()

    def _load_subjects(self, selected=None):
        self.subjects.clear()
        for subject in storage.list_subjects():
            self.subjects.addItem(subject.name, subject.id)
        if selected is not None:
            self.subjects.setCurrentIndex(self.subjects.findData(selected))

    def _add_subject(self):
        name, ok = QInputDialog.getText(self, "Новый предмет", "Название предмета:")
        if ok:
            try:
                subject = storage.create_subject(name)
                self._load_subjects(subject.id)
                self.lesson_changed.emit()
            except Exception as error:
                self.state.setText(str(error))

    def _set_source(self, source):
        self.source = source
        self.source_label.setText(str(source) if source else "Аудио не выбрано или удалено. Текст лекции сохранён.")

    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите запись", "",
                                             "Аудио (*.wav *.mp3 *.m4a *.flac *.ogg *.webm *.mp4 *.mpeg *.mpga)")
        if path:
            self._set_source(Path(path))
            self._busy(False)

    def _import_transcript(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите расшифровку UTF-8", "", "Текст (*.txt)")
        if not path:
            return
        try:
            with Path(path).open(encoding="utf-8-sig") as source:
                text = source.read(1_000_001)
            if len(text) > 1_000_000 or not text.strip():
                raise ValueError("Нужен непустой текст длиной до миллиона символов.")
        except (OSError, ValueError) as error:
            self.state.setText(f"Не удалось импортировать текст: {error}")
            return
        if self.text.toPlainText().strip() and QMessageBox.question(
            self, "Заменить расшифровку?", "Заменить текст в редакторе содержимым файла?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.text.setPlainText(text)
        if not self.title.text().strip():
            self.title.setText(Path(path).stem)

    def _validate(self):
        if self.subjects.currentData() is None or not self.title.text().strip():
            self.state.setText("Выберите или создайте предмет и укажите название лекции.")
            return False
        return True

    def _busy(self, busy):
        existing = self.lesson_id is not None
        for widget in (self.title, self.subjects, self.add_subject):
            widget.setEnabled(not busy)
        for widget in (self.choose, self.record, self.devices):
            widget.setEnabled(not busy and (not existing or self._replace_audio))
        for widget in (self.models, self.context, self.reduce_noise):
            widget.setEnabled(not busy)
        self.text.setReadOnly(busy)
        self.notes.setReadOnly(busy)
        self.tabs.tabBar().setEnabled(not busy or self.mode != "record")
        self.notes_style.setEnabled(not busy)
        self.auto_notes.setEnabled(not busy)
        self.make_notes.setEnabled(not busy and bool(self.text.toPlainText().strip()))
        self.save_notes.setEnabled(not busy and self.lesson_id is not None and bool(self.notes.toPlainText().strip()))
        self.transcribe.setEnabled(not busy and self.source is not None)
        self.import_text.setEnabled(not busy)
        self.save.setEnabled(not busy and (existing or self.source is not None or bool(self.text.toPlainText().strip())))
        self.delete_lesson.setEnabled(not busy and existing)
        self.delete_audio.setEnabled(not busy and self.source is not None)
        self.play.setEnabled(not busy and self.source is not None and self.source.is_file())
        self.export.setEnabled(not busy and bool(self._export_text().strip()))
        self.close_button.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.cancel.setVisible(busy and self.mode in ("transcribe", "notes"))
        self.stop.setVisible(busy and self.mode == "record")
        self.stop.setEnabled(True)
        self.cancel.setEnabled(True)
        self.reset.setEnabled(not busy)

    def _start(self, action, mode):
        if self.job is not None:
            return
        self.mode = mode
        self.job = AudioJob(action, self)
        self.job.message.connect(self.state.setText)
        self.job.meter.connect(self._meter)
        self.job.finished.connect(self._finished)
        self._busy(True)
        self.job.start()

    def _record(self):
        if not self._validate():
            return
        device = self.devices.currentData()
        self._auto_transcribe = True
        self.state.setText("Подключение микрофона… Если macOS спросит, разрешите доступ.")
        self._start(lambda job: record_audio(job.stop_event, device=device, progress=job.meter.emit), "record")

    def _meter(self, seconds, peak):
        self.level.setValue(round(peak * 100))
        elapsed = int(seconds)
        self.state.setText(f"Идёт запись: {elapsed // 60:02d}:{elapsed % 60:02d}. Нажмите «Остановить и распознать».")

    def _stop(self):
        if self.job:
            self.job.stop_event.set()
            self.stop.setEnabled(False)
            self.state.setText("Сохранение записи…")

    def _cancel(self):
        if self.job:
            self.job.stop_event.set()
            self.cancel.setEnabled(False)
            self.state.setText("Отмена создания конспекта… Прежний конспект сохранится." if self.mode == "notes" else "Отмена после текущего фрагмента или загрузки модели. Аудиозапись сохранится.")

    def _transcribe(self):
        if not self._validate() or self.source is None:
            return
        if (self.text.toPlainText().strip() != self._loaded_transcript
                or self.notes.document().isModified()) and not self._confirm_replace(
                    "При успешном распознавании несохранённые правки будут заменены."
                ):
            return
        lesson_id, source = self.lesson_id, self.source
        subject_id, title = self.subjects.currentData(), self.title.text().strip()
        model, prompt = self.models.currentData(), self.context.text().strip() or None
        reduce_noise = self.reduce_noise.isChecked()
        def process(job):
            if lesson_id is None:
                lesson = lesson_audio.create_lesson_with_audio(subject_id, title, source, max_size_bytes=MAX_FILE_BYTES)
                job.lesson_id = lesson.id
            else:
                stored = storage.get_lesson(lesson_id)
                storage.update_lesson_details(lesson_id, subject_id, title)
                if not stored.audio_path or Path(stored.audio_path).resolve() != source.resolve():
                    lesson_audio.attach_audio_to_lesson(lesson_id, source, max_size_bytes=MAX_FILE_BYTES)
                job.lesson_id = lesson_id
            return transcribe_lesson(job.lesson_id, model=model, prompt=prompt,
                                     cancel_event=job.stop_event, progress=job.message.emit, reduce_noise=reduce_noise)
        self.state.setText("Сохранение аудио и запуск распознавания…")
        self._start(process, "transcribe")

    def _finished(self):
        job, mode = self.job, self.mode
        self.job = None
        if job.lesson_id is not None:
            self.lesson_id = job.lesson_id
            lesson = storage.get_lesson(self.lesson_id)
            self._set_source(Path(lesson.audio_path) if lesson.audio_path else None)
            self._replace_audio = not lesson.audio_path or not Path(lesson.audio_path).is_file()
        if job.error is not None:
            self.state.setText(str(job.error))
        elif mode == "record":
            self._set_source(job.result)
            self.state.setText("Запись сохранена.")
        elif mode == "notes":
            self._notes_source = job.result.transcript
            self.notes.setMarkdown(job.result.summary or "")
            self.tabs.setCurrentIndex(1)
            self.notes_hint.setText("Конспект сохранён в лекции. Можно исправить его и сохранить правки.")
            self.state.setText("ИИ-конспект готов и сохранён.")
        else:
            self.lesson_id = job.result.id
            self._set_source(Path(job.result.audio_path) if job.result.audio_path else None)
            previous_transcript = self._loaded_transcript
            self.text.setPlainText(job.result.transcript or "")
            self._loaded_transcript = job.result.transcript or ""
            self._notes_source = job.result.transcript or ""
            if self._notes_source != previous_transcript:
                self.notes.setMarkdown(job.result.summary or "")
            self.state.setText("Расшифровка сохранена. Конспект можно создать на вкладке «Конспект».")
        self._busy(False)
        self.lesson_changed.emit()
        job.deleteLater()
        if mode == "record" and job.error is None and self._auto_transcribe:
            self._auto_transcribe = False
            self._transcribe()
        elif mode == "transcribe" and job.error is None and self.auto_notes.isChecked():
            self._generate_notes()

    def _reset_processing(self):
        answer = QMessageBox.question(
            self, "Восстановить обработку",
            "Если приложение было аварийно закрыто, статус мог остаться «Обрабатывается». "
            "Убедитесь, что этот урок сейчас не обрабатывается в другой копии приложения. "
            "Вернуть его в очередь?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            try:
                storage.set_lesson_status(self.lesson_id, storage.STATUS_QUEUED)
                self.reset.hide()
                self.state.setText("Урок снова в очереди. Можно запустить распознавание.")
                self.lesson_changed.emit()
            except Exception as error:
                self.state.setText(str(error))

    def _confirm_replace(self, text):
        return QMessageBox.question(
            self, "Несохранённые правки", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

    def _save(self):
        if not self._validate():
            return False
        transcript = self.text.toPlainText().strip()
        if not transcript and self._loaded_transcript:
            self.state.setText("Расшифровка пуста. Для сохранения добавьте текст.")
            return False
        if transcript != self._loaded_transcript and self.notes.document().isModified():
            if not self._confirm_replace("Изменение расшифровки сбросит прежний конспект и его несохранённые правки."):
                return False
        try:
            created_from_text = self.lesson_id is None and self.source is None
            if self.lesson_id is None:
                if self.source is None:
                    if not transcript:
                        return False
                    lesson = storage.create_lesson(self.subjects.currentData(), self.title.text(), None, transcript=transcript)
                else:
                    lesson = lesson_audio.create_lesson_with_audio(self.subjects.currentData(), self.title.text().strip(), self.source, max_size_bytes=MAX_FILE_BYTES)
                self.lesson_id = lesson.id
                self._set_source(Path(lesson.audio_path) if lesson.audio_path else None)
            else:
                stored = storage.get_lesson(self.lesson_id)
                storage.update_lesson_details(self.lesson_id, self.subjects.currentData(), self.title.text())
                if self.source is not None and (not stored.audio_path or Path(stored.audio_path).resolve() != self.source.resolve()):
                    lesson = lesson_audio.attach_audio_to_lesson(self.lesson_id, self.source, max_size_bytes=MAX_FILE_BYTES)
                    self._set_source(Path(lesson.audio_path))
            self._replace_audio = self.source is None
            if transcript and transcript != self._loaded_transcript and not created_from_text:
                storage.save_lesson_transcript(self.lesson_id, transcript)
            stored = storage.get_lesson(self.lesson_id)
            if self._loaded_transcript != (stored.transcript or ""):
                self.notes.setMarkdown(stored.summary or "")
                self._notes_source = stored.transcript or ""
            self._loaded_transcript = stored.transcript or ""
            self._busy(False)
            self.state.setText("Лекция сохранена в выбранном предмете.")
            self.lesson_changed.emit()
            return True
        except Exception as error:
            self.state.setText(str(error))
            return False

    def _play(self):
        if self.source and self.source.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.source.resolve())))

    def _delete_audio(self):
        if self.job is not None or self.source is None:
            return
        if QMessageBox.question(self, "Удалить аудио", "Переместить аудио приложения в корзину? Текст лекции останется сохранённым.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            if self.lesson_id is not None:
                library.archive_lesson(self.lesson_id, audio_only=True)
            elif self.source.parent.resolve() == (storage.get_data_dir() / "recordings").resolve():
                library.archive_recording(self.source)
            self._set_source(None)
            self._replace_audio = True
            self._busy(False)
            self.state.setText("Аудио убрано. Файлы приложения можно восстановить из корзины.")
            self.lesson_changed.emit()
        except Exception as error:
            self.state.setText(str(error))

    def _delete_lesson(self):
        if self.job is not None or self.lesson_id is None:
            return
        if QMessageBox.question(self, "Удалить лекцию", "Переместить лекцию с её аудио и текстом в корзину?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            library.archive_lesson(self.lesson_id)
            self.lesson_changed.emit()
            self.accept()
        except Exception as error:
            self.state.setText(str(error))

    def _export_text(self):
        return self.notes.toMarkdown() if self.tabs.currentIndex() == 1 else self.text.toPlainText()

    def _update_note_buttons(self, *args):
        idle = self.job is None
        on_notes = self.tabs.currentIndex() == 1
        self.audio_panel.setVisible(not on_notes)
        self.transcribe.setVisible(not on_notes)
        self.import_text.setVisible(not on_notes)
        self.lesson_heading.setVisible(on_notes)
        self.lesson_heading.setText(self.title.text() or "Конспект лекции")
        self.save.setVisible(not on_notes)
        self.save.setEnabled(idle and (self.lesson_id is not None or self.source is not None
                                      or bool(self.text.toPlainText().strip())))
        self.export.setText("Экспорт конспекта" if on_notes else "Экспорт расшифровки")
        self.make_notes.setEnabled(idle and bool(self.text.toPlainText().strip()))
        self.save_notes.setEnabled(idle and self.lesson_id is not None and bool(self.notes.toPlainText().strip()))
        self.export.setEnabled(idle and bool(self._export_text().strip()))

    def _generate_notes(self):
        if self.job is not None:
            return
        if not self.text.toPlainText().strip():
            self.state.setText("Сначала получите расшифровку лекции.")
            return
        if self.notes.document().isModified() and self.text.toPlainText().strip() == self._loaded_transcript:
            if not self._confirm_replace("При успешной генерации несохранённые правки конспекта будут заменены."):
                return
        if not self._save():
            return
        lesson_id, style = self.lesson_id, self.notes_style.currentData()
        def generate(job):
            job.lesson_id = lesson_id
            return summarize_lesson(lesson_id, style=style, cancel_event=job.stop_event, progress=job.message.emit)
        self.tabs.setCurrentIndex(1)
        self.state.setText("Запуск локального создания конспекта…")
        self._start(generate, "notes")

    def _save_notes(self):
        if self.job is not None or self.lesson_id is None:
            return
        try:
            if self.text.toPlainText().strip() != self._notes_source:
                raise storage.StorageError("Расшифровка изменена. Сохраните её и создайте конспект заново.")
            storage.save_lesson_summary(self.lesson_id, self.notes.toMarkdown(), source_transcript=self._notes_source)
            self.notes.document().setModified(False)
            self.notes_hint.setText("Правки конспекта сохранены.")
            self.lesson_changed.emit()
        except Exception as error:
            self.state.setText(str(error))

    def _export(self):
        is_notes = self.tabs.currentIndex() == 1
        name = "конспект.md" if is_notes else "расшифровка.txt"
        file_filter = "Markdown (*.md);;Текст (*.txt)" if is_notes else "Текст (*.txt)"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить конспект" if is_notes else "Сохранить расшифровку", name, file_filter)
        if path:
            try:
                Path(path).write_text(self._export_text() + "\n", encoding="utf-8")
                self.state.setText(f"Сохранено: {path}")
            except OSError as error:
                self.state.setText(str(error))

    def reject(self):
        if self.job is not None:
            self.state.setText("Сначала остановите запись или отмените обработку и дождитесь завершения.")
            return
        if self.text.toPlainText().strip() != self._loaded_transcript or self.notes.document().isModified():
            if not self._confirm_replace("Закрыть лекцию без сохранения правок текста или конспекта?"):
                return
        super().reject()

    def closeEvent(self, event):
        if self.job is not None:
            event.ignore()
            self.reject()
        else:
            super().closeEvent(event)
