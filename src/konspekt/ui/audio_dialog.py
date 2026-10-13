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
)

from .. import lesson_audio, storage, library
from ..pipeline import transcribe_lesson
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
            if not isinstance(error, TranscriptionCancelled):
                logging.getLogger(__name__).exception("Ошибка обработки аудио")


class AudioDialog(QDialog):
    lesson_changed = Signal()

    def __init__(self, lesson_id: int | None = None, parent=None, *, subject_id=None, source_path=None):
        super().__init__(parent)
        self.setWindowTitle("Запись и расшифровка лекции")
        self.resize(780, 720)
        self.lesson_id = lesson_id
        self.source = None
        self.job = None
        self.mode = None
        self._auto_transcribe = False
        self._replace_audio = False
        root = QVBoxLayout(self)
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
        root.addLayout(form)
        hint = QLabel("Аудио обрабатывается на компьютере бесплатно. При первом запуске выбранная модель скачивается из интернета. До 4 часов и 2 ГБ.")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.devices = QComboBox()
        self.devices.addItem("Микрофон по умолчанию", None)
        try:
            for index, name in list_input_devices():
                self.devices.addItem(name, index)
        except RecordingError as error:
            self.devices.setToolTip(str(error))
        root.addWidget(self.devices)
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
        root.addLayout(actions)
        self.source_label = QLabel("Аудио ещё не выбрано")
        self.source_label.setTextFormat(Qt.TextFormat.PlainText)
        self.source_label.setWordWrap(True)
        root.addWidget(self.source_label)
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setValue(0)
        self.level.setFormat("Уровень микрофона: %p%")
        root.addWidget(self.level)
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
        self.text = QTextEdit()
        self.text.setPlaceholderText("Здесь появится расшифровка. Её можно будет исправить и сохранить.")
        root.addWidget(self.text, 1)
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
        self.export = QPushButton("Экспорт в TXT")
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
            self.reset.setVisible(lesson.status == storage.STATUS_PROCESSING)
            self.state.setText(lesson.error_message or "Аудиозапись сохранена. Можно запустить распознавание повторно.")
        if lesson_id is None and source_path:
            self._set_source(Path(source_path))
        self._busy(False)
        self.text.textChanged.connect(lambda: self.export.setEnabled(self.job is None and bool(self.text.toPlainText().strip())))

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
        for widget in (self.models, self.context):
            widget.setEnabled(not busy)
        self.text.setReadOnly(busy)
        self.transcribe.setEnabled(not busy and self.source is not None)
        self.save.setEnabled(not busy and (existing or self.source is not None))
        self.delete_lesson.setEnabled(not busy and existing)
        self.delete_audio.setEnabled(not busy and self.source is not None)
        self.play.setEnabled(not busy and self.source is not None and self.source.is_file())
        self.export.setEnabled(not busy and bool(self.text.toPlainText().strip()))
        self.close_button.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.cancel.setVisible(busy and self.mode == "transcribe")
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
            self.state.setText("Отмена после текущего фрагмента или загрузки модели. Аудиозапись сохранится.")

    def _transcribe(self):
        if not self._validate() or self.source is None:
            return
        lesson_id, source = self.lesson_id, self.source
        subject_id, title = self.subjects.currentData(), self.title.text().strip()
        model, prompt = self.models.currentData(), self.context.text().strip() or None
        def process(job):
            if lesson_id is None:
                lesson = lesson_audio.create_lesson_with_audio(subject_id, title, source, max_size_bytes=MAX_FILE_BYTES)
                job.lesson_id = lesson.id
            else:
                stored = storage.get_lesson(lesson_id)
                if not stored.audio_path or Path(stored.audio_path).resolve() != source.resolve():
                    lesson_audio.attach_audio_to_lesson(lesson_id, source, max_size_bytes=MAX_FILE_BYTES)
                storage.update_lesson_details(lesson_id, subject_id, title)
                job.lesson_id = lesson_id
            return transcribe_lesson(job.lesson_id, model=model, prompt=prompt,
                                     cancel_event=job.stop_event, progress=job.message.emit)
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
        else:
            self.lesson_id = job.result.id
            self._set_source(Path(job.result.audio_path))
            self.text.setPlainText(job.result.transcript or "")
            self.state.setText("Расшифровка сохранена в уроке. Можно исправить текст или экспортировать его.")
        self._busy(False)
        self.lesson_changed.emit()
        job.deleteLater()
        if mode == "record" and job.error is None and self._auto_transcribe:
            self._auto_transcribe = False
            self._transcribe()

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

    def _save(self):
        if not self._validate():
            return
        try:
            if self.lesson_id is None:
                if self.source is None:
                    return
                lesson = lesson_audio.create_lesson_with_audio(self.subjects.currentData(), self.title.text().strip(), self.source, max_size_bytes=MAX_FILE_BYTES)
                self.lesson_id = lesson.id
                self._set_source(Path(lesson.audio_path))
            else:
                stored = storage.get_lesson(self.lesson_id)
                if self.source is not None and (not stored.audio_path or Path(stored.audio_path).resolve() != self.source.resolve()):
                    lesson = lesson_audio.attach_audio_to_lesson(self.lesson_id, self.source, max_size_bytes=MAX_FILE_BYTES)
                    self._set_source(Path(lesson.audio_path))
                storage.update_lesson_details(self.lesson_id, self.subjects.currentData(), self.title.text())
            self._replace_audio = self.source is None
            if self.text.toPlainText().strip():
                storage.save_lesson_transcript(self.lesson_id, self.text.toPlainText())
            self._busy(False)
            self.state.setText("Лекция сохранена в выбранном предмете.")
            self.lesson_changed.emit()
        except Exception as error:
            self.state.setText(str(error))

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

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить расшифровку", "расшифровка.txt", "Текст (*.txt)")
        if path:
            try:
                Path(path).write_text(self.text.toPlainText() + "\n", encoding="utf-8")
                self.state.setText(f"Сохранено: {path}")
            except OSError as error:
                self.state.setText(str(error))

    def reject(self):
        if self.job is not None:
            self.state.setText("Сначала остановите запись или отмените обработку и дождитесь завершения.")
            return
        super().reject()

    def closeEvent(self, event):
        if self.job is not None:
            event.ignore()
            self.reject()
        else:
            super().closeEvent(event)
