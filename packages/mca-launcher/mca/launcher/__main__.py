"""
``python -m mca.launcher`` - the same entry point as the ``mca-launcher`` command.
"""

# python imports
import sys

# mca imports
from mca.launcher.cli import main


if __name__ == '__main__':
    sys.exit(main())
