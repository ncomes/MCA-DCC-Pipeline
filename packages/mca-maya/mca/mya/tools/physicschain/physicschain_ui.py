"""
Physics Chain - layer secondary motion onto a rig component that already exists.

A physics chain is not a component of its own. The pony tail is already an
FKComponent with flags an animator keys; this layers lag and overshoot on top of
that. The animator keeps their flags, and a weight of 0 gives back exactly what
they animated.

The window is a thin shell over :mod:`physicschain_api`. Every button calls one
API function and shows the ``message`` it gets back, so what the UI reports and
what a script gets are the same sentence.

**Where the knobs really live.** Once a chain exists, every setting is mirrored
onto the component's root flag as a keyable channel. That is the interface an
animator should use - they select the control they were already holding and tune
it in the channel box. This window is for adding, blending, baking and removing:
the things that are not one attribute.

:Requires: the mcaPhysicsChain plug-in, which the window loads for you.
"""

# software specific imports
import maya.cmds as cmds

# Qt imports
from mca.common.pyqt.pygui import qtwidgets, qtcore

# MCA python imports
from mca.common import log
from mca.mya.pyqt import mayawindows
from mca.mya.tools.physicschain import physicschain_api

logger = log.MCA_LOGGER


class PhysicsChainUI(mayawindows.MCAMayaWindow):
    """
    The Physics Chain window.
    """

    VERSION = '1.0.0'

    def __init__(self, parent=None, **kwargs):
        super().__init__(title='Physics Chain', ui_path=None, show_window=True,
                         version=self.VERSION, **kwargs)

        self._chain = None

        self.setMinimumSize(430, 560)
        self._build_ui()
        self._check_plugin()
        self._refresh()

    # --- construction ------------------------------------------------------- #

    def _build_ui(self):
        """
        Lay the window out.
        """

        layout = self.main_layout
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # --- adding ---------------------------------------------------------- #
        add_box = qtwidgets.QGroupBox('Add physics to a component')
        add_form = qtwidgets.QFormLayout(add_box)

        self.preset = qtwidgets.QComboBox()
        self.preset.addItems(sorted(physicschain_api.PRESETS))
        index = self.preset.findText(physicschain_api.DEFAULT_PRESET)
        if index >= 0:
            self.preset.setCurrentIndex(index)
        self.preset.setToolTip(
            'Measured starting points. Drag is how far the chain trails the animation, '
            'Springiness how much it carries past the pose, Gravity how far it hangs '
            'towards straight down. All three are scale free, so the same number means '
            'the same thing on a short braid and a long tail.')
        add_form.addRow('Preset', self.preset)

        self.weight = qtwidgets.QDoubleSpinBox()
        self.weight.setRange(0.0, 1.0)
        self.weight.setSingleStep(0.05)
        self.weight.setDecimals(3)
        self.weight.setValue(1.0)
        self.weight.setToolTip(
            '0 is the animation, untouched and exact. 1 is the simulation. Anything '
            'between is a blend, and it is keyable, so physics can be dialled out for '
            'one shot without unpicking anything.')
        add_form.addRow('Weight', self.weight)

        self.pin_root = qtwidgets.QCheckBox('Pin the first joint to the animation')
        self.pin_root.setChecked(True)
        add_form.addRow('', self.pin_root)

        add_button = qtwidgets.QPushButton('Add Physics to Selected Component')
        add_button.setMinimumHeight(32)
        add_button.setToolTip('Select any flag or joint of the component you want to '
                              'layer physics onto.')
        add_button.clicked.connect(self._add)
        add_form.addRow(add_button)
        layout.addWidget(add_box)

        # --- what is already in the scene --------------------------------------- #
        live_box = qtwidgets.QGroupBox('Physics in this scene')
        live_layout = qtwidgets.QVBoxLayout(live_box)

        self.chain_list = qtwidgets.QListWidget()
        self.chain_list.setToolTip('Every physics layer in the open scene.')
        self.chain_list.currentRowChanged.connect(self._chain_chosen)
        self.chain_list.setMinimumHeight(110)
        live_layout.addWidget(self.chain_list)

        buttons = qtwidgets.QHBoxLayout()
        refresh = qtwidgets.QPushButton('Refresh')
        refresh.clicked.connect(self._refresh)
        select = qtwidgets.QPushButton('Select Its Flag')
        select.setToolTip('Select the control that carries the channels, which is where '
                          'an animator should be tuning this.')
        select.clicked.connect(self._select_flag)
        buttons.addWidget(refresh)
        buttons.addWidget(select)
        live_layout.addLayout(buttons)
        layout.addWidget(live_box)

        # --- acting on the chosen one --------------------------------------------- #
        self.actions = qtwidgets.QGroupBox('Selected chain')
        action_layout = qtwidgets.QVBoxLayout(self.actions)

        weight_row = qtwidgets.QHBoxLayout()
        weight_row.addWidget(qtwidgets.QLabel('Weight'))
        self.live_weight = qtwidgets.QDoubleSpinBox()
        self.live_weight.setRange(0.0, 1.0)
        self.live_weight.setSingleStep(0.05)
        self.live_weight.setDecimals(3)
        self.live_weight.valueChanged.connect(self._set_weight)
        weight_row.addWidget(self.live_weight)
        action_layout.addLayout(weight_row)

        preset_row = qtwidgets.QHBoxLayout()
        self.live_preset = qtwidgets.QComboBox()
        self.live_preset.addItems(sorted(physicschain_api.PRESETS))
        apply_preset = qtwidgets.QPushButton('Apply Preset')
        apply_preset.clicked.connect(self._apply_preset)
        preset_row.addWidget(self.live_preset)
        preset_row.addWidget(apply_preset)
        action_layout.addLayout(preset_row)

        finish_row = qtwidgets.QHBoxLayout()
        bake = qtwidgets.QPushButton('Bake')
        bake.setToolTip('Bake the simulation onto the component\'s flags over the '
                        'playback range, then take the physics off. The result is plain '
                        'keys an animator can edit.')
        bake.clicked.connect(self._bake)
        remove = qtwidgets.QPushButton('Remove')
        remove.setToolTip('Take the physics back off. Nothing was destroyed on the way '
                          'in, so the component is left as it was.')
        remove.clicked.connect(self._remove)
        finish_row.addWidget(bake)
        finish_row.addWidget(remove)
        action_layout.addLayout(finish_row)

        self.actions.setEnabled(False)
        layout.addWidget(self.actions)

        layout.addStretch()

        self.status = qtwidgets.QLabel('')
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(36)
        self.status.setAlignment(qtcore.Qt.AlignTop)
        layout.addWidget(self.status)

    # --- helpers --------------------------------------------------------------- #

    def _say(self, message, ok=True):
        """
        Put a line under the window.

        :param str message: What happened.
        :param bool ok: False colours it as a problem.
        """

        self.status.setStyleSheet('color: #cccccc;' if ok else 'color: #e06c5a;')
        self.status.setText(message)
        (logger.info if ok else logger.warning)('Physics Chain: %s', message)

    def _handle(self, response):
        """
        Show a response and say whether it worked.

        :param dict response: An ``ok/result/message`` response.
        :return: True when it worked.
        :rtype: bool
        """

        self._say(response['message'], ok=response['ok'])
        return response['ok']

    def _check_plugin(self):
        """
        Load the plug-in, and say so plainly if it will not come up.
        """

        available, reason = physicschain_api.plugin_is_available()
        if available:
            self._say('Ready. Select a component and add physics.')
            return
        self._say(reason, ok=False)

    # --- actions ------------------------------------------------------------------ #

    def _add(self):
        """
        Layer physics onto whatever component is selected.
        """

        selection = cmds.ls(selection=True) or []
        if not selection:
            self._say('Select a flag or joint on the component you want physics on.',
                      ok=False)
            return

        # **A flag is not a network node, and this used to hand one straight to
        # FRAGNode().** The button's own instruction says "select a flag or joint", and
        # FRAGNode() only accepts the component's network node, so following the
        # instruction raised `Node hul:f_fnt_cloth_l_01 is not a network node and can't be
        # a FRAG Node` - and the window reported that as "not part of a FRAG rig
        # component", which is the opposite of true. A flag knows its component through its
        # message plug; `get_frag_parent` is what walks it.
        try:
            import pymel.core as pm
            from mca.mya.rigging import frag
            picked = pm.PyNode(selection[0])
            if picked.nodeType() == 'network':
                # They picked the component node itself. get_frag_parent would answer its
                # PARENT - the rig - so ask FRAGNode directly.
                component = frag.FRAGNode(picked)
            else:
                component = frag.get_frag_parent(picked)
        except Exception as exc:
            self._say('Could not work out which component {} belongs to: {}'
                      .format(selection[0], exc), ok=False)
            return

        if component is None:
            self._say('{} is not part of a FRAG rig component, so there is nothing to put '
                      'physics on. Select a flag or joint that belongs to one.'
                      .format(selection[0]), ok=False)
            return

        response = physicschain_api.add_physics(
            component,
            weight=self.weight.value(),
            preset=self.preset.currentText(),
            pin_root=self.pin_root.isChecked())
        if self._handle(response):
            self._refresh()

    def _refresh(self):
        """
        Re-read the scene into the list.
        """

        self.chain_list.clear()
        self._chain = None
        self.actions.setEnabled(False)

        response = physicschain_api.list_physics_chains()
        if not response['ok']:
            self._handle(response)
            return

        for row in response['result'] or []:
            label = '{}    weight {:.2f}    {} levels'.format(
                row['component'] or row['node'], row['weight'], row['levels'])
            item = qtwidgets.QListWidgetItem(label)
            # Keep the node name on the item rather than parsing it back out of
            # the label, which would break the moment the label changes.
            item.setData(qtcore.Qt.UserRole, row['node'])
            item.setData(qtcore.Qt.UserRole + 1, row['flag'])
            self.chain_list.addItem(item)

        if self.chain_list.count() == 0:
            self._say('No physics chains in this scene yet. Select a flag or joint on the '
                      'component you want physics on, then press Add - everything below the '
                      'list stays greyed out until there is a chain to act on.')
        else:
            self._say(response['message'])

    def _current(self):
        """
        :return: The selected chain's node name, or None.
        :rtype: str
        """

        item = self.chain_list.currentItem()
        if item is None:
            return None
        node = item.data(qtcore.Qt.UserRole)
        if node and cmds.objExists(node):
            return node
        self._say('That chain is gone. Refreshing.', ok=False)
        self._refresh()
        return None

    def _chain_chosen(self, row):
        """
        :param int row: The row now selected, or -1.
        """

        if row < 0:
            self._chain = None
            self.actions.setEnabled(False)
            return
        self._chain = self._current()
        self.actions.setEnabled(bool(self._chain))
        if not self._chain:
            return
        blocked = self.live_weight.blockSignals(True)
        try:
            plug = '{}.physicsWeight'.format(self._chain)
            if cmds.objExists(plug):
                self.live_weight.setValue(cmds.getAttr(plug))
        finally:
            self.live_weight.blockSignals(blocked)

    def _select_flag(self):
        """
        Select the control carrying the channels.
        """

        item = self.chain_list.currentItem()
        if item is None:
            if self.chain_list.count() == 0:
                self._say('There are no physics chains in this scene yet, which is why '
                          'everything below the list is greyed out. Select a flag or joint '
                          'on the component you want physics on and press Add.', ok=False)
            else:
                self._say('Pick a chain from the list first.', ok=False)
            return
        flag = item.data(qtcore.Qt.UserRole + 1)
        if not flag or not cmds.objExists(flag):
            self._say('That chain has no flag recorded.', ok=False)
            return
        cmds.select(flag)
        self._say('Selected {}. The channels are in the channel box.'.format(flag))

    def _set_weight(self, value):
        """
        :param float value: New blend, 0 animation to 1 simulation.
        """

        if self._chain:
            self._handle(physicschain_api.set_weight(self._chain, value))

    def _apply_preset(self):
        """
        Drop a measured set of settings onto the chosen chain.
        """

        if self._chain:
            self._handle(physicschain_api.apply_preset(self._chain,
                                                       self.live_preset.currentText()))

    def _bake(self):
        """
        Bake the simulation to keys, then take the physics off.
        """

        if not self._chain:
            return
        answer = qtwidgets.QMessageBox.question(
            self, 'Physics Chain',
            'Bake this chain onto the flags over the playback range, and remove the '
            'physics afterwards?',
            qtwidgets.QMessageBox.Yes | qtwidgets.QMessageBox.No)
        if answer != qtwidgets.QMessageBox.Yes:
            self._say('Left it alone.')
            return
        if self._handle(physicschain_api.bake_physics(self._chain)):
            self._refresh()

    def _remove(self):
        """
        Take the physics back off.
        """

        if self._chain and self._handle(physicschain_api.remove_physics(self._chain)):
            self._refresh()


def open_tool(*args, **kwargs):
    """
    Open the Physics Chain window. This is what the Toolbox button calls.

    :return: The window.
    :rtype: PhysicsChainUI
    """

    return PhysicsChainUI()
