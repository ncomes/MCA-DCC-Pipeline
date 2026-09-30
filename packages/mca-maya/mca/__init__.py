"""
The ``mca`` namespace.

Declared as a namespace package so ``mca-common``, ``mca-maya``, ``mca-mobu`` and
``mca-unreal`` can be installed and updated separately and still import as one ``mca``.
"""

__path__ = __import__('pkgutil').extend_path(__path__, __name__)
