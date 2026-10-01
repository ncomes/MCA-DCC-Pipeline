"""
Everything the launcher can do, as functions that answer instead of raising.

This module is the launcher. The window is a set of buttons wired to it, the command line is
an argument parser wired to it, and an MCP tool would be a spec wired to it. There is no
operation an artist can do by clicking that a script cannot do by calling - which is the
property that makes the dependency guarantee possible, because ``launch`` is the only way in
and it calls ``ensure_dependencies`` itself.

Every function answers ``{'ok': bool, 'result': ..., 'message': str}``. The message is
written for a person: on a failure it says what to do next.
"""

# python imports
import logging
import os
import sys

# mca imports
from mca import launcher
from mca.launcher.core import dccs, dependencies, environment, platform_paths, prefs
from mca.launcher.core import projects, shortcuts
from mca.launcher.core.dccs import base
from mca.launcher.core.contract import safe


logger = logging.getLogger('mca-launcher')


# ---------------------------------------------------------------------------- #
# Projects
# ---------------------------------------------------------------------------- #
@safe
def list_projects():
    """
    The projects set up on this machine.

    :return: Response whose result is a list of projects, and which one is current.
    :rtype: dict
    """

    found = projects.list_projects()
    current = prefs.GlobalSelections.load().current([one['name'] for one in found])
    result = {'projects': found, 'current': current}
    if not found:
        return result, ('No projects are set up yet. Add one with the launcher\'s project '
                        'setup, or api.save_project(name, project_root, framework_path).')
    return result, ('{} project(s): {}. Current: {}.'
                    .format(len(found), ', '.join(one['name'] for one in found),
                            current or 'none'))


@safe
def current_project():
    """
    :return: Response whose result is the current project's preferences as plain data.
    :rtype: dict
    """

    name = _resolve_project(None)
    project = prefs.ProjectPrefs.load(name)
    return ({'name': name, 'values': project.values, 'missing': project.missing()},
            'Current project is {}, rooted at {}.'.format(name, project.project_root))


@safe
def set_current_project(name):
    """
    Remember which project the launcher opens with.

    :param str name: The project name.
    :return: Response whose result is the name.
    :rtype: dict
    """

    available = prefs.project_names()
    if name not in available:
        raise ValueError('There is no project called {!r}. There is: {}.'
                         .format(name, ', '.join(available) or 'nothing'))
    globals_ = prefs.GlobalSelections.load()
    globals_.project_name = name
    globals_.save()
    return name, '{} is now the project the launcher opens with.'.format(name)


@safe
def save_project(name, project_root, framework_path, art_path='', art_paths=None,
                 common_tools='', make_current=True):
    """
    Create or update a project.

    :param str name: The project name.
    :param str project_root: The project root folder.
    :param str framework_path: The packages folder, or the folder holding it.
    :param str art_path: The art root. Used to fill in the art folders that are not given.
    :param dict art_paths: Any of the MCA_*_PATH values, by environment name.
    :param str common_tools: A shared tools folder, if there is one.
    :param bool make_current: Open the launcher with this project from now on.
    :return: Response whose result is the saved values.
    :rtype: dict
    """

    values = {}
    if art_path:
        values['MCA_ART_PATH'] = art_path
        values.update(projects.default_art_paths(art_path))
    values.update(art_paths or {})

    project = projects.save_project(name, project_root, framework_path,
                                    art_paths=values, common_tools=common_tools)
    if make_current:
        globals_ = prefs.GlobalSelections.load()
        globals_.project_name = project.project_name
        globals_.save()

    return ({'name': project.project_name, 'values': project.values},
            'Saved {} to {}. Framework: {}.'
            .format(project.project_name, prefs.project_prefs_file(project.project_name),
                    project.framework_path))


@safe
def remove_project(name):
    """
    Forget a project. Its preferences go; its art and its code do not.

    :param str name: The project name.
    :return: Response whose result is the folder that was deleted.
    :rtype: dict
    """

    folder = projects.remove_project(name)
    globals_ = prefs.GlobalSelections.load()
    if globals_.project_name == name:
        globals_.project_name = ''
        globals_.save()
    return folder, 'Removed {}. Nothing outside that folder was touched.'.format(folder)


