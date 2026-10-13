"""All saved lessons, including imports that can be retried after a failure."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QPushButton, QLabel

from ... import storage
from ..formatting import format_datetime
from ..widgets import ScrollPage, LessonRow


class LessonsPage(ScrollPage):
    lesson_requested = Signal(int)
    delete_requested = Signal(int)

    def refresh(self):
        while self.body.count():
            widget = self.body.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        self.body.addWidget(QLabel("Все лекции"))
        try:
            subjects = storage.list_subjects()
            lessons = [(lesson, subject.name) for subject in subjects for lesson in storage.list_lessons(subject.id)]
            for lesson, subject_name in sorted(lessons, key=lambda item: item[0].id, reverse=True):
                row = LessonRow(lesson.title, f"{subject_name} · {format_datetime(lesson.created_at)}",
                                lesson.status, lesson.error_message)
                button = QPushButton("Открыть")
                button.clicked.connect(lambda checked=False, ident=lesson.id: self.lesson_requested.emit(ident))
                row.layout().addWidget(button)
                delete = QPushButton("Удалить")
                delete.clicked.connect(lambda checked=False, ident=lesson.id: self.delete_requested.emit(ident))
                row.layout().addWidget(delete)
                self.body.addWidget(row)
            if not lessons:
                self.body.addWidget(QLabel("Добавьте первую лекцию на главной странице."))
        except Exception as error:
            label = QLabel()
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setText(str(error))
            self.body.addWidget(label)
        self.body.addStretch(1)
