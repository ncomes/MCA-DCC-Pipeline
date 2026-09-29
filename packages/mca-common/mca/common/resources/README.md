# Resources

The framework draws with icons, images, movies and stylesheets, and **none of them are in
this repository**. The folders come from the environment the launcher builds:

| what | where it comes from |
|---|---|
| the framework's icons | `MCA_ICONS_PATH` |
| the project's own icons | `<project>/Tools/Common/Tools/Resources/Icons` |
| images | `MCA_IMAGES_PATH` |
| animations | `MCA_MOVIES_PATH` |
| stylesheets | `MCA_STYLES_PATH` |

So a studio points at its own art and a clone with none still runs — `icon()` answers None
and says which name was missing, rather than failing to start.

## Why they are not here

The set this framework was using is 1,269 icons and 21 stylesheets with no licence file and
no attribution anywhere in them, and several of the names — `plumpy` among the icon folders,
and `adaptic`, `darkeum`, `devsion`, `genetive`, `incrypt` among the stylesheets — belong to
icon and Qt-theme packs that are sold commercially. Shipping them under this repository's
MIT licence would be claiming a licence over them that nobody here can grant.

Before any of it comes across, each set needs its provenance established: bought (and under
what terms), drawn in-house, or from a source whose licence allows redistribution. Anything
in-house can come over as it is; anything bought stays on the studio's own share, which is
what `MCA_ICONS_PATH` is for; anything whose origin cannot be established should be replaced.
