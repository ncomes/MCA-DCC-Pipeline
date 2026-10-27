"""
Cage Wrap - deform a mesh with a cage wrapped around it.

The window is a thin shell over :mod:`cagewrap_api`. Every button calls one API
function and shows the ``message`` it gets back, so what the window reports and what a
script gets are the same sentence.

**Read the two numbers under "What happened".** The rest error says whether the bind is
sound - it is how far the mesh moves the moment it is bound, and it should be a
millionth of a unit. The points-outside count says whether the cage actually contains
the mesh; anything poking through is bound to its nearest cage face, which is a guess.

:Requires: the mcaCageWrap plug-in, which the window loads for you.
"""

# software specific imports
import maya.cmds as cmds

# Qt imports
from mca.common.pyqt.pygui import qtwidgets

# MCA python imports
from mca.common import log
from mca.mya.pyqt import mayawindows
from mca.mya.tools.cagewrap import cagewrap_api

logger = log.MCA_LOGGER


class CageWrapUI(mayawindows.MCAMayaWindow):
    """
    The Cage Wrap window.
    """

    VERSION = '1.0.0'

    def __init__(self, parent=None, **kwargs):
        super().__init__(title='Cage Wrap', ui_path=None, show_window=True,
                         version=self.VERSION, **kwargs)

        self._mesh = None
        self._cage = None
        self._last = None

        self.setMinimumSize(440, 620)
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

        # ---- the mesh -------------------------------------------------------- #
        group = qtwidgets.QGroupBox('The mesh to deform')
        layout.addWidget(group)
        rows = qtwidgets.QVBoxLayout(group)

        row = qtwidgets.QHBoxLayout()
        rows.addLayout(row)
        self._mesh_field = qtwidgets.QLineEdit()
        self._mesh_field.setReadOnly(True)
        self._mesh_field.setPlaceholderText('select the mesh, or just leave it selected')
        row.addWidget(self._mesh_field)
        button = qtwidgets.QPushButton('Use Selected')
        button.clicked.connect(self._pick_mesh)
        row.addWidget(button)

        # ---- the cage -------------------------------------------------------- #
        group = qtwidgets.QGroupBox('The cage')
        group.setToolTip('Any closed mesh that surrounds the one above. Quads are fine - it '
                         'is triangulated for you.')
        layout.addWidget(group)
        rows = qtwidgets.QVBoxLayout(group)

        note = qtwidgets.QLabel(
            'The cage you end up with is the one to animate. A hidden copy of it is kept as '
            'the rest pose, so there is nothing to freeze and nothing to remember not to '
            'touch.')
        note.setWordWrap(True)
        rows.addWidget(note)

        row = qtwidgets.QHBoxLayout()
        rows.addLayout(row)
        self._cage_field = qtwidgets.QLineEdit()
        self._cage_field.setReadOnly(True)
        self._cage_field.setPlaceholderText('leave empty to have one built')
        row.addWidget(self._cage_field)
        button = qtwidgets.QPushButton('Use Selected')
        button.clicked.connect(self._pick_cage)
        row.addWidget(button)

        row = qtwidgets.QHBoxLayout()
        rows.addLayout(row)
        row.addWidget(qtwidgets.QLabel('Or build one with about'))
        self._faces = qtwidgets.QSpinBox()
        self._faces.setRange(20, 5000)
        self._faces.setValue(cagewrap_api.DEFAULT_CAGE_FACES)
        self._faces.setToolTip('Faces. More follows the shape more closely and costs more to '
                               'bind against - the bind is mesh points times cage faces.')
        row.addWidget(self._faces)
        row.addWidget(qtwidgets.QLabel('faces'))
        row = qtwidgets.QHBoxLayout()
        rows.addLayout(row)
        self._relax = qtwidgets.QSpinBox()
        self._relax.setRange(0, 20)
        self._relax.setValue(cagewrap_api.DEFAULT_RELAX)
        self._relax.setToolTip('Rounds of averaging, to take the mesh\'s own small detail '
                               'off the cage. That detail is nothing anybody wants to '
                               'animate, and it makes the cage\'s normals noisy - and the '
                               'normals are half of what the deformation is built from.')
        row.addWidget(qtwidgets.QLabel('Relax'))
        row.addWidget(self._relax)
        self._symmetry = qtwidgets.QCheckBox('Make it symmetrical')
        self._symmetry.setToolTip('Retopology never comes out symmetrical, and a cage that '
                                  'is not symmetrical cannot be posed symmetrically - every '
                                  'symmetrical shape has to be built twice by hand.')
        row.addWidget(self._symmetry)

        button = qtwidgets.QPushButton('Build A Cage')
        button.setToolTip('Retopologises the mesh down to roughly that many faces and pushes '
                          'the result out until the whole mesh is inside it. A starting '
                          'point - delete what you do not need and move the rest.')
        button.clicked.connect(self._build_cage)
        row.addWidget(button)

        row = qtwidgets.QHBoxLayout()
        rows.addLayout(row)
        note = qtwidgets.QLabel('Or from the skeleton:')
        row.addWidget(note)
        self._sides = qtwidgets.QSpinBox()
        self._sides.setRange(3, 24)
        self._sides.setValue(6)
        self._sides.setToolTip('Points per ring. 6 is round enough to follow a limb and few '
                               'enough to grab; 4 gives a box-section tube.')
        row.addWidget(qtwidgets.QLabel('sides'))
        row.addWidget(self._sides)
        self._rings = qtwidgets.QSpinBox()
        self._rings.setRange(0, 8)
        self._rings.setValue(1)
        self._rings.setToolTip('Extra rings along each bone. 0 puts one at each joint only; '
                               'a long bone wants 1 or 2.')
        row.addWidget(qtwidgets.QLabel('extra rings'))
        row.addWidget(self._rings)
        button = qtwidgets.QPushButton('Build From Bones')
        button.setToolTip('A ring of points around each joint, bridged into a closed tube - '
                          'laid out where an animator expects handles rather than where the '
                          'model has detail. One cage per chain of bones, breaking at every '
                          'branch, because a deformer takes one closed cage and a skeleton '
                          'is a tree. Uses the mesh\'s own skin weights to size each ring.')
        button.clicked.connect(self._build_bone_cage)
        row.addWidget(button)

        # ---- behaviour ------------------------------------------------------- #
        group = qtwidgets.QGroupBox('How it should behave')
        layout.addWidget(group)
        grid = qtwidgets.QGridLayout(group)

        grid.addWidget(qtwidgets.QLabel('Thickness follows the cage'), 0, 0)
        self._stretch = qtwidgets.QDoubleSpinBox()
        self._stretch.setRange(0.0, 1.0)
        self._stretch.setSingleStep(0.1)
        self._stretch.setValue(0.0)
        self._stretch.setToolTip('0 keeps the shape the thickness it always was, however far '
                                 'the cage is stretched - what a bending gun barrel wants. '
                                 '1 lets it thicken and thin with the cage, which is what '
                                 'squash and stretch means. Keyable afterwards.')
        grid.addWidget(self._stretch, 0, 1)

        button = qtwidgets.QPushButton('Wrap The Mesh To The Cage')
        button.setMinimumHeight(34)
        button.setToolTip('Binds the mesh, then checks itself: it reports how far the mesh '
                          'moves the moment it is bound - which should be nothing - and how '
                          'many points fell outside the cage.')
        button.clicked.connect(self._wrap)
        layout.addWidget(button)

        # ---- baking ---------------------------------------------------------- #
        group = qtwidgets.QGroupBox('Bake it into joints and skin weights')
        group.setToolTip('None of this runs outside Maya, so for anything that ships the cage '
                         'is the authoring tool and a skinCluster is the deliverable.')
        layout.addWidget(group)
        rows = qtwidgets.QVBoxLayout(group)

        note = qtwidgets.QLabel(
            'Animate the cage across a range of frames - one shape per frame, through the '
            'extremes the rig has to reach - then hand those shapes to the pose skinner. '
            'Every pose is information; identical poses are not.')
        note.setWordWrap(True)
        rows.addWidget(note)

        row = qtwidgets.QHBoxLayout()
        rows.addLayout(row)
        row.addWidget(qtwidgets.QLabel('Frames'))
        self._start = qtwidgets.QDoubleSpinBox()
        self._start.setRange(-10000.0, 10000.0)
        self._start.setValue(cmds.playbackOptions(q=True, min=True) or 0.0)
        row.addWidget(self._start)
        row.addWidget(qtwidgets.QLabel('to'))
        self._end = qtwidgets.QDoubleSpinBox()
        self._end.setRange(-10000.0, 10000.0)
        self._end.setValue(cmds.playbackOptions(q=True, max=True) or 24.0)
        row.addWidget(self._end)
        row.addWidget(qtwidgets.QLabel('joints'))
        self._joints = qtwidgets.QSpinBox()
        self._joints.setRange(1, 512)
        self._joints.setValue(20)
        self._joints.setToolTip('How many joints to invent. The pose skinner clusters the '
                                'vertices that travel together and puts one in each group.')
        row.addWidget(self._joints)

        button = qtwidgets.QPushButton('Bake To Skin')
        button.setToolTip('Solves joints and skin weights that reproduce the cage '
                          'deformation, holding every fourth frame out of the fit so the '
                          'error you read is about a pose nobody solved for.')
        button.clicked.connect(self._bake)
        rows.addWidget(button)

        # ---- housekeeping ---------------------------------------------------- #
        row = qtwidgets.QHBoxLayout()
        layout.addLayout(row)
        button = qtwidgets.QPushButton('Report')
        button.setToolTip('What the bind measured about itself, and how much memory it is '
                          'holding.')
        button.clicked.connect(self._report)
        row.addWidget(button)
        button = qtwidgets.QPushButton('Remove The Wrap')
        button.setToolTip('Takes the deformer off and removes the hidden rest cage. The cage '
                          'you have been animating is left alone.')
        button.clicked.connect(self._remove)
        row.addWidget(button)
        button = qtwidgets.QPushButton('Build An Example Scene')
        button.setToolTip('Builds a worked example in the current scene and fills this '
                          'window in: a lumpy prop with no skeleton, a cage built from its '
                          'own shape, the prop wrapped to it, and the cage keyed through a '
                          'squash and stretch. Press play. Nothing is loaded from disk, so '
                          'it works in every Maya the plug-in builds for.')
        button.clicked.connect(self._example)
        row.addWidget(button)

        # ---- report ---------------------------------------------------------- #
        group = qtwidgets.QGroupBox('What happened')
        layout.addWidget(group)
        rows = qtwidgets.QVBoxLayout(group)
        self._report_box = qtwidgets.QPlainTextEdit()
        self._report_box.setReadOnly(True)
        self._report_box.setMinimumHeight(140)
        rows.addWidget(self._report_box)

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

        available, reason = cagewrap_api.plugin_is_available()
        if not available:
            self._say(reason, False)

    @staticmethod
    def _is_mesh(node):
        """
        :param node: A node name.
        :return: True when it is a mesh or has one under it.
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

    def _resolve_mesh(self):
        """
        The mesh: the one that was picked, or whatever is selected right now.

        Use Selected is a convenience for pinning a choice while you select something
        else, not a gate - a window that says "pick the mesh first" at somebody who has
        the mesh selected is a maddening thing.

        :return: The mesh, or None with a message already said.
        :rtype: str or None
        """

        if self._mesh and cmds.objExists(self._mesh):
            return self._mesh
        found = [each for each in self._meshes_in(cmds.ls(selection=True, long=True) or [])
                 if each != self._cage]
        if not found:
            self._say('Select the mesh to deform, or press Use Selected next to it.', False)
            return None
        self._mesh = found[0]
        self._mesh_field.setText(self._mesh.split('|')[-1])
        return self._mesh

    def _frames(self):
        """
        :return: The frames to bake.
        :rtype: list
        """

        start = self._start.value()
        end = self._end.value()
        if end <= start:
            raise ValueError('The end frame is not after the start frame.')
        return [float(frame) for frame in range(int(start), int(end) + 1)]

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
        self._say('Deforming: {}.'.format(self._mesh.split('|')[-1]))

    def _pick_cage(self):
        """
        Take the cage from the selection.
        """

        found = self._meshes_in(cmds.ls(selection=True, long=True) or [])
        if not found:
            self._say('Select the cage first - any closed mesh around the one you are '
                      'deforming.', False)
            return
        self._cage = found[-1] if found[-1] != self._mesh else found[0]
        self._cage_field.setText(self._cage.split('|')[-1])

        holes = cagewrap_api.border_edges(self._cage)
        if holes:
            self._say('{} has {} border edge(s), so it is not closed - fill the holes before '
                      'wrapping to it.'.format(self._cage.split('|')[-1], holes), False)
        else:
            self._say('Cage: {}.'.format(self._cage.split('|')[-1]))

    def _build_cage(self):
        """
        Build a cage around the mesh.
        """

        if not self._resolve_mesh():
            return
        response = self._handle(cagewrap_api.cage_from_mesh(
            self._mesh, faces=self._faces.value(), relax=self._relax.value(),
            symmetry=self._symmetry.isChecked()))
        if response['ok']:
            self._cage = response['result']['cage']
            self._cage_field.setText(self._cage.split('|')[-1])

    def _build_bone_cage(self):
        """
        Build cages that follow the skeleton.
        """

        if not self._resolve_mesh():
            return
        response = self._handle(cagewrap_api.cage_from_skeleton(
            self._mesh, sides=self._sides.value(), rings=self._rings.value()))
        if response['ok'] and response['result']['cages']:
            # The first one, because the window wraps one mesh to one cage. With several
            # chains the others are in the scene to pick from - said out loud rather than
            # left for somebody to notice.
            self._cage = response['result']['cages'][0]['cage']
            self._cage_field.setText(self._cage.split('|')[-1])
            if len(response['result']['cages']) > 1:
                self._say('{} cages were built, one per chain of bones. This window wraps one '
                          'mesh to one cage, so it has taken {} - select another and press Use '
                          'Selected to use that one instead.'
                          .format(len(response['result']['cages']),
                                  self._cage.split('|')[-1]))

    def _wrap(self):
        """
        Bind the mesh to the cage.
        """

        if not self._resolve_mesh():
            return
        cage = self._cage if self._cage and cmds.objExists(self._cage) else None
        response = self._handle(cagewrap_api.wrap(self._mesh, cage=cage,
                                                 stretch=self._stretch.value(),
                                                 faces=self._faces.value(),
                                                 relax=self._relax.value(),
                                                 symmetry=self._symmetry.isChecked()))
        if response['ok']:
            self._last = response['result']
            self._cage = response['result']['cage']
            self._cage_field.setText(self._cage.split('|')[-1])

    def _bake(self):
        """
        Hand the cage deformation to the pose skinner.
        """

        if not self._resolve_mesh():
            return
        try:
            frames = self._frames()
        except Exception as error:
            self._say(str(error), False)
            return
        self._handle(cagewrap_api.bake_to_skin(self._mesh, frames,
                                               count=self._joints.value()))

    def _example(self):
        """
        Build a worked example in the current scene and point the window at it.
        """

        if cmds.file(query=True, modified=True):
            answer = qtwidgets.QMessageBox.question(
                self, 'Build the example here?',
                'The example is built in the CURRENT scene, and this one has unsaved '
                'changes. It adds a prop, a cage and a wrap, and replaces anything already '
                'called cagewrap_example. Carry on?',
                qtwidgets.QMessageBox.Yes | qtwidgets.QMessageBox.No)
            if answer != qtwidgets.QMessageBox.Yes:
                self._say('Example not built - the scene was left alone.')
                return

        response = self._handle(cagewrap_api.example_scene())
        if not response['ok']:
            return
        made = response['result']

        # Fill the window in, so the next thing somebody presses acts on the example
        # rather than on nothing.
        self._mesh = made['mesh']
        self._mesh_field.setText(self._mesh.split('|')[-1])
        self._cage = made['cage']
        self._cage_field.setText(self._cage.split('|')[-1])
        self._stretch.setValue(1.0)

        cmds.select(made['cage'], replace=True)
        try:
            cmds.viewFit(fitFactor=0.9)
        except Exception:
            logger.debug('Could not frame the example.', exc_info=True)
        cmds.select(clear=True)

    def _report(self):
        """
        Say what the bind measured.
        """

        if not self._resolve_mesh():
            return
        found = cagewrap_api.find_wraps(self._mesh)
        if not found:
            self._say('{} has no cage wrap on it.'.format(self._mesh.split('|')[-1]), False)
            return
        for node in found:
            self._handle(cagewrap_api.report(node))

    def _remove(self):
        """
        Take the deformer off.
        """

        if not self._resolve_mesh():
            return
        self._handle(cagewrap_api.remove(self._mesh))


def _close_old_windows():
    """
    Shut any window this tool left open.

    Reloading the module leaves the old window alive and connected to the OLD code, so
    without this an artist can have two windows up, one of them running code from before
    the last edit, and no way to tell which is which.
    """

    for widget in qtwidgets.QApplication.topLevelWidgets():
        try:
            if widget.windowTitle() == 'Cage Wrap' and widget.__class__.__name__ != 'CageWrapUI':
                widget.close()
            elif isinstance(widget, CageWrapUI):
                widget.close()
                widget.deleteLater()
        except Exception:
            logger.debug('Could not close an old Cage Wrap window.', exc_info=True)


def open_tool():
    """
    Open the window. This is what the Toolbox button calls.

    :return: The window.
    :rtype: CageWrapUI
    """

    _close_old_windows()
    return CageWrapUI()