# ---------------------------------------------------------------------------- #
# What can be launched
# ---------------------------------------------------------------------------- #
@safe
def dcc_targets(dcc=None, project=None, include_missing=True):
    """
    What is installed on this machine, and what was picked last time.

    :param str dcc: One DCC name, or None for all of them.
    :param str project: The project whose remembered choice to report. None uses the current
        one, and no project at all is fine - the answer is then just what is installed.
    :param bool include_missing: Also list the versions this launcher supports that are not
        installed, each marked ``installed: False``. They cannot be launched; they can be
        installed.
    :return: Response whose result is a list of DCC entries.
    :rtype: dict
    """

    wanted = [dccs.get(dcc)] if dcc else list(dccs.DCCS)

    selections = None
    installers = ''
    project_name = _resolve_project(project, required=False)
    if project_name:
        selections = prefs.Selections.load(project_name)
        # Read once, not once per DCC: it is a folder test, and there are three of them.
        installers = projects.installers_root(prefs.ProjectPrefs.load(project_name))

    listing = []
    for one in wanted:
        # Everything the launcher knows about, not only what is here: a version that is
        # supported but missing should be visible and offerable, not absent. That includes
        # versions only the project's installer folder knows about.
        targets = [target.as_dict() for target in
                   (one.available(installers) if include_missing else one.targets())]
        keys = [target['key'] for target in targets if target['installed']]
        listing.append({
            'dcc': one.name,
            'label': one.label,
            'icon': one.icon,
            'targets': targets,
            'chosen': selections.chosen(one.name, keys) if selections else (keys[0] if keys
                                                                           else ''),
            'unreal_projects': (selections.unreal_projects
                                if selections and one.name == 'unreal' else []),
            'installers': installers,
        })

    total = sum(len([t for t in one['targets'] if t['installed']]) for one in listing)
    if not total:
        return listing, ('Nothing installed was found. The launcher reads the registry, so '
                         'this means Maya, MotionBuilder and Unreal are not installed on '
                         'this machine - or are installed somewhere the registry does not '
                         'know about.')
    return listing, ('Found {}.'.format(', '.join(
        '{} {}'.format(one['label'],
                       ', '.join(target['key'] for target in one['targets']
                                 if target['installed']))
        for one in listing if any(t['installed'] for t in one['targets']))))


@safe
def choose(dcc, key, project=None):
    """
    Remember a choice without launching anything.

    :param str dcc: The DCC name.
    :param str key: The version, or for Unreal the project path.
    :param str project: The project. None uses the current one.
    :return: Response whose result is the choice.
    :rtype: dict
    """

    dcc_object = dccs.get(dcc)
    name = _resolve_project(project)
    selections = prefs.Selections.load(name)
    selections.choose(dcc_object.name, key)
    selections.save(name)
    return {'dcc': dcc, 'key': key}, 'Remembered {} {} for {}.'.format(dcc, key, name)


