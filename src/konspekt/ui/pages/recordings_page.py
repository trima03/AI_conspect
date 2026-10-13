"""Capture originals that may not yet belong to a lecture."""
from PySide6.QtCore import Signal, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QPushButton

from ... import library
from ..widgets import ScrollPage, Card
from PySide6.QtWidgets import QHBoxLayout


class RecordingsPage(ScrollPage):
    recording_requested = Signal(str)
    delete_requested = Signal(str)
    lesson_requested = Signal(int)

    def refresh(self):
        while self.body.count():
            widget = self.body.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        title = QLabel('Записи с микрофона')
        title.setObjectName('PageTitle')
        self.body.addWidget(title)
        recordings = library.list_recordings()
        for recording in recordings:
            row = Card()
            layout = QHBoxLayout(row)
            label = QLabel()
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setText(f'{recording.path.name}\n{recording.size / 1024**2:.1f} МБ')
            label.setWordWrap(True)
            layout.addWidget(label, 1)
            play = QPushButton('Прослушать')
            play.clicked.connect(lambda checked=False, p=str(recording.path): QDesktopServices.openUrl(QUrl.fromLocalFile(p)))
            layout.addWidget(play)
            use = QPushButton('Открыть лекцию' if recording.lesson_ids else 'Добавить в предмет')
            if recording.lesson_ids:
                use.clicked.connect(lambda checked=False, ident=recording.lesson_ids[0]: self.lesson_requested.emit(ident))
            else:
                use.clicked.connect(lambda checked=False, p=str(recording.path): self.recording_requested.emit(p))
            layout.addWidget(use)
            delete = QPushButton('Удалить запись')
            delete.setEnabled(not recording.lesson_ids)
            delete.setToolTip('Связанное аудио удаляется в окне лекции.' if recording.lesson_ids else 'Переместить в корзину')
            delete.clicked.connect(lambda checked=False, p=str(recording.path): self.delete_requested.emit(p))
            layout.addWidget(delete)
            self.body.addWidget(row)
        if not recordings:
            self.body.addWidget(QLabel('Записей пока нет. Запишите лекцию через «Добавить лекцию».'))
        self.body.addStretch(1)
