"""
Mesh Tiler - repeat one mesh across the surface of another.

The window is a thin shell over :mod:`meshtiler_api`. Every button calls one API
function and shows the ``message`` it gets back, so what the UI reports and what
a script would get are the same thing, and a failure reads as a sentence rather
than a traceback in the script editor.

Two halves:

* **Build** - pick a tile and a target, set the knobs, make tiles.
* **Live tiler** - only enabled once something is built, or once you select a
  tiler that already exists. Turning tiles, baking down, taking it back out.

:Requires: the mcaMeshTiler plug-in, which the window loads for you.
"""

# python imports
import os

# software specific imports
import maya.cmds as cmds

# Qt imports
from mca.common.pyqt.pygui import qtwidgets, qtcore

# MCA python imports
from mca.common import log
from mca.mya.pyqt import mayawindows
from mca.mya.tools.meshtiler import meshtiler_api

logger = log.MCA_LOGGER

#: Where build_sample.py lives, relative to this file.
SAMPLES_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '..', '..', 'plugins', 'mcaMeshTiler', 'samples'))


class MeshTilerUI(mayawindows.MCAMayaWindow):
    """
    The Mesh Tiler window.

    Built on :class:`mayawindows.MCAMayaWindow` rather than the plain
    ``MCAMainWindow``, so it is parented to Maya's main window: it stays in front
    of Maya instead of getting lost behind it, it closes with Maya, and it
    follows the same conventions as every other tool in this tree.
    """

    VERSION = '1.1.0'

    def __init__(self, parent=None, **kwargs):
        super().__init__(title='Mesh Tiler', ui_path=None, show_window=True,
                         version=self.VERSION, **kwargs)

        self._tile = None
        self._target = None
        self._tiler = None

        self.setMinimumSize(420, 660)
        self._build_ui()
        self._connect_live_editing()
        self._check_plugin()

    # --- construction ------------------------------------------------------- #

    def _build_ui(self):
        """
        Lay the window out.
        """

        layout = self.main_layout
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # --- meshes ---------------------------------------------------------- #
        meshes = qtwidgets.QGroupBox('Meshes')
        mesh_form = qtwidgets.QGridLayout(meshes)
        self.tile_field = self._mesh_row(mesh_form, 0, 'Tile', self._pick_tile,
                                         'The mesh that gets repeated. Author it flat, '
                                         'with the up axis below pointing off the surface.')
        self.target_field = self._mesh_row(mesh_form, 1, 'Target', self._pick_target,
                                           'The surface to repeat it across. Any topology - '
                                           'triangles and n-gons are fine.')
        layout.addWidget(meshes)

        # --- placement -------------------------------------------------------- #
        placement = qtwidgets.QGroupBox('Placement')
        place_form = qtwidgets.QFormLayout(placement)

        self.up_axis = qtwidgets.QComboBox()
        self.up_axis.addItems(['X', 'Y', 'Z'])
        self.up_axis.setCurrentIndex(1)
        self.up_axis.setToolTip('Which tile axis points away from the surface.')
        place_form.addRow('Up axis', self.up_axis)

        self.height = self._spin(1.0, -100.0, 100.0, 0.05)
        self.height.setToolTip('Multiplies how far the tile stands off the surface.')
        place_form.addRow('Height', self.height)

        self.height_offset = self._spin(0.0, -100.0, 100.0, 0.05)
        self.height_offset.setToolTip(
            'Added to how far it stands off, in world units - the same amount everywhere, '
            'however curved the surface is.')
        place_form.addRow('Height offset', self.height_offset)

        # Fill rather than stretch. One tile per face is what the tool this
        # replaces could do, and it means a big face gets a big tile.
        grid_row = qtwidgets.QHBoxLayout()
        self.tiles_u = qtwidgets.QSpinBox()
        self.tiles_v = qtwidgets.QSpinBox()
        for box in (self.tiles_u, self.tiles_v):
            box.setRange(1, 64)
            box.setValue(1)
            box.setToolTip('How many tiles fit across each face, and down it. '
                           '1 x 1 stretches a single tile over the whole face; '
                           'anything higher fills it with a grid.')
        grid_row.addWidget(self.tiles_u)
        grid_row.addWidget(qtwidgets.QLabel('x'))
        grid_row.addWidget(self.tiles_v)
        grid_row.addStretch()
        place_form.addRow('Tiles per face', grid_row)

        self.area_scale = self._spin(0.0, 0.0, 1.0, 0.05)
        self.area_scale.setToolTip(
            '0 leaves every tile the same size. 1 scales each one by the square root of '
            "its face's area, so tiles on a stretched face grow to match.")
        place_form.addRow('Area scale', self.area_scale)
        layout.addWidget(placement)

        # --- surface ----------------------------------------------------------- #
        surface = qtwidgets.QGroupBox('Surface')
        surface_form = qtwidgets.QFormLayout(surface)

        self.normal_mode = qtwidgets.QComboBox()
        self.normal_mode.addItems(['Face', 'Surface', 'Derivative'])
        self.normal_mode.setCurrentIndex(1)
        self.normal_mode.setToolTip(
            'Where a tile\'s normal comes from. Face is flat per face; Surface interpolates '
            'the limit surface, which is what you want almost always; Derivative is more '
            'faithful on a heavily creased target and slower.')
        surface_form.addRow('Normals', self.normal_mode)

        self.boundary = qtwidgets.QComboBox()
        self.boundary.addItems(['Edge', 'Edge and Corner'])
        self.boundary.setCurrentIndex(1)
        self.boundary.setToolTip('How the limit surface behaves where the target has an open edge.')
        surface_form.addRow('Boundary', self.boundary)

        self.use_mesh_creases = qtwidgets.QCheckBox('Honour the creases authored on the target')
        self.use_mesh_creases.setChecked(True)
        surface_form.addRow('', self.use_mesh_creases)
        layout.addWidget(surface)

        # --- tiles ---------------------------------------------------------------- #
        tiles = qtwidgets.QGroupBox('Tiles')
        tiles_layout = qtwidgets.QVBoxLayout(tiles)
        self.copy_uvs = qtwidgets.QCheckBox('Copy the tile\'s UV sets')
        self.copy_uvs.setChecked(True)
        self.copy_uvs.setToolTip('Every tile lands on the same patch of texture.')
        self.refine_non_quads = qtwidgets.QCheckBox('Tile triangles and n-gons as well as quads')
        self.refine_non_quads.setChecked(True)
        self.refine_non_quads.setToolTip(
            'Off means a non-quad target is refused rather than quietly half-tiled.')
        self.inherit_shader = qtwidgets.QCheckBox('Give the result the tile\'s shader')
        self.inherit_shader.setChecked(True)
        self.inherit_shader.setToolTip(
            'Applies when the tiles are created. Everything above this line can be '
            'changed on a tiler that already exists; this one and the pin below are '
            'about how the graph is wired, so they are set once.')
        self.pin_to_target = qtwidgets.QCheckBox('Pin the tiles to the target')
        self.pin_to_target.setChecked(False)
        self.pin_to_target.setToolTip(
            'Welds the tiles to the target so they stay on it wherever the result is '
            'moved. The catch is that this makes the result IMMOVABLE - the solve '
            'cancels out anything you do to its transform. Leave it off and the tiled '
            'mesh behaves like any other object. Applies when the tiles are created.')
        for widget in (self.copy_uvs, self.refine_non_quads, self.inherit_shader,
                       self.pin_to_target):
            tiles_layout.addWidget(widget)
        layout.addWidget(tiles)

        self.create_button = qtwidgets.QPushButton('Create Tiles')
        self.create_button.setMinimumHeight(34)
        self.create_button.clicked.connect(self._create)
        layout.addWidget(self.create_button)

        # --- the live tiler -------------------------------------------------------- #
        self.live = qtwidgets.QGroupBox('Live tiler')
        live_layout = qtwidgets.QVBoxLayout(self.live)

        self.tiler_label = qtwidgets.QLabel('Nothing selected.')
        self.tiler_label.setWordWrap(True)
        live_layout.addWidget(self.tiler_label)

        use_tiler = qtwidgets.QPushButton('Use Selected Tiler')
        use_tiler.setToolTip('Select a tiled mesh or its tiler node to work on one you made earlier.')
        use_tiler.clicked.connect(self._pick_tiler)
        live_layout.addWidget(use_tiler)

        rotate_row = qtwidgets.QHBoxLayout()
        for label, steps in (('Rotate Faces  -', -1), ('Rotate Faces  +', 1)):
            button = qtwidgets.QPushButton(label)
            button.setToolTip('Select faces on the TARGET mesh, then turn their tiles a '
                              'quarter turn.')
            button.clicked.connect(lambda _=False, value=steps: self._rotate(value))
            rotate_row.addWidget(button)
        live_layout.addLayout(rotate_row)

        clear = qtwidgets.QPushButton('Clear Rotations')
        clear.clicked.connect(self._clear_rotations)
        live_layout.addWidget(clear)

        finish_row = qtwidgets.QHBoxLayout()
        freeze = qtwidgets.QPushButton('Freeze')
        freeze.setToolTip('Bake the tiles down to a plain mesh and delete the tiler.')
        freeze.clicked.connect(self._freeze)
        remove = qtwidgets.QPushButton('Remove')
        remove.setToolTip('Take the whole thing back out. Nothing it read was modified.')
        remove.clicked.connect(self._remove)
        finish_row.addWidget(freeze)
        finish_row.addWidget(remove)
        live_layout.addLayout(finish_row)

        self.live.setEnabled(False)
        layout.addWidget(self.live)

        layout.addStretch()

        sample = qtwidgets.QPushButton('Build Sample Scene')
        sample.setToolTip('Three setups in an empty scene: quads, triangles and n-gons.')
        sample.clicked.connect(self._build_sample)
        layout.addWidget(sample)

        self.status = qtwidgets.QLabel('')
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(36)
        self.status.setAlignment(qtcore.Qt.AlignTop)
        layout.addWidget(self.status)

    def _mesh_row(self, grid, row, label, callback, tip):
        """
        A read-only name field with a "use the selection" button next to it.

        :param grid: The layout to add to.
        :param int row: Which row.
        :param str label: Field label.
        :param callback: What the button calls.
        :param str tip: Tool tip.
        :return: The field.
        :rtype: qtwidgets.QLineEdit
        """

        grid.addWidget(qtwidgets.QLabel(label), row, 0)
        field = qtwidgets.QLineEdit()
        field.setReadOnly(True)
        field.setPlaceholderText('nothing picked')
        field.setToolTip(tip)
        grid.addWidget(field, row, 1)
        button = qtwidgets.QPushButton('Use Selected')
        button.clicked.connect(callback)
        grid.addWidget(button, row, 2)
        return field

    @staticmethod
    def _spin(value, minimum, maximum, step):
        """
        :return: A double spin box.
        :rtype: qtwidgets.QDoubleSpinBox
        """

        box = qtwidgets.QDoubleSpinBox()
        box.setRange(minimum, maximum)
        box.setSingleStep(step)
        box.setDecimals(3)
        box.setValue(value)
        return box

    # --- driving a live tiler ---------------------------------------------------- #
    #
    # Every setting in the top half is a plain attribute on the node, so there is
    # no reason it should only apply at create time. Without this, changing Tiles
    # Per Face on a tiler that already exists does nothing at all, and the window
    # quietly disagrees with the node it is pointed at.

    def _settings(self):
        """
        The widgets that map straight onto node attributes.

        :return: ``(widget, attribute name)`` pairs.
        :rtype: tuple
        """

        return ((self.up_axis, 'tileUpAxis'),
                (self.tiles_u, 'tilesU'),
                (self.tiles_v, 'tilesV'),
                (self.height, 'height'),
                (self.height_offset, 'heightOffset'),
                (self.area_scale, 'areaScale'),
                (self.normal_mode, 'normalMode'),
                (self.boundary, 'boundaryInterpolation'),
                (self.use_mesh_creases, 'useMeshCreases'),
                (self.copy_uvs, 'copyUVs'),
                (self.refine_non_quads, 'refineNonQuads'))

    @staticmethod
    def _widget_value(widget):
        """
        :param widget: One of the setting widgets.
        :return: What it is currently set to, in the type the attribute wants.
        """

        if isinstance(widget, qtwidgets.QComboBox):
            return widget.currentIndex()
        if isinstance(widget, qtwidgets.QCheckBox):
            return widget.isChecked()
        return widget.value()

    @staticmethod
    def _set_widget_value(widget, value):
        """
        Put a value into a widget without setting off its change signal.

        :param widget: One of the setting widgets.
        :param value: What the node says it is.
        """

        blocked = widget.blockSignals(True)
        try:
            if isinstance(widget, qtwidgets.QComboBox):
                widget.setCurrentIndex(int(value))
            elif isinstance(widget, qtwidgets.QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, qtwidgets.QSpinBox):
                widget.setValue(int(value))
            else:
                widget.setValue(float(value))
        finally:
            widget.blockSignals(blocked)

    def _connect_live_editing(self):
        """
        Make every setting drive the live tiler as soon as it is changed.
        """

        for widget, attribute in self._settings():
            if isinstance(widget, qtwidgets.QComboBox):
                signal = widget.currentIndexChanged
            elif isinstance(widget, qtwidgets.QCheckBox):
                signal = widget.toggled
            else:
                signal = widget.valueChanged
            signal.connect(lambda _=None, w=widget, a=attribute: self._push(w, a))

    def _push(self, widget, attribute):
        """
        Send one setting to the live tiler, if there is one.

        Silent when there is no tiler: the widgets are also the settings the next
        Create Tiles will use, so changing them with nothing live is not an error.

        :param widget: The widget that changed.
        :param str attribute: The node attribute it drives.
        """

        if not self._tiler or not cmds.objExists(self._tiler):
            return
        try:
            cmds.setAttr('{}.{}'.format(self._tiler, attribute),
                         self._widget_value(widget))
        except Exception as exc:
            self._say('Could not set {}: {}'.format(attribute, exc), ok=False)

    def _pull(self):
        """
        Read the live tiler's settings back into the window.

        Called when a tiler is adopted, so the window shows what that node
        actually is rather than whatever was last typed into it.
        """

        if not self._tiler or not cmds.objExists(self._tiler):
            return
        for widget, attribute in self._settings():
            try:
                self._set_widget_value(widget,
                                       cmds.getAttr('{}.{}'.format(self._tiler, attribute)))
            except Exception:
                logger.debug('Mesh Tiler: could not read %s.', attribute, exc_info=True)

    # --- helpers --------------------------------------------------------------- #

    def _say(self, message, ok=True):
        """
        Put a line under the window.

        :param str message: What happened.
        :param bool ok: False colours it as a problem.
        """

        self.status.setStyleSheet('color: #cccccc;' if ok else 'color: #e06c5a;')
        self.status.setText(message)
        (logger.info if ok else logger.warning)('Mesh Tiler: %s', message)

    def _check_plugin(self):
        """
        Load the plug-in, and say so plainly if it will not come up.
        """

        available, reason = meshtiler_api.plugin_is_available()
        if available:
            self._say('Ready. Pick a tile and a target.')
            return
        self.create_button.setEnabled(False)
        self._say(reason, ok=False)

    @staticmethod
    def _selected_mesh():
        """
        The first selected transform or mesh.

        :return: Its name, or None.
        :rtype: str
        """

        for node in cmds.ls(selection=True, long=False) or []:
            if cmds.listRelatives(node, shapes=True, type='mesh') or \
                    cmds.nodeType(node) == 'mesh':
                return node
        return None

    def _pick_tile(self):
        """
        Take the tile from the selection.
        """

        mesh = self._selected_mesh()
        if not mesh:
            self._say('Select a polygon mesh to use as the tile.', ok=False)
            return
        self._tile = mesh
        self.tile_field.setText(mesh)
        self._say('Tile set to {}.'.format(mesh))

    def _pick_target(self):
        """
        Take the target from the selection.
        """

        mesh = self._selected_mesh()
        if not mesh:
            self._say('Select a polygon mesh to use as the target.', ok=False)
            return
        self._target = mesh
        self.target_field.setText(mesh)
        self._say('Target set to {}.'.format(mesh))

    def _pick_tiler(self):
        """
        Adopt a tiler that already exists, from whatever is selected.

        Accepts the tiler node itself or anything downstream of it, so selecting
        the tiled mesh in the viewport is enough.
        """

        for node in cmds.ls(selection=True) or []:
            if cmds.nodeType(node) == meshtiler_api.NODE_TYPE:
                self._adopt(node)
                return
            history = cmds.listHistory(node, type=meshtiler_api.NODE_TYPE) or []
            if history:
                self._adopt(history[0])
                return
        self._say('Select a tiled mesh, or its tiler node.', ok=False)

    def _adopt(self, tiler):
        """
        Point the live half of the window at a tiler.

        :param str tiler: The tiler node.
        """

        self._tiler = tiler
        self.live.setEnabled(True)
        self.tiler_label.setText(
            'Working on {}. Changing a setting above updates it live.'.format(tiler))
        self._pull()
        self._say('Using {}.'.format(tiler))

    def _needs_tiler(self):
        """
        :return: True when there is a live tiler to act on.
        :rtype: bool
        """

        if self._tiler and cmds.objExists(self._tiler):
            return True
        self._tiler = None
        self.live.setEnabled(False)
        self.tiler_label.setText('Nothing selected.')
        self._say('That tiler is gone. Use Selected Tiler to pick another.', ok=False)
        return False

    def _handle(self, response):
        """
        Show a response and say whether it worked.

        :param dict response: An ``ok/result/message`` response.
        :return: True when it worked.
        :rtype: bool
        """

        self._say(response['message'], ok=response['ok'])
        return response['ok']

    # --- actions ------------------------------------------------------------------ #

    def _create(self):
        """
        Build the tiles.
        """

        if not self._tile or not cmds.objExists(self._tile):
            self._say('Pick a tile mesh first.', ok=False)
            return
        if not self._target or not cmds.objExists(self._target):
            self._say('Pick a target mesh first.', ok=False)
            return

        response = meshtiler_api.tile_mesh(
            self._tile, self._target,
            up_axis=self.up_axis.currentIndex(),
            height=self.height.value(),
            height_offset=self.height_offset.value(),
            area_scale=self.area_scale.value(),
            normal_mode=self.normal_mode.currentIndex(),
            boundary=self.boundary.currentIndex(),
            use_mesh_creases=self.use_mesh_creases.isChecked(),
            copy_uvs=self.copy_uvs.isChecked(),
            refine_non_quads=self.refine_non_quads.isChecked(),
            inherit_shader=self.inherit_shader.isChecked(),
            pin_to_target=self.pin_to_target.isChecked(),
            tiles_u=self.tiles_u.value(),
            tiles_v=self.tiles_v.value())
        if not self._handle(response):
            return

        result = response['result']
        self._adopt(str(result['tiler']))
        self._say(response['message'])
        cmds.select(str(result['transform']))

    def _rotate(self, steps):
        """
        Turn the tiles on the selected target faces.

        :param int steps: Quarter turns, signed.
        """

        if self._needs_tiler():
            self._handle(meshtiler_api.rotate_selected_faces(self._tiler, steps))

    def _clear_rotations(self):
        """
        Put every tile back to the orientation its face gives it.
        """

        if self._needs_tiler():
            self._handle(meshtiler_api.clear_face_rotations(self._tiler))

    def _output_transform(self):
        """
        The transform the tiler drives.

        :return: Its name, or None.
        :rtype: str
        """

        for shape in cmds.listConnections(self._tiler + '.outMesh', type='mesh') or []:
            parents = cmds.listRelatives(shape, parent=True) or []
            if parents:
                return parents[0]
        return None

    def _freeze(self):
        """
        Bake the tiles down to plain geometry.
        """

        if not self._needs_tiler():
            return
        transform = self._output_transform()
        if not transform:
            self._say('Cannot find the mesh that tiler drives.', ok=False)
            return
        if self._handle(meshtiler_api.freeze_tiling(transform)):
            self._tiler = None
            self.live.setEnabled(False)
            self.tiler_label.setText('Nothing selected.')

    def _remove(self):
        """
        Take the tiling back out.
        """

        if not self._needs_tiler():
            return
        transform = self._output_transform()
        if not transform:
            self._say('Cannot find the mesh that tiler drives.', ok=False)
            return
        if self._handle(meshtiler_api.remove_tiling(transform)):
            self._tiler = None
            self.live.setEnabled(False)
            self.tiler_label.setText('Nothing selected.')

    def _build_sample(self):
        """
        Build the sample scene, so the tool can be seen working without setting
        anything up first.

        The sample does not clean up after itself, so this asks before dropping a
        second copy of everything into a scene that already has one.
        """

        import sys
        if SAMPLES_PATH not in sys.path:
            sys.path.append(SAMPLES_PATH)
        try:
            import build_sample
            import importlib
            importlib.reload(build_sample)
        except Exception as exc:
            self._say('Could not load the sample: {}'.format(exc), ok=False)
            return

        if cmds.objExists('setup1_quads'):
            answer = qtwidgets.QMessageBox.question(
                self, 'Mesh Tiler',
                'This scene already has a sample in it. Build another one?',
                qtwidgets.QMessageBox.Yes | qtwidgets.QMessageBox.No)
            if answer != qtwidgets.QMessageBox.Yes:
                self._say('Left the scene alone.')
                return

        try:
            made = build_sample.build()
        except Exception as exc:
            self._say('The sample failed: {}'.format(exc), ok=False)
            logger.warning('Mesh Tiler sample failed.', exc_info=True)
            return
        self._say('Built {}. Select a target cage and drag a vertex - the tiles follow.'
                  .format(', '.join(made)))


def open_tool(*args, **kwargs):
    """
    Open the Mesh Tiler window. This is what the Toolbox button calls.

    :return: The window.
    :rtype: MeshTilerUI
    """

    return MeshTilerUI()
