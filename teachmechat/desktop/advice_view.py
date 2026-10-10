"""Rich typography built with text cursors, never rendering model HTML."""
import re
from PySide6.QtGui import QTextCharFormat, QTextCursor, QTextBlockFormat, QFont
from PySide6.QtWidgets import QTextEdit

from .theme import COLORS


class AdviceAnalysis(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setAcceptRichText(False)
        self.setPlaceholderText("建议生成后，我会帮你理清对话，也提醒你照顾自己的感受。")
        self.document().setDocumentMargin(18)

    def show_advice(self, advice):
        self.clear()
        cursor = self.textCursor()
        for index, (title, body) in enumerate((("对话里发生了什么", advice.analysis),
                                             ("照顾好自己", advice.wellbeing),
                                             ("需要留意", "\n".join("• " + line for line in advice.limitations)))):
            if index:
                cursor.insertBlock()
            block = QTextBlockFormat()
            block.setTopMargin(14)
            block.setBottomMargin(10)
            cursor.setBlockFormat(block)
            heading = QTextCharFormat()
            heading.setFontPointSize(13)
            heading.setFontWeight(QFont.Weight.DemiBold)
            cursor.insertText(title, heading)
            cursor.insertBlock()
            body_block = QTextBlockFormat()
            body_block.setBottomMargin(7)
            body_block.setLineHeight(145, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            cursor.setBlockFormat(body_block)
            normal = QTextCharFormat()
            normal.setFontPointSize(11)
            normal.setFontWeight(QFont.Weight.Normal)
            # Only explicit **emphasis** receives weight; HTML remains literal text.
            for part in re.split(r"(\*\*[^*\n]{1,160}\*\*)", body):
                if part.startswith("**") and part.endswith("**"):
                    emphasis = QTextCharFormat(normal)
                    emphasis.setFontWeight(QFont.Weight.DemiBold)
                    cursor.insertText(part[2:-2], emphasis)
                else:
                    cursor.insertText(part, normal)
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.setTextCursor(cursor)