@safe
def install_dcc(dcc, key=None, project=None):
    """
    Get a version the machine does not have.

    Runs the project's own installer when it has one - a studio keeps them in a folder laid
    out per DCC and version, and the installer is whatever it put there: an ``.exe``, a
    ``.bat`` that copies a prepared build off a share, a ``.ps1``, an ``.msi``. Otherwise it
    opens the vendor's download page. Doing nothing and saying "not installed" would be the
    third option, and the least useful.

    :param str dcc: The DCC name.
    :param str key: The version wanted. None takes the newest the project can install, which
        is what "Install" on a row with no installed version means.
    :param str project: The project. None uses the current one.
    :return: Response saying what was started or opened.
    :rtype: dict
    """

    import subprocess
    import webbrowser

    dcc_object = dccs.get(dcc)

    project_name = _resolve_project(project, required=False)
    root = ''
    if project_name:
        root = projects.installers_root(prefs.ProjectPrefs.load(project_name))

    if not key:
        # Nothing chosen: offer the newest thing the project can actually install, and fall
        # back to the newest version this launcher knows about so the download page is still
        # a sensible one.
        installable = dcc_object.installer_versions(root)
        if installable:
            key = sorted(installable, key=base.version_sort_key)[-1]
        elif dcc_object.known_versions:
            key = sorted(dcc_object.known_versions, key=base.version_sort_key)[-1]
        else:
            key = ''

    if key and dcc_object.is_installed(key):
        return ({'installed': True, 'dcc': dcc_object.name, 'key': key},
                '{} {} is already installed.'.format(dcc_object.label, key))

    installer = dcc_object.installer(key, root) if key else ''
    if installer:
        # The installer is the project's, not ours: start it the way its kind needs starting
        # and let it do its own talking.
        command = base.installer_command(installer)
        logger.info('running installer: %s', ' '.join(command))
        subprocess.Popen(command, cwd=os.path.dirname(installer))
        return ({'installer': installer, 'command': command, 'dcc': dcc_object.name,
                 'key': key},
                'Started {} for {} {}. Once it finishes, press Refresh - the launcher reads '
                'the registry, so the new version appears by itself.'
                .format(os.path.basename(installer), dcc_object.label, key))

    if not dcc_object.download_url:
        raise ValueError('{} {} is not installed, and there is no installer for it in this '
                         'project and no download page on record.'
                         .format(dcc_object.label, key or 'anything'))

    webbrowser.open(dcc_object.download_url)
    if not root:
        where = 'this project has no installer folder'
    elif not dcc_object.installer_folder:
        where = 'the launcher has no installer folder name for {}'.format(dcc_object.label)
    else:
        where = ('this project\'s installer folder has nothing for that version ({})'
                 .format(os.path.join(root, dcc_object.installer_folder, str(key))))
    return ({'url': dcc_object.download_url, 'dcc': dcc_object.name, 'key': key,
             'installers_root': root},
            'Opened the download page for {} {}, because {}. Install it, then press Refresh.'
            .format(dcc_object.label, key or '', where))


# ---------------------------------------------------------------------------- #
# Shortcuts
# ---------------------------------------------------------------------------- #
@safe
def create_shortcut(dcc, key=None, project=None, folder='', name=''):
    """
    Put a shortcut on the desktop that starts one DCC for one project.

    The shortcut carries the project by name, not "whichever is current": a shortcut whose
    behaviour depends on a setting you cannot see from the desktop is a trap. It does not
    skip the dependency check - it runs the same ``api.launch`` the window does, which
    refuses when the packages are not ready. What it skips is the window.

    :param str dcc: The DCC name.
    :param str key: The version, or for Unreal the project path. None uses what is picked.
    :param str project: The project. None uses the current one.
    :param str folder: Where to write it. Empty means the desktop.
    :param str name: What to call it, without .lnk. Empty means "Maya 2025 - SampleGame".
    :return: Response whose result is the shortcut's path.
    :rtype: dict
    """

    dcc_object = dccs.get(dcc)
    project_name = _resolve_project(project)

    if not key:
        installed = [target.key for target in dcc_object.targets()]
        key = prefs.Selections.load(project_name).chosen(dcc_object.name, installed)
        if not key:
            raise ValueError('There is no {} on this machine to make a shortcut for.'
                             .format(dcc_object.label))

    if dcc_object.name != 'unreal' and not dcc_object.is_installed(key):
        raise ValueError('{} {} is not installed here, so a shortcut to it would not start '
                         'anything. Install it first.'.format(dcc_object.label, key))

    target, leading = shortcuts.runner()
    if not target:
        raise ValueError('The launcher cannot work out how it would be started from a '
                         'shortcut: it is not a frozen build, there is no mca-launcher '
                         'command beside {}, and {} is missing.'
                         .format(sys.executable, shortcuts.RUNNER_NAME))

    where = folder or shortcuts.desktop_folder()
    label = name or shortcuts.shortcut_name(dcc_object.label, key, project_name)
    path = os.path.join(where, label + '.lnk')

    written = shortcuts.write(
        path, target,
        arguments=leading + ['{}:{}'.format(dcc_object.name, key), '--project', project_name],
        working_directory=os.path.dirname(target),
        icon=dcc_object.executable(key),
        description='Start {} {} for {} with the MCA pipeline.'
                    .format(dcc_object.label, key, project_name))

    message = ('Put "{}" on your desktop. It starts {} {} for {} without opening the '
               'launcher.'.format(label, dcc_object.label, key, project_name))

    # A .lnk cannot carry an environment variable, so a shortcut made by a launcher that is
    # running with redirected folders - first_run.bat, or a test - will read the real ones
    # when it is double-clicked, and find no such project. Say so rather than leaving a
    # shortcut that fails later for a reason nobody could guess.
    sandboxed = [name for name in ('MCA_PREFS_ROOT', 'MCA_DEPS_ROOT') if os.getenv(name)]
    if sandboxed:
        message += (' Note: this launcher is running with {} redirected, and a shortcut '
                    'cannot carry that - double-clicking it uses the real preferences and '
                    'dependency folders.'.format(' and '.join(sandboxed)))

    return ({'path': written, 'dcc': dcc_object.name, 'key': key, 'project': project_name,
             'target': target, 'redirected': sandboxed},
            message)


