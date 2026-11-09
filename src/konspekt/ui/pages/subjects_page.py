"""Subjects with their real saved lessons, including queued/failed recordings."""
from PySide6.QtCore import Signal, QSignalBlocker, Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QVBoxLayout

from ... import storage
from ..formatting import format_datetime
from ..widgets import ScrollPage, LessonRow


class SubjectsPage(ScrollPage):
    lesson_requested = Signal(int)
    delete_requested = Signal(int)
    add_requested = Signal(int)
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        heading = QLabel('Предметы')
        heading.setObjectName('PageTitle')
        self.body.addWidget(heading)
        row = QHBoxLayout()
        self.subjects = QComboBox()
        self.subjects.currentIndexChanged.connect(self._show_lessons)
        add = QPushButton('+ Предмет')
        add.clicked.connect(self._add_subject)
        self.add_lesson = QPushButton('+ Лекция в этом предмете')
        self.add_lesson.clicked.connect(self._add_lesson)
        row.addWidget(self.subjects, 1)
        row.addWidget(add)
        self.rename = QPushButton('Переименовать')
        self.rename.clicked.connect(self._rename_subject)
        row.addWidget(self.rename)
        row.addWidget(self.add_lesson)
        self.body.addLayout(row)
        self.rows = QVBoxLayout()
        self.body.addLayout(self.rows)
        self.body.addStretch(1)

    def refresh(self):
        selected = self.subjects.currentData()
        with QSignalBlocker(self.subjects):
            self.subjects.clear()
            for subject in storage.list_subjects():
                count = len(storage.list_lessons(subject.id))
                self.subjects.addItem(f'{subject.name} ({count})', subject.id)
            index = self.subjects.findData(selected)
            if index >= 0:
                self.subjects.setCurrentIndex(index)
        self.add_lesson.setEnabled(self.subjects.count() > 0)
        self.rename.setEnabled(self.subjects.count() > 0)
        self._show_lessons()

    def _show_lessons(self, index=None):
        while self.rows.count():
            widget = self.rows.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        subject_id = self.subjects.currentData()
        lessons = storage.list_lessons(subject_id) if subject_id is not None else []
        for lesson in reversed(lessons):
            row = LessonRow(lesson.title, format_datetime(lesson.created_at), lesson.status, lesson.error_message)
            open_button = QPushButton('Открыть')
            open_button.clicked.connect(lambda checked=False, ident=lesson.id: self.lesson_requested.emit(ident))
            delete = QPushButton('Удалить')
            delete.setObjectName(f'deleteLesson_{lesson.id}')
            delete.clicked.connect(lambda checked=False, ident=lesson.id: self.delete_requested.emit(ident))
            row.layout().addWidget(open_button)
            row.layout().addWidget(delete)
            self.rows.addWidget(row)
        if not lessons:
            self.rows.addWidget(QLabel('В этом предмете пока нет лекций.' if subject_id is not None else 'Создайте первый предмет.'))

    def _add_subject(self):
        name, ok = QInputDialog.getText(self, 'Новый предмет', 'Название:')
        if ok:
            try:
                subject = storage.create_subject(name)
                self.refresh()
                self.subjects.setCurrentIndex(self.subjects.findData(subject.id))
                self.changed.emit()
            except Exception as error:
                QMessageBox.warning(self, 'Предмет', str(error))

    def _rename_subject(self):
        subject_id = self.subjects.currentData()
        if subject_id is None:
            return
        try:
            current = storage.get_subject(subject_id)
            name, ok = QInputDialog.getText(self, 'Переименование', 'Название:', text=current.name)
            if ok:
                storage.rename_subject(subject_id, name)
                self.changed.emit()
        except storage.StorageError as error:
            QMessageBox.warning(self, 'Предмет', str(error))

    def _add_lesson(self):
        if self.subjects.currentData() is not None:
            self.add_requested.emit(self.subjects.currentData())
