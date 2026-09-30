"""
What the package says about itself: mca_package.yaml and mca/mya/__init__.py.

Needs no Maya. This is the suite that would have caught the thing wrong with the manifest
for as long as it has existed - every path in it named a folder called ``mca.mya``, with a
dot, which has never been on disk.
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def body(suite):
    harness.add_sibling_packages()

    from mca.common.startup.configs import package_config
    from mca import mya

    suite.check('mya.MAYA_PATH is the folder the code is in', os.path.isdir(mya.MAYA_PATH))
    suite.check('mya.MAYA_PATH is mca/mya', os.path.basename(mya.MAYA_PATH) == 'mya')
    suite.check('mya.PACKAGE_ROOT is the package folder',
                os.path.basename(mya.PACKAGE_ROOT) == 'mca-maya')
    suite.check('the manifest path is normalised - no .. left in it',
                '..' not in mya.PACKAGE_FILE.replace(os.sep, '/').split('/'))
    suite.check('the manifest is where the constant says', os.path.isfile(mya.PACKAGE_FILE))

    # The duplicate the old __init__ carried.
    suite.check('MAYA_TOP_ROOT is gone - it was MAYA_PATH under a second name',
                not hasattr(mya, 'MAYA_TOP_ROOT'))
    suite.check('MAYA_MCA_PACKAGE is gone - PACKAGE_FILE replaces it',
                not hasattr(mya, 'MAYA_MCA_PACKAGE'))

    manifest = package_config.PackageManifest(mya.PACKAGE_FILE)
    suite.check('the manifest reads', bool(manifest.values))
    suite.check('it names this package', manifest.name == 'mca-maya', manifest.name)
    suite.check('it has a version', bool(manifest.version), manifest.version)

    problems = manifest.problems()
    suite.check('every path in the manifest is a folder that exists',
                not problems, '; '.join(problems))

    resolved = manifest.environment()
    suite.check('MCA_MAYA_BASE_PATH resolves to the code folder',
                os.path.normpath(resolved.get('MCA_MAYA_BASE_PATH', '')) ==
                os.path.normpath(mya.MAYA_PATH), resolved.get('MCA_MAYA_BASE_PATH'))

    paths = resolved.get('MCA_MAYA_PATHS', '')
    suite.check('a list-valued variable is joined the way the platform joins paths',
                os.pathsep in paths or paths.count(os.sep) >= 1, repr(paths))
    suite.check('and is not the repr of a Python list',
                not paths.startswith('['), repr(paths))
    for entry in paths.split(os.pathsep):
        suite.check('{} exists'.format(os.path.basename(entry)), os.path.isdir(entry), entry)

    # The spelling the old manifest used, which never matched a folder.
    raw = open(mya.PACKAGE_FILE, encoding='utf-8').read()
    declared = [line for line in raw.splitlines() if not line.lstrip().startswith('#')]
    suite.check("no path in the manifest says 'mca.mya'",
                not any('mca.mya' in line for line in declared))

    # And the mistake the reader was written to find, in the other direction: this package
    # must not set another DCC's variables, the way mca-ue's manifest did.
    suite.check('every variable is named for this package',
                all(name.startswith('MCA_MAYA_') for name in resolved),
                ', '.join(sorted(resolved)))


sys.exit(harness.run('package', body))
