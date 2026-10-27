"""
RBF Retargeter - carry meshes across from one shape of a mesh to another.

Describe a deformation by giving the same mesh twice - once as it is now, once
as you want it - and everything sitting on it comes along: correctives, a
garment, a prop.

The window is a thin shell over :mod:`rbfretargeter_api`. Every button calls one
API function and shows the ``message`` it gets back, so what the UI reports and
what a script gets are the same sentence.

Why the fields are named the way they are
------------------------------------------
They used to be Source, Target and Shapes, which is what the tool this replaces
called them, and people got them the wrong way round every time - including the
person who asked for this window. The words do not say which way the deformation
runs, and "Target" reads like "the thing I want changed", which is the exact
opposite of what it is.

So: **Deform from** and **Deform to** are the same mesh twice and must share
topology; **Meshes to deform** is everything riding along, and needs no matching
topology at all. The two counts sit next to the fields and turn red when they
disagree, there is a swap button between them, and the note under the list says
the topology rule out loud.

What this window adds over calling the command
-----------------------------------------------
It says what a solve will cost BEFORE you start it. The cost is cubic in the
number of solver vertices, so the difference between a good pick and a careless
one is the difference between two seconds and ten minutes - and the tool this
replaces printed that number to stdout, which on Windows goes to a console
nobody has open.

And **Deform to** takes a list. One garment onto five body variants is one press,
not five, and the results come back named ``<mesh>_<variant>``.

:Requires: the mcaRBFRetargeter plug-in, which the window loads for you.
"""

# software specific imports
import maya.cmds as cmds

# Qt imports
from mca.common.pyqt.pygui import qtwidgets, qtcore

# MCA python imports
from mca.common import log
from mca.mya.pyqt import mayawindows
from mca.mya.tools.rbfretargeter import rbfretargeter_api

logger = log.MCA_LOGGER

#: Shown next to a field whose vertex count disagrees with the other one.
MISMATCH_COLOUR = '#e06c5a'
QUIET_COLOUR = '#999999'