# ---------------------------------------------------------------------------- #
# Dependencies
# ---------------------------------------------------------------------------- #
@safe
def dependency_status(dcc, key, project=None):
    """
    Whether a DCC version has the dependencies the framework needs.

    Cheap: it reads one stamp file and compares a hash. Nothing is started.

    :param str dcc: The DCC name.
    :param str key: The version, or for Unreal the project path.
    :param str project: The project. None uses the current one.
    :return: Response whose result says whether it is satisfied, and why.
    :rtype: dict
    """

    dcc_object = dccs.get(dcc)
    name = _resolve_project(project)
    project_prefs = prefs.ProjectPrefs.load(name)
    deps_key = dcc_object.deps_key(key)

    answer = dependencies.status(dcc_object.name, deps_key, project_prefs.framework_path)
    answer['interpreter'] = dcc_object.interpreter(key)
    return answer, answer['reason']


@safe
def ensure_dependencies(dcc, key, project=None, force=False, progress=None):
    """
    Install a DCC version's dependencies if they are missing, out of date, or unproven.

    This is the guarantee: the first time a project is opened, and every time anything about
    the requirements or the folder has changed, the packages are installed with that DCC's
    own interpreter and then proved by importing them. When there is nothing to do it costs
    a file read.

    :param str dcc: The DCC name.
    :param str key: The version, or for Unreal the project path.
    :param str project: The project. None uses the current one.
    :param bool force: Reinstall even when the stamp says it is fine.
    :param callable progress: Called with each line of progress. May be None.
    :return: Response whose result says what happened.
    :rtype: dict
    """

    dcc_object = dccs.get(dcc)
    name = _resolve_project(project)
    project_prefs = prefs.ProjectPrefs.load(name)
    deps_key = dcc_object.deps_key(key)
    interpreter = dcc_object.interpreter(key)

    if not interpreter:
        raise ValueError('{} {} does not appear to be installed here, so its dependencies '
                         'cannot be installed: no interpreter was found. The launcher reads '
                         'the registry to find it.'.format(dcc_object.label, key))

    outcome = dependencies.ensure(dcc_object.name, deps_key, project_prefs.framework_path,
                                 interpreter, progress=progress, force=force)
    if not outcome['ok']:
        # A failed install is a failed response, so no caller can miss it and launch anyway.
        from mca.launcher.core.contract import failed
        return failed(outcome['message'], outcome)
    return outcome, outcome['message']


