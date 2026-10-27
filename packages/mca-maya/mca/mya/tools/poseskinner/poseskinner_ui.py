"""
Pose Skinner - turn a deformation into joints and skin weights.

The window is a thin shell over :mod:`poseskinner_api`. Every button calls one API
function and shows the ``message`` it gets back, so what the window reports and
what a script gets are the same sentence.

**Read the held-out number, not the fitted one.** Error on the poses that were
fitted falls as you add joints whether or not the skin is any good. The window
holds a few poses back by default and shows both, because the second number is the
one that predicts how the skin behaves on a pose nobody solved for.

:Requires: the mcaPoseSkinner plug-in, which the window loads for you.
"""

# software specific imports
import maya.cmds as cmds

# Qt imports
from mca.common.pyqt.pygui import qtwidgets, qtcore

# MCA python imports
from mca.common import log
from mca.mya.pyqt import mayawindows
from mca.mya.tools.poseskinner import poseskinner_api

logger = log.MCA_LOGGER


class PoseSkinnerUI(mayawindows.MCAMayaWindow):
    """
    The Pose Skinner window.
    """

    VERSION = '1.0.0'

    def __init__(self, parent=None, **kwargs):
        super().__init__(title='Pose Skinner', ui_path=None, show_window=True,
                         version=self.VERSION, **kwargs)

        self._mesh = None
        self._joints = []
        self._donors = []
        self._last = None
        #: frame -> blendshape channel, when the poses came from a layout. A frame
        #: number tells an artist nothing; "jaw_up" tells them where to look.
        self._named = {}

        self.setMinimumSize(460, 700)
        self._build_ui()
        self._check_plugin()

    # --- construction ------------------------------------------------------- #

    def _build_ui(self):
        """
        Lay the window out.
        """

        central = qtwidgets.QWidget()
        self.setCentralWidget(central)
        layout = qtwidgets.QVBoxLayout(central)

        # ---- what deforms --------------------------------------------------- #
        deform = qtwidgets.QGroupBox('The mesh that deforms')
        layout.addWidget(deform)
        deform_layout = qtwidgets.QVBoxLayout(deform)

        row = qtwidgets.QHBoxLayout()
        deform_layout.addLayout(row)
        self._mesh_field = qtwidgets.QLineEdit()
        self._mesh_field.setReadOnly(True)
        self._mesh_field.setPlaceholderText('select the mesh and press Use Selected')
        row.addWidget(self._mesh_field)
        button = qtwidgets.QPushButton('Use Selected')
        button.clicked.connect(self._pick_mesh)
        row.addWidget(button)

        row = qtwidgets.QHBoxLayout()
        deform_layout.addLayout(row)
        row.addWidget(qtwidgets.QLabel('Poses on frames'))
        self._start = qtwidgets.QDoubleSpinBox()
        self._start.setRange(-100000.0, 100000.0)
        self._start.setDecimals(2)
        self._start.setValue(cmds.playbackOptions(q=True, min=True) or 1.0)
        row.addWidget(self._start)
        row.addWidget(qtwidgets.QLabel('to'))
        self._end = qtwidgets.QDoubleSpinBox()
        self._end.setRange(-100000.0, 100000.0)
        self._end.setDecimals(2)
        self._end.setValue(cmds.playbackOptions(q=True, max=True) or 24.0)
        row.addWidget(self._end)

        row = qtwidgets.QHBoxLayout()
        deform_layout.addLayout(row)
        row.addWidget(qtwidgets.QLabel('Rest pose on frame'))
        self._rest = qtwidgets.QDoubleSpinBox()
        self._rest.setRange(-100000.0, 100000.0)
        self._rest.setDecimals(2)
        self._rest.setValue(cmds.playbackOptions(q=True, min=True) or 0.0)
        self._rest.setToolTip('The neutral shape every weight is measured from. It must be a '
                              'frame where the mesh is undeformed and the joints are at their '
                              'bind pose.')
        row.addWidget(self._rest)
        button = qtwidgets.QPushButton('Lay Out BlendShape')
        button.setToolTip('Key the blendShape on the selected mesh out onto one frame per '
                          'target, then fill the frame range in above. The rig\'s joints have '
                          'to be driven by those same channels for the poses to mean anything.')
        button.clicked.connect(self._lay_out)
        row.addWidget(button)

        # ---- joints --------------------------------------------------------- #
        bones = qtwidgets.QGroupBox('The joints')
        layout.addWidget(bones)
        bones_layout = qtwidgets.QVBoxLayout(bones)

        row = qtwidgets.QHBoxLayout()
        bones_layout.addLayout(row)
        self._joint_field = qtwidgets.QLineEdit()
        self._joint_field.setReadOnly(True)
        self._joint_field.setPlaceholderText('select the joints and press Use Selected')
        row.addWidget(self._joint_field)
        button = qtwidgets.QPushButton('Use Selected')
        button.clicked.connect(self._pick_joints)
        row.addWidget(button)

        row = qtwidgets.QHBoxLayout()
        bones_layout.addLayout(row)
        row.addWidget(qtwidgets.QLabel('Or make'))
        self._auto_count = qtwidgets.QSpinBox()
        self._auto_count.setRange(1, 512)
        self._auto_count.setValue(20)
        row.addWidget(self._auto_count)
        button = qtwidgets.QPushButton('Joints From The Deformation')
        button.setToolTip('For a cache or a deformer with no skeleton at all: groups vertices '
                          'that move together, drops a joint in each group and solves both the '
                          'weights and the joints\' motion.')
        button.clicked.connect(self._auto_joints)
        row.addWidget(button)

        # ---- pin the joints to the mesh ------------------------------------- #
        pinning = qtwidgets.QGroupBox('Make the joints follow the mesh')
        pinning.setToolTip('For the usual way of driving a face: the blendShapes stay on this '
                           'mesh, the joints ride on its surface, and the skin those joints '
                           'deform goes on a second mesh. Do this FIRST - a solve can only fit '
                           'joints that already move.')
        layout.addWidget(pinning)
        pinning_layout = qtwidgets.QVBoxLayout(pinning)

        note = qtwidgets.QLabel(
            'Sticks each joint above to the closest point on the mesh, by UV, through one '
            'uvPin. The rest pose does not move: the pin drives how far the surface has '
            'travelled since this frame, so at this frame every joint is exactly where you '
            'put it and its own translate and rotate still work.')
        note.setWordWrap(True)
        pinning_layout.addWidget(note)

        self._pin_rotate = qtwidgets.QCheckBox('Let the surface rotate the joints as well')
        self._pin_rotate.setToolTip('Off by default. Rotation comes from the surface\'s tangent '
                                    'frame, which twists wherever the UVs do, and a face rig '
                                    'usually wants the joints\' orientation left as the rigger '
                                    'set it. Turning it on makes the joints\' current rotate '
                                    'values their rest.')
        pinning_layout.addWidget(self._pin_rotate)

        row = qtwidgets.QHBoxLayout()
        pinning_layout.addLayout(row)
        button = qtwidgets.QPushButton('Pin Joints To Mesh')
        button.setMinimumHeight(30)
        button.setToolTip('Pins the joints to the mesh at the rest frame above, then checks that '
                          'none of them moved and says how far each one sits off the surface - '
                          'a joint deep inside the head pins to whatever is nearest it, which '
                          'is worth knowing about.')
        button.clicked.connect(self._pin)
        row.addWidget(button)
        button = qtwidgets.QPushButton('Unpin')
        button.setToolTip('Removes the pins this tool made and puts the joints\' '
                          'offsetParentMatrix back as it was. Leaves anything else alone.')
        button.clicked.connect(self._unpin)
        row.addWidget(button)

        # ---- add to an existing skin ---------------------------------------- #
        additive = qtwidgets.QGroupBox('Or add these joints to a skin that already exists')
        additive.setToolTip('For a mesh that is ALREADY skinned - a head bound to a head joint, '
                            'say - where you want to add face joints without disturbing the '
                            'rest of it.')
        layout.addWidget(additive)
        additive_layout = qtwidgets.QVBoxLayout(additive)

        note = qtwidgets.QLabel(
            'Solve And Skin works out the whole skin, so every vertex has to reach 1.0 from the '
            'joints you gave it - which is why a cheek joint can end up with weight on the back '
            'of the head. This instead fits only what the existing skin cannot reach, and takes '
            'the weight it needs out of the influences below. Everything else is left exactly '
            'as it is.')
        note.setWordWrap(True)
        additive_layout.addWidget(note)

        row = qtwidgets.QHBoxLayout()
        additive_layout.addLayout(row)
        row.addWidget(qtwidgets.QLabel('Pull weight from'))
        self._donor_field = qtwidgets.QLineEdit()
        self._donor_field.setPlaceholderText('head            (the influence that has the weight now)')
        self._donor_field.setToolTip('One or more influences of the existing skinCluster, comma '
                                     'separated. These are the only ones that change - every '
                                     'other influence comes out bit-identical.')
        row.addWidget(self._donor_field)
        button = qtwidgets.QPushButton('Use Selected')
        button.clicked.connect(self._pick_donors)
        row.addWidget(button)

        button = qtwidgets.QPushButton('Add To Existing Skin')
        button.setMinimumHeight(30)
        button.setToolTip('Adds the joints above as influences of the existing skin, taking '
                          'their weight out of the donors. By default the result goes on a clean '
                          'COPY of the mesh with the existing skinning carried over first, so '
                          'the blendShape stays on the original - set "Always skin the mesh in '
                          'place" under Quality to write into it instead. Checks afterwards that '
                          'the other influences did not move and every vertex still sums to one, '
                          'and says so.')
        button.clicked.connect(self._add_to_skin)
        additive_layout.addWidget(button)

        # ---- quality -------------------------------------------------------- #
        quality = qtwidgets.QGroupBox('Quality')
        layout.addWidget(quality)
        grid = qtwidgets.QGridLayout(quality)

        grid.addWidget(qtwidgets.QLabel('Influences per vertex'), 0, 0)
        self._influences = qtwidgets.QSpinBox()
        self._influences.setRange(1, 64)
        self._influences.setValue(poseskinner_api.DEFAULT_MAX_INFLUENCES)
        self._influences.setToolTip('What the engine allows. Four and eight are the usual '
                                   'budgets. Influence Report measures what each one costs.')
        grid.addWidget(self._influences, 0, 1)

        grid.addWidget(qtwidgets.QLabel('Nearest joints considered'), 1, 0)
        self._locality = qtwidgets.QSpinBox()
        self._locality.setRange(0, 512)
        self._locality.setValue(0)
        self._locality.setToolTip('0 is automatic, which is four times the influence count. '
                                 'Restricting a vertex to its nearest joints measurably '
                                 'improves accuracy - 31% closer to the truth on the test '
                                 'suite - and stops two parts of a mesh that happen to move '
                                 'alike from sharing influences. Set it high to turn the '
                                 'restriction off.')
        grid.addWidget(self._locality, 1, 1)

        grid.addWidget(qtwidgets.QLabel('Weight smoothness'), 2, 0)
        self._smoothing = qtwidgets.QDoubleSpinBox()
        self._smoothing.setRange(0.0, 5.0)
        self._smoothing.setSingleStep(0.05)
        self._smoothing.setDecimals(2)
        self._smoothing.setValue(0.0)
        self._smoothing.setToolTip('Pulls neighbouring vertices toward the same weights. This '
                                  'makes a weight map that is easier to edit by hand and that '
                                  'LODs better - it does NOT make the fit more accurate, and '
                                  'measured, it costs a little. 0 is off.')
        grid.addWidget(self._smoothing, 2, 1)

        grid.addWidget(qtwidgets.QLabel('Hold out every Nth pose'), 3, 0)
        self._holdout = qtwidgets.QSpinBox()
        self._holdout.setRange(0, 20)
        self._holdout.setValue(5)
        self._holdout.setToolTip('Keeps those poses out of the fit and reports their error '
                                'separately. This is the number that says whether the skin '
                                'will hold up on a pose nobody solved for. 0 fits everything '
                                'and tells you less.')
        grid.addWidget(self._holdout, 3, 1)

        self._copy = qtwidgets.QComboBox()
        self._copy.addItems(['Skin a copy when the mesh still has its deformers',
                             'Always skin a copy', 'Always skin the mesh in place'])
        self._copy.setToolTip('A mesh that still carries the blendShape or the cache the skin '
                             'was fitted to would end up with the deformation applied twice. '
                             'Whenever a copy is made and the original was already skinned, '
                             'that skinning is carried onto the copy first - so the shapes stay '
                             'on one mesh and the skin lives on another.')
        grid.addWidget(self._copy, 4, 0, 1, 2)

        self._geodesic = qtwidgets.QCheckBox('Measure "nearest joint" across the surface')
        self._geodesic.setChecked(True)
        self._geodesic.setToolTip('The upper lip and the lower lip are a millimetre apart '
                                 'through the air and on opposite sides of a hole, so straight '
                                 'line distance lets them share joints and the mouth fights '
                                 'itself. This walks the mesh instead. It also stops a separate '
                                 'eyeball, tooth or tongue shell being weighted to a face joint '
                                 'at all - turn it off if a joint is MEANT to carry a separate '
                                 'mesh.')
        grid.addWidget(self._geodesic, 5, 0, 1, 2)

        self._scaling = qtwidgets.QCheckBox('Let the joints scale (only when making joints)')
        self._scaling.setToolTip('A rigid joint cannot squash anything. On a face with six '
                                 'squash shapes, letting the joints scale beat adding 50% more '
                                 'rigid joints: rms 0.0102 against 0.0121, worst 0.28 against '
                                 '0.49. Whether you can use it is a question about your engine.')
        grid.addWidget(self._scaling, 6, 0, 1, 2)

        self._paint = qtwidgets.QCheckBox('Paint the error onto the mesh afterwards')
        self._paint.setChecked(True)
        self._paint.setToolTip('Per-vertex error as vertex colours. One number for a whole '
                             'mesh cannot tell you the fit is fine everywhere except the '
                             'armpits.')
        grid.addWidget(self._paint, 7, 0, 1, 2)

        # ---- do it ---------------------------------------------------------- #
        row = qtwidgets.QHBoxLayout()
        layout.addLayout(row)
        button = qtwidgets.QPushButton('Solve And Skin')
        button.setMinimumHeight(34)
        button.clicked.connect(self._solve)
        row.addWidget(button)
        button = qtwidgets.QPushButton('Influence Report')
        button.setToolTip('Solves 4, 8 and 12 influences and puts the numbers side by side, '
                          'so the budget argument is settled by measurement.')
        button.clicked.connect(self._report)
        row.addWidget(button)

        row = qtwidgets.QHBoxLayout()
        layout.addLayout(row)
        button = qtwidgets.QPushButton('Add Correctives')
        button.setToolTip('Builds a blendShape in front of the skin holding whatever the skin '
                          'could not reach, so the poses you solved for come back exactly.')
        button.clicked.connect(self._correctives)
        row.addWidget(button)
        button = qtwidgets.QPushButton('Clear Error Colours')
        button.clicked.connect(self._clear_colours)
        row.addWidget(button)

        # ---- report --------------------------------------------------------- #
        report = qtwidgets.QGroupBox('What happened')
        layout.addWidget(report)
        report_layout = qtwidgets.QVBoxLayout(report)
        self._report_box = qtwidgets.QPlainTextEdit()
        self._report_box.setReadOnly(True)
        self._report_box.setMinimumHeight(140)
        report_layout.addWidget(self._report_box)

        self._status = qtwidgets.QLabel('')
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

    # --- plumbing ----------------------------------------------------------- #

    def _say(self, message, ok=True):
        """
        :param str message: What to show.
        :param bool ok: Whether it went well.
        """

        self._status.setText(message)
        self._status.setStyleSheet('color: #9fd39f;' if ok else 'color: #e08c8c;')
        self._report_box.appendPlainText(message)
        logger.info(message) if ok else logger.warning(message)

    def _handle(self, response):
        """
        Show a response and hand it back.

        :param dict response: From the API.
        :return: The same response.
        :rtype: dict
        """

        self._say(response['message'], response['ok'])
        return response

    def _check_plugin(self):
        """
        Say so up front if the plug-in is not there, rather than on the first click.
        """

        available, reason = poseskinner_api.plugin_is_available()
        if not available:
            self._say(reason, False)

    def _frames(self):
        """
        :return: The frames to fit.
        :rtype: list(float)
        """

        start = self._start.value()
        end = self._end.value()
        if end < start:
            raise ValueError('The end frame is before the start frame.')
        frames = [float(frame) for frame in range(int(start), int(end) + 1)]
        if len(frames) < 1:
            raise ValueError('That range has no frames in it.')
        return frames

    def _holdout_frames(self, frames):
        """
        Every Nth pose, and never all of them.

        :param list frames: The frames being fitted.
        :return: The ones to hold back.
        :rtype: list(float)
        """

        every = self._holdout.value()
        if not every or len(frames) < 3:
            return []
        held = frames[every - 1::every]
        if len(held) >= len(frames):
            return []
        return held

    def _duplicate_choice(self):
        """
        :return: What to pass as ``duplicate``.
        """

        return {0: None, 1: True, 2: False}[self._copy.currentIndex()]

    # --- buttons ------------------------------------------------------------ #

    def _pick_mesh(self):
        """
        Take the mesh from the selection.
        """

        found = self._meshes_in(cmds.ls(selection=True, long=True) or [])
        if not found:
            self._say('Select a mesh first.', False)
            return
        self._mesh = found[0]
        self._mesh_field.setText(self._mesh.split('|')[-1])
        self._say('Deforming mesh: {}.'.format(self._mesh.split('|')[-1]))

    @staticmethod
    def _is_mesh(node):
        """
        :param node: A node name.
        :return: True when it is a mesh or a transform with one under it.
        :rtype: bool
        """

        if cmds.nodeType(node) == 'mesh':
            return True
        return any(cmds.nodeType(shape) == 'mesh' for shape in
                   (cmds.listRelatives(node, shapes=True, noIntermediate=True,
                                       fullPath=True) or []))

    def _meshes_in(self, nodes):
        """
        :param nodes: Node names.
        :return: Those that are meshes.
        :rtype: list
        """

        return [each for each in nodes if self._is_mesh(each)]

    def _joints_in(self, nodes):
        """
        The joints among these nodes, which is not "everything that is a transform".

        A mesh's transform IS a transform, so selecting the head and its face joints
        together and pressing Use Selected used to add the head to the joint list. It
        would then be solved as an influence of itself.

        :param nodes: Node names.
        :return: Those that can act as joints.
        :rtype: list
        """

        return [each for each in nodes
                if cmds.nodeType(each) in ('joint', 'transform') and not self._is_mesh(each)]

    def _resolve_mesh(self):
        """
        The mesh to work on: the one that was picked, or the one selected right now.

        **Why this exists.** Requiring Use Selected first meant the window could say
        "Pick the mesh that deforms first" at somebody who had the mesh selected, which
        is a maddening thing for a tool to do. Use Selected is now a convenience for
        pinning a choice while you select something else, not a gate.

        :return: The mesh, or None with a message already said.
        :rtype: str or None
        """

        if self._mesh and cmds.objExists(self._mesh):
            return self._mesh
        found = self._meshes_in(cmds.ls(selection=True, long=True) or [])
        if not found:
            self._say('Select the mesh that deforms, or press Use Selected next to it.', False)
            return None
        self._mesh = found[0]
        self._mesh_field.setText(self._mesh.split('|')[-1])
        if len(found) > 1:
            self._say('Using {} - {} meshes were selected, so the first one was taken.'.format(
                self._mesh.split('|')[-1], len(found)))
        return self._mesh

    def _resolve_joints(self):
        """
        The joints: the ones that were picked, or the ones selected right now.

        :return: The joints, or an empty list with a message already said.
        :rtype: list
        """

        alive = [each for each in (self._joints or []) if cmds.objExists(each)]
        if alive:
            return alive
        found = self._joints_in(cmds.ls(selection=True, long=True) or [])
        if not found:
            self._say('Select the joints as well as the mesh, or press Use Selected next to '
                      'them.', False)
            return []
        self._joints = found
        self._joint_field.setText('{} joint(s)'.format(len(found)))
        return found

    def _pick_joints(self):
        """
        Take the joints from the selection.
        """

        selected = self._joints_in(cmds.ls(selection=True, long=True) or [])
        if not selected:
            self._say('Select the joints to solve for. A mesh in the selection is ignored '
                      'here - it cannot act as an influence.', False)
            return
        self._joints = selected
        self._joint_field.setText('{} joint(s)'.format(len(selected)))
        self._say('{} joint(s) chosen.'.format(len(selected)))

    def _pick_donors(self):
        """
        Take the donor influences from the selection.
        """

        selected = [each for each in (cmds.ls(selection=True, long=True) or [])
                    if cmds.nodeType(each) in ('joint', 'transform')]
        if not selected:
            self._say('Select the influence(s) that hold the weight now - on a head that is '
                      'usually the head joint.', False)
            return
        self._donors = selected
        self._donor_field.setText(', '.join(each.split('|')[-1] for each in selected))
        self._say('{} donor(s) chosen: {}.'.format(
            len(selected), ', '.join(each.split('|')[-1] for each in selected)))

    def _donor_list(self):
        """
        The donors, from the picker or from whatever was typed in the field.

        :return: Influence names.
        :rtype: list
        """

        typed = [each.strip() for each in self._donor_field.text().split(',') if each.strip()]
        if getattr(self, '_donors', None) and self._donor_field.text() == ', '.join(
                each.split('|')[-1] for each in self._donors):
            return list(self._donors)
        return typed

    def _pin(self):
        """
        Pin the chosen joints to the chosen mesh.
        """

        if not self._resolve_mesh():
            return
        if not self._resolve_joints():
            return
        self._handle(poseskinner_api.pin_joints(
            self._mesh, self._joints, rotate=self._pin_rotate.isChecked(),
            rest_frame=self._rest.value()))

    def _unpin(self):
        """
        Take this tool's pins off the chosen joints, or off the whole mesh.
        """

        joints = [each for each in (self._joints or []) if cmds.objExists(each)]
        selected = self._joints_in(cmds.ls(selection=True, long=True) or [])
        self._handle(poseskinner_api.unpin_joints(
            joints=selected or joints or None,
            mesh=self._mesh if cmds.objExists(self._mesh or '') else None))

    def _add_to_skin(self):
        """
        Add the chosen joints to the skin that is already on the mesh.
        """

        if not self._resolve_mesh():
            return
        if not self._resolve_joints():
            return
        donors = self._donor_list()
        if not donors:
            self._say('Name the influence that holds the weight now, in "Pull weight from" - on '
                      'a head that is usually the head joint. That is where the new joints take '
                      'their weight from, and nothing else is touched.', False)
            return
        try:
            frames = self._frames()
        except Exception as error:
            self._say(str(error), False)
            return

        # "Always skin the mesh in place" is the only setting that writes into the
        # original; the other two put the result on a copy with the existing skinning
        # carried across, which is the default and what you want in an engine.
        duplicate = self._copy.currentIndex() != 2
        response = self._handle(poseskinner_api.add_to_skin(
            self._mesh, self._joints, frames, donors,
            rest_frame=self._rest.value(), max_influences=self._influences.value(),
            holdout=self._holdout_frames(frames), show=self._paint.isChecked(),
            locality=self._locality.value() or None,
            geodesic=self._geodesic.isChecked(),
            smoothing=self._smoothing.value(), duplicate=duplicate))
        if response['ok']:
            self._last = response['result']
            self._show_numbers(response['result']['solve'])

    def _lay_out(self):
        """
        Key a blendShape's targets onto frames and fill the range in.
        """

        if not self._resolve_mesh():
            return
        response = self._handle(poseskinner_api.poses_from_blendshape(
            self._mesh, start_frame=self._rest.value()))
        if response['ok']:
            frames = response['result']['frames']
            self._start.setValue(frames[0])
            self._end.setValue(frames[-1])
            self._rest.setValue(response['result']['rest_frame'])
            self._named = dict(zip(frames, response['result']['channels']))

    def _solve(self):
        """
        The whole job.
        """

        if not self._resolve_mesh():
            return
        if not self._resolve_joints():
            return
        try:
            frames = self._frames()
        except Exception as error:
            self._say(str(error), False)
            return

        locality = self._locality.value() or None
        response = self._handle(poseskinner_api.skin_from_poses(
            self._mesh, self._joints, frames, rest_frame=self._rest.value(),
            max_influences=self._influences.value(), holdout=self._holdout_frames(frames),
            show=self._paint.isChecked(), duplicate=self._duplicate_choice(),
            locality=locality, geodesic=self._geodesic.isChecked(),
            smoothing=self._smoothing.value()))
        if response['ok']:
            self._last = response['result']
            self._show_numbers(response['result']['solve'])

    def _show_numbers(self, solved):
        """
        The per-pose error, worst first, so the pose to look at is at the top.

        :param dict solved: The parsed solve.
        """

        rows = sorted(zip(solved['frames'], solved['pose_error']), key=lambda row: -row[1])
        lines = ['    {}: {:.4f}'.format(self._named.get(frame, 'frame {:g}'.format(frame)),
                                         error)
                 for frame, error in rows[:8]]
        self._report_box.appendPlainText('  hardest poses:\n' + '\n'.join(lines))

        # A rigid joint cannot squash, so if the hard poses are named for squashing
        # then the model is the limit rather than the fit - and the answer is scaling
        # joints or correctives, not more joints. Worth saying rather than leaving
        # somebody to raise the joint count and wonder why it barely helps.
        hard = [self._named.get(frame, '') for frame, _ in rows[:8]]
        if any(any(word in name.lower() for word in ('squash', 'stretch', 'compress'))
               for name in hard):
            self._report_box.appendPlainText(
                '  Some of those are squash or stretch shapes, which a rigid joint cannot '
                'reproduce at all. Try "Let the joints scale", or Add Correctives.')

    def _auto_joints(self):
        """
        Make joints from the deformation, then solve.
        """

        if not self._resolve_mesh():
            return
        try:
            frames = self._frames()
        except Exception as error:
            self._say(str(error), False)
            return
        response = self._handle(poseskinner_api.auto_joints(
            self._mesh, self._auto_count.value(), frames, rest_frame=self._rest.value(),
            max_influences=self._influences.value(), show=self._paint.isChecked(),
            holdout=self._holdout_frames(frames),
            duplicate=self._duplicate_choice(), rigid_bones=not self._scaling.isChecked(),
            geodesic=self._geodesic.isChecked(),
            locality=self._locality.value() or None,
            smoothing=self._smoothing.value()))
        if response['ok']:
            self._last = response['result']
            self._joints = response['result']['joints']
            self._joint_field.setText('{} joint(s)'.format(len(self._joints)))
            if response['result'].get('solve'):
                self._show_numbers(response['result']['solve'])

    def _report(self):
        """
        What each influence budget costs.
        """

        if not self._resolve_mesh() or not self._resolve_joints():
            self._say('Pick the mesh and the joints first.', False)
            return
        try:
            frames = self._frames()
        except Exception as error:
            self._say(str(error), False)
            return
        response = self._handle(poseskinner_api.influence_report(
            self._mesh, self._joints, frames, rest_frame=self._rest.value(),
            holdout=self._holdout_frames(frames)))
        if response['ok']:
            for row in response['result']:
                held = ('' if row['holdout_rms'] is None
                        else ', held out {:.4f}'.format(row['holdout_rms']))
                self._report_box.appendPlainText(
                    '    {} influences: rms {:.4f}, worst {:.4f}{}'
                    .format(row['max_influences'], row['rms'], row['worst'], held))

    def _correctives(self):
        """
        Absorb the residual into a blendShape in front of the skin.
        """

        if not self._last:
            self._say('Solve something first - the correctives are built against the skin '
                      'this window just made.', False)
            return
        try:
            frames = self._frames()
        except Exception as error:
            self._say(str(error), False)
            return
        self._handle(poseskinner_api.add_correctives(self._last['skinned_mesh'],
                                                     self._last['mesh'], frames))

    def _clear_colours(self):
        """
        Take the heat map off.
        """

        target = (self._last or {}).get('skinned_mesh') or self._mesh
        if not target:
            self._say('Nothing painted.', False)
            return
        self._handle(poseskinner_api.clear_error_colours(target))