class RBFRetargeterUI(mayawindows.MCAMayaWindow):
    """
    The RBF Retargeter window.
    """

    VERSION = '1.7.0'

    def __init__(self, parent=None, **kwargs):
        super().__init__(title='RBF Retargeter', ui_path=None, show_window=True,
                         version=self.VERSION, **kwargs)

        #: Source vertex indices to solve on. Empty means every vertex.
        self._solver_vertices = []
        #: The count Auto-pick used, when the current set came from it. A
        #: multi-target run re-picks per target, which is measurably better, and
        #: it can only do that if it knows the set was not hand-chosen.
        self._auto_picked = None
        self._cancel_pick = False

        self.setMinimumSize(470, 720)
        self._build_ui()
        self._check_plugin()
        self._refresh_counts()

    # --- construction ------------------------------------------------------- #

    def _build_ui(self):
        """
        Lay the window out.
        """

        layout = self.main_layout
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # --- the deformation --------------------------------------------------- #
        deformation = qtwidgets.QGroupBox('The deformation')
        grid = qtwidgets.QGridLayout(deformation)

        grid.addWidget(qtwidgets.QLabel('Deform from'), 0, 0)
        self.from_field = qtwidgets.QLineEdit()
        self.from_field.setPlaceholderText('the mesh everything is fitted to now')
        self.from_field.editingFinished.connect(self._refresh_counts)
        grid.addWidget(self.from_field, 0, 1)
        self.from_count = qtwidgets.QLabel('')
        self.from_count.setMinimumWidth(78)
        grid.addWidget(self.from_count, 0, 2)
        from_pick = qtwidgets.QPushButton('<')
        from_pick.setFixedWidth(26)
        from_pick.setToolTip('Use the selected mesh.')
        from_pick.clicked.connect(self._take_from)
        grid.addWidget(from_pick, 0, 3)

        # A swap, because getting these two the wrong way round is THE mistake
        # this tool invites and retyping both names to fix it is a punishment.
        swap = qtwidgets.QPushButton(u'⇅')
        swap.setFixedWidth(26)
        swap.setToolTip('Swap - put the first "to" mesh in "from" and vice versa.')
        swap.clicked.connect(self._swap)
        grid.addWidget(swap, 1, 3)

        grid.addWidget(qtwidgets.QLabel('Deform to'), 1, 0, qtcore.Qt.AlignTop)
        self.to_list = qtwidgets.QListWidget()
        self.to_list.setSelectionMode(qtwidgets.QAbstractItemView.ExtendedSelection)
        self.to_list.setMaximumHeight(84)
        self.to_list.setToolTip('One solve per mesh here. Each must share the '
                                '"deform from" mesh\'s topology.')
        grid.addWidget(self.to_list, 1, 1)
        self.to_count = qtwidgets.QLabel('')
        grid.addWidget(self.to_count, 1, 2, qtcore.Qt.AlignTop)

        to_buttons = qtwidgets.QHBoxLayout()
        add_to = qtwidgets.QPushButton('Add Selected')
        add_to.clicked.connect(self._add_to)
        remove_to = qtwidgets.QPushButton('Remove')
        remove_to.clicked.connect(lambda: self._remove_rows(self.to_list))
        for button in (add_to, remove_to):
            to_buttons.addWidget(button)
        grid.addLayout(to_buttons, 2, 1, 1, 2)

        self.topology_note = qtwidgets.QLabel('')
        self.topology_note.setWordWrap(True)
        grid.addWidget(self.topology_note, 3, 0, 1, 4)

        layout.addWidget(deformation)

        # --- what rides along ---------------------------------------------------- #
        riders = qtwidgets.QGroupBox('Meshes to deform')
        riders_layout = qtwidgets.QVBoxLayout(riders)
        riders_layout.addWidget(self._note(
            'Anything sitting on the "deform from" mesh - a garment, correctives, a '
            'prop. These do NOT have to share its topology: what the solve builds is '
            'a function of position, so it applies to any mesh in the same space.'))
        self.shape_list = qtwidgets.QListWidget()
        self.shape_list.setSelectionMode(qtwidgets.QAbstractItemView.ExtendedSelection)
        self.shape_list.setMinimumHeight(96)
        riders_layout.addWidget(self.shape_list)

        shape_buttons = qtwidgets.QHBoxLayout()
        add = qtwidgets.QPushButton('Add Selected')
        add.clicked.connect(self._add_shapes)
        remove = qtwidgets.QPushButton('Remove')
        remove.clicked.connect(lambda: self._remove_rows(self.shape_list))
        from_blend = qtwidgets.QPushButton('Add From BlendShape')
        from_blend.setToolTip('Read every live target off the blendShape on the '
                              '"deform from" mesh.')
        from_blend.clicked.connect(self._shapes_from_blendshape)
        for button in (add, remove, from_blend):
            shape_buttons.addWidget(button)
        riders_layout.addLayout(shape_buttons)
        layout.addWidget(riders)

        # --- solver vertices ---------------------------------------------------- #
        solver = qtwidgets.QGroupBox('Solver vertices')
        solver_layout = qtwidgets.QVBoxLayout(solver)
        solver_layout.addWidget(self._note(
            'Vertices on the "deform from" mesh. A few hundred spread over it beats '
            'every vertex: the cost grows as the cube of the count, and a smaller '
            'well-spread set extrapolates better. They do have to span three '
            'dimensions - vertices all in one plane cannot describe motion off that '
            'plane. Nothing set uses every vertex.'))

        self.vertex_label = qtwidgets.QLabel('none set - every vertex will be used')
        solver_layout.addWidget(self.vertex_label)

        # Auto-pick, on its own row and first, because on any real mesh this is
        # the step. A 16,747-vertex body is 300x over the guard, so the tool's
        # own advice - "select a few hundred well-spread vertices" - was work it
        # was asking for and not offering.
        auto_row = qtwidgets.QHBoxLayout()
        auto = qtwidgets.QPushButton('Auto-pick Solver Vertices')
        auto.setToolTip(
            'Picks where the transfer is hardest, not evenly.\n\n'
            'With a "deform to" mesh set, both shapes are known, so the error of any '
            'candidate set can be measured: it fits, sees where it misses, puts the '
            'next points there, and refits. A body does not deform evenly - it is the '
            'chest, shoulders and armpits that move - so an even spread wastes points '
            'on the shins.\n\n'
            'Measured on a 16,747-vertex body: 1,000 points chosen this way beat 2,000 '
            'spread evenly, and cut the worst garment error from 3.2 scene units to '
            '0.6.\n\n'
            'With no "deform to" mesh it falls back to an even spread.')
        auto.clicked.connect(self._auto_pick)
        auto_row.addWidget(auto, 1)
        self.auto_count_field = qtwidgets.QSpinBox()
        self.auto_count_field.setRange(4, 100000)
        self.auto_count_field.setValue(rbfretargeter_api.DEFAULT_SOLVER_POINTS)
        self.auto_count_field.setToolTip(
            'How many to pick. The solve grows as the cube of this, so the pick is\n'
            'where the money goes: 1,000 chosen well beats 2,000 chosen evenly.')
        auto_row.addWidget(self.auto_count_field)
        solver_layout.addLayout(auto_row)

        vertex_buttons = qtwidgets.QHBoxLayout()
        take = qtwidgets.QPushButton('Use Selected Vertices')
        take.clicked.connect(self._take_vertices)
        reselect = qtwidgets.QPushButton('Reselect')
        reselect.setToolTip('Select the vertices currently set, to look at or edit them.')
        reselect.clicked.connect(self._reselect_vertices)
        clear = qtwidgets.QPushButton('Clear')
        clear.clicked.connect(self._clear_vertices)
        for button in (take, reselect, clear):
            vertex_buttons.addWidget(button)
        solver_layout.addLayout(vertex_buttons)
        layout.addWidget(solver)

        # --- settings ------------------------------------------------------------ #
        settings = qtwidgets.QGroupBox('Settings')
        settings_layout = qtwidgets.QGridLayout(settings)

        settings_layout.addWidget(qtwidgets.QLabel('Sphere anchors'), 0, 0)
        self.sphere_field = qtwidgets.QSpinBox()
        self.sphere_field.setRange(0, 5000)
        self.sphere_field.setValue(0)
        self.sphere_field.setToolTip(
            'Extra points spread over the bounding sphere, the "from" mesh\'s paired '
            'to the "to" mesh\'s, so the solve has something outside the mesh to push '
            'against instead of extrapolating at the silhouette. Also the fix for '
            'solver vertices that all lie in one plane. 0 is off.')
        self.sphere_field.valueChanged.connect(self._update_cost)
        settings_layout.addWidget(self.sphere_field, 0, 1)

        settings_layout.addWidget(qtwidgets.QLabel('Regularization'), 1, 0)
        self.regularisation_field = qtwidgets.QDoubleSpinBox()
        self.regularisation_field.setDecimals(6)
        self.regularisation_field.setRange(0.0, 100.0)
        self.regularisation_field.setSingleStep(0.0001)
        self.regularisation_field.setValue(0.0)
        self.regularisation_field.setToolTip(
            'Added to the matrix diagonal. 0 passes exactly through every solver '
            'vertex; a small value trades that for stability and is the way out when '
            'two of them sit on top of each other.')
        settings_layout.addWidget(self.regularisation_field, 1, 1)

        settings_layout.addWidget(qtwidgets.QLabel('Max solver points'), 2, 0)
        self.max_points_field = qtwidgets.QSpinBox()
        self.max_points_field.setRange(0, 1000000)
        self.max_points_field.setValue(rbfretargeter_api.DEFAULT_MAX_SOLVER_POINTS)
        self.max_points_field.setToolTip(
            'Refuse a solve above this many points rather than allocating a matrix '
            'nobody can hold. 0 removes the guard, which is not advised.')
        self.max_points_field.valueChanged.connect(self._update_cost)
        settings_layout.addWidget(self.max_points_field, 2, 1)

        settings_layout.addWidget(qtwidgets.QLabel('Shaders from'), 4, 0)
        self.shader_choice = qtwidgets.QComboBox()
        self.shader_choice.addItem('the mesh it was made from', 'shape')
        self.shader_choice.addItem('the mesh it was deformed to', 'target')
        self.shader_choice.addItem('leave unassigned', 'none')
        self.shader_choice.setToolTip(
            'The command leaves what it makes assigned to nothing at all - not even '
            'initialShadingGroup - so without this a retargeted garment comes out '
            'with no material and renders as nothing. "The mesh it was made from" '
            'keeps the garment\'s own material and is nearly always right; "the mesh '
            'it was deformed to" is for correctives that should look like the head '
            'they now belong to.')
        settings_layout.addWidget(self.shader_choice, 4, 1)

        self.place_box = qtwidgets.QCheckBox('Place each result on the mesh it was '
                                            'deformed to')
        self.place_box.setChecked(True)
        self.place_box.setToolTip(
            'The solve works in object space, so what comes out is the shape change '
            'and nothing else. When the meshes are laid out side by side by their '
            'transforms - how a set of body variants is usually arranged - every '
            'result lands back where the original was, stacked and impossible to '
            'look at. This puts each one where its target is. Turn it off if the '
            'results are going straight into a blendShape on the original.')
        settings_layout.addWidget(self.place_box, 5, 0, 1, 2)

        self.affine_box = qtwidgets.QCheckBox('Reproduce moves, scales and rotations exactly')
        self.affine_box.setChecked(True)
        self.affine_box.setToolTip(
            'Adds the linear polynomial term. On, a "to" mesh that is simply the '
            '"from" mesh moved, scaled or rotated comes back exact; off, the result '
            'drifts between the solver vertices - which is what the tool this replaces '
            'did. Turn it off only to reproduce that behaviour.')
        self.affine_box.stateChanged.connect(self._update_cost)
        settings_layout.addWidget(self.affine_box, 6, 0, 1, 2)

        layout.addWidget(settings)

        # --- cost and go ------------------------------------------------------------ #
        self.cost_label = qtwidgets.QLabel('')
        self.cost_label.setWordWrap(True)
        layout.addWidget(self.cost_label)

        self.retarget_button = qtwidgets.QPushButton('Deform')
        self.retarget_button.setMinimumHeight(30)
        self.retarget_button.clicked.connect(self._retarget)
        layout.addWidget(self.retarget_button)

        layout.addStretch(1)

        # **The bar tracks the PICK, not the solve.** Measured on a 16,747-vertex body:
        # choosing 1,000 solver vertices takes 7.49 s and the C++ solve that follows takes
        # 0.18 s, so 98% of the wait is the part written in Python - which is also the only
        # part that can report on itself. A bar driven off the solve would sit at zero for
        # the whole wait and then flick to full.
        self.progress = qtwidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(True)
        self.progress.setFormat('%p%  -  %v of %m solver vertices chosen')
        self.progress.hide()
        layout.addWidget(self.progress)

        self.status = qtwidgets.QLabel('')
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(36)
        self.status.setAlignment(qtcore.Qt.AlignTop)
        layout.addWidget(self.status)

    @staticmethod
    def _note(text):
        """
        :param str text: What to say.
        :return: A wrapped, quiet label.
        :rtype: qtwidgets.QLabel
        """

        label = qtwidgets.QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet('color: {};'.format(QUIET_COLOUR))
        return label

    # --- saying things -------------------------------------------------------- #

    def _say(self, message, ok=True):
        """
        Put a line under the window.
        """

        self.status.setStyleSheet('color: #cccccc;' if ok
                                  else 'color: {};'.format(MISMATCH_COLOUR))
        self.status.setText(message)
        (logger.info if ok else logger.warning)('RBF Retargeter: %s', message)

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

        available, reason = rbfretargeter_api.plugin_is_available()
        if available:
            self._say('Ready. Set the two meshes that describe the deformation, then '
                      'add what should come along.')
            return
        self._say(reason, ok=False)

    # --- reading the scene ------------------------------------------------------- #

    @staticmethod
    def _selected_meshes():
        """
        :return: The selected transforms that have a mesh under them.
        :rtype: list(str)
        """

        found = []
        for node in (cmds.ls(selection=True, long=False, objectsOnly=True) or []):
            shapes = cmds.listRelatives(node, shapes=True, noIntermediate=True,
                                        type='mesh') or []
            if shapes or cmds.objectType(node, isType='mesh'):
                found.append(node)
        return found

    @staticmethod
    def _vertex_count(name):
        """
        :param str name: A transform or mesh name.
        :return: Its vertex count, or None if there is no mesh there.
        :rtype: int or None
        """

        if not name or not cmds.objExists(name):
            return None
        shapes = cmds.listRelatives(name, shapes=True, noIntermediate=True,
                                    type='mesh') or []
        if not shapes and cmds.objectType(name, isType='mesh'):
            shapes = [name]
        if not shapes:
            return None
        return cmds.polyEvaluate(shapes[0], vertex=True)

    def _rows(self, widget):
        """
        :param widget: A list widget.
        :return: Its contents, top to bottom.
        :rtype: list(str)
        """

        return [widget.item(row).text() for row in range(widget.count())]

    # --- picking things ---------------------------------------------------------- #

    def _take_from(self):
        """
        Put the selected mesh in the "deform from" field.
        """

        meshes = self._selected_meshes()
        if not meshes:
            self._say('Select a polygon mesh first.', ok=False)
            return
        self.from_field.setText(meshes[0])
        self._say('Deforming from {}.'.format(meshes[0]) +
                  ('  ({} meshes were selected.)'.format(len(meshes))
                   if len(meshes) > 1 else ''))
        self._refresh_counts()

    def _add_to(self):
        """
        Add the selected meshes to the "deform to" list.
        """

        added = self._add_rows(self.to_list, self._selected_meshes())
        if not added:
            self._say('Nothing to add - select the mesh or meshes to deform to.',
                      ok=False)
            return
        self._say('Deforming to {} mesh(es).'.format(self.to_list.count()))
        self._refresh_counts()

    def _add_shapes(self):
        """
        Add the selected meshes to the "meshes to deform" list.
        """

        added = self._add_rows(self.shape_list, self._selected_meshes())
        if not added:
            self._say('Nothing to add - select what should come along.', ok=False)
            return
        self._say('Carrying {} mesh(es) across.'.format(self.shape_list.count()))

    @staticmethod
    def _add_rows(widget, names):
        """
        :param widget: The list to add to.
        :param list names: What to add, skipping what is already there.
        :return: How many were added.
        :rtype: int
        """

        existing = {widget.item(row).text() for row in range(widget.count())}
        added = 0
        for name in names:
            if name in existing:
                continue
            widget.addItem(name)
            added += 1
        return added

    def _remove_rows(self, widget):
        """
        Take the highlighted rows out of a list.
        """

        for item in widget.selectedItems():
            widget.takeItem(widget.row(item))
        self._refresh_counts()

    def _swap(self):
        """
        Put the first "deform to" mesh in "deform from" and vice versa.

        Getting these two the wrong way round is the mistake this tool invites,
        and without this the fix is retyping both names.
        """

        first = self._rows(self.to_list)
        if not first:
            self._say('Nothing to swap with - the "deform to" list is empty.', ok=False)
            return
        was_from = self.from_field.text().strip()
        self.from_field.setText(first[0])
        self.to_list.takeItem(0)
        if was_from:
            self.to_list.insertItem(0, was_from)
        self._say('Swapped. Deforming from {} now.'.format(first[0]))
        self._refresh_counts()

    def _shapes_from_blendshape(self):
        """
        Fill the shape list from the blendShape on the "deform from" mesh.
        """

        source = self.from_field.text().strip()
        if not source:
            self._say('Set a "deform from" mesh first.', ok=False)
            return
        if not cmds.objExists(source):
            self._say('There is nothing called "{}" in this scene.'.format(source),
                      ok=False)
            return

        # Read it through the api rather than walking the node here. The window
        # used to do its own walk and read inputTargetItem[6000] only, which is
        # the full target and nothing else - so a rig's in-betweens were dropped
        # on the way in, silently, and the list looked complete.
        reading = rbfretargeter_api.read_blendshape(source)
        if not self._handle(reading):
            return

        found, in_betweens = [], 0
        for weight in reading['result']['weights']:
            for entry in weight['targets']:
                transform = cmds.listRelatives(entry['mesh'], parent=True)
                found.append(transform[0] if transform else entry['mesh'])
                if entry['weight'] != 1.0:
                    in_betweens += 1

        if not found:
            self._say('{} has no live target meshes to read - its targets were deleted '
                      'after it was made.'.format(reading['result']['blendshape']),
                      ok=False)
            return

        self.shape_list.clear()
        for name in found:
            self.shape_list.addItem(name)
        self._say('Read {} target(s) off {}{}.  To rebuild the whole node on the '
                  'target instead - channel names, in-betweens and all - use '
                  'retarget_blendshape.'
                  .format(len(found), reading['result']['blendshape'],
                          ', {} of them in-betweens'.format(in_betweens)
                          if in_betweens else ''))

    # --- solver vertices -------------------------------------------------------- #

    def _take_vertices(self):
        """
        Remember the selected vertices on the "deform from" mesh.
        """

        source = self.from_field.text().strip()
        picked = rbfretargeter_api.selected_vertex_indices(
            source if source and cmds.objExists(source) else None)
        if not picked:
            self._say('Select some vertices on the "deform from" mesh first.', ok=False)
            return
        self._solver_vertices = picked
        self._auto_picked = None          # hand-chosen; use them as given
        self._say('Solving on {} vertices.'.format(len(picked)))
        self._update_cost()

    def _progress_hook(self, label):
        """
        Build a callback for the api's picking loop.

        Repainting from inside the loop needs ``processEvents`` because the pick runs on
        Maya's main thread - the same thread Qt draws on - so without it the window simply
        stops redrawing and looks hung, which is the whole complaint this is answering.

        :param str label: What to show beside the bar.
        :return: A function fit for ``suggest_solver_vertices(progress=...)``.
        """

        self.progress.setValue(0)
        self.progress.show()
        self._cancel_pick = False

        def report(picked, wanted, worst):
            self.progress.setMaximum(max(1, int(wanted)))
            self.progress.setValue(int(picked))
            self.status.setText('{} - {:,} of {:,} vertices, worst error {:.3f} so far.'
                                .format(label, picked, wanted, worst))
            application = qtwidgets.QApplication.instance()
            if application is not None:
                application.processEvents()
            return not self._cancel_pick

        return report

    def _end_progress(self):
        """Put the bar away again."""

        self.progress.setValue(self.progress.maximum())
        self.progress.hide()

    def _auto_pick(self):
        """
        Have the api choose a well-spread set, and show them.
        """

        source = self.from_field.text().strip()
        if not source or not cmds.objExists(source):
            self._say('Set a "deform from" mesh first.', ok=False)
            return

        # Hand it the first "deform to" mesh. With one, the pick is error-driven
        # and much better; without one it can only spread points evenly.
        targets = self._rows(self.to_list)
        target = next((name for name in targets if cmds.objExists(name)), None)
        if target is None:
            self._say('No "deform to" mesh set, so this can only spread points '
                      'evenly. Add one for a considerably better pick.', ok=False)

        self.retarget_button.setEnabled(False)
        try:
            response = rbfretargeter_api.suggest_solver_vertices(
                source, count=self.auto_count_field.value(), target=target,
                select=True, affine=self.affine_box.isChecked(),
                progress=self._progress_hook('Choosing solver vertices'))
        finally:
            self._end_progress()
            self.retarget_button.setEnabled(True)
        if not self._handle(response):
            return
        self._solver_vertices = list(response['result'])
        self._auto_picked = self.auto_count_field.value() if target else None
        self._update_cost()

    def _reselect_vertices(self):
        """
        Select the vertices currently set, so they can be looked at or edited.
        """

        source = self.from_field.text().strip()
        if not self._solver_vertices or not source or not cmds.objExists(source):
            self._say('No solver vertices are set.', ok=False)
            return
        cmds.select(['{}.vtx[{}]'.format(source, index)
                     for index in self._solver_vertices], replace=True)
        self._say('Selected {} vertices.'.format(len(self._solver_vertices)))

    def _clear_vertices(self):
        """
        Go back to solving on every vertex.
        """

        self._solver_vertices = []
        self._auto_picked = None
        self._say('Cleared - every vertex will be used.')
        self._update_cost()

    # --- counts and cost ---------------------------------------------------------- #

    def _refresh_counts(self):
        """
        Show both vertex counts, and say plainly when they disagree.

        This is the whole point of the rename: the rule is that these two meshes
        are the SAME mesh in two shapes, and the fastest way to say so is to put
        the two numbers side by side and colour them when they differ.
        """

        source = self.from_field.text().strip()
        source_count = self._vertex_count(source)
        targets = self._rows(self.to_list)
        target_counts = [self._vertex_count(name) for name in targets]

        self.from_count.setText('' if source_count is None
                                else '{:,} verts'.format(source_count))

        known = [count for count in target_counts if count is not None]
        if not known:
            self.to_count.setText('')
        elif len(set(known)) == 1:
            self.to_count.setText('{:,} verts'.format(known[0]))
        else:
            self.to_count.setText('mixed')

        wrong = [name for name, count in zip(targets, target_counts)
                 if count is not None and source_count is not None
                 and count != source_count]
        bad = bool(wrong)
        colour = MISMATCH_COLOUR if bad else QUIET_COLOUR
        for label in (self.from_count, self.to_count):
            label.setStyleSheet('color: {};'.format(colour))

        if bad:
            self.topology_note.setStyleSheet('color: {};'.format(MISMATCH_COLOUR))
            self.topology_note.setText(
                '{} does not share {}\'s topology, so it cannot describe a deformation '
                'of it. If it is something worn on {}, it belongs in "Meshes to '
                'deform" below.'.format(wrong[0], source or 'the "from" mesh',
                                        source or 'it'))
        else:
            self.topology_note.setStyleSheet('color: {};'.format(QUIET_COLOUR))
            self.topology_note.setText(
                'The same mesh in two shapes - these must share topology.')
        self._update_cost()

    def _update_cost(self):
        """
        Say what the solve will cost, before anyone waits for it.
        """

        if self._solver_vertices:
            self.vertex_label.setText('{} vertices set'.format(len(self._solver_vertices)))
        else:
            self.vertex_label.setText('none set - every vertex will be used')

        source = self.from_field.text().strip()
        if not source or not cmds.objExists(source):
            self.cost_label.setText('')
            return

        response = rbfretargeter_api.estimate_cost(
            source, solver_vertices=self._solver_vertices,
            sphere_anchors=self.sphere_field.value(),
            affine=self.affine_box.isChecked())
        if not response['ok']:
            self.cost_label.setText('')
            return

        cost = response['result']
        limit = self.max_points_field.value()
        over = bool(limit) and cost['points'] > limit
        runs = max(1, self.to_list.count())
        self.cost_label.setStyleSheet(
            'color: {};'.format('#e0a45a' if over else QUIET_COLOUR))
        self.cost_label.setText(
            '{:,} solver points, a {:.1f} MB matrix{}.{}'
            .format(cost['points'], cost['megabytes'],
                    ', solved {} times'.format(runs) if runs > 1 else '',
                    '  Above the limit - this will be refused. Press Auto-pick '
                    'Solver Vertices.' if over else ''))

    # --- the button ---------------------------------------------------------------- #

    def _retarget(self):
        """
        Do it.
        """

        source = self.from_field.text().strip()
        targets = self._rows(self.to_list)
        shapes = self._rows(self.shape_list)

        if not source:
            self._say('Set a "deform from" mesh.', ok=False)
            return
        if not targets:
            self._say('Add at least one "deform to" mesh.', ok=False)
            return
        if not shapes:
            self._say('Add at least one mesh to deform.', ok=False)
            return
        # The confusions that are easy to make, and whose result looks like the
        # tool misbehaving rather than like a mistake.
        if source in targets:
            self._say('{} is on both sides of the deformation.'.format(source), ok=False)
            return
        overlap = [name for name in shapes if name == source or name in targets]
        if overlap:
            self._say('{} is both part of the deformation and a mesh to deform.'
                      .format(overlap[0]), ok=False)
            return

        # Say it here rather than letting three targets each report the same
        # refusal. The count does not depend on which target it is.
        cost = rbfretargeter_api.estimate_cost(
            source, solver_vertices=self._solver_vertices,
            sphere_anchors=self.sphere_field.value(),
            affine=self.affine_box.isChecked())
        limit = self.max_points_field.value()
        if cost['ok'] and limit and cost['result']['points'] > limit:
            # **Nobody picking solver vertices means "every vertex of the source", and on
            # any real body that is the one choice guaranteed to be unusable.** A
            # 16,747-vertex body asks for a 2,140.8 MB matrix, so doing nothing earned a
            # refusal and a pointer to a button whose purpose is not obvious from the
            # error. Worse, the number named is the source BODY, not the geometry being
            # carried across, so somebody retargeting a 300-vertex pocket reads
            # "16,747 solver points is over the limit" and reasonably concludes their own
            # mesh is too big.
            #
            # So when nothing was chosen by hand, choose the default set and carry on.
            # DEFAULT_SOLVER_POINTS is 1000 from measurement: an error-driven pick of 1000
            # beats an even spread of 2000 on every column, so this is not a compromise to
            # get under the limit - it is the better answer anyway.
            if not self._solver_vertices:
                try:
                    picked = rbfretargeter_api.suggest_solver_vertices(
                        source, count=rbfretargeter_api.DEFAULT_SOLVER_POINTS,
                        target=next((n for n in targets if cmds.objExists(n)), None),
                        select=False, affine=self.affine_box.isChecked(),
                        progress=self._progress_hook('Choosing solver vertices'))
                finally:
                    self._end_progress()
                if picked['ok'] and picked['result']:
                    self._solver_vertices = list(picked['result'])
                    self._auto_picked = rbfretargeter_api.DEFAULT_SOLVER_POINTS
                    self.auto_count_field.setValue(rbfretargeter_api.DEFAULT_SOLVER_POINTS)
                    self._update_cost()
                    self._say('No solver vertices were chosen, so {:,} of {}\'s {:,} '
                              'vertices were picked automatically - solving on the whole '
                              'body would have needed a {:,.0f} MB matrix. This is the '
                              'mesh the deformation is measured FROM; the size of what you '
                              'are carrying across does not affect it.'
                              .format(len(self._solver_vertices), source,
                                      cost['result']['points'], cost['result']['megabytes']))
                else:
                    self._say('{:,} solver points on {} is over the {:,} limit, and the '
                              'automatic pick could not run: {}'
                              .format(cost['result']['points'], source, limit,
                                      picked['message']), ok=False)
                    return
            else:
                self._say('{:,} solver vertices are chosen on {}, over the {:,} limit - a '
                          '{:,.0f} MB matrix. Press Auto-pick Solver Vertices for a '
                          'workable set, or raise the limit if you mean to wait.'
                          .format(cost['result']['points'], source, limit,
                                  cost['result']['megabytes']), ok=False)
                return

        self.retarget_button.setEnabled(False)
        cmds.undoInfo(openChunk=True)
        try:
            settings = dict(solver_vertices=self._solver_vertices or None,
                            place_on_target=self.place_box.isChecked(),
                            shaders=self.shader_choice.currentData(),
                            sphere_anchors=self.sphere_field.value(),
                            regularisation=self.regularisation_field.value(),
                            affine=self.affine_box.isChecked(),
                            max_solver_points=self.max_points_field.value())
            if len(targets) == 1:
                response = rbfretargeter_api.retarget_shapes(
                    source, targets[0], shapes, **settings)
                made = response['result'] or []
            else:
                if self._auto_picked:
                    # Let it choose per target rather than reusing one target's
                    # set for all of them.
                    settings['solver_vertices'] = None
                    settings['auto_pick'] = self._auto_picked
                response = rbfretargeter_api.retarget_to_many(
                    source, targets, shapes, **settings)
                made = [node for group in (response['result'] or {}).values()
                        for node in group]
        finally:
            cmds.undoInfo(closeChunk=True)
            self.retarget_button.setEnabled(True)

        if self._handle(response) and made:
            cmds.select([str(node) for node in made], replace=True)


def open_tool(*args, **kwargs):
    """
    Open the RBF Retargeter window. This is what the Toolbox button calls.

    :return: The window.
    :rtype: RBFRetargeterUI
    """

    return RBFRetargeterUI()
