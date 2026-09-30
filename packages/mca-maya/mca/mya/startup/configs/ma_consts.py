"""
Names and tables the Maya package reads, in one place.

Two kinds of thing live here. The environment variable *names* the pipeline sets and reads - the
strings, not the values - so that a typo in one place cannot silently disagree with another. And
the two ordered tables that mirror Maya's own joint enums, where the order is the meaning and
getting it wrong would relabel every joint in a skeleton.

What was wrong before:

- **The module docstring described something else entirely** - "Module that contains the mca
  decorators at a base python level", which is the fourth module in this package to carry that
  line. It also opened with four quotation marks rather than three, so the first character of the
  docstring was a quote.
- **``THRIDPARTY``** - the third-party path variable's name was misspelled, in the constant name
  rather than in the value, so every reader had to misspell it too. It is ``THIRDPARTY`` now;
  the environment variable it names is unchanged, so nothing outside Python sees a difference.
- ``PARENT_SEPARATOR`` (``'|'``) and ``JOINT_TYPE_LABELS`` (thirty joint type names) had no
  readers anywhere in the pipeline. Gone.
"""

# python imports

# software specific imports

# mca imports


# --------------------------------------------------------------------------------------- #
# environment variable names
# --------------------------------------------------------------------------------------- #
#: Where the Maya tools live.
TOOLS_PATH = 'MCA_MAYA_TOOLS_PATH'

#: Where the Maya configuration files live.
CONFIGS_PATH = 'MCA_MAYA_CONFIGS_PATH'

#: Where the Python dependencies installed for Maya live.
DEPS_ROOT = 'MCA_MAYA_DEPS_PATH'

#: Where Studio Library keeps its data.
STUDIOLIBRARY = 'MCA_STUDIO_LIBRARY_PATH'

#: Where the third-party tools folder is. The constant used to be spelled ``THRIDPARTY``.
THIRDPARTY = 'MCA_THIRDPARTY_PATH'

#: Where Epic's Pose Wrangler is.
POSE_WRANGLER = 'MCA_POSE_WRANGLER'

#: Where the Unreal ML Deformer tooling is.
MCA_UE_ML_DEFORMER = 'MCA_UE_ML_DEFORMER'


# --------------------------------------------------------------------------------------- #
# joint markup
# --------------------------------------------------------------------------------------- #
#: Maya's own ``joint.side`` enum, in its own order - the index *is* the stored value, so this
#: list cannot be sorted, added to in the middle, or renamed without relabelling every skeleton
#: that has ever been saved.
SIDE_LABELS = ['Center', 'Left', 'Right', 'None']


# --------------------------------------------------------------------------------------- #
# extension points
# --------------------------------------------------------------------------------------- #
#: Packages outside this one that hold FRAG component classes. ``frag_base`` walks it on import
#: to find them. Nothing has ever filled it - it is the hook for a studio to add its own
#: components without editing this package - so the loop it feeds is a no-op today.
FRAG_NODE_PACKAGE_PATHS = []
