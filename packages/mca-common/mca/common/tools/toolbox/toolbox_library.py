"""
The toolbox library: loads every section and toolbox for a DCC and performs all edits.

Everything that changes toolbox data goes through :class:`ToolboxLibrary` so version control, file layout and the
rules below live in one place. The Qt UI, the headless ``toolbox_api`` and the MCP tools are thin callers.

Rules:

- Sections are shared by every toolbox that shows them: names, commands and item order are the same everywhere.
- Colors belong to a toolbox, so each toolbox has its own color scheme. A user can also keep private colors on
  top of a shared toolbox ("just for me"), stored in their preferences folder.
- ``All Tools`` always shows every shared section. Its file only stores section order and colors.
- Deleting a section deletes it everywhere. Removing it from a toolbox only hides it there.
- Shared files are checked out / added / deleted through the shared backend (Perforce by default) and re-read
  from disk right before each edit, so an edit is always applied to the latest data.
- Personal toolboxes are local. They can show shared sections next to their own local sections, and hold
  ``reference`` items that point at shared items.

Layout on disk::

    <shared_root>/sections/<section_id>.yaml   (Tools/Common/Tools/<Dcc>/Toolbox)
    <shared_root>/toolboxes/<name>.yaml
    <local_root>/sections/<section_id>.yaml    (mca_preferences/<project>/prefs/<dcc>/Toolbox)
    <local_root>/toolboxes/<name>.yaml
    <local_root>/overrides/<name>.yaml
    <local_root>/state.yaml
    <shared_root>/icons/, <local_root>/icons/  (item icons, see resolve_icon)

Side effects: reads/writes the files above; shared writes run p4 commands.
"""

# python imports
import os
import re

# MCA python imports
from mca.common import log
from mca.common.tools.toolbox import toolbox_model, toolbox_vcs

logger = log.MCA_LOGGER

__all__ = ['ToolboxLibrary', 'get_library', 'reset_library', 'KEEP']

SECTIONS_DIR = 'sections'
TOOLBOXES_DIR = 'toolboxes'
OVERRIDES_DIR = 'overrides'
STATE_FILE = 'state.yaml'
# Item icons: <shared_root>/icons (checked in) and <local_root>/icons (personal).
ICONS_DIR = 'icons'
ICON_EXTENSIONS = ('.png', '.svg', '.jpg', '.jpeg', '.bmp', '.ico')

# Item type used in personal toolboxes to show a shared item without copying it.
REFERENCE_TYPE = 'reference'


class _Keep:
    """
    Sentinel for "argument not given", so None can still mean "clear this value".
    """

    def __repr__(self):
        return 'KEEP'


KEEP = _Keep()

# dcc_util.application() name (lowercase) -> folder name under Tools/Common/Tools.
DCC_FOLDERS = {'maya': 'Maya', 'mobu': 'MoBu', 'motionbuilder': 'MoBu', 'unreal': 'Unreal'}

# One library per DCC name, shared by every open toolbox window so an edit in one window refreshes the others.
_LIBRARIES = {}


def default_shared_root(dcc):
    """
    :param str dcc: DCC folder name, e.g. ``'Maya'``.
    :return: ``Tools/Common/Tools/<dcc>/Toolbox`` in the project depot.
    :rtype: str
    """

    from mca.common.paths import paths
    return os.path.join(paths.get_common_tools_path(), dcc, 'Toolbox')


def default_local_root(dcc):
    """
    :param str dcc: DCC folder name, e.g. ``'Maya'``.
    :return: ``mca_preferences/<project>/prefs/<dcc>/Toolbox``.
    :rtype: str
    """

    from mca.common.paths import paths
    return os.path.join(paths.get_dcc_prefs_folder(dcc.lower()), 'Toolbox')


def get_library(dcc=None):
    """
    Return the shared library for a DCC, creating it on first use.

    :param str dcc: DCC folder name. Defaults to the running application (``'Maya'``, ``'Unreal'``...).
    :return: The library.
    :rtype: ToolboxLibrary
    """

    if not dcc:
        from mca.common.utils import dcc_util
        dcc = dcc_util.application()
    # Use the depot folder spelling so every caller shares one library and p4 paths match the depot.
    dcc = DCC_FOLDERS.get(dcc.lower(), dcc)
    if dcc not in _LIBRARIES:
        _LIBRARIES[dcc] = ToolboxLibrary(dcc=dcc)
    return _LIBRARIES[dcc]


def reset_library(dcc=None):
    """
    Drop cached libraries so the next :func:`get_library` call reloads from disk.

    :param str dcc: Only reset this DCC's library. None resets all.
    """

    if dcc:
        _LIBRARIES.pop(dcc, None)
    else:
        _LIBRARIES.clear()


def safe_file_name(name):
    """
    :param str name: A toolbox name.
    :return: The name with characters Windows does not allow in file names replaced by ``_``.
    :rtype: str
    """

    return re.sub(r'[<>:"/\\|?*]+', '_', name).strip(' .') or 'toolbox'


