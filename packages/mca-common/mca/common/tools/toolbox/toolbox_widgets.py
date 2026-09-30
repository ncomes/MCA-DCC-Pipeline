"""
The MCA Toolbox widget: sections of tools that users edit in place.

:class:`ToolboxWidget` is a plain QWidget so each DCC can host it the way that DCC needs (Maya dock, Unreal window,
standalone window). It never writes files itself; every edit goes through ``toolbox_library.ToolboxLibrary``, which
refreshes every open toolbox afterwards.

Interaction:

- Click a tool to run it. Right-click tools, section headers or empty space for edit options.
- Toggle **Edit Layout** to drag tools (within and across sections, even into another open toolbox) and to drag
  section headers to reorder sections. In edit layout mode clicks do not run tools, so nothing fires by accident.
- The filter matches tool names, tooltips, tags and section names. ``-word`` excludes.
"""

# python imports
import contextlib
import time

# Qt imports
from mca.common.pyqt.pygui import qtwidgets, qtcore, qtgui, shiboken

# MCA python imports
from mca.common import log
from mca.common.tools.toolbox import (toolbox_dialogs, toolbox_items, toolbox_library, toolbox_model,
                                      toolbox_runner, toolbox_vcs)

logger = log.MCA_LOGGER

__all__ = ['ToolboxWidget', 'GridFlowLayout']

ITEM_MIME = 'application/x-mca-toolbox-item'
SECTION_MIME = 'application/x-mca-toolbox-section'

# Narrowest a grid cell (a button) gets before the section drops to fewer columns.
MIN_CELL_WIDTH = 110
# Qt's "no maximum" widget size (QWIDGETSIZE_MAX is not exposed by PySide).
QWIDGETSIZE_MAX = 16777215
# Seconds between checks for toolbox files changed outside this session (Perforce sync, another DCC).
POLL_SECONDS = 5
# How long status messages stay visible.
STATUS_SECONDS = 10

# Returned by ToolboxWidget._edit when the edit failed (None is a valid result of many library calls).
FAILED = object()


def _exec_drag(drag):
    """
    :param qtgui.QDrag drag: The drag to run.
    :return: The drop action.
    :rtype: qtcore.Qt.DropAction
    """

    runner = getattr(drag, 'exec', None) or getattr(drag, 'exec_')
    return runner(qtcore.Qt.MoveAction)


def _event_pos(event):
    """
    Event position as a QPoint on PySide2 and PySide6.

    :param qtcore.QEvent event: A mouse or drag event.
    :return: The position in widget coordinates.
    :rtype: qtcore.QPoint
    """

    if hasattr(event, 'position'):
        return event.position().toPoint()
    return event.pos()


class _WindowFlashGuard(qtcore.QObject):
    """
    Application event filter that keeps windows shown while a panel is being built off the screen.

    Many MCA tool widgets are windows that call ``show()`` in their constructor. Embedding them would flash a window
    on screen for a moment. Qt sends the Show event before it maps the native window, so setting
    ``WA_DontShowOnScreen`` there keeps the window invisible.
    """

    def __init__(self):
        super().__init__()
        self.windows = []

    def eventFilter(self, obj, event):
        if event.type() == qtcore.QEvent.Show and isinstance(obj, qtwidgets.QWidget) and obj.isWindow() and \
                not obj.testAttribute(qtcore.Qt.WA_DontShowOnScreen):
            obj.setAttribute(qtcore.Qt.WA_DontShowOnScreen, True)
            self.windows.append(obj)
        return False

    def release(self, keep_hidden=None):
        """
        Undo the guard. The embedded panel is hidden (its frame shows it once parented); any other window the tool
        opened on purpose is really shown now.

        :param qtwidgets.QWidget keep_hidden: The panel widget that is about to be embedded.
        """

        for window in self.windows:
            if not shiboken.isValid(window):
                continue
            was_visible = window.isVisible()
            window.hide()
            window.setAttribute(qtcore.Qt.WA_DontShowOnScreen, False)
            if window is not keep_hidden and was_visible:
                window.show()
        self.windows = []


@contextlib.contextmanager
def _no_window_flash():
    """
    Context manager: windows shown inside it are kept off screen until :meth:`_WindowFlashGuard.release`.

    :return: The guard.
    :rtype: _WindowFlashGuard
    """

    app = qtwidgets.QApplication.instance()
    guard = _WindowFlashGuard()
    app.installEventFilter(guard)
    try:
        yield guard
    finally:
        app.removeEventFilter(guard)


def call_when_idle(callback, retry_ms=50):
    """
    Run a callback once no popup, modal dialog or mouse button is active.

    Hosts use this for anything a toolbox widget signal triggers that creates, docks or deletes windows (opening
    another toolbox from the picker, "New Toolbox"). Doing that inside the combo box or menu that emitted the signal can
    destroy the widget Qt returns into and abort the application. The callback should hold no widget references.

    :param callable callback: Called with no arguments. Exceptions are logged.
    :param int retry_ms: Milliseconds between checks while busy.
    """

    def attempt():
        app = qtwidgets.QApplication
        if app.activePopupWidget() or app.activeModalWidget() or app.mouseButtons() != qtcore.Qt.NoButton:
            qtcore.QTimer.singleShot(retry_ms, attempt)
            return
        try:
            callback()
        except Exception:
            logger.exception('Toolbox: deferred action failed.')

    qtcore.QTimer.singleShot(0, attempt)


def _relax_panel_width(widget):
    """
    Drop the fixed widths an embedded panel brought from its life as a window.

    Panel tools are windows built from Qt Designer files, which often pin the window's minimum and maximum width
    (Apply Skinning is locked to 250 px although its buttons fit in ~200). Inside a toolbox the dock decides the width,
    so those limits only clip the panel. Only the panel and its loaded ``.ui`` root are touched; limits deeper in the
    tool (e.g. fixed-size buttons) are real layout choices and stay. Heights are left alone.

    :param qtwidgets.QWidget widget: The embedded panel widget.
    """

    targets = [widget, getattr(widget, 'ui', None)]
    if isinstance(widget, qtwidgets.QMainWindow):
        targets.append(widget.centralWidget())
    for target in targets:
        if isinstance(target, qtwidgets.QWidget) and shiboken.isValid(target):
            target.setMinimumWidth(0)
            target.setMaximumWidth(QWIDGETSIZE_MAX)


# --- Layout ------------------------------------------------------------------------------------------------------

