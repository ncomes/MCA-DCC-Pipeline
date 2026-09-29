"""
Package manifests, checked against the mistakes the real ones have in them.

The module this replaces could not run at all - it called three ``consts`` names that do not
exist - so the manifests it was meant to read had never been checked by anything. All three
in the depot are wrong in some way.

    python tests/test_package_config.py
"""

# python imports
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common.startup.configs import package_config  # noqa: E402
from mca.common.textio import datafile  # noqa: E402


def body(suite):
    temp = suite.temp

    # ---------------------------------------------------------------- #
    # A good one
    # ---------------------------------------------------------------- #
    package = os.path.join(temp, 'mca-example')
    os.makedirs(os.path.join(package, 'tools'))
    os.makedirs(os.path.join(package, 'resources', 'icons'))
    os.makedirs(os.path.join(package, 'utils'))

    datafile.write({
        'name': 'mca-example',
        'displayName': 'MCA Example',
        'depotName': 'maya',
        'version': '1.2.3',
        'required': True,
        'environment': {
            'MCA_MAYA_TOOLS_PATH': '{self}/tools',
            'MCA_MAYA_ICONS_PATH': '{self}/resources/icons',
            'MCA_MAYA_PATHS': ['{self}/tools', '{self}/utils'],
        },
        'urls': {'rigging': 'https://example.invalid/rigging', 'jira': ''},
    }, os.path.join(package, package_config.PACKAGE_FILE), fmt='yaml')

    manifest = package_config.read_package(package)
    suite.check('a package is read from the folder it is in', manifest is not None)
    suite.check('and says what it is',
                (manifest.name, manifest.version, manifest.depot_name) ==
                ('mca-example', '1.2.3', 'maya'),
                str((manifest.name, manifest.version, manifest.depot_name)))
    suite.check('the file can be found from a folder inside the package too',
                package_config.find_package_file(os.path.join(package, 'tools', 'deeper')) ==
                os.path.join(package, package_config.PACKAGE_FILE) or
                package_config.find_package_file(os.path.join(package, 'tools')) ==
                os.path.join(package, package_config.PACKAGE_FILE),
                package_config.find_package_file(os.path.join(package, 'tools')))

    environment = manifest.environment()
    suite.check('{self} becomes the folder the manifest is in',
                environment['MCA_MAYA_TOOLS_PATH'] == os.path.join(package, 'tools'),
                environment['MCA_MAYA_TOOLS_PATH'])

    # The one that produced "['a', 'b']" in an environment variable.
    suite.check('a list becomes paths joined the way this platform joins them, not a '
                'Python list formatted into a string',
                environment['MCA_MAYA_PATHS'] == os.pathsep.join(
                    [os.path.join(package, 'tools'), os.path.join(package, 'utils')]),
                environment['MCA_MAYA_PATHS'])
    suite.check('and there are no brackets or quotes anywhere in it',
                '[' not in environment['MCA_MAYA_PATHS'] and
                "'" not in environment['MCA_MAYA_PATHS'])

    suite.check('a manifest that makes sense has nothing to report',
                manifest.problems() == [], str(manifest.problems()))

    suite.check('empty urls are dropped, so a caller can just ask for one',
                manifest.urls == {'rigging': 'https://example.invalid/rigging'},
                str(manifest.urls))

    # ---------------------------------------------------------------- #
    # Applying it
    # ---------------------------------------------------------------- #
    os.environ.pop('MCA_MAYA_TOOLS_PATH', None)
    os.environ['MCA_MAYA_ICONS_PATH'] = 'set by the launcher'
    was_set = manifest.apply(overwrite=False)
    suite.check('applying sets what is not already set',
                'MCA_MAYA_TOOLS_PATH' in was_set and
                os.getenv('MCA_MAYA_TOOLS_PATH') == os.path.join(package, 'tools'),
                str(was_set))
    suite.check('and leaves alone what the launcher already said',
                os.getenv('MCA_MAYA_ICONS_PATH') == 'set by the launcher')

    # ---------------------------------------------------------------- #
    # The mistakes the real manifests actually have
    # ---------------------------------------------------------------- #
    unreal = os.path.join(temp, 'mca-ue')
    os.makedirs(unreal)
    datafile.write({
        'name': 'mca-unreal',
        'depotName': 'ue',
        'version': '1.0.0',
        # Copied from the Maya manifest and never renamed. This is verbatim what mca-ue has.
        'environment': {'MCA_MAYA_BASE_PATH': '{self}',
                        'MCA_MAYA_TOOLS_PATH': '{self}/mca.ue/tools'},
    }, os.path.join(unreal, package_config.PACKAGE_FILE), fmt='yaml')

    problems = package_config.PackageManifest(
        os.path.join(unreal, package_config.PACKAGE_FILE)).problems()
    suite.check('a package setting another DCC\'s variables is reported',
                any('named for another DCC' in one for one in problems), str(problems))
    suite.check('and so is a path that is not there - mca-maya points at mca.mya, with a '
                'dot, where the folder is mca/mya',
                any('not there' in one for one in problems), str(problems))

    bare = os.path.join(temp, 'mca-bare')
    os.makedirs(bare)
    datafile.write({'environment': {}}, os.path.join(bare, package_config.PACKAGE_FILE),
                   fmt='yaml')
    problems = package_config.PackageManifest(
        os.path.join(bare, package_config.PACKAGE_FILE)).problems()
    suite.check('a manifest with no name, version or depot says all three',
                len(problems) == 3, str(problems))

    # ---------------------------------------------------------------- #
    # Nothing to read
    # ---------------------------------------------------------------- #
    suite.check('a folder with no manifest answers None rather than raising',
                package_config.read_package(os.path.join(temp, 'nowhere')) is None)
    suite.check('and finding one where there is none answers empty',
                package_config.find_package_file('') == '')

    # ---------------------------------------------------------------- #
    # mca-common's own
    # ---------------------------------------------------------------- #
    import mca.common as common_package

    ours = package_config.read_package(os.path.dirname(common_package.__file__))
    suite.check('mca-common ships a manifest', ours is not None)
    suite.check('and it is this package',
                ours.name == 'mca-common' and ours.depot_name == 'common',
                '{} / {}'.format(ours.name, ours.depot_name))
    suite.check('and it has nothing wrong with it', ours.problems() == [],
                str(ours.problems()))
    suite.check('its urls are blank until there are pages to point at, rather than a '
                'previous employer\'s wiki', ours.urls == {}, str(ours.urls))

    suite.note('checks_written', len(suite.checks))


if __name__ == '__main__':
    sys.exit(harness.run('package_config', body))