class ToolboxLibrary:
    """
    All sections and toolboxes for one DCC, plus the user's local state.
    """

    def __init__(self, dcc='Maya', shared_root=None, local_root=None, shared_backend=None, local_backend=None):
        """
        :param str dcc: DCC folder name, e.g. ``'Maya'``.
        :param str shared_root: Folder of the version controlled toolbox files. Defaults to the project depot.
        :param str local_root: Folder of the user's personal files. Defaults to mca_preferences.
        :param toolbox_vcs.LocalBackend shared_backend: Backend for shared files. None asks
            :func:`toolbox_vcs.shared_backend`, which is Perforce where Perforce is set up and
            plain disk writes where it is not. The version this replaces defaulted to Perforce
            outright, so every shared edit failed on a machine without it.
        :param toolbox_vcs.LocalBackend local_backend: Backend for local files. Defaults to plain disk writes.
        """

        self.dcc = dcc
        self.shared_root = os.path.normpath(shared_root or default_shared_root(dcc))
        self.local_root = os.path.normpath(local_root or default_local_root(dcc))
        self.shared_backend = shared_backend or toolbox_vcs.shared_backend()
        self.local_backend = local_backend or toolbox_vcs.LocalBackend()

        # Messages from the last edit that the UI should show, e.g. "also checked out by ...".
        self.warnings = []

        self.sections = {}
        self.toolboxes = {}
        self._overrides = {}
        self._state = {}
        self._listeners = []
        self._snapshot = {}
        self.reload(notify=False)

    # --- loading -------------------------------------------------------------------------------------------------

    def _dir(self, source, kind):
        """
        :param str source: :data:`toolbox_model.SHARED` or :data:`toolbox_model.LOCAL`.
        :param str kind: :data:`SECTIONS_DIR`, :data:`TOOLBOXES_DIR` or :data:`OVERRIDES_DIR`.
        :return: The folder for that kind of file.
        :rtype: str
        """

        root = self.shared_root if source == toolbox_model.SHARED else self.local_root
        return os.path.join(root, kind)

    def _backend(self, source):
        """
        :param str source: :data:`toolbox_model.SHARED` or :data:`toolbox_model.LOCAL`.
        :return: The backend that writes files of that source.
        :rtype: toolbox_vcs.LocalBackend
        """

        return self.shared_backend if source == toolbox_model.SHARED else self.local_backend

    def _watched_files(self):
        """
        :return: Every toolbox file path with its modification time, used to spot changes made outside this session
            (a Perforce sync, another DCC session).
        :rtype: dict
        """

        snapshot = {}
        for source in (toolbox_model.SHARED, toolbox_model.LOCAL):
            for kind in (SECTIONS_DIR, TOOLBOXES_DIR, OVERRIDES_DIR):
                folder = self._dir(source, kind)
                if not os.path.isdir(folder):
                    continue
                for file_name in os.listdir(folder):
                    if file_name.endswith('.yaml'):
                        path = os.path.join(folder, file_name)
                        try:
                            snapshot[path] = os.path.getmtime(path)
                        except OSError:
                            pass
        return snapshot

    def reload(self, notify=True):
        """
        Re-read every file from disk.

        :param bool notify: Tell listeners (open toolbox windows) to rebuild.
        """

        self.sections = {}
        self.toolboxes = {}
        self._overrides = {}

        # Shared first so a local file can never shadow a shared one with the same id or name.
        for source in (toolbox_model.SHARED, toolbox_model.LOCAL):
            folder = self._dir(source, SECTIONS_DIR)
            if os.path.isdir(folder):
                for file_name in sorted(os.listdir(folder)):
                    if not file_name.endswith('.yaml'):
                        continue
                    path = os.path.join(folder, file_name)
                    data = toolbox_model.read_yaml(path)
                    if not data:
                        continue
                    section = toolbox_model.ToolboxSection.from_dict(data, source=source, path=path)
                    # The file name is the id; it wins over a hand edited id inside the file.
                    section.id = os.path.splitext(file_name)[0]
                    if section.id in self.sections:
                        logger.warning(f'Toolbox: duplicate section id {section.id} in {path} ignored.')
                        continue
                    self.sections[section.id] = section

            folder = self._dir(source, TOOLBOXES_DIR)
            if os.path.isdir(folder):
                for file_name in sorted(os.listdir(folder)):
                    if not file_name.endswith('.yaml'):
                        continue
                    path = os.path.join(folder, file_name)
                    toolbox = toolbox_model.Toolbox.from_dict(toolbox_model.read_yaml(path), source=source,
                                                              path=path, name=os.path.splitext(file_name)[0])
                    if toolbox.name in self.toolboxes:
                        logger.warning(f'Toolbox: "{toolbox.name}" in {path} has the same name as a shared toolbox '
                                       'and is hidden.')
                        continue
                    self.toolboxes[toolbox.name] = toolbox

        # All Tools always exists, even before its file has been written.
        if toolbox_model.ALL_TOOLS not in self.toolboxes:
            self.toolboxes[toolbox_model.ALL_TOOLS] = toolbox_model.Toolbox(
                toolbox_model.ALL_TOOLS, source=toolbox_model.SHARED,
                path=os.path.join(self._dir(toolbox_model.SHARED, TOOLBOXES_DIR),
                                  f'{toolbox_model.ALL_TOOLS}.yaml'))

        self._state = toolbox_model.read_yaml(os.path.join(self.local_root, STATE_FILE))
        self._snapshot = self._watched_files()
        if notify:
            self._notify()

    def refresh_if_changed(self):
        """
        Reload when any toolbox file changed on disk since the last load or save. Cheap enough to poll.

        :return: True when a reload happened.
        :rtype: bool
        """

        if self._watched_files() != self._snapshot:
            logger.debug('Toolbox: files changed on disk, reloading.')
            self.reload()
            return True
        return False

    # --- listeners -----------------------------------------------------------------------------------------------

    def add_listener(self, callback):
        """
        :param callable callback: Called with no arguments after any change.
        """

        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback):
        """
        :param callable callback: A callback previously passed to :meth:`add_listener`.
        """

        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify(self):
        """
        Call every listener. A failing listener (e.g. a closed window) is dropped instead of breaking the edit.
        """

        for callback in list(self._listeners):
            try:
                callback()
            except RuntimeError:
                # "Internal C++ object already deleted": the window went away without unregistering.
                self._listeners.remove(callback)
            except Exception:
                logger.exception('Toolbox: listener failed.')

    # --- queries -------------------------------------------------------------------------------------------------

    def toolbox_names(self):
        """
        :return: All Tools first, then shared toolboxes, then personal toolboxes, each group sorted by name.
        :rtype: list[str]
        """

        shared = sorted(x.name for x in self.toolboxes.values() if x.is_shared and not x.is_all_tools)
        local = sorted(x.name for x in self.toolboxes.values() if not x.is_shared)
        return [toolbox_model.ALL_TOOLS] + shared + local

    def get_toolbox(self, name):
        """
        :param str name: Toolbox name.
        :return: The toolbox.
        :rtype: toolbox_model.Toolbox
        """

        toolbox = self.toolboxes.get(name)
        if not toolbox:
            raise KeyError(f'No toolbox named "{name}".')
        return toolbox

    def get_section(self, section_id):
        """
        :param str section_id: Section id.
        :return: The section.
        :rtype: toolbox_model.ToolboxSection
        """

        section = self.sections.get(section_id)
        if not section:
            raise KeyError(f'No section with id "{section_id}".')
        return section

    def find_item(self, item_id):
        """
        :param str item_id: Item id.
        :return: (section, item), or (None, None) when no section holds the item.
        :rtype: tuple
        """

        for section in self.sections.values():
            item = section.get_item(item_id)
            if item:
                return section, item
        return None, None

    def resolve_item(self, item):
        """
        Follow a reference item to the shared item it points at.

        :param toolbox_model.ToolboxItem item: Any item.
        :return: The item itself, the referenced item, or None when the reference is broken.
        :rtype: toolbox_model.ToolboxItem|None
        """

        if item.type != REFERENCE_TYPE:
            return item
        _, target = self.find_item(item.settings.get('item_id', ''))
        return target

    def sections_in(self, toolbox_name):
        """
        The sections a toolbox shows, in display order. Missing ids (deleted sections) are skipped.

        :param str toolbox_name: Toolbox name.
        :return: Ordered sections.
        :rtype: list[toolbox_model.ToolboxSection]
        """

        toolbox = self.get_toolbox(toolbox_name)
        ordered = [self.sections[x] for x in toolbox.sections if x in self.sections]
        if toolbox.is_all_tools:
            ordered = [x for x in ordered if x.source == toolbox_model.SHARED]
            listed = set(x.id for x in ordered)
            ordered += sorted((x for x in self.sections.values()
                               if x.source == toolbox_model.SHARED and x.id not in listed),
                              key=lambda x: x.name.lower())
        return ordered

    def toolboxes_showing(self, section_id):
        """
        :param str section_id: Section id.
        :return: Names of toolboxes that show the section (All Tools included for shared sections).
        :rtype: list[str]
        """

        return [name for name in self.toolbox_names() if section_id in [x.id for x in self.sections_in(name)]]

    def get_overrides(self, toolbox_name):
        """
        :param str toolbox_name: Toolbox name.
        :return: The user's private colors for that toolbox (empty when there are none).
        :rtype: toolbox_model.ColorOverrides
        """

        if toolbox_name not in self._overrides:
            path = os.path.join(self._dir(toolbox_model.LOCAL, OVERRIDES_DIR), f'{safe_file_name(toolbox_name)}.yaml')
            data = toolbox_model.read_yaml(path)
            self._overrides[toolbox_name] = toolbox_model.ColorOverrides.from_dict(
                data, source=toolbox_model.LOCAL, path=path, name=toolbox_name)
        return self._overrides[toolbox_name]

    def section_colors(self, toolbox_name, section_id):
        """
        Effective colors of a section in a toolbox: private override, then toolbox color.

        :param str toolbox_name: Toolbox name.
        :param str section_id: Section id.
        :return: ``{'background': hex|None, 'header': hex|None}``.
        :rtype: dict
        """

        toolbox_colors = self.get_toolbox(toolbox_name).section_colors.get(section_id, {})
        override_colors = self.get_overrides(toolbox_name).section_colors.get(section_id, {})
        return {key: override_colors.get(key) or toolbox_colors.get(key) for key in ('background', 'header')}

    def item_color(self, toolbox_name, item_id):
        """
        Effective color of an item in a toolbox: private override, then toolbox color.

        :param str toolbox_name: Toolbox name.
        :param str item_id: Item id.
        :return: Hex color or None.
        :rtype: str|None
        """

        return self.get_overrides(toolbox_name).item_colors.get(item_id) or \
            self.get_toolbox(toolbox_name).item_colors.get(item_id)

    # --- local UI state ------------------------------------------------------------------------------------------

    def get_state(self, toolbox_name, key, default=None):
        """
        :param str toolbox_name: Toolbox name.
        :param str key: State key, e.g. ``'open_on_start'``, ``'collapsed'``, ``'locked'``.
        :param object default: Returned when the key is not set.
        :return: The stored value.
        :rtype: object
        """

        return (self._state.get('toolboxes') or {}).get(toolbox_name, {}).get(key, default)

    def set_state(self, toolbox_name, key, value):
        """
        Store a per-user UI setting and save ``state.yaml``. Does not notify listeners.

        :param str toolbox_name: Toolbox name.
        :param str key: State key.
        :param object value: YAML-safe value.
        """

        self._state.setdefault('toolboxes', {}).setdefault(toolbox_name, {})[key] = value
        try:
            toolbox_model.write_yaml(os.path.join(self.local_root, STATE_FILE), self._state)
        except OSError as exc:
            logger.warning(f'Toolbox: could not save state: {exc}')

    def startup_toolboxes(self):
        """
        :return: Names of toolboxes the user wants opened when the DCC starts.
        :rtype: list[str]
        """

        return [name for name in self.toolbox_names() if self.get_state(name, 'open_on_start', False)]

    # --- write plumbing ------------------------------------------------------------------------------------------

    def _begin(self):
        """
        Start an edit: clear the previous edit's warnings.
        """

        self.warnings = []

    def _prepare(self, obj):
        """
        Make an object's file writable (check it out) before anything is written.

        :param toolbox_model.ToolboxSection|toolbox_model.Toolbox obj: The object to be saved.
        """

        self.warnings += self._backend(obj.source).prepare_edit(obj.path)

    def _fresh_section(self, section_id):
        """
        Check out a section and re-read it from disk so the edit applies to the latest version.

        :param str section_id: Section id.
        :return: The freshly loaded section (also stored in the library).
        :rtype: toolbox_model.ToolboxSection
        """

        section = self.get_section(section_id)
        self._prepare(section)
        if os.path.isfile(section.path):
            data = toolbox_model.read_yaml(section.path)
            if data:
                section = toolbox_model.ToolboxSection.from_dict(data, source=section.source, path=section.path)
                section.id = section_id
                self.sections[section_id] = section
        return section

    def _fresh_toolbox(self, name):
        """
        Check out a toolbox and re-read it from disk so the edit applies to the latest version.

        :param str name: Toolbox name.
        :return: The freshly loaded toolbox (also stored in the library).
        :rtype: toolbox_model.Toolbox
        """

        toolbox = self.get_toolbox(name)
        self._prepare(toolbox)
        if os.path.isfile(toolbox.path):
            toolbox = toolbox_model.Toolbox.from_dict(toolbox_model.read_yaml(toolbox.path), source=toolbox.source,
                                                      path=toolbox.path, name=name)
            self.toolboxes[name] = toolbox
        return toolbox

    def _save(self, obj):
        """
        Write an object's file and let the backend add it when new.

        :param toolbox_model.ToolboxSection|toolbox_model.Toolbox obj: The object to save. Must be prepared first.
        """

        is_new = not os.path.isfile(obj.path)
        try:
            toolbox_model.write_yaml(obj.path, obj.to_dict())
        except OSError as exc:
            raise toolbox_vcs.ToolboxWriteError(f'Could not save {os.path.basename(obj.path)}: {exc}')
        self.warnings += self._backend(obj.source).after_write(obj.path, is_new)
        try:
            self._snapshot[obj.path] = os.path.getmtime(obj.path)
        except OSError:
            pass

    def _finish(self):
        """
        End an edit: log warnings and refresh listeners.
        """

        for warning in self.warnings:
            logger.warning(f'Toolbox: {warning}')
        self._notify()

    @staticmethod
    def _insert(sequence, value, index=None, before=None):
        """
        Insert a value into a list by index or before another value. Appends when neither is usable.

        :param list sequence: The list to change in place.
        :param object value: Value to insert.
        :param int index: Target index.
        :param object before: Insert before this value when it is in the list.
        """

        if before is not None and before in sequence:
            sequence.insert(sequence.index(before), value)
        elif index is not None and 0 <= index <= len(sequence):
            sequence.insert(index, value)
        else:
            sequence.append(value)

    def _full_order(self, toolbox):
        """
        The section order to write back to a freshly loaded toolbox.

        Ids this session does not know (sections someone else just added) are kept, so saving never drops other
        people's work. For All Tools, shared sections missing from its file are appended in display order, so a drop
        position computed from what is on screen lands in the right place.

        :param toolbox_model.Toolbox toolbox: A toolbox freshly loaded from disk.
        :return: Section ids.
        :rtype: list[str]
        """

        order = list(toolbox.sections)
        if toolbox.is_all_tools:
            order += [x.id for x in self.sections_in(toolbox.name) if x.id not in order]
        return order

    # --- toolboxes -----------------------------------------------------------------------------------------------

    def create_toolbox(self, name, shared=False):
        """
        Create an empty toolbox.

        :param str name: New toolbox name.
        :param bool shared: True for a version controlled toolbox everyone sees, False for a personal one.
        :return: The new toolbox.
        :rtype: toolbox_model.Toolbox
        """

        name = (name or '').strip()
        if not name:
            raise ValueError('A toolbox needs a name.')
        if name in self.toolboxes:
            raise ValueError(f'A toolbox named "{name}" already exists.')
        source = toolbox_model.SHARED if shared else toolbox_model.LOCAL
        path = os.path.join(self._dir(source, TOOLBOXES_DIR), f'{safe_file_name(name)}.yaml')
        if os.path.exists(path):
            raise ValueError(f'The file for "{name}" already exists: {path}')
        self._begin()
        toolbox = toolbox_model.Toolbox(name, source=source, path=path)
        self._save(toolbox)
        self.toolboxes[name] = toolbox
        self._finish()
        return toolbox

    def delete_toolbox(self, name):
        """
        Delete a toolbox (not its sections). All Tools cannot be deleted. A personal toolbox's local sections are
        deleted with it, because nothing else can show them.

        :param str name: Toolbox name.
        """

        toolbox = self.get_toolbox(name)
        if toolbox.is_all_tools:
            raise ValueError('All Tools cannot be deleted.')
        self._begin()
        if not toolbox.is_shared:
            for section_id in toolbox.sections:
                section = self.sections.get(section_id)
                if section and section.source == toolbox_model.LOCAL and \
                        not any(section_id in x.sections for x in self.toolboxes.values() if x is not toolbox):
                    self.warnings += self.local_backend.delete(section.path)
                    self.sections.pop(section_id, None)
        self.warnings += self._backend(toolbox.source).delete(toolbox.path)
        self.toolboxes.pop(name, None)
        overrides = self.get_overrides(name)
        self.local_backend.delete(overrides.path)
        self._overrides.pop(name, None)
        if (self._state.get('toolboxes') or {}).pop(name, None) is not None:
            try:
                toolbox_model.write_yaml(os.path.join(self.local_root, STATE_FILE), self._state)
            except OSError as exc:
                logger.warning(f'Toolbox: could not save state: {exc}')
        self._snapshot = self._watched_files()
        self._finish()

    # --- sections ------------------------------------------------------------------------------------------------

    def add_section(self, toolbox_name, name, index=None, before_id=None, background=None, header=None,
                    personal_colors=False):
        """
        Create a section and show it in a toolbox. A section made in a shared toolbox is shared (and therefore also in
        All Tools); a section made in a personal toolbox is local.

        :param str toolbox_name: Toolbox to add the section to.
        :param str name: Section display name.
        :param int index: Position in the toolbox.
        :param str before_id: Insert before this section id (wins over ``index``).
        :param str background: Background color for this toolbox.
        :param str header: Header color for this toolbox.
        :param bool personal_colors: Store the colors privately instead of in the toolbox.
        :return: The new section.
        :rtype: toolbox_model.ToolboxSection
        """

        name = (name or '').strip()
        if not name:
            raise ValueError('A section needs a name.')
        toolbox = self.get_toolbox(toolbox_name)
        source = toolbox.source
        section = toolbox_model.ToolboxSection(name=name, source=source)
        section.path = os.path.join(self._dir(source, SECTIONS_DIR), f'{section.id}.yaml')

        self._begin()
        toolbox = self._fresh_toolbox(toolbox_name)
        self._save(section)
        self.sections[section.id] = section
        order = [x for x in self._full_order(toolbox) if x != section.id]
        self._insert(order, section.id, index=index, before=before_id)
        toolbox.sections = order
        # A personal toolbox is already private, so "personal" colors only mean something on shared toolboxes.
        self._apply_section_colors(toolbox_name, section.id, background, header,
                                   personal_colors and toolbox.is_shared, toolbox=toolbox)
        self._save(toolbox)
        self._finish()
        return section

    def add_existing_section(self, toolbox_name, section_id, index=None, before_id=None):
        """
        Show an existing section in another toolbox (or move it within the toolbox when already shown).

        :param str toolbox_name: Toolbox name.
        :param str section_id: Section to show.
        :param int index: Position in the toolbox.
        :param str before_id: Insert before this section id (wins over ``index``).
        """

        section = self.get_section(section_id)
        toolbox = self.get_toolbox(toolbox_name)
        if toolbox.is_shared and section.source == toolbox_model.LOCAL:
            raise ValueError(f'"{section.name}" is a personal section and cannot be added to a shared toolbox.')
        if before_id == section_id:
            # Dropped onto itself: nothing moves.
            return
        self._begin()
        toolbox = self._fresh_toolbox(toolbox_name)
        order = [x for x in self._full_order(toolbox) if x != section_id]
        self._insert(order, section_id, index=index, before=before_id)
        toolbox.sections = order
        self._save(toolbox)
        self._finish()

    def move_section(self, toolbox_name, section_id, index=None, before_id=None):
        """
        Reorder a section inside a toolbox. Same as :meth:`add_existing_section`.

        :param str toolbox_name: Toolbox name.
        :param str section_id: Section to move.
        :param int index: New position.
        :param str before_id: Place before this section id (wins over ``index``).
        """

        self.add_existing_section(toolbox_name, section_id, index=index, before_id=before_id)

    def remove_section_from_toolbox(self, toolbox_name, section_id):
        """
        Hide a section in one toolbox without deleting it. Not possible in All Tools, which always shows every shared
        section; use :meth:`delete_section` there.

        :param str toolbox_name: Toolbox name.
        :param str section_id: Section id.
        """

        toolbox = self.get_toolbox(toolbox_name)
        section = self.get_section(section_id)
        if toolbox.is_all_tools:
            raise ValueError('All Tools always shows every section. Delete the section to remove it.')
        if section.source == toolbox_model.LOCAL:
            # A local section only exists for its toolbox, so removing it from the toolbox is deleting it.
            self.delete_section(section_id)
            return
        self._begin()
        toolbox = self._fresh_toolbox(toolbox_name)
        toolbox.forget(section_id=section_id, item_ids=[x.id for x in section.items])
        self._save(toolbox)
        self._finish()

    def delete_section(self, section_id):
        """
        Delete a section everywhere: its file, and its entry and colors in every toolbox this user can edit.

        Personal toolboxes of other users simply stop showing it (missing ids are skipped).

        :param str section_id: Section id.
        """

        section = self.get_section(section_id)
        item_ids = [x.id for x in section.items]
        affected = [x for x in self.toolboxes.values()
                    if section_id in x.sections or section_id in x.section_colors]
        self._begin()
        # Check out everything first so a checkout failure stops the delete before anything changed.
        for toolbox in affected:
            self._prepare(toolbox)
        self.warnings += self._backend(section.source).delete(section.path)
        self.sections.pop(section_id, None)
        for toolbox in affected:
            fresh = self._fresh_toolbox(toolbox.name)
            if fresh.forget(section_id=section_id, item_ids=item_ids):
                self._save(fresh)
        for name in list(self.toolboxes):
            overrides = self.get_overrides(name)
            if overrides.forget(section_id=section_id, item_ids=item_ids):
                self._save_overrides(overrides)
        self._snapshot = self._watched_files()
        self._finish()

    def rename_section(self, section_id, name):
        """
        :param str section_id: Section id.
        :param str name: New display name.
        """

        name = (name or '').strip()
        if not name:
            raise ValueError('A section needs a name.')
        self._begin()
        section = self._fresh_section(section_id)
        section.name = name
        self._save(section)
        self._finish()

    def _apply_section_colors(self, toolbox_name, section_id, background, header, personal, toolbox=None):
        """
        Write section colors onto a toolbox or the user's overrides. Does not save a passed-in toolbox.

        :param str toolbox_name: Toolbox name.
        :param str section_id: Section id.
        :param str|None|_Keep background: New background color, None to clear, KEEP to leave alone.
        :param str|None|_Keep header: New header color, None to clear, KEEP to leave alone.
        :param bool personal: Store privately.
        :param toolbox_model.Toolbox toolbox: An already prepared toolbox to change in place.
        """

        target = self.get_overrides(toolbox_name) if personal else toolbox
        changed = False
        for key, value in (('background', background), ('header', header)):
            if value is KEEP or (value is None and target is toolbox and key not in
                                 target.section_colors.get(section_id, {})):
                continue
            target.set_section_color(section_id, key, value)
            changed = True
        if personal and changed:
            self._save_overrides(target)

    def set_section_colors(self, toolbox_name, section_id, background=KEEP, header=KEEP, personal=False):
        """
        Set the colors a section uses in one toolbox.

        :param str toolbox_name: Toolbox name.
        :param str section_id: Section id.
        :param str|None background: Hex color, None to clear, or omit to leave unchanged.
        :param str|None header: Hex color, None to clear, or omit to leave unchanged.
        :param bool personal: Store privately (only this user sees it) instead of in the shared toolbox.
        """

        self.get_section(section_id)
        self._begin()
        toolbox = self.get_toolbox(toolbox_name)
        # A personal toolbox is already private; its colors go straight into it.
        personal = personal and toolbox.is_shared
        if personal:
            self._apply_section_colors(toolbox_name, section_id, background, header, True)
        else:
            toolbox = self._fresh_toolbox(toolbox_name)
            self._apply_section_colors(toolbox_name, section_id, background, header, False, toolbox=toolbox)
            self._save(toolbox)
        self._finish()

    # --- items ---------------------------------------------------------------------------------------------------

    def add_item(self, section_id, item, index=None, before_id=None, toolbox_name=None, color=None,
                 personal_color=False):
        """
        Add an item to a section.

        :param str section_id: Section id.
        :param toolbox_model.ToolboxItem|dict item: The item, or a dict in the file format.
        :param int index: Position in the section.
        :param str before_id: Insert before this item id (wins over ``index``).
        :param str toolbox_name: Toolbox the item is being added from; ``color`` is stored there.
        :param str color: Color for the item in ``toolbox_name``.
        :param bool personal_color: Store the color privately.
        :return: The added item.
        :rtype: toolbox_model.ToolboxItem
        """

        if isinstance(item, dict):
            item = toolbox_model.ToolboxItem.from_dict(item)
        if not item.name.strip() and item.type not in ('separator',):
            raise ValueError('An item needs a name.')
        if self.find_item(item.id)[1]:
            raise ValueError(f'An item with id "{item.id}" already exists.')
        section = self.get_section(section_id)
        if section.source == toolbox_model.SHARED and item.type == REFERENCE_TYPE:
            raise ValueError('Reference items can only live in personal toolboxes.')

        self._begin()
        section = self._fresh_section(section_id)
        ids = [x.id for x in section.items]
        self._insert(ids, item.id, index=index, before=before_id)
        section.items.insert(ids.index(item.id), item)
        self._save(section)
        if toolbox_name and color:
            self._set_item_color(toolbox_name, item.id, color, personal_color)
        self._finish()
        return item

    def update_item(self, item_id, name=KEEP, tooltip=KEEP, command=KEEP, settings=KEEP, tags=KEEP, item_type=KEEP):
        """
        Change an item's shared fields. Omitted arguments are left unchanged.

        :param str item_id: Item id.
        :param str name: Display name.
        :param str tooltip: Tooltip.
        :param dict|str command: Command dict, or a code string.
        :param dict settings: Replaces the type specific settings.
        :param list[str] tags: Filter tags.
        :param str item_type: Registered item type.
        :return: The updated item.
        :rtype: toolbox_model.ToolboxItem
        """

        section, _ = self.find_item(item_id)
        if not section:
            raise KeyError(f'No item with id "{item_id}".')
        self._begin()
        section = self._fresh_section(section.id)
        item = section.get_item(item_id)
        if item is None:
            raise KeyError(f'Item "{item_id}" was removed by someone else.')
        if name is not KEEP:
            item.name = name or ''
        if tooltip is not KEEP:
            item.tooltip = tooltip or ''
        if command is not KEEP:
            item.command = toolbox_model.ToolboxItem._normalize_command(command)
        if settings is not KEEP:
            item.settings = dict(settings or {})
        if tags is not KEEP:
            item.tags = [str(x) for x in (tags or [])]
        if item_type is not KEEP:
            item.type = item_type
        self._save(section)
        self._finish()
        return item

    def set_item_icon(self, item_id, icon=KEEP, icon_only=KEEP):
        """
        Set or clear a button's icon without replacing its other settings.

        :param str item_id: Item id.
        :param str|None icon: Icon name from :meth:`list_icons`, a path relative to an icon folder, or an absolute
            path. None or ``''`` removes the icon.
        :param bool icon_only: Hide the button text (the name moves into the tooltip).
        :return: The updated item.
        :rtype: toolbox_model.ToolboxItem
        """

        section, item = self.find_item(item_id)
        if not section:
            raise KeyError(f'No item with id "{item_id}".')
        if item.type != 'button':
            raise ValueError(f'Only buttons show icons; "{item.name}" is a {item.type}.')
        if icon is not KEEP and icon and not self.resolve_icon(icon):
            raise ValueError(f'Icon "{icon}" was not found. Use list_icons, or import_icon for a new file.')
        settings = dict(item.settings)
        if icon is not KEEP:
            if icon:
                settings['icon'] = icon
            else:
                settings.pop('icon', None)
        if icon_only is not KEEP:
            if icon_only:
                settings['icon_only'] = True
            else:
                settings.pop('icon_only', None)
        return self.update_item(item_id, settings=settings)

    # --- icons ---------------------------------------------------------------------------------------------------

    def icon_folders(self):
        """
        Folders searched for item icons, in lookup order: the toolbox's own shared icons, the user's local icons, then
        the MCA icon libraries. Only existing folders are returned.

        :return: Absolute folder paths.
        :rtype: list[str]
        """

        folders = [os.path.join(self.shared_root, ICONS_DIR), os.path.join(self.local_root, ICONS_DIR)]
        for getter_name in ('get_common_icons_path', 'get_icons_path'):
            try:
                from mca.common.paths import paths
                folders.append(getattr(paths, getter_name)())
            except Exception:
                # These need the MCA environment; tests and bare Python only get the toolbox folders.
                logger.debug(f'Toolbox: {getter_name} unavailable.', exc_info=True)
        result = []
        for folder in folders:
            folder = os.path.normpath(folder)
            if os.path.isdir(folder) and os.path.normcase(folder) not in [os.path.normcase(x) for x in result]:
                result.append(folder)
        return result

    def resolve_icon(self, icon):
        """
        Find the image file for an item's icon setting.

        :param str icon: Icon name (``'export.png'``), a path relative to an icon folder (``'color/question.png'``),
            or an absolute path. Environment variables are expanded.
        :return: Absolute file path, or None when the icon is empty or missing.
        :rtype: str|None
        """

        if not icon:
            return None
        icon = os.path.expandvars(str(icon).strip())
        if os.path.isabs(icon):
            return os.path.normpath(icon) if os.path.isfile(icon) else None
        for folder in self.icon_folders():
            path = os.path.normpath(os.path.join(folder, icon))
            if os.path.isfile(path):
                return path
        return None

    def list_icons(self, text=None):
        """
        List the icons items can use.

        :param str text: Only names containing this text (case-insensitive).
        :return: ``[{'icon': name to store, 'path': absolute path}]`` sorted by name; the first folder wins when two
            folders have the same name.
        :rtype: list[dict]
        """

        found = {}
        for folder in self.icon_folders():
            for root, _, files in os.walk(folder):
                for file_name in files:
                    if os.path.splitext(file_name)[1].lower() not in ICON_EXTENSIONS:
                        continue
                    path = os.path.join(root, file_name)
                    name = os.path.relpath(path, folder).replace('\\', '/')
                    if text and text.lower() not in name.lower():
                        continue
                    found.setdefault(name, path)
        return [{'icon': name, 'path': found[name]} for name in sorted(found, key=str.lower)]

    def icon_name_for(self, path):
        """
        :param str path: An image file.
        :return: The name to store for ``path`` when it already lives in an icon folder (so it works for everyone),
            else None.
        :rtype: str|None
        """

        path = os.path.abspath(path)
        for folder in self.icon_folders():
            # normcase only for the comparison; the stored name keeps the file's real casing.
            if os.path.normcase(path).startswith(os.path.normcase(folder) + os.sep):
                return os.path.relpath(path, folder).replace('\\', '/')
        return None

    def import_icon(self, file_path, shared=True):
        """
        Copy an image into the toolbox icon folder so every user can see it. Shared icons are added to Perforce.

        Images already inside an icon folder are not copied. A different image with the same file name gets a
        numbered name instead of replacing the existing icon.

        :param str file_path: Image to import.
        :param bool shared: Import into the shared (version controlled) folder; False keeps it local.
        :return: The icon name to store on items.
        :rtype: str
        """

        if not os.path.isfile(file_path):
            raise ValueError(f'No file at "{file_path}".')
        extension = os.path.splitext(file_path)[1].lower()
        if extension not in ICON_EXTENSIONS:
            raise ValueError(f'Icons must be one of: {", ".join(ICON_EXTENSIONS)}.')
        existing = self.icon_name_for(file_path)
        if existing:
            return existing

        folder = os.path.join(self.shared_root if shared else self.local_root, ICONS_DIR)
        os.makedirs(folder, exist_ok=True)
        with open(file_path, 'rb') as handle:
            data = handle.read()
        base = re.sub(r'[^A-Za-z0-9_.-]+', '_', os.path.splitext(os.path.basename(file_path))[0]) or 'icon'
        name = f'{base}{extension}'
        counter = 1
        while os.path.isfile(os.path.join(folder, name)):
            with open(os.path.join(folder, name), 'rb') as handle:
                if handle.read() == data:
                    return name
            counter += 1
            name = f'{base}_{counter}{extension}'

        self._begin()
        target = os.path.join(folder, name)
        try:
            with open(target, 'wb') as handle:
                handle.write(data)
        except OSError as exc:
            raise toolbox_vcs.ToolboxWriteError(f'Could not save icon {name}: {exc}')
        self.warnings += self._backend(toolbox_model.SHARED if shared else toolbox_model.LOCAL).after_write(target,
                                                                                                             True)
        for warning in self.warnings:
            logger.warning(f'Toolbox: {warning}')
        return name

    def delete_item(self, item_id):
        """
        Delete an item from its section (and so from every toolbox showing that section).

        :param str item_id: Item id.
        """

        section, _ = self.find_item(item_id)
        if not section:
            raise KeyError(f'No item with id "{item_id}".')
        self._begin()
        section = self._fresh_section(section.id)
        section.items = [x for x in section.items if x.id != item_id]
        self._save(section)
        self._finish()

    def duplicate_item(self, item_id):
        """
        Copy an item (new id) and place the copy right after the original.

        :param str item_id: Item id.
        :return: The copy.
        :rtype: toolbox_model.ToolboxItem
        """

        section, item = self.find_item(item_id)
        if not section:
            raise KeyError(f'No item with id "{item_id}".')
        copy_item = item.copy(new_id=True)
        copy_item.name = f'{item.name} Copy' if item.name else item.name
        index = section.index_of(item_id) + 1
        return self.add_item(section.id, copy_item, index=index)

    def move_item(self, item_id, target_section_id, index=None, before_id=None):
        """
        Move an item within its section or to another section.

        Moving a shared item into a personal (local) section adds a reference to it and leaves the original in place,
        so personal toolboxes never take tools away from everyone else.

        :param str item_id: Item id.
        :param str target_section_id: Destination section id.
        :param int index: Position in the destination, counted without the moved item.
        :param str before_id: Place before this item id (wins over ``index``).
        :return: The item now in the target section (a new reference item when a shared item went local).
        :rtype: toolbox_model.ToolboxItem
        """

        source_section, item = self.find_item(item_id)
        if not source_section:
            raise KeyError(f'No item with id "{item_id}".')
        target = self.get_section(target_section_id)
        if before_id == item_id and source_section.id == target_section_id:
            # Dropped onto itself: nothing moves.
            return item
        if before_id == item_id:
            before_id = None

        if source_section.source == toolbox_model.SHARED and target.source == toolbox_model.LOCAL:
            reference = toolbox_model.ToolboxItem(item_type=REFERENCE_TYPE, name=item.name,
                                                  settings={'item_id': item.id})
            return self.add_item(target_section_id, reference, index=index, before_id=before_id)
        if item.type == REFERENCE_TYPE and target.source == toolbox_model.SHARED:
            raise ValueError('Reference items can only live in personal toolboxes.')

        self._begin()
        if source_section.id == target_section_id:
            section = self._fresh_section(target_section_id)
            moved = section.get_item(item_id)
            if moved is None:
                raise KeyError(f'Item "{item_id}" was removed by someone else.')
            section.items.remove(moved)
            ids = [x.id for x in section.items]
            self._insert(ids, item_id, index=index, before=before_id)
            section.items.insert(ids.index(item_id), moved)
            self._save(section)
        else:
            # Check out both files before writing either, so a failure cannot lose the item.
            self._prepare(source_section)
            self._prepare(target)
            source_fresh = self._fresh_section(source_section.id)
            target_fresh = self._fresh_section(target_section_id)
            moved = source_fresh.get_item(item_id)
            if moved is None:
                raise KeyError(f'Item "{item_id}" was removed by someone else.')
            source_fresh.items.remove(moved)
            ids = [x.id for x in target_fresh.items]
            self._insert(ids, item_id, index=index, before=before_id)
            target_fresh.items.insert(ids.index(item_id), moved)
            # Write the destination first: if the second write fails the item exists twice rather than not at all.
            self._save(target_fresh)
            self._save(source_fresh)
        self._finish()
        return moved

    def _set_item_color(self, toolbox_name, item_id, color, personal):
        """
        Store an item color without starting/finishing an edit.

        :param str toolbox_name: Toolbox name.
        :param str item_id: Item id.
        :param str|None color: Hex color or None to clear.
        :param bool personal: Store privately.
        """

        toolbox = self.get_toolbox(toolbox_name)
        if personal and toolbox.is_shared:
            overrides = self.get_overrides(toolbox_name)
            overrides.set_item_color(item_id, color)
            self._save_overrides(overrides)
        else:
            toolbox = self._fresh_toolbox(toolbox_name)
            toolbox.set_item_color(item_id, color)
            self._save(toolbox)

    def set_item_color(self, toolbox_name, item_id, color, personal=False):
        """
        Set the color an item uses in one toolbox.

        :param str toolbox_name: Toolbox name.
        :param str item_id: Item id.
        :param str|None color: Hex color, or None to clear.
        :param bool personal: Store privately (only this user sees it) instead of in the shared toolbox.
        """

        self._begin()
        self._set_item_color(toolbox_name, item_id, color, personal)
        self._finish()

    def _save_overrides(self, overrides):
        """
        Save private colors, deleting the file when nothing is left.

        :param toolbox_model.ColorOverrides overrides: The overrides to save.
        """

        if overrides.section_colors or overrides.item_colors:
            toolbox_model.write_yaml(overrides.path, overrides.to_dict())
        else:
            self.local_backend.delete(overrides.path)
        self._snapshot = self._watched_files()

    def clear_personal_colors(self, toolbox_name):
        """
        Remove all of the user's private colors for a toolbox.

        :param str toolbox_name: Toolbox name.
        """

        self._begin()
        overrides = self.get_overrides(toolbox_name)
        overrides.section_colors = {}
        overrides.item_colors = {}
        self._save_overrides(overrides)
        self._finish()