class GridFlowLayout(qtwidgets.QLayout):
    """
    Responsive grid: tools fill equal-width columns (as many as fit), full-width items (sliders, forms, panels) take
    a whole row. Hidden widgets take no space, which is how the filter hides tools without rebuilding them.
    """

    def __init__(self, parent=None, spacing=4):
        """
        :param qtwidgets.QWidget parent: Widget the layout is installed on.
        :param int spacing: Pixels between cells.
        """

        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(4, 4, 4, 4)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(qtcore.QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        margins = self.contentsMargins()
        # A full-width item that cannot shrink (e.g. an embedded panel with a row of buttons) sets the section's
        # minimum, so a narrow dock scrolls sideways instead of clipping the panel.
        content_width = MIN_CELL_WIDTH
        for item in self._items:
            if not item.isEmpty() and self._is_full_width(item):
                content_width = max(content_width, item.minimumSize().width())
        width = content_width + margins.left() + margins.right()
        return qtcore.QSize(width, self.heightForWidth(max(width, 200)))

    @staticmethod
    def _is_full_width(item):
        """
        :param qtwidgets.QLayoutItem item: Layout item.
        :return: True when the item's widget asked for a whole row.
        :rtype: bool
        """

        widget = item.widget()
        return bool(widget and widget.property(toolbox_items.FULL_WIDTH_PROPERTY))

    def _do_layout(self, rect, apply):
        """
        Place (or just measure) every visible item.

        :param qtcore.QRect rect: Available area.
        :param bool apply: Move the widgets; False only computes the height.
        :return: Height used.
        :rtype: int
        """

        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        spacing = self._spacing
        columns = max(1, (area.width() + spacing) // (MIN_CELL_WIDTH + spacing))
        cell_width = max(1, (area.width() - spacing * (columns - 1)) // columns)
        x0 = area.x()
        y = area.y()
        placed_any = False
        # Cells of the row being filled: [layout item, first column, span, height].
        row = []

        def flush_row(y):
            """Place the pending row, stretching its last tool over any empty cells. Returns the next row's y."""
            if not row:
                return y
            used_columns = row[-1][1] + row[-1][2]
            row[-1][2] += columns - used_columns
            if apply:
                for cell_item, first_column, span, height in row:
                    width = span * cell_width + (span - 1) * spacing
                    cell_item.setGeometry(qtcore.QRect(x0 + first_column * (cell_width + spacing), y, width, height))
            next_y = y + max(x[3] for x in row) + spacing
            row.clear()
            return next_y

        for item in self._items:
            if item.isEmpty():
                continue
            placed_any = True
            if self._is_full_width(item):
                y = flush_row(y)
                hint = item.sizeHint()
                height = item.heightForWidth(area.width()) if item.hasHeightForWidth() else hint.height()
                height = max(height, item.minimumSize().height())
                if apply:
                    item.setGeometry(qtcore.QRect(x0, y, area.width(), height))
                y += height + spacing
                continue
            hint = item.sizeHint()
            height = max(hint.height(), item.minimumSize().height())
            # A tool whose label does not fit one cell spans as many cells as it needs (up to the whole row).
            span = 1
            while span < columns and span * cell_width + (span - 1) * spacing < hint.width():
                span += 1
            column = row[-1][1] + row[-1][2] if row else 0
            if column + span > columns:
                y = flush_row(y)
                column = 0
            row.append([item, column, span, height])
            if column + span >= columns:
                y = flush_row(y)
        y = flush_row(y)
        used = (y - spacing if placed_any else y) - rect.y() + margins.bottom()
        return max(used, margins.top() + margins.bottom())

    def insertion_index(self, pos):
        """
        Where a tool dropped at ``pos`` should go, counted over all items (hidden ones included).

        :param qtcore.QPoint pos: Drop position in the parent widget.
        :return: Index to insert before (``count()`` means at the end).
        :rtype: int
        """

        best_index = len(self._items)
        best_distance = None
        for index, item in enumerate(self._items):
            if item.isEmpty():
                continue
            geometry = item.geometry()
            if geometry.contains(pos):
                if self._is_full_width(item):
                    return index if pos.y() < geometry.center().y() else index + 1
                return index if pos.x() < geometry.center().x() else index + 1
            # Nearest item wins when the drop lands in a gap.
            distance = (geometry.center() - pos).manhattanLength()
            if best_distance is None or distance < best_distance:
                best_distance = distance
                after = pos.y() > geometry.bottom() or (pos.y() >= geometry.top() and pos.x() > geometry.center().x())
                best_index = index + 1 if after else index
        return best_index


# --- Tool and section widgets ------------------------------------------------------------------------------------

class ItemFrame(qtwidgets.QFrame):
    """
    Wraps one tool widget: carries its ids, starts drags in edit mode and routes the context menu.
    """

    def __init__(self, toolbox, section, item, widget, full_width):
        """
        :param ToolboxWidget toolbox: The owning toolbox widget.
        :param toolbox_model.ToolboxSection section: The section the item lives in.
        :param toolbox_model.ToolboxItem item: The item.
        :param qtwidgets.QWidget widget: The widget created by the item type.
        :param bool full_width: Take a whole row in the grid.
        """

        super().__init__()
        self.toolbox = toolbox
        self.section = section
        self.item = item
        self.inner = widget
        self._press_pos = None
        self.setObjectName(f'tbx_item_{item.id}')
        self.setProperty(toolbox_items.FULL_WIDTH_PROPERTY, full_width)
        layout = qtwidgets.QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.addWidget(widget)
        # Embedded panels come in hidden (they were standalone windows or detached for a rebuild). Show them only now
        # that they are children of this frame, so nothing flashes on screen as a separate window.
        widget.setVisible(True)
        self.set_edit_mode(False)

    def set_edit_mode(self, enabled):
        """
        In edit mode the tool ignores the mouse so the frame can be dragged, and a dashed outline shows it is movable.

        :param bool enabled: Edit layout mode on/off.
        """

        self.edit_mode = enabled
        self.inner.setAttribute(qtcore.Qt.WA_TransparentForMouseEvents, enabled)
        self.setCursor(qtcore.Qt.OpenHandCursor if enabled else qtcore.Qt.ArrowCursor)
        border = '1px dashed #8a8a8a' if enabled else '1px solid transparent'
        self.setStyleSheet(f'QFrame#{self.objectName()} {{ border: {border}; border-radius: 3px; }}')

    def mousePressEvent(self, event):
        if self.edit_mode and event.button() == qtcore.Qt.LeftButton:
            self._press_pos = _event_pos(event)
            # Accept the press: a widget that ignores it never receives the following mouse moves, so no drag.
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.edit_mode and self._press_pos is not None and \
                (_event_pos(event) - self._press_pos).manhattanLength() >= qtwidgets.QApplication.startDragDistance():
            self._press_pos = None
            mime = qtcore.QMimeData()
            mime.setData(ITEM_MIME, qtcore.QByteArray(self.item.id.encode('utf-8')))
            drag = qtgui.QDrag(self)
            drag.setMimeData(mime)
            drag.setPixmap(self.grab())
            drag.setHotSpot(_event_pos(event))
            # The drop edits the library during exec(); keep this frame alive until exec() returns.
            with self.toolbox.busy():
                _exec_drag(drag)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        self.toolbox.show_item_menu(self.section, self.item, event.globalPos())


class SectionHeader(qtwidgets.QFrame):
    """
    Clickable section title bar: click collapses, drag (in edit mode) reorders, right-click edits.
    """

    def __init__(self, section_widget):
        """
        :param SectionWidget section_widget: The section this header belongs to.
        """

        super().__init__()
        self.section_widget = section_widget
        self._press_pos = None
        self._dragged = False
        self.setObjectName(f'tbx_header_{section_widget.section.id}')
        self.setMinimumHeight(24)
        layout = qtwidgets.QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        self.arrow = qtwidgets.QLabel()
        self.arrow.setFixedWidth(12)
        self.title = qtwidgets.QLabel(section_widget.section.name)
        self.title.setStyleSheet('font-weight: bold;')
        self.count = qtwidgets.QLabel()
        self.count.setStyleSheet('color: #9a9a9a;')
        layout.addWidget(self.arrow)
        layout.addWidget(self.title, 1)
        layout.addWidget(self.count)

    def mousePressEvent(self, event):
        if event.button() == qtcore.Qt.LeftButton:
            self._press_pos = _event_pos(event)
            self._dragged = False
            # Accept the press so this header receives the mouse moves (drag) and release (collapse click).
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        toolbox = self.section_widget.toolbox
        if toolbox.edit_mode and self._press_pos is not None and \
                (_event_pos(event) - self._press_pos).manhattanLength() >= qtwidgets.QApplication.startDragDistance():
            self._press_pos = None
            self._dragged = True
            mime = qtcore.QMimeData()
            mime.setData(SECTION_MIME, qtcore.QByteArray(self.section_widget.section.id.encode('utf-8')))
            drag = qtgui.QDrag(self)
            drag.setMimeData(mime)
            drag.setPixmap(self.grab())
            # The drop edits the library during exec(); keep this header alive until exec() returns.
            with toolbox.busy():
                _exec_drag(drag)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == qtcore.Qt.LeftButton and self._press_pos is not None and not self._dragged:
            self.section_widget.toggle_collapsed()
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        self.section_widget.toolbox.show_section_menu(self.section_widget.section, event.globalPos())


class SectionBody(qtwidgets.QWidget):
    """
    The grid of tools in a section. Accepts tool drops and draws where the tool will land.
    """

    def __init__(self, section_widget):
        """
        :param SectionWidget section_widget: The owning section.
        """

        super().__init__()
        self.section_widget = section_widget
        self.grid = GridFlowLayout(self)
        self._drop_index = None
        self.setAcceptDrops(True)

    def _accepts(self, event):
        return event.mimeData().hasFormat(ITEM_MIME)

    def dragEnterEvent(self, event):
        if self._accepts(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if not self._accepts(event):
            event.ignore()
            return
        event.acceptProposedAction()
        self._drop_index = self.grid.insertion_index(_event_pos(event))
        self.update()

    def dragLeaveEvent(self, event):
        self._drop_index = None
        self.update()

    def dropEvent(self, event):
        index = self.grid.insertion_index(_event_pos(event))
        self._drop_index = None
        self.update()
        if not self._accepts(event):
            event.ignore()
            return
        item_id = bytes(event.mimeData().data(ITEM_MIME)).decode('utf-8')
        event.acceptProposedAction()
        frames = self.section_widget.item_frames
        before_id = frames[index].item.id if index < len(frames) else None
        # Defer the edit: the drag source widget is destroyed by the rebuild and must outlive QDrag.exec().
        qtcore.QTimer.singleShot(0, lambda: self.section_widget.toolbox.drop_item(
            item_id, self.section_widget.section.id, before_id))

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drop_index is None:
            return
        painter = qtgui.QPainter(self)
        painter.setPen(qtgui.QPen(qtgui.QColor('#3daee9'), 3))
        frames = self.section_widget.item_frames
        visible = [x for x in frames if x.isVisible()]
        if self._drop_index < len(frames) and frames[self._drop_index].isVisible():
            geometry = frames[self._drop_index].geometry()
            if frames[self._drop_index].property(toolbox_items.FULL_WIDTH_PROPERTY):
                painter.drawLine(geometry.topLeft() + qtcore.QPoint(0, -2), geometry.topRight() + qtcore.QPoint(0, -2))
            else:
                painter.drawLine(geometry.topLeft() + qtcore.QPoint(-2, 0),
                                 geometry.bottomLeft() + qtcore.QPoint(-2, 0))
        elif visible:
            geometry = visible[-1].geometry()
            painter.drawLine(geometry.bottomLeft() + qtcore.QPoint(0, 3), geometry.bottomRight() + qtcore.QPoint(0, 3))
        else:
            painter.drawRect(self.rect().adjusted(2, 2, -2, -2))
        painter.end()


class SectionWidget(qtwidgets.QFrame):
    """
    One section: header plus a grid of tools, colored with this toolbox's colors.
    """

    def __init__(self, toolbox, section):
        """
        :param ToolboxWidget toolbox: The owning toolbox widget.
        :param toolbox_model.ToolboxSection section: The section to draw.
        """

        super().__init__()
        self.toolbox = toolbox
        self.section = section
        self.item_frames = []
        self.setObjectName(f'tbx_section_{section.id}')
        layout = qtwidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = SectionHeader(self)
        self.body = SectionBody(self)
        layout.addWidget(self.header)
        layout.addWidget(self.body)
        self.collapsed = section.id in (toolbox.library.get_state(toolbox.toolbox_name, 'collapsed', []) or [])
        self.apply_colors()
        self.populate()
        self.set_collapsed(self.collapsed, save=False)

    def apply_colors(self):
        """
        Color the section with this toolbox's (and the user's private) colors.
        """

        colors = self.toolbox.library.section_colors(self.toolbox.toolbox_name, self.section.id)
        background = colors.get('background')
        header = colors.get('header')
        section_style = f'QFrame#{self.objectName()} {{ border: 1px solid #3c3c3c; border-radius: 4px;'
        if background:
            section_style += f' background-color: {background};'
        self.setStyleSheet(section_style + ' }')
        header_name = self.header.objectName()
        header_style = f'QFrame#{header_name} {{ border-top-left-radius: 4px; border-top-right-radius: 4px;'
        header_style += f' background-color: {header or "#3a3a3a"}; }}'
        text = toolbox_items.text_color_for(header or '#3a3a3a')
        header_style += f' QFrame#{header_name} QLabel {{ color: {text}; background: transparent; }}'
        self.header.setStyleSheet(header_style)

    def populate(self):
        """
        Create a frame for every item in the section.
        """

        library = self.toolbox.library
        for item in self.section.items:
            resolved = library.resolve_item(item) or item
            type_class = toolbox_items.get_item_type(item.type)
            full_width = toolbox_items.get_item_type(resolved.type).FULL_WIDTH if item.type == 'reference' \
                else type_class.FULL_WIDTH
            color = library.item_color(self.toolbox.toolbox_name, item.id)
            try:
                widget = type_class.create_widget(item, self.toolbox, color)
            except Exception as exc:
                logger.exception(f'Toolbox: could not build "{item.name}".')
                widget = qtwidgets.QLabel(f'{item.name}: {exc}')
                widget.setEnabled(False)
            frame = ItemFrame(self.toolbox, self.section, item, widget, full_width)
            self.body.grid.addWidget(frame)
            self.item_frames.append(frame)
        self.header.count.setText(str(len(self.section.items)))
        if not self.section.items:
            hint = qtwidgets.QLabel('Empty section. Right-click the header to add a tool, or drag one here.')
            hint.setWordWrap(True)
            hint.setStyleSheet('color: #8a8a8a; padding: 6px;')
            hint.setProperty(toolbox_items.FULL_WIDTH_PROPERTY, True)
            self.body.grid.addWidget(hint)

    def set_collapsed(self, collapsed, save=True):
        """
        :param bool collapsed: Hide the tools.
        :param bool save: Remember the state for next time.
        """

        self.collapsed = collapsed
        self.body.setVisible(not collapsed)
        self.header.arrow.setText('▸' if collapsed else '▾')
        if save:
            library = self.toolbox.library
            name = self.toolbox.toolbox_name
            state = [x for x in (library.get_state(name, 'collapsed', []) or []) if x != self.section.id]
            if collapsed:
                state.append(self.section.id)
            library.set_state(name, 'collapsed', state)

    def toggle_collapsed(self):
        """
        Flip the collapsed state. Ignored while filtering, where sections are forced open.
        """

        if self.toolbox.filter_terms():
            return
        self.set_collapsed(not self.collapsed)

    def apply_filter(self, include, exclude):
        """
        Show only matching tools.

        :param list[str] include: Every term must match.
        :param list[str] exclude: No term may match.
        :return: True when anything in the section is visible.
        :rtype: bool
        """

        if not include and not exclude:
            for frame in self.item_frames:
                frame.setVisible(True)
            self.setVisible(True)
            self.set_collapsed(self.collapsed, save=False)
            return True

        section_text = self.section.name.lower()
        any_visible = False
        for frame in self.item_frames:
            resolved = self.toolbox.library.resolve_item(frame.item) or frame.item
            text = f'{section_text} {frame.item.search_text()} {resolved.search_text()}'
            visible = all(term in text for term in include) and not any(term in text for term in exclude)
            frame.setVisible(visible)
            any_visible = any_visible or visible
        self.setVisible(any_visible)
        if any_visible:
            # Force open while filtering without touching the saved collapsed state.
            self.body.setVisible(True)
            self.header.arrow.setText('▾')
        return any_visible


class SectionContainer(qtwidgets.QWidget):
    """
    Holds the section widgets. Accepts section drops (reorder / add to this toolbox) and empty-area right-clicks.
    """

    def __init__(self, toolbox):
        """
        :param ToolboxWidget toolbox: The owning toolbox widget.
        """

        super().__init__()
        self.toolbox = toolbox
        self.layout_ = qtwidgets.QVBoxLayout(self)
        self.layout_.setContentsMargins(4, 4, 4, 4)
        self.layout_.setSpacing(6)
        self._drop_y = None
        self.setAcceptDrops(True)

    def section_widgets(self):
        """
        :return: Section widgets in display order.
        :rtype: list[SectionWidget]
        """

        widgets = []
        for index in range(self.layout_.count()):
            widget = self.layout_.itemAt(index).widget()
            if isinstance(widget, SectionWidget):
                widgets.append(widget)
        return widgets

    def _before_section(self, pos):
        """
        :param qtcore.QPoint pos: Position in this widget.
        :return: The visible section widget the drop goes before, or None for the end.
        :rtype: SectionWidget|None
        """

        for widget in self.section_widgets():
            if widget.isVisible() and pos.y() < widget.geometry().center().y():
                return widget
        return None

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(SECTION_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if not event.mimeData().hasFormat(SECTION_MIME):
            event.ignore()
            return
        event.acceptProposedAction()
        before = self._before_section(_event_pos(event))
        visible = [x for x in self.section_widgets() if x.isVisible()]
        if before:
            self._drop_y = before.geometry().top() - 3
        elif visible:
            self._drop_y = visible[-1].geometry().bottom() + 3
        else:
            self._drop_y = 6
        self.update()

    def dragLeaveEvent(self, event):
        self._drop_y = None
        self.update()

    def dropEvent(self, event):
        self._drop_y = None
        self.update()
        if not event.mimeData().hasFormat(SECTION_MIME):
            event.ignore()
            return
        section_id = bytes(event.mimeData().data(SECTION_MIME)).decode('utf-8')
        before = self._before_section(_event_pos(event))
        before_id = before.section.id if before else None
        event.acceptProposedAction()
        qtcore.QTimer.singleShot(0, lambda: self.toolbox.drop_section(section_id, before_id))

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drop_y is None:
            return
        painter = qtgui.QPainter(self)
        painter.setPen(qtgui.QPen(qtgui.QColor('#3daee9'), 3))
        painter.drawLine(4, self._drop_y, self.width() - 4, self._drop_y)
        painter.end()

    def contextMenuEvent(self, event):
        self.toolbox.show_empty_menu(event.globalPos())


# --- Toolbox widget ----------------------------------------------------------------------------------------------

class ToolboxWidget(qtwidgets.QWidget):
    """
    A toolbox: toolbox picker, filter, edit layout toggle, and the sections.

    Implements the item "host" interface used by ``toolbox_items`` (``run_item``, ``build_panel``, ``library``).
    """

    toolbox_changed = qtcore.Signal(str)

    def __init__(self, toolbox_name=toolbox_model.ALL_TOOLS, library=None, switch_handler=None, parent=None):
        """
        :param str toolbox_name: Toolbox to show first.
        :param toolbox_library.ToolboxLibrary library: Library to use. Defaults to the running DCC's library.
        :param callable switch_handler: ``switch_handler(toolbox_name)`` called when the user picks another toolbox.
            Hosts with one dock per toolbox (Maya) use it to open/raise that toolbox's own dock. None switches this
            widget in place.
        :param qtwidgets.QWidget parent: Parent widget.
        """

        super().__init__(parent)
        self.library = library or toolbox_library.get_library()
        if toolbox_name not in self.library.toolboxes:
            toolbox_name = toolbox_model.ALL_TOOLS
        self.toolbox_name = toolbox_name
        self.switch_handler = switch_handler
        self.edit_mode = False
        # item id -> (panel widget, command signature). Panels are expensive and stateful, so they survive rebuilds.
        self._panels = {}
        self._rebuild_pending = False
        # Depth of nested event loops started from inside section/tool widgets (see busy()).
        self._busy = 0
        self._status_time = 0
        self.setObjectName('MCAToolboxWidget')
        self.setMinimumWidth(220)

        layout = qtwidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(3)

        # Top bar: toolbox picker, edit toggle, menu.
        top = qtwidgets.QHBoxLayout()
        self.toolbox_combo = qtwidgets.QComboBox()
        self.toolbox_combo.setSizeAdjustPolicy(qtwidgets.QComboBox.AdjustToContents)
        top.addWidget(self.toolbox_combo, 1)
        self.edit_button = qtwidgets.QToolButton()
        self.edit_button.setText('Edit Layout')
        self.edit_button.setCheckable(True)
        self.edit_button.setToolTip('Drag tools and sections around. Tools do not run while this is on.')
        top.addWidget(self.edit_button)
        self.menu_button = qtwidgets.QToolButton()
        self.menu_button.setText('☰')
        self.menu_button.setPopupMode(qtwidgets.QToolButton.InstantPopup)
        self.menu_button.setMenu(qtwidgets.QMenu(self.menu_button))
        top.addWidget(self.menu_button)
        layout.addLayout(top)

        self.filter_edit = qtwidgets.QLineEdit()
        self.filter_edit.setPlaceholderText('Filter tools...  (-word excludes)')
        self.filter_edit.setClearButtonEnabled(True)
        layout.addWidget(self.filter_edit)

        self.scroll = qtwidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        # Only shows when the dock is narrower than a panel's real minimum width (see GridFlowLayout.minimumSize).
        self.scroll.setHorizontalScrollBarPolicy(qtcore.Qt.ScrollBarAsNeeded)
        self.scroll.setFrameShape(qtwidgets.QFrame.NoFrame)
        self.container = SectionContainer(self)
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll, 1)

        self.status_label = qtwidgets.QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        self.menu_button.menu().aboutToShow.connect(self._fill_main_menu)
        self.toolbox_combo.activated.connect(self._combo_activated)
        self.edit_button.toggled.connect(self.set_edit_mode)
        self.filter_edit.textChanged.connect(self.apply_filter)

        self._poll_timer = qtcore.QTimer(self)
        self._poll_timer.setInterval(POLL_SECONDS * 1000)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

        self.library.add_listener(self.schedule_rebuild)
        self.destroyed.connect(lambda *args, lib=self.library, cb=self.schedule_rebuild: lib.remove_listener(cb))
        self.rebuild()

    # --- building ------------------------------------------------------------------------------------------------

    @property
    def toolbox(self):
        """
        :return: The shown toolbox.
        :rtype: toolbox_model.Toolbox
        """

        return self.library.get_toolbox(self.toolbox_name)

    def set_toolbox(self, name):
        """
        Show another toolbox in this widget.

        :param str name: Toolbox name.
        """

        if name not in self.library.toolboxes:
            return
        self.toolbox_name = name
        self.edit_button.setChecked(False)
        self.rebuild()
        self.toolbox_changed.emit(name)

    def request_toolbox(self, name):
        """
        The user asked for another toolbox: hand it to the host's switch handler, or switch in place.

        :param str name: Toolbox name.
        """

        if name == self.toolbox_name:
            return
        if self.switch_handler:
            # Keep showing this toolbox; the host opens the other one in its own dock.
            self.toolbox_combo.setCurrentIndex(max(0, self.toolbox_combo.findData(self.toolbox_name)))
            self.switch_handler(name)
        else:
            self.set_toolbox(name)

    def _combo_activated(self, index):
        self.request_toolbox(self.toolbox_combo.itemData(index))

    @contextlib.contextmanager
    def busy(self):
        """
        Mark a stretch of code that runs a nested event loop (drag, context menu, dialog, message box) from inside a
        section or tool widget. Rebuilds wait until it ends: rebuilding deletes those widgets, and Qt returning into a
        deleted widget after the loop aborts the host application (Maya crashed this way).
        """

        self._busy += 1
        try:
            yield
        finally:
            self._busy -= 1

    def schedule_rebuild(self):
        """
        Rebuild once it is safe. Library listeners call this: rebuilding immediately could delete the widget whose
        signal, menu or drag started the edit.
        """

        if not shiboken.isValid(self):
            raise RuntimeError('Toolbox widget deleted.')
        if not self._rebuild_pending:
            self._rebuild_pending = True
            qtcore.QTimer.singleShot(0, self._rebuild_when_idle)

    def _rebuild_when_idle(self):
        """
        Rebuild now, or retry shortly while a drag, menu, dialog or mouse press is still in progress.
        """

        if not shiboken.isValid(self):
            return
        app = qtwidgets.QApplication
        if self._busy or app.activePopupWidget() or app.activeModalWidget() or \
                app.mouseButtons() != qtcore.Qt.NoButton:
            qtcore.QTimer.singleShot(100, self._rebuild_when_idle)
            return
        self.rebuild()

    def rebuild(self):
        """
        Recreate every section from the library, keeping scroll position, filter and edit mode.
        """

        self._rebuild_pending = False
        if not shiboken.isValid(self):
            return
        if self.toolbox_name not in self.library.toolboxes:
            # The toolbox was deleted (here or in another window).
            self.toolbox_name = toolbox_model.ALL_TOOLS
            self.toolbox_changed.emit(self.toolbox_name)

        scroll_value = self.scroll.verticalScrollBar().value()
        self.toolbox_combo.blockSignals(True)
        self.toolbox_combo.clear()
        for name in self.library.toolbox_names():
            label = name if self.library.get_toolbox(name).is_shared else f'{name}  (personal)'
            self.toolbox_combo.addItem(label, name)
        self.toolbox_combo.setCurrentIndex(max(0, self.toolbox_combo.findData(self.toolbox_name)))
        self.toolbox_combo.blockSignals(False)

        # Detach cached panels before their old frames are deleted.
        for widget, _ in self._panels.values():
            if shiboken.isValid(widget):
                widget.setParent(None)

        while self.container.layout_.count():
            child = self.container.layout_.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        sections = self.library.sections_in(self.toolbox_name)
        for section in sections:
            self.container.layout_.addWidget(SectionWidget(self, section))
        if not sections:
            hint = qtwidgets.QLabel('This toolbox is empty.\nRight-click here to add a section.')
            hint.setAlignment(qtcore.Qt.AlignCenter)
            hint.setStyleSheet('color: #8a8a8a; padding: 20px;')
            self.container.layout_.addWidget(hint)
        self.container.layout_.addStretch(1)

        # Drop panels whose items no longer exist.
        live_ids = set(item.id for section in self.library.sections.values() for item in section.items)
        for item_id in [x for x in self._panels if x not in live_ids]:
            widget, _ = self._panels.pop(item_id)
            if shiboken.isValid(widget):
                widget.deleteLater()

        self.set_edit_mode(self.edit_mode)
        self.apply_filter()
        qtcore.QTimer.singleShot(0, lambda: shiboken.isValid(self) and
                                 self.scroll.verticalScrollBar().setValue(scroll_value))

    def _poll(self):
        """
        Pick up toolbox files changed outside this session, only while the toolbox is on screen.
        """

        if self.isVisible():
            try:
                self.library.refresh_if_changed()
            except Exception:
                logger.debug('Toolbox: refresh check failed.', exc_info=True)
        if self.status_label.isVisible() and time.time() - self._status_time > STATUS_SECONDS:
            self.status_label.setVisible(False)

    # --- host interface ------------------------------------------------------------------------------------------

    def run_item(self, item, variables=None):
        """
        Run an item's command and report failures in the status line.

        :param toolbox_model.ToolboxItem item: The item.
        :param dict variables: ``value`` / ``values`` for the command.
        :return: The run result.
        :rtype: toolbox_runner.RunResult
        """

        if not item.has_command:
            return toolbox_runner.RunResult(True)
        result = toolbox_runner.run_command(item.command, item.name or item.type, variables, keep_alive_key=item.id)
        if not result.ok:
            self.show_status(f'"{item.name}" failed: {result.error}', error=True)
        return result

    def build_panel(self, item):
        """
        Return the embedded widget of a panel item, reusing it across rebuilds while its command is unchanged.

        :param toolbox_model.ToolboxItem item: The panel item.
        :return: The widget, or an error label.
        :rtype: qtwidgets.QWidget
        """

        signature = repr(sorted(item.command.items()))
        cached = self._panels.get(item.id)
        if cached and cached[1] == signature and shiboken.isValid(cached[0]):
            # Shown by ItemFrame once re-parented; showing it here would flash it as a top-level window.
            return cached[0]
        with _no_window_flash() as guard:
            widget, error = toolbox_runner.build_panel(item.command, item.name)
        guard.release(keep_hidden=widget)
        if widget is None or not isinstance(widget, qtwidgets.QWidget):
            label = qtwidgets.QLabel(f'{item.name}: {error or "the command did not create a widget"}')
            label.setWordWrap(True)
            label.setStyleSheet('color: #e06c6c;')
            return label
        _relax_panel_width(widget)
        self._panels[item.id] = (widget, signature)
        return widget

    # --- modes and filter ----------------------------------------------------------------------------------------

    def set_edit_mode(self, enabled):
        """
        :param bool enabled: Turn edit layout mode on or off.
        """

        self.edit_mode = bool(enabled)
        if self.edit_button.isChecked() != self.edit_mode:
            self.edit_button.blockSignals(True)
            self.edit_button.setChecked(self.edit_mode)
            self.edit_button.blockSignals(False)
        for section_widget in self.container.section_widgets():
            section_widget.header.setCursor(qtcore.Qt.OpenHandCursor if self.edit_mode else qtcore.Qt.PointingHandCursor)
            for frame in section_widget.item_frames:
                frame.set_edit_mode(self.edit_mode)

    def filter_terms(self):
        """
        :return: (include terms, exclude terms) from the filter box, lowercase.
        :rtype: tuple[list[str], list[str]]
        """

        words = self.filter_edit.text().lower().split()
        include = [x for x in words if not x.startswith('-')]
        exclude = [x[1:] for x in words if x.startswith('-') and len(x) > 1]
        return (include, exclude) if (include or exclude) else ()

    def apply_filter(self, *args):
        """
        Show only tools matching the filter text. Hides widgets instead of rebuilding them.
        """

        terms = self.filter_terms()
        include, exclude = terms if terms else ([], [])
        for section_widget in self.container.section_widgets():
            section_widget.apply_filter(include, exclude)

    def show_status(self, text, error=False):
        """
        Show a message under the toolbox for a few seconds.

        :param str text: Message.
        :param bool error: Show in red.
        """

        self.status_label.setText(text)
        self.status_label.setStyleSheet(f'color: {"#e06c6c" if error else "#d8b25c"}; padding: 2px;')
        self.status_label.setVisible(True)
        self._status_time = time.time()

    # --- editing helpers -----------------------------------------------------------------------------------------

    def _edit(self, label, callback, *args, **kwargs):
        """
        Run a library edit, turning failures into a message box and warnings into the status line.

        :param str label: What is being done, for the error title.
        :param callable callback: Library method.
        :return: The callback's return value, or :data:`FAILED`.
        :rtype: object
        """

        with self.busy():
            return self._edit_unguarded(label, callback, *args, **kwargs)

    def _edit_unguarded(self, label, callback, *args, **kwargs):
        """
        Body of :meth:`_edit`; always call through ``_edit`` so rebuilds wait for its message boxes.

        :param str label: What is being done, for the error title.
        :param callable callback: Library method.
        :return: The callback's return value, or :data:`FAILED`.
        :rtype: object
        """

        qtwidgets.QApplication.setOverrideCursor(qtcore.Qt.WaitCursor)
        try:
            result = callback(*args, **kwargs)
        except (toolbox_vcs.ToolboxWriteError, ValueError, KeyError) as exc:
            qtwidgets.QApplication.restoreOverrideCursor()
            qtwidgets.QMessageBox.warning(self, f'Toolbox - {label}', str(exc).strip("'\""))
            return FAILED
        except Exception as exc:
            qtwidgets.QApplication.restoreOverrideCursor()
            logger.exception(f'Toolbox: {label} failed.')
            qtwidgets.QMessageBox.critical(self, f'Toolbox - {label}', f'{type(exc).__name__}: {exc}')
            return FAILED
        qtwidgets.QApplication.restoreOverrideCursor()
        if self.library.warnings:
            self.show_status('\n'.join(self.library.warnings))
        return result

    def _confirm(self, title, text):
        """
        :param str title: Dialog title.
        :param str text: Question.
        :return: True when the user clicked Yes.
        :rtype: bool
        """

        answer = qtwidgets.QMessageBox.question(self, title, text,
                                                qtwidgets.QMessageBox.Yes | qtwidgets.QMessageBox.No,
                                                qtwidgets.QMessageBox.No)
        return answer == qtwidgets.QMessageBox.Yes

    def _ask_text(self, title, label, text=''):
        """
        :param str title: Dialog title.
        :param str label: Prompt.
        :param str text: Starting text.
        :return: The entered text, or None when cancelled/empty.
        :rtype: str|None
        """

        value, ok = qtwidgets.QInputDialog.getText(self, title, label, qtwidgets.QLineEdit.Normal, text)
        value = (value or '').strip()
        return value if ok and value else None

    def drop_item(self, item_id, section_id, before_id):
        """
        Handle a tool dropped on a section (from this or another toolbox window).

        :param str item_id: Dropped item.
        :param str section_id: Target section.
        :param str before_id: Item the drop landed before, or None for the end.
        """

        self._edit('Move tool', self.library.move_item, item_id, section_id, before_id=before_id)

    def drop_section(self, section_id, before_id):
        """
        Handle a section dropped on the section list: reorder, or add it when it came from another toolbox.

        :param str section_id: Dropped section.
        :param str before_id: Section the drop landed before, or None for the end.
        """

        self._edit('Move section', self.library.add_existing_section, self.toolbox_name, section_id,
                   before_id=before_id)

    def add_item_dialog(self, section, before_id=None):
        """
        Prompt for a new item and add it to a section.

        :param toolbox_model.ToolboxSection section: Target section.
        :param str before_id: Insert before this item.
        """

        dialog = toolbox_dialogs.ItemDialog(shared_toolbox=self.toolbox.is_shared, run_callback=self.run_item,
                                            library=self.library,
                                            shared_section=section.source == toolbox_model.SHARED, parent=self)
        if not toolbox_dialogs.exec_dialog(dialog):
            return
        data = dialog.result_data()
        self._edit('Add tool', self.library.add_item, section.id, data['item'], before_id=before_id,
                   toolbox_name=self.toolbox_name, color=data['color'], personal_color=data['personal'])

    def edit_item_dialog(self, item):
        """
        Edit an item's settings, command and color.

        :param toolbox_model.ToolboxItem item: The item.
        """

        color = self.library.item_color(self.toolbox_name, item.id)
        section, _ = self.library.find_item(item.id)
        dialog = toolbox_dialogs.ItemDialog(item, color=color, shared_toolbox=self.toolbox.is_shared,
                                            run_callback=self.run_item, library=self.library,
                                            shared_section=section is None or section.source == toolbox_model.SHARED,
                                            parent=self)
        if not toolbox_dialogs.exec_dialog(dialog):
            return
        data = dialog.result_data()
        new = data['item']
        self._panels.pop(item.id, None)
        if self._edit('Edit tool', self.library.update_item, item.id, name=new.name, tooltip=new.tooltip,
                      command=new.command, settings=new.settings, tags=new.tags, item_type=new.type) is FAILED:
            return
        if data['color'] != color:
            self._edit('Tool color', self.library.set_item_color, self.toolbox_name, item.id, data['color'],
                       personal=data['personal'])

    def section_dialog(self, section=None):
        """
        Create a section, or edit a section's name and colors.

        :param toolbox_model.ToolboxSection section: Section to edit. None creates one.
        """

        colors = self.library.section_colors(self.toolbox_name, section.id) if section else {}
        dialog = toolbox_dialogs.SectionDialog(name=section.name if section else '',
                                               background=colors.get('background'), header=colors.get('header'),
                                               shared_toolbox=self.toolbox.is_shared,
                                               title='Edit Section' if section else 'Add Section', parent=self)
        if not toolbox_dialogs.exec_dialog(dialog):
            return
        data = dialog.result_data()
        if section is None:
            self._edit('Add section', self.library.add_section, self.toolbox_name, data['name'],
                       background=data['background'], header=data['header'], personal_colors=data['personal'])
            return
        if data['name'] != section.name:
            if self._edit('Rename section', self.library.rename_section, section.id, data['name']) is FAILED:
                return
        if data['background'] != colors.get('background') or data['header'] != colors.get('header'):
            self._edit('Section colors', self.library.set_section_colors, self.toolbox_name, section.id,
                       background=data['background'], header=data['header'], personal=data['personal'])

    def _pick_color(self, current):
        """
        :param str current: Current hex color.
        :return: (picked hex color, True) or (None, False) when cancelled.
        :rtype: tuple
        """

        start = qtgui.QColor(current) if current else qtgui.QColor('#4a6fa5')
        color = qtwidgets.QColorDialog.getColor(start, self, 'Pick a color')
        return (color.name(), True) if color.isValid() else (None, False)

    # --- menus ---------------------------------------------------------------------------------------------------

    def _exec_menu(self, menu, pos):
        runner = getattr(menu, 'exec', None) or getattr(menu, 'exec_')
        # Menu actions (and the dialogs they open) run inside exec, while the right-clicked widget is on the stack.
        with self.busy():
            runner(pos)

    def show_item_menu(self, section, item, pos):
        """
        Right-click menu of a tool.

        :param toolbox_model.ToolboxSection section: The item's section.
        :param toolbox_model.ToolboxItem item: The item.
        :param qtcore.QPoint pos: Global position.
        """

        library = self.library
        shared = self.toolbox.is_shared
        menu = qtwidgets.QMenu(self)
        resolved = library.resolve_item(item)
        if resolved and resolved.has_command and resolved.type in ('button', 'form'):
            menu.addAction('Run', lambda: self.run_item(resolved))
        if item.type == 'reference':
            menu.addAction('Edit Original...', lambda: resolved and self.edit_item_dialog(resolved))
        else:
            menu.addAction('Edit...', lambda: self.edit_item_dialog(item))

        color_menu = menu.addMenu('Color')
        current = library.get_toolbox(self.toolbox_name).item_colors.get(item.id)
        color_menu.addAction('Set Color For This Toolbox...' if shared else 'Set Color...',
                             lambda: self._set_item_color(item, False))
        if current:
            color_menu.addAction('Clear Color', lambda: self._edit('Tool color', library.set_item_color,
                                                                   self.toolbox_name, item.id, None))
        if shared:
            color_menu.addSeparator()
            color_menu.addAction('Set Color Just For Me...', lambda: self._set_item_color(item, True))
            if library.get_overrides(self.toolbox_name).item_colors.get(item.id):
                color_menu.addAction('Clear My Color', lambda: self._edit(
                    'Tool color', library.set_item_color, self.toolbox_name, item.id, None, personal=True))

        if item.type != 'reference':
            menu.addAction('Duplicate', lambda: self._edit('Duplicate tool', library.duplicate_item, item.id))
            menu.addAction('Add Tool Here...', lambda: self.add_item_dialog(section, before_id=item.id))
        personal = [x for x in library.toolbox_names() if not library.get_toolbox(x).is_shared]
        if section.source == toolbox_model.SHARED and personal:
            add_menu = menu.addMenu('Add To Personal Toolbox')
            for name in personal:
                add_menu.addAction(name, lambda name=name: self._add_to_personal(item, name))
        if resolved and resolved.has_command and resolved.command.get('kind') == toolbox_model.COMMAND_PYTHON:
            menu.addAction('Copy Code', lambda: qtwidgets.QApplication.clipboard().setText(
                resolved.command.get('code', '')))
        menu.addSeparator()
        menu.addAction('Delete' if item.type != 'reference' else 'Remove',
                       lambda: self._delete_item(section, item))
        self._exec_menu(menu, pos)

    def _set_item_color(self, item, personal):
        color, ok = self._pick_color(self.library.item_color(self.toolbox_name, item.id))
        if ok:
            self._edit('Tool color', self.library.set_item_color, self.toolbox_name, item.id, color,
                       personal=personal)

    def _delete_item(self, section, item):
        where = ''
        if section.source == toolbox_model.SHARED:
            others = [x for x in self.library.toolboxes_showing(section.id)]
            where = f'\n\nIt is removed from every toolbox showing "{section.name}":\n' + ', '.join(others)
        if self._confirm('Delete Tool', f'Delete "{item.name}"?{where}'):
            self._edit('Delete tool', self.library.delete_item, item.id)

    def _add_to_personal(self, item, toolbox_name):
        """
        Put a reference to a shared tool in a personal toolbox, in its first personal section (made when missing).

        :param toolbox_model.ToolboxItem item: Shared item.
        :param str toolbox_name: Personal toolbox.
        """

        sections = [x for x in self.library.sections_in(toolbox_name) if x.source == toolbox_model.LOCAL]
        section = sections[0] if sections else self._edit('Add section', self.library.add_section, toolbox_name,
                                                          'Favorites')
        if section is FAILED:
            return
        if self._edit('Add to personal toolbox', self.library.move_item, item.id, section.id) is not FAILED:
            self.show_status(f'Added "{item.name}" to {toolbox_name} / {section.name}.')

    def show_section_menu(self, section, pos):
        """
        Right-click menu of a section header.

        :param toolbox_model.ToolboxSection section: The section.
        :param qtcore.QPoint pos: Global position.
        """

        library = self.library
        toolbox = self.toolbox
        menu = qtwidgets.QMenu(self)
        menu.addAction('Add Tool...', lambda: self.add_item_dialog(section))
        menu.addAction('Edit Section (Name, Colors)...', lambda: self.section_dialog(section))
        if toolbox.is_shared and library.get_overrides(self.toolbox_name).section_colors.get(section.id):
            menu.addAction('Clear My Colors', lambda: self._edit(
                'Section colors', library.set_section_colors, self.toolbox_name, section.id, background=None,
                header=None, personal=True))
        menu.addSeparator()
        menu.addAction('Collapse All', lambda: self._set_all_collapsed(True))
        menu.addAction('Expand All', lambda: self._set_all_collapsed(False))

        targets = [x for x in library.toolbox_names() if x != self.toolbox_name and
                   not library.get_toolbox(x).is_all_tools and
                   section.id not in library.get_toolbox(x).sections and
                   (section.source == toolbox_model.SHARED or not library.get_toolbox(x).is_shared)]
        if targets:
            menu.addSeparator()
            add_menu = menu.addMenu('Show In Toolbox')
            for name in targets:
                add_menu.addAction(name, lambda name=name: self._edit(
                    'Add section', library.add_existing_section, name, section.id))
        menu.addSeparator()
        if not toolbox.is_all_tools and section.source == toolbox_model.SHARED:
            menu.addAction('Remove From This Toolbox', lambda: self._edit(
                'Remove section', library.remove_section_from_toolbox, self.toolbox_name, section.id))
        menu.addAction('Delete Section...', lambda: self._delete_section(section))
        self._exec_menu(menu, pos)

    def _delete_section(self, section):
        shown_in = self.library.toolboxes_showing(section.id)
        text = f'Delete "{section.name}" and its {len(section.items)} tool(s)?'
        if section.source == toolbox_model.SHARED:
            text += f'\n\nThis removes it from every toolbox:\n{", ".join(shown_in)}\n\n' \
                    'The delete goes into your pending changelist, so it can be reverted until submitted.'
        if self._confirm('Delete Section', text):
            self._edit('Delete section', self.library.delete_section, section.id)

    def _set_all_collapsed(self, collapsed):
        for section_widget in self.container.section_widgets():
            section_widget.set_collapsed(collapsed, save=False)
        self.library.set_state(self.toolbox_name, 'collapsed',
                               [x.section.id for x in self.container.section_widgets()] if collapsed else [])

    def _add_existing_menu(self, parent_menu):
        """
        Add an "Add Existing Section" submenu listing sections this toolbox does not show yet.

        :param qtwidgets.QMenu parent_menu: Menu to add to.
        """

        toolbox = self.toolbox
        if toolbox.is_all_tools:
            return
        shown = set(x.id for x in self.library.sections_in(self.toolbox_name))
        candidates = [x for x in self.library.sections.values() if x.id not in shown and
                      (x.source == toolbox_model.SHARED or not toolbox.is_shared)]
        if not candidates:
            return
        sub = parent_menu.addMenu('Add Existing Section')
        for section in sorted(candidates, key=lambda x: x.name.lower()):
            label = section.name if section.source == toolbox_model.SHARED else f'{section.name} (personal)'
            sub.addAction(label, lambda section=section: self._edit(
                'Add section', self.library.add_existing_section, self.toolbox_name, section.id))

    def show_empty_menu(self, pos):
        """
        Right-click menu of the empty area around sections.

        :param qtcore.QPoint pos: Global position.
        """

        menu = qtwidgets.QMenu(self)
        menu.addAction('Add Section...', lambda: self.section_dialog())
        self._add_existing_menu(menu)
        menu.addSeparator()
        action = menu.addAction('Edit Layout')
        action.setCheckable(True)
        action.setChecked(self.edit_mode)
        action.toggled.connect(self.set_edit_mode)
        self._exec_menu(menu, pos)

    def _fill_main_menu(self):
        """
        Rebuild the top-right menu each time it opens so it reflects the current toolbox.
        """

        menu = self.menu_button.menu()
        menu.clear()
        toolbox = self.toolbox
        menu.addAction('Add Section...', lambda: self.section_dialog())
        self._add_existing_menu(menu)
        menu.addSeparator()
        menu.addAction('New Personal Toolbox...', self._new_personal_toolbox)
        menu.addAction('New Shared Toolbox...', lambda: self._new_toolbox(shared=True))
        if not toolbox.is_all_tools:
            menu.addAction(f'Delete "{toolbox.name}"...', self._delete_toolbox)
        menu.addSeparator()
        startup = menu.addAction('Open On Startup')
        startup.setCheckable(True)
        startup.setChecked(bool(self.library.get_state(self.toolbox_name, 'open_on_start', False)))
        startup.toggled.connect(lambda state: self.library.set_state(self.toolbox_name, 'open_on_start', state))
        if toolbox.is_shared:
            menu.addAction('Clear My Colors', lambda: self._edit('Clear colors', self.library.clear_personal_colors,
                                                                 self.toolbox_name))
        menu.addSeparator()
        menu.addAction('Find Broken Tools...', self._find_broken)
        menu.addAction('Reload', lambda: self._edit('Reload', self.library.reload))

    def _new_personal_toolbox(self):
        self._new_toolbox(shared=False)

    def _new_toolbox(self, shared):
        kind = 'shared' if shared else 'personal'
        name = self._ask_text(f'New {kind.title()} Toolbox', f'Name of the new {kind} toolbox:')
        if name and self._edit('New toolbox', self.library.create_toolbox, name, shared=shared) is not FAILED:
            self.request_toolbox(name)

    def _delete_toolbox(self):
        toolbox = self.toolbox
        text = f'Delete the toolbox "{toolbox.name}"?\n\n'
        text += ('Its sections stay in All Tools.' if toolbox.is_shared
                 else 'Its personal sections are deleted with it. Shared sections stay in All Tools.')
        if self._confirm('Delete Toolbox', text):
            if self._edit('Delete toolbox', self.library.delete_toolbox, toolbox.name) is not FAILED:
                self.set_toolbox(toolbox_model.ALL_TOOLS)

    def _find_broken(self):
        """
        Statically check every command in this toolbox and list the ones that reference missing code.
        """

        lines = []
        for section in self.library.sections_in(self.toolbox_name):
            for item in section.items:
                if item.type == 'reference':
                    if self.library.resolve_item(item) is None:
                        lines.append(f'{section.name} / {item.name}: shared tool was deleted')
                    continue
                if not item.has_command:
                    continue
                problems = toolbox_runner.check_command(item.command)
                if problems:
                    lines.append(f'{section.name} / {item.name}: {"; ".join(problems)}')
        box = qtwidgets.QMessageBox(self)
        box.setWindowTitle('Find Broken Tools')
        if lines:
            box.setText(f'{len(lines)} tool(s) look broken. See details.')
            box.setDetailedText('\n'.join(lines))
        else:
            box.setText('No broken tools found.')
        toolbox_dialogs.exec_dialog(box)
