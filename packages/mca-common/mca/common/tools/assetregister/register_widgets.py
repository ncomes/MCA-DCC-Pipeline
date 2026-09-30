"""
Small widgets and value helpers shared across the register modules.

Split out of ``unified_register`` so the register modules can share these
without importing the window. The code is unchanged.

:Requires: mca.common.pyqt
"""

# python imports
import os

# MCA python imports
from mca.common import log
from mca.common.pyqt.pygui import qtcore, qtwidgets, shiboken
from mca.common.resources import resources


logger = log.MCA_LOGGER


# First entry of the tree filter dropdowns; means "do not filter on this field".
TREE_FILTER_ALL = 'All'


# Settings keys for preferences. Centralized so the preferences dialog and the
# scaffold builder agree on names without duplicating string literals.
PREF_KEY_AUTO_SUBMIT = 'prefs/auto_submit'


PREF_KEY_CREATE_FOLDERS = 'prefs/create_folders'


PREF_KEY_LAST_CATEGORY = 'last_category'


# (field_key, display label, factory-default checked state) for every
# classification "In Path" checkbox. Keyed off the same field_keys used in
# self._classification_rows so the preferences dialog can drive the form.
IN_PATH_FIELDS = (
    ('subtype', 'Sub Category', True),
    ('faction', 'Faction', True),
    ('gender', 'Gender', False),
    ('asset_type', 'Asset Type', False),
    ('skeleton', 'Skeleton', False),
    ('body_type', 'Body Type', False),
    ('additional_types', 'Additional Types', True),
)


def format_channel_default(default, ch_type):
    """
    Format a stored channel default for display in the line edit.

    Linear-color defaults are 4-element lists shown as ``r,g,b,a``;
    scalar defaults are floats shown as their string form. Anything
    unparseable round-trips as its raw string.

    :param default: Stored default value.
    :param str ch_type: Channel type (``linear_color`` or ``scalar``).
    :return: Display text for the default field.
    :rtype: str
    """

    if default is None:
        return ''
    if ch_type == 'linear_color' and isinstance(default, (list, tuple)):
        return ','.join(_fmt_float(v) for v in default)
    if ch_type == 'scalar' and isinstance(default, (int, float)):
        return _fmt_float(default)
    return str(default)


def parse_channel_default(text, ch_type):
    """
    Parse a default-value line edit into a typed value.

    Falls back to the raw string when the input does not match the
    expected shape so user typos round-trip rather than silently zeroing.

    :param str text: Raw text from the default line edit.
    :param str ch_type: Channel type (``linear_color`` or ``scalar``).
    :return: Parsed list[float], float, or original string.
    """

    text = (text or '').strip()
    if not text:
        return None
    if ch_type == 'linear_color':
        parts = [p.strip() for p in text.split(',') if p.strip()]
        try:
            values = [float(p) for p in parts]
        except ValueError:
            return text
        # Pad to RGBA so downstream consumers don't have to length-check.
        while len(values) < 4:
            values.append(1.0 if len(values) == 3 else 0.0)
        return values[:4]
    if ch_type == 'scalar':
        try:
            return float(text)
        except ValueError:
            return text
    return text


def coerce_rgba(value):
    """
    Coerce a stored linear_color value into a 4-element float tuple.

    Accepts list / tuple of 3 or 4 numbers; returns ``(r, g, b, a)``
    with alpha defaulting to 1.0 when missing. Anything unparseable
    falls back to opaque black so editors never crash on bad data.

    :param value: Stored channel value.
    :return: ``(r, g, b, a)``.
    :rtype: tuple
    """

    try:
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            r = float(value[0])
            g = float(value[1])
            b = float(value[2])
            a = float(value[3]) if len(value) > 3 else 1.0
            return (r, g, b, a)
    except (TypeError, ValueError):
        pass
    return (0.0, 0.0, 0.0, 1.0)


def _fmt_float(v):
    """
    Format a float compactly for display, trimming trailing zeros.

    :param v: Number to format.
    :return: String representation.
    :rtype: str
    """

    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = f'{f:.6f}'.rstrip('0').rstrip('.')
    return s if s else '0'


class UiNamespace:
    """Simple namespace to hold widget references, mimicking QUiLoader output."""
    pass


class ClassificationRow(qtwidgets.QWidget):
    """
    Row widget whose lifetime is managed explicitly by the host, not by
    Qt's index-widget machinery.

    Why this exists: ``QAbstractItemView::setIndexWidget`` unconditionally
    calls ``oldWidget->deleteLater()`` whenever the index widget at a
    given row is replaced *or* when that row is removed from the model
    (e.g. via ``QListWidget.clear()``). That is fine for one-shot row
    widgets, but ``_rebuild_classification_order`` reuses the same row
    widgets across every rebuild — clear() queues a ``DeferredDelete``
    against every row, ``setItemWidget(new_item, same_row)`` re-attaches
    the (still-alive) row to a fresh item, and then the pending
    ``DeferredDelete`` fires on the next event-loop tick and destroys the
    row. Qt's newly rebuilt index-widget map then contains a dangling
    pointer; the next layout timer crashes inside
    ``QAbstractItemView::updateEditorGeometries``. That is the exact
    stack in the 2026-04-21 crash logs (4 consecutive, identical dumps).

    Fix: override ``event`` to swallow ``QEvent::DeferredDelete``. The
    host (``UnifiedRegisterUI``) owns these rows via
    ``self._classification_rows`` and explicitly destroys them in
    ``_teardown_classification_list`` using ``deleteLater`` *after*
    unparenting them from the list view — which is the one place we want
    deletion to actually happen.
    """

    def event(self, e):
        if e.type() == qtcore.QEvent.DeferredDelete:
            # Swallow: lifetime is managed by the host window, not Qt's
            # setIndexWidget cleanup.
            e.accept()
            return True
        return super().event(e)


