"""Readable local-only chat presentation. No HTML or external resource loading."""
import time

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget, QLayout)


def text_label(text, name="bubbleBody"):
    value = QLabel(text)
    value.setObjectName(name)
    value.setTextFormat(Qt.TextFormat.PlainText)
    value.setWordWrap(True)
    value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    value.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    return value


class ChatView(QScrollArea):
    # Large first loads yield between finite batches. Refreshes reuse the common
    # prefix rather than deleting thousands of widgets on each source poll.
    _BATCH_SIZE = 80
    _SYNC_LIMIT = 100

    def __init__(self, parent=None):
        super().__init__(parent)
        # QScrollArea's widgetResizable heightForWidth negotiation uses the
        # layout minimum width, which can massively overestimate wrapped text.
        # We own both canvas dimensions, measured at the actual viewport width.
        self.setWidgetResizable(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.canvas = QWidget()
        self.canvas.setObjectName("chatCanvas")
        self.rows = QVBoxLayout(self.canvas)
        self.rows.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.rows.setContentsMargins(8, 18, 8, 18)
        self.rows.setSpacing(20)
        self.setWidget(self.canvas)
        self._plain = ""
        self._signature = None
        self._raw_signature = None
        self._conversation = None
        self._bubbles = []
        self._entries = []
        self._formatted = []
        self._current_day = None
        self._follow_bottom = True
        self._layout_busy = False
        self._measured_width = None
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._fit)
        self._batch_timer = QTimer(self)
        self._batch_timer.setSingleShot(True)
        self._batch_timer.timeout.connect(self._append_batch)
        self.verticalScrollBar().valueChanged.connect(self._scroll_changed)
        self.viewport().installEventFilter(self)
        self.show_empty()

    def _reset(self):
        self._batch_timer.stop()
        self._fit_timer.stop()
        self.rows.setEnabled(True)
        self.canvas.setUpdatesEnabled(True)
        self._bubbles.clear()
        self._entries.clear()
        self._formatted = []
        self._current_day = None
        self._measured_width = None
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def show_empty(self, title="想聊谁？先选一位联系人吧。", subtitle="也可以直接写下你想回复的话。"):
        self._reset()
        self._plain = ""
        self._signature = None
        self._raw_signature = None
        self._conversation = None
        self._follow_bottom = True
        empty = QWidget()
        empty.setObjectName("chatCanvas")
        layout = QVBoxLayout(empty)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 28, 20, 28)
        heading = text_label(title, "section")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)
        if subtitle:
            caption = text_label(subtitle, "muted")
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(caption)
        self.rows.addStretch()
        self.rows.addWidget(empty)
        self.rows.addStretch()
        self._fit()

    def clear(self):
        self.show_empty()

    def toPlainText(self):
        return self._plain

    def setPlainText(self, text):
        self.show_empty("聊天预览", str(text))
        self._plain = str(text)

    @staticmethod
    def _date(message):
        try:
            return (time.strftime("%m月%d日", time.localtime(message.timestamp)),
                    time.strftime("%H:%M", time.localtime(message.timestamp)))
        except (ValueError, OSError, OverflowError):
            return "", ""

    def set_messages(self, messages, conversation_name="", conversation_id=""):
        from .message_format import format_message
        messages = list(messages)
        conversation = (conversation_id, conversation_name)
        # Snapshot the fields the safe formatter reads, not object identity:
        # source workers can enrich a ChatMessage in place between polls.
        raw_signature = tuple((m.id, m.timestamp, m.sender, m.text, m.kind, m.outgoing,
                               tuple(sorted((key, repr(value)) for key, value in (m.metadata or {}).items())))
                              for m in messages)
        if raw_signature == self._raw_signature and conversation == self._conversation:
            return
        previous_raw = self._raw_signature if conversation == self._conversation else None
        formatted = [self._formatted[index] if previous_raw is not None
                     and index < len(previous_raw) and index < len(self._formatted)
                     and previous_raw[index] == raw_signature[index]
                     else format_message(message, conversation_name, conversation_id)
                     for index, message in enumerate(messages)]
        signature = tuple((message.id, display) for message, display in zip(messages, formatted))
        if signature == self._signature and conversation == self._conversation:
            self._raw_signature = raw_signature
            return
        if not formatted:
            self.show_empty("这里还没有消息", "可以先在下方写点背景，或写下你想回复的话。")
            self._signature = signature
            self._raw_signature = raw_signature
            self._conversation = conversation
            return
        # Retain unchanged rows for appends and suffix edits (e.g. transcription).
        common = 0
        if conversation == self._conversation and self._signature is not None:
            for old, new in zip(self._signature, signature):
                if old != new:
                    break
                common += 1
        anchor = self._anchor()
        following = self._follow_bottom
        self._batch_timer.stop()
        # A bounded recent-history query rolls its window forward as messages
        # arrive. Reuse the overlapping rows instead of rebuilding the window.
        if not common and conversation == self._conversation and self._signature:
            try:
                shift = self._signature.index(signature[0])
            except ValueError:
                shift = 0
            overlap = min(len(self._signature) - shift, len(signature))
            if shift and shift < len(self._bubbles) and self._signature[shift:shift + overlap] == signature[:overlap]:
                for entry in self._entries[:shift]:
                    for widget in entry:
                        self.rows.removeWidget(widget)
                        widget.hide()
                        widget.deleteLater()
                del self._entries[:shift]
                del self._bubbles[:shift]
                common = min(overlap, len(self._bubbles))
                if len(self._entries[0]) == 1:
                    date = text_label(self._date(formatted[0])[0], "bubbleMeta")
                    date.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.rows.insertWidget(1, date)
                    self._entries[0].insert(0, date)
                    date.show()
        if not common:
            self._reset()
            self.rows.addStretch()  # Spare height belongs ABOVE the messages.
            if conversation != self._conversation or self._signature is None:
                following = True
        else:
            # A batch may not yet have materialized the complete common prefix.
            common = min(common, len(self._bubbles))
            while len(self._bubbles) > common:
                self._bubbles.pop()
                for widget in self._entries.pop():
                    self.rows.removeWidget(widget)
                    widget.hide()
                    widget.deleteLater()
            self._current_day = self._date(formatted[common - 1])[0] if common else None
        self._follow_bottom = following
        self._signature = signature
        self._raw_signature = raw_signature
        self._conversation = conversation
        self._formatted = formatted
        self._plain = "\n\n".join(
            f"{message.speaker} · {self._date(message)[1]}\n" +
            "\n".join(s for s in (message.title, message.body, message.detail) if s)
            for message in formatted)
        self._append_batch(anchor, synchronous=len(formatted) - len(self._bubbles) <= self._SYNC_LIMIT)

    def _append_batch(self, anchor=None, *, synchronous=False):
        if anchor is None:
            anchor = self._anchor()
        start = len(self._bubbles)
        end = len(self._formatted) if synchronous else min(start + self._BATCH_SIZE, len(self._formatted))
        self.canvas.setUpdatesEnabled(False)
        self.rows.setEnabled(False)
        try:
            for message in self._formatted[start:end]:
                self._append_message(message)
            self._fit(anchor)
        finally:
            # Do not repaint the entire growing hierarchy after every batch.
            # The event loop still runs; enable painting once the finite load
            # has reached its latest message (or reset cancels it).
            self.canvas.setUpdatesEnabled(end == len(self._formatted))
        if end < len(self._formatted):
            # Not a settle/retry loop: each timeout consumes a bounded batch,
            # and reset/replacement cancels the sole pending callback.
            self._batch_timer.start(0)

    def _append_message(self, message):
        day, stamp = self._date(message)
        entry = []
        if day != self._current_day:
            date = text_label(day, "bubbleMeta")
            date.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.rows.addWidget(date)
            entry.append(date)
            self._current_day = day
        row = QWidget()
        row.setObjectName("chatCanvas")
        horizontal = QHBoxLayout(row)
        horizontal.setContentsMargins(0, 0, 0, 0)
        horizontal.setSpacing(0)
        stack = QWidget()
        stack.setObjectName("chatCanvas")
        content = QVBoxLayout(stack)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(6)
        conversation_id = self._conversation[0]
        meta_text = f"{message.speaker}  ·  {stamp}" if conversation_id.endswith("@chatroom") or message.speaker == "方向未确认" else stamp
        meta = text_label(meta_text, "bubbleMeta")
        if message.outgoing:
            meta.setAlignment(Qt.AlignmentFlag.AlignRight)
        content.addWidget(meta)
        bubble = QFrame()
        special = message.kind not in {"text", "system"}
        bubble.setObjectName("share" if special else "outgoing" if message.outgoing else "incoming")
        body = QVBoxLayout(bubble)
        body.setContentsMargins(15, 12, 15, 13)
        body.setSpacing(9)
        if message.title:
            body.addWidget(text_label(message.title, "bubbleTitle"))
        if message.body:
            body.addWidget(text_label(message.body))
        if message.detail:
            body.addWidget(text_label(message.detail, "bubbleMeta"))
        content.addWidget(bubble)
        if message.outgoing:
            horizontal.addStretch(1)
        horizontal.addWidget(stack)
        if not message.outgoing:
            horizontal.addStretch(1)
        self._bubbles.append(stack)
        self.rows.addWidget(row)
        entry.append(row)
        self._entries.append(entry)
        row.show()
        for widget in entry[:-1]:
            widget.show()

    def _scroll_changed(self, value):
        if not self._layout_busy:
            self._follow_bottom = self.verticalScrollBar().maximum() - value <= 2

    def _anchor(self):
        """Retain a visible row and its pixel offset, including across rewraps."""
        bar = self.verticalScrollBar()
        if self._follow_bottom:
            return None
        for stack in self._bubbles:
            top = stack.mapTo(self.canvas, QPoint()).y()
            if top + stack.height() > bar.value():
                return stack, top - bar.value()
        return None

    def _fit(self, anchor=None):
        if self._layout_busy:
            return
        if anchor is None:
            anchor = self._anchor()
        self._layout_busy = True
        try:
            width = max(1, self.viewport().width())
            bubble_width = max(1, int(max(1, width - 24) * .88))
            resized = []
            for stack in self._bubbles:
                if stack.width() != bubble_width or self._measured_width != width or not stack.minimumHeight():
                    stack.ensurePolished()
                    stack.setFixedWidth(bubble_width)
                    layout = stack.layout()
                    layout.invalidate()
                    height = max(layout.totalMinimumSize().height(), layout.totalHeightForWidth(bubble_width))
                    stack.setFixedHeight(height)
                    stack.parentWidget().setFixedHeight(height)
                    resized.append(stack)
            self._measured_width = width
            self.rows.invalidate()
            # Explicitly use the viewport width; never an unconstrained sizeHint
            # or the minimum width used by widgetResizable's negotiation.
            height = max(self.viewport().height(), self.rows.totalHeightForWidth(width),
                         self.rows.totalMinimumSize().height())
            self.canvas.setMinimumHeight(height)
            self.canvas.resize(width, height)
            self.rows.setGeometry(self.canvas.rect())
            self.rows.activate()
            # Child geometry must be settled before mapping an anchor/bubble.
            for stack in resized:
                stack.parentWidget().layout().activate()
                stack.layout().activate()
            bar = self.verticalScrollBar()
            if self._follow_bottom:
                bar.setValue(bar.maximum())
            elif anchor is not None and anchor[0] in self._bubbles:
                bar.setValue(anchor[0].mapTo(self.canvas, QPoint()).y() - anchor[1])
        finally:
            self._layout_busy = False

    def eventFilter(self, watched, event):
        if watched is self.viewport() and event.type() == QEvent.Type.Resize:
            # Coalesce actual viewport changes (including scrollbar appearance),
            # not timed guesses about when a large hierarchy will have settled.
            self._fit_timer.start(0)
        return super().eventFilter(watched, event)
