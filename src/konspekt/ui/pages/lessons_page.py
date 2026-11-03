"""Search saved lessons by title, subject, transcript or notes."""
from PySide6.QtCore import Signal, Qt, QSignalBlocker, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QPushButton, QLabel, QLineEdit, QComboBox, QVBoxLayout, QHBoxLayout

from ... import storage, search
from ..formatting import format_datetime, status_style
from ..widgets import ScrollPage, LessonRow


class LessonsPage(ScrollPage):
    lesson_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, parent=None, *, title="Все лекции"):
        super().__init__(parent)
        heading = QLabel(title)
        heading.setObjectName("PageTitle")
        self.body.addWidget(heading)
        self.query = QLineEdit()
        self.query.setAccessibleName("Поиск по лекциям")
        self.query.setPlaceholderText("Название, предмет или слова из расшифровки и конспекта")
        self.query.setClearButtonEnabled(True)
        self.query.setMaxLength(search.MAX_QUERY_CHARS)
        self.body.addWidget(self.query)

        filters = QHBoxLayout()
        self.subjects = QComboBox()
        self.subjects.setAccessibleName("Предмет для поиска")
        self.statuses = QComboBox()
        self.statuses.setAccessibleName("Состояние обработки")
        self.statuses.addItem("Любое состояние", None)
        for status in storage.ALL_STATUSES:
            self.statuses.addItem(status_style(status).text, status)
        self.clear = QPushButton("Сбросить поиск")
        self.clear.clicked.connect(self._clear_filters)
        filters.addWidget(self.subjects, 1)
        filters.addWidget(self.statuses, 1)
        filters.addWidget(self.clear)
        self.body.addLayout(filters)

        self.result_count = QLabel()
        self.result_count.setObjectName("Muted")
        self.result_count.setWordWrap(True)
        self.body.addWidget(self.result_count)
        self.rows = QVBoxLayout()
        self.body.addLayout(self.rows)
        self.body.addStretch(1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(180)
        self._timer.timeout.connect(self._show_results)
        self.query.textChanged.connect(lambda: self._timer.start())
        self.query.returnPressed.connect(self._show_results)
        self.subjects.currentIndexChanged.connect(self._show_results)
        self.statuses.currentIndexChanged.connect(self._show_results)
        self._find_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        self._find_shortcut.activated.connect(self.query.setFocus)

    def refresh(self):
        selected = self.subjects.currentData()
        try:
            subjects = storage.list_subjects()
            with QSignalBlocker(self.subjects):
                self.subjects.clear()
                self.subjects.addItem("Все предметы", None)
                for subject in subjects:
                    self.subjects.addItem(subject.name, subject.id)
                index = self.subjects.findData(selected)
                self.subjects.setCurrentIndex(max(0, index))
            self._show_results()
        except Exception as error:
            self._clear_rows()
            self._show_error(error)

    def _clear_rows(self):
        while self.rows.count():
            widget = self.rows.takeAt(0).widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

    def _show_results(self):
        self._timer.stop()
        self._clear_rows()
        try:
            result = search.search_lessons(self.query.text(), subject_id=self.subjects.currentData(),
                                           status=self.statuses.currentData())
            self.result_count.setText(f"Найдено лекций: {result.total}" if result.total <= search.RESULT_LIMIT
                                     else f"Найдено лекций: {result.total}. Показаны первые {search.RESULT_LIMIT}, уточните запрос.")
            for match in result.matches:
                lesson = match.lesson
                row = LessonRow(lesson.title, f"{match.subject_name} · {format_datetime(lesson.created_at)}",
                                lesson.status, lesson.error_message, preview=match.excerpt)
                row.setProperty("lesson_id", lesson.id)
                button = QPushButton("Открыть")
                button.clicked.connect(lambda checked=False, ident=lesson.id: self.lesson_requested.emit(ident))
                row.layout().addWidget(button)
                delete = QPushButton("Удалить")
                delete.clicked.connect(lambda checked=False, ident=lesson.id: self.delete_requested.emit(ident))
                row.layout().addWidget(delete)
                self.rows.addWidget(row)
            if not result.matches:
                message = "Совпадений нет. Измените запрос или сбросьте фильтры." if (
                    self.query.text().strip() or self.subjects.currentData() is not None or self.statuses.currentData() is not None
                ) else "Добавьте первую лекцию на главной странице."
                self.rows.addWidget(QLabel(message))
        except Exception as error:
            self._show_error(error)

    def _show_error(self, error):
        self.result_count.clear()
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setText(str(error))
        label.setWordWrap(True)
        self.rows.addWidget(label)

    def _clear_filters(self):
        with QSignalBlocker(self.query), QSignalBlocker(self.subjects), QSignalBlocker(self.statuses):
            self.query.clear()
            self.subjects.setCurrentIndex(0)
            self.statuses.setCurrentIndex(0)
        self._show_results()
        self.query.setFocus()