def _close_old_windows():
    """
    Close any Pose Skinner window that is already open.

    **Why.** Reloading the module and opening the window again leaves the previous
    instances alive but hidden, still holding the mesh and joints they were given and
    still running the code they were built with. Somebody then sets the mesh on one
    window and presses Solve on another, and the tool says "pick the mesh first" at
    somebody who has plainly picked it. That happened, with three instances alive at
    once and the visible one empty.

    Failures here are ignored on purpose: an old window that cannot be closed is not a
    reason to refuse to open a new one.
    """

    try:
        from mca.common.pyqt import qtutils  # noqa: F401
    except Exception:
        pass
    try:
        try:
            from PySide6 import QtWidgets
        except ImportError:
            from PySide2 import QtWidgets
        for widget in QtWidgets.QApplication.allWidgets():
            if type(widget).__name__ != 'PoseSkinnerUI':
                continue
            try:
                widget.close()
                widget.deleteLater()
            except Exception:
                logger.debug('Could not close an old Pose Skinner window.', exc_info=True)
    except Exception:
        logger.debug('Could not look for old Pose Skinner windows.', exc_info=True)


def open_tool(*args, **kwargs):
    """
    Open the window. This is what a Toolbox button calls.

    :return: The window.
    :rtype: PoseSkinnerUI
    """

    _close_old_windows()
    return PoseSkinnerUI(*args, **kwargs)
