"""
Syntax highlighting for Python, in any text widget.

Brought across as it was - it is the newest and most careful module in the package, and it
already handles both of Qt's regular expression APIs. One line had to change:

    def color_format(color: Sequence[int] | str, style: str = "") -> ...

``X | Y`` in an annotation is Python 3.10 and later, and an annotation is evaluated when the
function is defined, so **this module could not be imported in Maya 2022 at all** - Python
3.7 there, where that line raises TypeError before anything has run. ``from __future__
import annotations`` makes annotations text until something asks for them, which works back
to 3.7 and leaves the annotations exactly as they are written.
"""

from __future__ import annotations

from typing import Any, Iterator, Sequence, Tuple

from mca.common.pyqt.pygui import qtcore, qtgui

_HAS_QREGULAR_EXPRESSION = hasattr(qtcore, "QRegularExpression")

if _HAS_QREGULAR_EXPRESSION:
    _RegexType = qtcore.QRegularExpression
else:
    _RegexType = qtcore.QRegExp


def _iter_matches(expression: Any, text: str, capture_index: int) -> Iterator[Tuple[int, int]]:
    """
    Yield match start/length tuples for an expression, supporting both Qt regex APIs.

    :param Any expression: Compiled regular expression instance.
    :param str text: Text to search.
    :param int capture_index: Capture group index to highlight.
    :return: Iterator providing start/length per match.
    :rtype: Iterator[Tuple[int, int]]
    """
    if _HAS_QREGULAR_EXPRESSION:
        iterator = expression.globalMatch(text)
        while iterator.hasNext():
            match = iterator.next()
            start = match.capturedStart(capture_index)
            length = match.capturedLength(capture_index)
            if start >= 0 and length > 0:
                yield start, length
    else:
        index = expression.indexIn(text, 0)
        while index >= 0:
            if capture_index == 0:
                start = index
                length = expression.matchedLength()
            else:
                start = expression.pos(capture_index)
                length = len(expression.cap(capture_index))
            if start >= 0 and length > 0:
                yield start, length
            step = max(expression.matchedLength(), 1)
            index = expression.indexIn(text, index + step)


def _first_match(expression: Any, text: str, start: int) -> Tuple[int, int]:
    """
    Return the first match start/length at or after a position.

    :param Any expression: Compiled regular expression instance.
    :param str text: Text to search.
    :param int start: Offset to begin search.
    :return: Tuple of (match_start, match_length) or (-1, 0) if not found.
    :rtype: Tuple[int, int]
    """
    if _HAS_QREGULAR_EXPRESSION:
        match = expression.match(text, start)
        if match.hasMatch():
            return match.capturedStart(), match.capturedLength()
        return -1, 0

    index = expression.indexIn(text, start)
    if index >= 0:
        return index, expression.matchedLength()
    return -1, 0


def color_format(color: Sequence[int] | str, style: str = "") -> qtgui.QTextCharFormat:
    """
    Build a ``qtgui.QTextCharFormat`` with the provided colour/style attributes.

    :param Sequence[int] | str color: Colour name or RGBA sequence.
    :param str style: Optional style flags (supports ``bold`` and ``italic``).
    :return: Configured text format.
    :rtype: qtgui.QTextCharFormat
    """
    _color = qtgui.QColor()
    if isinstance(color, (list, tuple)):
        _color.setRgb(color[0], color[1], color[2], color[3])
    elif isinstance(color, str):
        _color.setNamedColor(color)

    _format = qtgui.QTextCharFormat()
    _format.setForeground(_color)
    if 'bold' in style:
        _format.setFontWeight(qtgui.QFont.Bold)
    if 'italic' in style:
        _format.setFontItalic(True)

    return _format


# Syntax styles that can be shared by all languages
STYLES = {
    'keyword': color_format(color=(185, 128, 92, 255), style='bold'),
    'operator': color_format(color=(100, 130, 150, 255)),
    'brace': color_format(color=(232, 186, 54, 255)),
    'defclass': color_format(color=(139, 153, 198, 255)),
    'string': color_format(color=(206, 215, 74, 255)),
    'string2': color_format(color=(80, 155, 85, 255)),
    'comment': color_format(color=(0, 255, 53, 255), style='italic'),
    'self': color_format(color=(0, 255, 233, 255)),
    'numbers': color_format(color=(104, 151, 187, 255)),
    'built_in': color_format(color=(136, 136, 198, 255))
}