# ---------------------------------------------------------------------------- #
# Launching
# ---------------------------------------------------------------------------- #
@safe
def launch(dcc, key=None, project=None, progress=None, force_dependencies=False):
    """
    Start a DCC with the pipeline on its path.

    The order is the point:

    1. resolve the project and its framework path,
    2. find that DCC version's own interpreter,
    3. **make sure its dependencies are installed and importable**, and stop here if they
       are not,
    4. build the environment,
    5. start it, and remember what was picked.

    Step 3 cannot be skipped. A DCC started without its dependencies looks like working
    software with broken tools, and that is the most expensive kind of failure to diagnose.

    :param str dcc: The DCC name.
    :param str key: The version, or for Unreal the project path. None uses what was picked
        last time, or the newest installed version.
    :param str project: The project. None uses the current one.
    :param callable progress: Called with progress lines. May be None.
    :param bool force_dependencies: Reinstall the dependencies first.
    :return: Response whose result says what was started.
    :rtype: dict
    """

    def say(text):
        logger.info(text)
        if progress:
            progress(text)

    dcc_object = dccs.get(dcc)
    project_name = _resolve_project(project)
    project_prefs = prefs.ProjectPrefs.load(project_name)
    missing = project_prefs.missing()
    if missing:
        raise ValueError('The project {} is not fully set up: {} still needs a value. Open '
                         'the launcher\'s project setup.'
                         .format(project_name, ', '.join(missing)))

    selections = prefs.Selections.load(project_name)

    if not key:
        available = [target.key for target in dcc_object.targets()]
        key = selections.chosen(dcc_object.name, available)
        if not key:
            raise ValueError('No {} is installed on this machine, so there is nothing to '
                             'start.'.format(dcc_object.label))

    interpreter = dcc_object.interpreter(key)
    if not interpreter:
        raise ValueError('{} {} is not installed here, or its files have moved: no Python '
                         'interpreter was found for it.'.format(dcc_object.label, key))

    say('Checking dependencies for {} {}...'.format(dcc_object.label, key))
    checked = ensure_dependencies(dcc_object.name, key, project=project_name,
                                 force=force_dependencies, progress=progress)
    if not checked['ok']:
        # Refuse, and hand the reason straight back. Nothing is started.
        from mca.launcher.core.contract import failed
        return failed('{} was not started, because its dependencies are not ready. {}'
                      .format(dcc_object.label, checked['message']), checked['result'])

    values = environment.build(project_prefs, dcc_object.name, key)
    say('Starting {} {}...'.format(dcc_object.label, key))
    pid = dcc_object.launch(key, values)

    selections.choose(dcc_object.name, key)
    selections.save(project_name)

    result = {'dcc': dcc_object.name, 'key': key, 'pid': pid, 'project': project_name,
              'dependencies': checked['result'], 'environment': environment.describe(values)}
    message = ('{} {} started for {} (pid {}). {}'
               .format(dcc_object.label, key, project_name, pid, checked['message']))
    return result, message


# ---------------------------------------------------------------------------- #
# Unreal projects
# ---------------------------------------------------------------------------- #
@safe
def unreal_projects(project=None):
    """
    :param str project: The project. None uses the current one.
    :return: Response whose result is the .uproject paths that have been added.
    :rtype: dict
    """

    # Asking what Unreal projects are set up is a read, and a machine with no project set up
    # yet is a real state the window asks about on its very first draw. Refusing it there
    # meant a logged traceback behind a window that was working perfectly.
    name = _resolve_project(project, required=False)
    if not name:
        return [], 'No project is set up yet, so no Unreal projects have been added.'

    paths = prefs.Selections.load(name).unreal_projects
    listing = []
    unreal = dccs.get('unreal')
    for path in paths:
        listing.append({'path': path, 'name': os.path.splitext(os.path.basename(path))[0],
                        'exists': os.path.isfile(path),
                        'engine': unreal.engine_for_project(path)})
    return listing, ('{} Unreal project(s) added.'.format(len(listing)) if listing
                     else 'No Unreal projects have been added yet.')


@safe
def add_unreal_project(path, project=None):
    """
    :param str path: A .uproject file.
    :param str project: The project. None uses the current one.
    :return: Response whose result is the path.
    :rtype: dict
    """

    if not path or not str(path).lower().endswith('.uproject'):
        raise ValueError('That is not an Unreal project file: {}'.format(path))
    if not os.path.isfile(path):
        raise ValueError('There is no file at {}.'.format(path))

    name = _resolve_project(project)
    selections = prefs.Selections.load(name)
    added = selections.add_unreal_project(path)
    selections.last_browse = os.path.dirname(path)
    selections.save(name)

    engine = dccs.get('unreal').engine_for_project(path)
    return ({'path': os.path.normpath(path), 'engine': engine, 'added': added},
            '{} {} (engine {}).'.format('Added' if added else 'Already had',
                                        os.path.basename(path), engine or 'unknown'))


