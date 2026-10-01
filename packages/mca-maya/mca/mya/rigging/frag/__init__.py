"""
FRAG: the metadata graph that describes a rig, and the components it is built from.

Importing this package puts every component class, factory function and shared constant from the
modules below at package level, so a build script can write ``frag.FKComponent`` or
``frag.get_frag_rig`` without knowing which module either lives in. Filling the FRAGNode register is
a side effect of those imports, and it is what lets ``FRAGNode(network_node)`` hand back the right
subclass for any node in a scene - so a package that has not been imported is a component that
cannot be read back.

Modules already imported are dropped from ``sys.modules`` first, so importing this package again
during development picks up edited component code. Do not ``importlib.reload`` this package: purge
the ``mca.mya.rigging`` modules from ``sys.modules`` and import it again instead.

This lists the modules that have been ported, not the modules there will be; entries come back as
the components land.
"""

# python imports
import importlib
import inspect
import sys


#: The component modules, bases first and then what is built on them. Import order matters: a module
#: cannot be imported before the one it subclasses.
COMPONENT_MODULES = (
    'frag_base',
    'frag_root',
    'skeletal_mesh',
    'mesh_component',
    'frag_rig',
    'display_layers',
    'rig_component',
    'keyable_component',
    'multi_constraint',
    'animated_curves',
    'ik_component',
    'fk_component',
    'ikfk_component',
    'clavicle_component',
    'cog_component',
    'pelvis_component',
    'world_component',
    'pin_component',
)


def _purge_stale_submodules():
    """
    Forget the component modules already imported, so the imports below run against what is on disk.
    """

    prefix = __name__ + '.'
    for module_name in [name for name in sys.modules if name.startswith(prefix)]:
        if module_name[len(prefix):] in COMPONENT_MODULES:
            del sys.modules[module_name]


def _export_public_names(module):
    """
    Put the classes, functions and constants a component module defines at package level.

    Only what the module itself defines: the utilities and third-party modules it imported are its
    business, and re-exporting them would make ``frag.pm`` a thing callers could write.

    :param module module: A component module that has just been imported.
    """

    for name, value in vars(module).items():
        if name.startswith('_'):
            continue
        if inspect.isclass(value) or inspect.isfunction(value):
            if getattr(value, '__module__', '').startswith(__name__):
                globals()[name] = value
        elif name.isupper():
            globals()[name] = value


_purge_stale_submodules()
for _module_name in COMPONENT_MODULES:
    _export_public_names(importlib.import_module('{0}.{1}'.format(__name__, _module_name)))
del _module_name