class ReorderableClassificationList(qtwidgets.QListWidget):
    """
    QListWidget that signals a reorder request instead of actually performing
    Qt's InternalMove drop.

    Why this exists: combining ``InternalMove`` drag-drop with ``setItemWidget``
    on every row is a known Qt footgun. When Qt6 performs an InternalMove drop,
    the source ``QListWidgetItem`` is removed and a new one inserted at the
    target; the item-widget attached via ``setItemWidget`` is owned by the
    view's index-widget map and gets destroyed along with the source index.
    Our Python-side references (``_classification_rows`` dict, ``self.ui``
    combobox attributes) are then dangling C++ pointers, and the post-drop
    ``updateEditorGeometries`` layout timer crashes Maya with an access
    violation (seen in the 2026-04-21 crash dump).

    Fix: intercept ``dropEvent`` to compute the (source, target) rows and emit
    a signal. We never call ``super().dropEvent`` so Qt never performs the
    destructive reorder. The host then rebuilds the list safely via the
    existing ``_rebuild_classification_order`` path, which reparents every
    row widget away from the list before ``clear()`` runs.

    :signal reorder_requested(int, int): Emitted with (source_row, target_row)
        after a successful intra-widget drop. ``target_row`` is already
        adjusted for the source removal, so ``list.pop(source); list.insert(target, x)``
        is the correct reorder.
    """

    reorder_requested = qtcore.Signal(int, int)

    def dropEvent(self, event):
        # Only accept drops that originated inside this same list. InternalMove
        # should already guarantee this, but check defensively in case the mode
        # is ever widened.
        if event.source() is not self:
            event.ignore()
            return

        source_row = self.currentRow()
        # PySide6 (Maya 2025) only — pygui resolves to PySide6 here. If we
        # ever need to run under Maya 2024/PySide2 again, do the version
        # branch inside pygui, not here.
        drop_point = event.position().toPoint()

        target_index = self.indexAt(drop_point)
        target_row = target_index.row()
        indicator = self.dropIndicatorPosition()

        if target_row < 0:
            # Drop happened below the last row; append.
            target_row = self.count()
        elif indicator == qtwidgets.QAbstractItemView.BelowItem:
            target_row += 1

        # No-op drops: onto self, or onto the slot immediately after self.
        if source_row == target_row or source_row == target_row - 1:
            event.ignore()
            return

        # When moving downward, removing source first shifts everything above
        # target up by one; adjust so the visible position matches the indicator.
        if source_row < target_row:
            target_row -= 1

        event.accept()
        self.reorder_requested.emit(source_row, target_row)

    def hideEvent(self, event):
        # When the host window is closed, Qt propagates Hide to every child
        # widget before running dtors. That is our reliable hook — closeEvent
        # is only delivered to the widget close() is called on, never to
        # children. By clearing the list here we drain the view's
        # index-widget map so any queued QAbstractItemView::doItemsLayout
        # timer has nothing to walk when it fires during teardown (the exact
        # crash stack in MayaCrashLog260421.1323.log after startup.restart).
        #
        # Guard with shiboken.isValid so a cascade from an already-destroyed
        # parent does not re-enter dead C++ objects. Only clear when the
        # host window is actually closing — not on tab switches (the list
        # stays visible inside its own tab) or minimise (window still
        # visible to Qt).
        if shiboken.isValid(self):
            window = self.window()
            closing = (window is None
                       or not shiboken.isValid(window)
                       or not window.isVisible())
            if closing:
                was_blocked = self.signalsBlocked()
                self.blockSignals(True)
                try:
                    self.clear()
                finally:
                    self.blockSignals(was_blocked)
        super().hideEvent(event)


def in_path_pref_key(field_key):
    """Return the QSettings key for a given classification field's In Path default."""
    return f'prefs/in_path/{field_key}'


def waggle_gif():
    """
    :return: The animated logo shown while something slow is happening, or ``''`` when the
        project ships no such file.
    :rtype: str

    Asked of :mod:`mca.common.resources`, which reads the folders the launcher builds. The
    version this replaces walked up from its own file to ``mca/common/resources/movies`` and
    looked for the gif there - a path into the package's own folder, which no longer holds any
    art at all, so it would have answered None on every machine.
    """

    found = resources.movie('Logo_TailWaggle.gif')

    return found if found and os.path.isfile(found) else ''


def to_bool(value, default):
    """
    Coerce a QSettings-returned value to a real bool.

    Qt persists booleans as the strings ``'true'`` / ``'false'`` on some
    platforms, so a naive ``bool(value)`` mis-reads ``'false'`` as True.
    Returns ``default`` for anything unrecognized.
    """

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ('true', '1', 'yes'):
            return True
        if v in ('false', '0', 'no'):
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return bool(default)
