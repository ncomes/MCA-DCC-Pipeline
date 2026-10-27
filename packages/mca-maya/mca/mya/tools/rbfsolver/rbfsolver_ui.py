"""
RBF Solver - interpolate an N-dimensional key to an M-dimensional value.

A driven key with more than one dimension on each side. Put the rig where you
want it, say what the values should be there, press Add Pose. Do that a few
times and the solver blends between them.

The window is a thin shell over :mod:`rbfsolver_api`. Every button calls one API
function and shows the ``message`` it gets back, so what the UI reports and what
a script gets are the same sentence.

The knobs live on the node, so once a solver exists the settings drive it live -
change the kernel and the result updates. The poses are the part this window is
really for: reading a key off the live rig is something you cannot sensibly do
by typing numbers into the Attribute Editor.

:Requires: the mcaRBFSolver plug-in, which the window loads for you.
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
from mca.mya.tools.rbfsolver import rbfsolver_api

logger = log.MCA_LOGGER

#: Where build_sample.py lives, relative to this file.
SAMPLES_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '..', '..', 'plugins', 'mcaRBFSolver', 'samples'))


class RBFSolverUI(mayawindows.MCAMayaWindow):
    """
    The RBF Solver window.
    """

    VERSION = '1.0.0'

    def __init__(self, parent=None, **kwargs):
        super().__init__(title='RBF Solver', ui_path=None, show_window=True,
                         version=self.VERSION, **kwargs)

        self._solver = None

        self.setMinimumSize(460, 620)
        self._build_ui()
        self._connect_live_editing()
        self._check_plugin()
        self._refresh_solvers()

    # --- construction ------------------------------------------------------- #

    def _build_ui(self):
        """
        Lay the window out.
        """

        layout = self.main_layout
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # --- which solver ---------------------------------------------------- #
        pick = qtwidgets.QGroupBox('Solver')
        pick_layout = qtwidgets.QHBoxLayout(pick)
        self.solver_list = qtwidgets.QComboBox()
        self.solver_list.currentIndexChanged.connect(self._solver_chosen)
        pick_layout.addWidget(self.solver_list, 1)
        make = qtwidgets.QPushButton('New')
        make.clicked.connect(self._create)
        refresh = qtwidgets.QPushButton('Refresh')
        refresh.clicked.connect(self._refresh_solvers)
        pick_layout.addWidget(make)
        pick_layout.addWidget(refresh)
        layout.addWidget(pick)

        # --- wiring ----------------------------------------------------------- #
        wiring = qtwidgets.QGroupBox('Wiring')
        wiring_layout = qtwidgets.QVBoxLayout(wiring)
        note = qtwidgets.QLabel(
            'Select the attributes in the Channel Box, in the order you want them, '
            'then connect them. The order has to be the same for every pose.')
        note.setWordWrap(True)
        wiring_layout.addWidget(note)

        wiring_row = qtwidgets.QHBoxLayout()
        drive_button = qtwidgets.QPushButton('Connect As Key')
        drive_button.setToolTip('The things that drive the solver - a joint\'s rotation, '
                                'an aim vector, a slider.')
        drive_button.clicked.connect(self._connect_input)
        driven_button = qtwidgets.QPushButton('Connect As Value')
        driven_button.setToolTip('The things the solver drives - blendshape weights, '
                                 'a colour, anything.')
        driven_button.clicked.connect(self._connect_output)
        wiring_row.addWidget(drive_button)
        wiring_row.addWidget(driven_button)
        wiring_layout.addLayout(wiring_row)
        layout.addWidget(wiring)

        # --- poses -------------------------------------------------------------- #
        pose_box = qtwidgets.QGroupBox('Poses')
        pose_layout = qtwidgets.QVBoxLayout(pose_box)

        self.pose_list = qtwidgets.QListWidget()
        self.pose_list.setMinimumHeight(120)
        self.pose_list.setToolTip('Each pose is a key and the value it should produce.')
        pose_layout.addWidget(self.pose_list)

        value_row = qtwidgets.QHBoxLayout()
        value_row.addWidget(qtwidgets.QLabel('Value'))
        self.value_field = qtwidgets.QLineEdit()
        self.value_field.setPlaceholderText('1.0, 0.0, 0.5')
        self.value_field.setToolTip(
            'What the output should be at this pose, one number per dimension. '
            'The key is read off the rig as it stands, so put it where you want it first.')
        value_row.addWidget(self.value_field, 1)
        pose_layout.addLayout(value_row)

        add = qtwidgets.QPushButton('Add Pose From Current')
        add.setMinimumHeight(30)
        add.setToolTip('Records the key the rig is in right now, with the value above.')
        add.clicked.connect(self._add_pose)
        pose_layout.addWidget(add)

        pose_buttons = qtwidgets.QHBoxLayout()
        toggle = qtwidgets.QPushButton('Toggle Selected')
        toggle.setToolTip('Turn a pose off without losing it.')
        toggle.clicked.connect(self._toggle_pose)
        delete = qtwidgets.QPushButton('Delete Selected')
        delete.clicked.connect(self._remove_pose)
        pose_buttons.addWidget(toggle)
        pose_buttons.addWidget(delete)
        pose_layout.addLayout(pose_buttons)
        layout.addWidget(pose_box)

        # --- settings --------------------------------------------------------- #
        settings = qtwidgets.QGroupBox('Interpolation')
        form = qtwidgets.QFormLayout(settings)

        self.distance = qtwidgets.QComboBox()
        self.distance.addItems(['Euclidean', 'Angular', 'P-Norm (legacy)'])
        self.distance.setToolTip(
            'Euclidean is straight-line distance. Angular is the angle between keys, for '
            'direction keys like an aim vector where length means nothing. P-Norm is what '
            'the old tool called Euclidean and was not - kept so an old setup can be '
            'reproduced.')
        form.addRow('Distance', self.distance)

        self.kernel = qtwidgets.QComboBox()
        self.kernel.addItems(['Linear', 'Gaussian', 'Multiquadric', 'Inverse Quadratic',
                              'Inverse Multiquadric', 'Cubic', 'Thin Plate'])
        self.kernel.setCurrentIndex(1)
        form.addRow('Kernel', self.kernel)

        self.scale = qtwidgets.QDoubleSpinBox()
        self.scale.setRange(0.001, 100.0)
        self.scale.setSingleStep(0.1)
        self.scale.setDecimals(3)
        self.scale.setValue(1.0)
        self.scale.setToolTip('How far a pose\'s influence reaches.')
        form.addRow('Falloff scale', self.scale)

        self.normalise = qtwidgets.QCheckBox('Scale relative to how far apart the poses are')
        self.normalise.setChecked(True)
        self.normalise.setToolTip(
            'Keeps the falloff meaning the same thing whether the keys are centimetres, '
            'radians or weights.')
        form.addRow('', self.normalise)

        self.regularisation = qtwidgets.QDoubleSpinBox()
        self.regularisation.setRange(0.0, 1.0)
        self.regularisation.setSingleStep(0.001)
        self.regularisation.setDecimals(4)
        self.regularisation.setToolTip(
            '0 passes exactly through every pose. Raise it if two poses sit on the same '
            'key, or if the result is jumpy between them.')
        form.addRow('Regularization', self.regularisation)

        self.weights_sum_to_one = qtwidgets.QCheckBox('Make the outputs sum to one')
        self.weights_sum_to_one.setToolTip(
            'For blendshape weights: nothing negative, adding up to 1. The node calls '
            'this blendShapeMode.')
        form.addRow('', self.weights_sum_to_one)
        layout.addWidget(settings)

        layout.addStretch()

        sample = qtwidgets.QPushButton('Build Sample Scene')
        sample.setToolTip('Two setups in an empty scene: an aim vector driving a colour, '
                          'and a joint angle driving blendshape weights.')
        sample.clicked.connect(self._build_sample)
        layout.addWidget(sample)

        self.status = qtwidgets.QLabel('')
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(36)
        self.status.setAlignment(qtcore.Qt.AlignTop)
        layout.addWidget(self.status)

    # --- driving a live solver ----------------------------------------------- #

    def _settings(self):
        """
        The widgets that map straight onto node attributes.

        :return: ``(widget, attribute name)`` pairs.
        :rtype: tuple
        """

        return ((self.distance, 'distanceMode'),
                (self.kernel, 'rbfMode'),
                (self.scale, 'scale'),
                (self.normalise, 'normalize'),
                (self.regularisation, 'regularization'),
                (self.weights_sum_to_one, 'blendShapeMode'))

    @staticmethod
    def _widget_value(widget):
        """
        :return: What the widget is set to, in the type the attribute wants.
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
        """

        blocked = widget.blockSignals(True)
        try:
            if isinstance(widget, qtwidgets.QComboBox):
                widget.setCurrentIndex(int(value))
            elif isinstance(widget, qtwidgets.QCheckBox):
                widget.setChecked(bool(value))
            else:
                widget.setValue(float(value))
        finally:
            widget.blockSignals(blocked)

    def _connect_live_editing(self):
        """
        Make every setting drive the chosen solver as soon as it changes.

        Without this the settings would only apply to the next solver made, and
        the window would quietly disagree with the node it is pointed at.
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
        Send one setting to the chosen solver, if there is one.
        """

        if not self._solver or not cmds.objExists(self._solver):
            return
        try:
            cmds.setAttr('{}.{}'.format(self._solver, attribute),
                         self._widget_value(widget))
        except Exception as exc:
            self._say('Could not set {}: {}'.format(attribute, exc), ok=False)

    def _pull(self):
        """
        Read the chosen solver's settings back into the window.
        """

        if not self._solver or not cmds.objExists(self._solver):
            return
        for widget, attribute in self._settings():
            try:
                self._set_widget_value(
                    widget, cmds.getAttr('{}.{}'.format(self._solver, attribute)))
            except Exception:
                logger.debug('RBF Solver: could not read %s.', attribute, exc_info=True)

    # --- helpers --------------------------------------------------------------- #

    def _say(self, message, ok=True):
        """
        Put a line under the window.
        """

        self.status.setStyleSheet('color: #cccccc;' if ok else 'color: #e06c5a;')
        self.status.setText(message)
        (logger.info if ok else logger.warning)('RBF Solver: %s', message)

    def _handle(self, response):
        """
        Show a response and say whether it worked.
        """

        self._say(response['message'], ok=response['ok'])
        return response['ok']

    def _check_plugin(self):
        """
        Load the plug-in, and say so plainly if it will not come up.
        """

        available, reason = rbfsolver_api.plugin_is_available()
        if available:
            self._say('Ready. Make a solver, or pick one from the list.')
            return
        self._say(reason, ok=False)

    def _needs_solver(self):
        """
        :return: True when there is a solver to act on.
        :rtype: bool
        """

        if self._solver and cmds.objExists(self._solver):
            return True
        self._say('Pick a solver first.', ok=False)
        return False

    @staticmethod
    def _selected_plugs():
        """
        The attributes selected in the Channel Box, in order.

        :return: Plug names.
        :rtype: list
        """

        nodes = cmds.ls(selection=True, long=False) or []
        attributes = cmds.channelBox('mainChannelBox', q=True,
                                     selectedMainAttributes=True) or []
        return ['{}.{}'.format(node, attribute)
                for node in nodes for attribute in attributes]

    # --- actions ------------------------------------------------------------------ #

    def _create(self):
        """
        Make a solver with the settings as they stand.
        """

        response = rbfsolver_api.create_solver(
            distance=self.distance.currentIndex(),
            kernel=self.kernel.currentIndex(),
            scale=self.scale.value(),
            normalise=self.normalise.isChecked(),
            regularisation=self.regularisation.value(),
            weights_sum_to_one=self.weights_sum_to_one.isChecked())
        if self._handle(response):
            self._refresh_solvers(select=str(response['result']))

    def _refresh_solvers(self, select=None):
        """
        Re-read the scene into the solver list.

        :param str select: Choose this one afterwards, if it is there.
        """

        blocked = self.solver_list.blockSignals(True)
        try:
            self.solver_list.clear()
            for node in rbfsolver_api.find_solvers():
                self.solver_list.addItem(str(node))
        finally:
            self.solver_list.blockSignals(blocked)

        if select:
            index = self.solver_list.findText(select)
            if index >= 0:
                self.solver_list.setCurrentIndex(index)
        self._solver_chosen(self.solver_list.currentIndex())

    def _solver_chosen(self, index):
        """
        :param int index: The row now chosen, or -1.
        """

        self._solver = self.solver_list.itemText(index) if index >= 0 else None
        if self._solver and not cmds.objExists(self._solver):
            self._solver = None
        self._pull()
        self._refresh_poses()

    def _connect_input(self):
        """
        Wire the selected channels in as the key.
        """

        if not self._needs_solver():
            return
        plugs = self._selected_plugs()
        if not plugs:
            self._say('Select the driving attributes in the Channel Box first.', ok=False)
            return
        self._handle(rbfsolver_api.connect_input(self._solver, plugs))

    def _connect_output(self):
        """
        Wire the selected channels in as the value.
        """

        if not self._needs_solver():
            return
        plugs = self._selected_plugs()
        if not plugs:
            self._say('Select the attributes to drive in the Channel Box first.', ok=False)
            return
        self._handle(rbfsolver_api.connect_output(self._solver, plugs))

    def _refresh_poses(self):
        """
        Re-read the chosen solver's poses into the list.
        """

        self.pose_list.clear()
        if not self._solver or not cmds.objExists(self._solver):
            return
        response = rbfsolver_api.list_poses(self._solver)
        if not response['ok']:
            self._handle(response)
            return
        for row in response['result']:
            label = '{}{}   key {}   value {}'.format(
                row['index'], '' if row['enabled'] else '  (off)',
                [round(v, 3) for v in row['key']],
                [round(v, 3) for v in row['value']])
            item = qtwidgets.QListWidgetItem(label)
            item.setData(qtcore.Qt.UserRole, row['index'])
            self.pose_list.addItem(item)

    def _chosen_pose(self):
        """
        :return: The selected pose's index, or None.
        """

        item = self.pose_list.currentItem()
        return None if item is None else item.data(qtcore.Qt.UserRole)

    def _add_pose(self):
        """
        Record the current rig position, with the value typed above.
        """

        if not self._needs_solver():
            return
        text = self.value_field.text().strip()
        if not text:
            self._say('Type the value this pose should produce, one number per dimension.',
                      ok=False)
            return
        try:
            value = [float(part) for part in text.replace(',', ' ').split()]
        except ValueError:
            self._say('The value should be numbers separated by commas or spaces.',
                      ok=False)
            return

        if self._handle(rbfsolver_api.add_pose(self._solver, value=value)):
            self._refresh_poses()

    def _toggle_pose(self):
        """
        Turn the selected pose on or off.
        """

        index = self._chosen_pose()
        if not self._needs_solver() or index is None:
            self._say('Pick a pose from the list first.', ok=False)
            return
        current = cmds.getAttr('{}.poses[{}].state'.format(self._solver, index))
        if self._handle(rbfsolver_api.set_pose_enabled(self._solver, index, not current)):
            self._refresh_poses()

    def _remove_pose(self):
        """
        Delete the selected pose.
        """

        index = self._chosen_pose()
        if not self._needs_solver() or index is None:
            self._say('Pick a pose from the list first.', ok=False)
            return
        if self._handle(rbfsolver_api.remove_pose(self._solver, index)):
            self._refresh_poses()


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

        if cmds.objExists('setup1_aim_to_colour'):
            answer = qtwidgets.QMessageBox.question(
                self, 'RBF Solver',
                'This scene already has a sample in it. Build another one?',
                qtwidgets.QMessageBox.Yes | qtwidgets.QMessageBox.No)
            if answer != qtwidgets.QMessageBox.Yes:
                self._say('Left the scene alone.')
                return

        try:
            made = build_sample.build()
        except Exception as exc:
            self._say('The sample failed: {}'.format(exc), ok=False)
            logger.warning('RBF Solver sample failed.', exc_info=True)
            return

        # The sample makes solvers, so the list is out of date the moment it
        # finishes.
        self._refresh_solvers()
        self._say('Built {}. Rotate either control and watch what it drives.'
                  .format(', '.join(made)))


def open_tool(*args, **kwargs):
    """
    Open the RBF Solver window. This is what the Toolbox button calls.

    :return: The window.
    :rtype: RBFSolverUI
    """

    return RBFSolverUI()