class PythonHighlighter(qtgui.QSyntaxHighlighter):
    """
    Syntax highlighter for the Python language.
    """

    # Python keywords
    keywords = [
        'and', 'assert', 'break', 'continue', 'class', 'def',
        'del', 'elif', 'else', 'except', 'exec', 'finally',
        'for', 'from', 'global', 'if', 'import', 'in',
        'is', 'lambda', 'not', 'or', 'pass', 'print',
        'raise', 'return', 'try', 'while', 'yield',
        'None', 'True', 'False'
    ]

    built_in = [
        'tuple', 'list', 'str', 'dict'
    ]

    # Python operators
    operators = [
        '=',
        # Comparison
        '==', '!=', '<', '<=', '>', '>=',
        # Arithmetic
        r'\+', '-', r'\*', '/', '//', r'\%', r'\*\*',
        # In-place
        r'\+=', '-=', r'\*=', '/=', r'\%=',
        # Bitwise
        r'\^', r'\|', r'\&', r'~', '>>', '<<',
    ]

    # Python braces
    braces = [
        r'\{', r'\}', r'\(', r'\)', r'\[', r'\]',
    ]

    def __init__(self, parent: qtgui.QTextDocument) -> None:
        super().__init__(parent)

        # Multi-line strings (expression, flag, style)
        self.tri_single = (_RegexType("'''"), 1, STYLES['string2'])
        self.tri_double = (_RegexType('"""'), 2, STYLES['string2'])

        rules = []

        # Keyword, operator, and brace rules
        rules += [(fr'\b{w}\b', 0, STYLES['keyword']) for w in PythonHighlighter.keywords]
        rules += [(fr'\b{w}\b', 0, STYLES['built_in']) for w in PythonHighlighter.built_in]
        rules += [(fr'{o}', 0, STYLES['operator']) for o in PythonHighlighter.operators]
        rules += [(fr'{b}', 0, STYLES['brace']) for b in PythonHighlighter.braces]

        # All other rules
        rules += [
            # 'self'
            (r'\bself\b', 0, STYLES['self']),
            (r'\bcls\b', 0, STYLES['self']),

            # 'def' followed by an identifier
            (r'\bdef\b\s*(\w+)', 1, STYLES['defclass']),
            # 'class' followed by an identifier
            (r'\bclass\b\s*(\w+)', 1, STYLES['defclass']),

            # Numeric literals
            (r'\b[+-]?[0-9]+[lL]?\b', 0, STYLES['numbers']),
            (r'\b[+-]?0[xX][0-9A-Fa-f]+[lL]?\b', 0, STYLES['numbers']),
            (r'\b[+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\b', 0, STYLES['numbers']),

            # Double-quoted string, possibly containing escape sequences
            (r'"[^"\\]*(\\.[^"\\]*)*"', 0, STYLES['string']),
            # Single-quoted string, possibly containing escape sequences
            (r"'[^'\\]*(\\.[^'\\]*)*'", 0, STYLES['string']),

            # From '#' until a newline
            (r'#[^\n]*', 0, STYLES['comment']),
        ]

        # Build a qtcore.QRegularExpression for each pattern
        self.rules = [(_RegexType(pat), index, fmt) for (pat, index, fmt) in rules]


    def highlightBlock(self, text: str) -> None:
        """
        Apply syntax highlighting to the given block of text.

        :param str text: Text that will get highlighted.
        """
        for expression, capture_index, text_format in self.rules:
            for start, length in _iter_matches(expression, text, capture_index):
                self.setFormat(start, length, text_format)

        self.setCurrentBlockState(0)

        # Do multi-line strings
        in_multiline = self.match_multiline(text, *self.tri_single)
        if not in_multiline:
            in_multiline = self.match_multiline(text, *self.tri_double)

    def match_multiline(
        self,
        text: str,
        delimiter: Any,
        in_state: int,
        style: qtgui.QTextCharFormat,
    ) -> bool:
        """
        Do highlighting of multi-line strings. Returns True if we're still
        inside a multi-line string when this function is finished.

        :param str text: Text that will get highlighted.
        :param Any delimiter: Compiled expression used to locate the delimiter.
        :param int in_state: Unique integer that represents the state inside the string.
        :param qtgui.QTextCharFormat style: Character format to apply to the match.
        :return: True if still inside a multi-line string, False otherwise.
        :rtype: bool
        """

        if self.previousBlockState() == in_state:
            start = 0
            delimiter_length = 0
        else:
            start, delimiter_length = _first_match(delimiter, text, 0)
            if start < 0:
                return False

        while start >= 0:
            end_start, end_length = _first_match(delimiter, text, start + delimiter_length)
            if end_start >= 0:
                total_length = end_start - start + delimiter_length + end_length
                self.setFormat(start, total_length, style)
                self.setCurrentBlockState(0)
                start, delimiter_length = _first_match(delimiter, text, end_start + end_length)
            else:
                self.setCurrentBlockState(in_state)
                remaining = len(text) - start
                if remaining > 0:
                    self.setFormat(start, remaining, style)
                return True

        return False

