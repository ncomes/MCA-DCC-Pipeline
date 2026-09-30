"""
The Maya half of the pipeline.

Everything under here needs a running Maya - ``maya.cmds``, ``maya.api.OpenMaya`` or
``pymel`` - which is the line between this package and ``mca-common``, where nothing does.

The version this replaces declared four module constants and two of them were the same
value: ``MAYA_PATH`` and ``MAYA_TOP_ROOT`` were both ``os.path.dirname(MAYA_INIT_PATH)``,
so "top root" was not a root of anything, and the two names were used interchangeably in
the start-up code as though they meant different folders. ``MAYA_MCA_PACKAGE`` joined
``'../../mca_package.yaml'`` without normalising, so it printed as a path with ``..`` in
the middle of it. One name, spelled once:
"""

# python imports
import os


#: The folder this file is in - ``.../mca-maya/mca/mya``. Everything the package ships
#: beside its code (configs, tools, resources) is found from here.
MAYA_PATH = os.path.dirname(os.path.abspath(__file__))

#: The package folder - ``.../mca-maya``.
PACKAGE_ROOT = os.path.dirname(os.path.dirname(MAYA_PATH))

#: The package manifest, normalised. It sits beside the code it describes, so ``{self}``
#: in it means this folder.
PACKAGE_FILE = os.path.join(MAYA_PATH, 'mca_package.yaml')
