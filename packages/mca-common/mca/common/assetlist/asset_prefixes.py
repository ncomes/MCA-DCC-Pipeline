"""
The prefixes the project's file names start with.

A declaration, not code: one place to read them from, so a tool building a file name and a
tool recognising one agree. Unreal's own naming convention is where most of these come from.
"""

#: Skeletal mesh - a mesh with a skeleton, ie a character.
SK = 'SK_'

#: Static mesh - a mesh with no skeleton, ie a prop.
SM = 'SM_'

#: Texture.
TEXTURE = 'T_'

#: Material.
MATERIAL = 'M_'

#: Blueprint.
BP = 'BP_'

#: Animation sequence.
ANIM = 'ANIM_'

#: A single pose.
POSE = 'POSE_'

#: Cinematic animation.
CIN = 'CIN_'

#: Animation blueprint.
ABP = 'ABP_'

#: Skeleton.
SKEL = 'SKEL_'

#: Control rig.
CR = 'CR_'
