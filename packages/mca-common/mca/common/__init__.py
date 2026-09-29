"""
mca-common: what every DCC in the pipeline shares.

Nothing in here imports a DCC. A module that needs Maya belongs in ``mca-maya``; what is
here runs in Maya, MotionBuilder, Unreal, a standalone Python, and the test suite.
"""

__version__ = '3.0.0'