@safe
def remove_unreal_project(path, project=None):
    """
    :param str path: A .uproject file.
    :param str project: The project. None uses the current one.
    :return: Response whose result says whether it was there.
    :rtype: dict
    """

    name = _resolve_project(project)
    selections = prefs.Selections.load(name)
    removed = selections.remove_unreal_project(path)
    selections.save(name)
    return ({'path': path, 'removed': removed},
            'Removed {}.'.format(os.path.basename(str(path))) if removed
            else '{} was not in the list.'.format(os.path.basename(str(path))))


# ---------------------------------------------------------------------------- #
# Diagnosis
# ---------------------------------------------------------------------------- #
@safe
def doctor(project=None):
    """
    Everything worth knowing when something is wrong, in one call.

    Written for the question "why will this not start", asked by a person or an agent: where
    the launcher is looking, what it found, and the state of every dependency folder.

    :param str project: The project. None uses the current one.
    :return: Response whose result is the whole picture.
    :rtype: dict
    """

    project_name = _resolve_project(project, required=False)
    project_prefs = prefs.ProjectPrefs.load(project_name) if project_name else None

    report = {
        'launcher_version': launcher.__version__,
        'platform': 'windows' if platform_paths.IS_WINDOWS else 'other',
        'preferences_folder': platform_paths.preferences_folder(),
        'dependencies_root': platform_paths.dependencies_root(),
        'projects': [one['name'] for one in projects.list_projects()],
        'project': project_name,
        'framework_path': project_prefs.framework_path if project_prefs else '',
        'requirements': '',
        'dccs': [],
        'problems': [],
    }

    if not project_name:
        report['problems'].append('No project is set up, so there is nothing to launch yet.')
    elif project_prefs.missing():
        report['problems'].append('The project is missing: {}.'
                                  .format(', '.join(project_prefs.missing())))

    if project_prefs and project_prefs.framework_path:
        try:
            report['requirements'] = dependencies.requirements_path(
                project_prefs.framework_path)
        except ValueError as error:
            report['problems'].append(str(error))

    for one in dccs.DCCS:
        for target in one.targets():
            entry = {'dcc': one.name, 'key': target.key, 'label': target.label,
                     'interpreter': one.interpreter(target.key),
                     'dependencies': 'unknown'}
            if project_prefs and report['requirements']:
                state = dependencies.status(one.name, one.deps_key(target.key),
                                           project_prefs.framework_path)
                entry['dependencies'] = 'ready' if state['satisfied'] else 'not ready'
                entry['reason'] = state['reason']
                entry['target'] = state['target']
                if not state['satisfied']:
                    report['problems'].append('{}: {}'.format(target.label, state['reason']))
            report['dccs'].append(entry)

    if not report['dccs']:
        report['problems'].append('No installed DCC was found in the registry.')

    summary = ('{} DCC version(s) found, {} problem(s).'
               .format(len(report['dccs']), len(report['problems'])))
    return report, summary


# ---------------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------------- #
def _resolve_project(name, required=True):
    """
    Work out which project a call is about.

    :param str name: A project name, or None for the current one.
    :param bool required: Raise when there is none. False answers '' instead, which is what
        a report wants.
    :return: The project name.
    :rtype: str
    :raises ValueError: When a project is needed and there is not one.
    """

    available = prefs.project_names()
    if name:
        if name not in available:
            raise ValueError('There is no project called {!r}. There is: {}.'
                             .format(name, ', '.join(available) or 'nothing'))
        return name

    current = prefs.GlobalSelections.load().current(available)
    if current:
        return current
    if required:
        raise ValueError('No project is set up yet. Run the launcher\'s project setup, or '
                         'call api.save_project(name, project_root, framework_path).')
    return ''
