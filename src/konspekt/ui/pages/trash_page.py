from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QLabel, QPushButton, QHBoxLayout
from ... import library
from ..widgets import ScrollPage, Card
from ..formatting import format_datetime


class TrashPage(ScrollPage):
    restore_requested = Signal(int)

    def refresh(self):
        while self.body.count():
            widget = self.body.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        title = QLabel('Корзина')
        title.setObjectName('PageTitle')
        self.body.addWidget(title)
        self.body.addWidget(QLabel('Удалённые лекции и аудио можно восстановить.'))
        items = library.list_trash()
        names = {'lesson': 'Лекция', 'audio': 'Аудио лекции', 'recording': 'Запись'}
        for item in items:
            row = Card(); layout = QHBoxLayout(row)
            label = QLabel()
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setText(f'{names.get(item.kind, item.kind)}: {item.title}\n{format_datetime(item.created_at)}')
            label.setWordWrap(True)
            layout.addWidget(label, 1)
            restore = QPushButton('Восстановить')
            restore.clicked.connect(lambda checked=False, ident=item.id: self.restore_requested.emit(ident))
            layout.addWidget(restore)
            self.body.addWidget(row)
        if not items:
            self.body.addWidget(QLabel('Корзина пуста.'))
        self.body.addStretch(1)
