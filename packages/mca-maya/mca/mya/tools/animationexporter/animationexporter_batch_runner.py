"""
Animation Exporter Batch Runner - Headless execution

This module runs animation exports in a clean headless Maya session.

Workflow:
1. Load parameters from JSON file
2. Open the saved scene
3. Export FRAG animation sequences using animationexporter_utils
4. Save output files
5. Log results
6. Quit

No codebase dependencies beyond mca-common and mca-maya essentials.
Clean Maya session without userSetup.py interference.
"""

import sys
import os
import json


def log(message, log_file):
    """
    Log message to both console and file.

    :param str message: Message to log.
    :param str log_file: Path to log file.
    """
    # Replace Unicode characters with ASCII for Windows console compatibility
    safe_message = message.replace('\u2713', '[OK]').replace('\u2717', '[ERROR]').replace('\u2192', '->')
    print(safe_message)
    sys.stdout.flush()
    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(message + '\n')  # Keep Unicode in file
            f.flush()
    except Exception as e:
        print(f"ERROR writing to log: {e}")


def run_batch_export():
    """
    Run animation export in batch Maya.

    Expects params file path as first command line argument after this script.

    :return: Exit code (0 for success, 1 for failure).
    :rtype: int
    """
    from maya import cmds

    # Get params file from command line
    if len(sys.argv) < 2:
        print("ERROR: No parameters file specified")
        return 1

    params_file = sys.argv[1]

    if not os.path.exists(params_file):
        print(f"ERROR: Parameters file not found: {params_file}")
        return 1

    # Load parameters
    try:
        with open(params_file, 'r') as f:
            params = json.load(f)
    except Exception as e:
        print(f"ERROR: Could not load parameters: {e}")
        return 1

    log_file = params.get('log_file', 'animation_export.log')

    log("=" * 60, log_file)
    log("Animation Exporter Batch Runner (maya.exe)", log_file)
    log("=" * 60, log_file)
    log(f"Parameters file: {params_file}", log_file)
    log(f"Log file: {log_file}", log_file)

    try:
        # Extract parameters
        scene_file = params['scene_file']
        rig_names = params['rig_names']
        sequences_to_skip = params.get('sequences_to_skip', [])

        log(f"Scene: {scene_file}", log_file)
        log(f"Rigs: {rig_names}", log_file)
        log(f"Sequences to skip: {sequences_to_skip if sequences_to_skip else 'None'}", log_file)

        # Load scene
        log(f"Loading scene: {scene_file}", log_file)
        try:
            cmds.file(scene_file, open=True, force=True)
            log("\u2713 Scene loaded", log_file)
        except Exception as e:
            log(f"\u2717 ERROR loading scene: {e}", log_file)
            import traceback
            log(traceback.format_exc(), log_file)
            return 1

        # Initialize MCA framework in headless mode
        log("Initializing MCA framework (headless)...", log_file)
        try:
            # Add mca-common and mca-maya to path
            packages_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..')
            packages_dir = os.path.abspath(packages_dir)

            mca_common = os.path.join(packages_dir, 'mca-common')
            mca_maya = os.path.join(packages_dir, 'mca-maya')

            if mca_common not in sys.path:
                sys.path.insert(0, mca_common)
            if mca_maya not in sys.path:
                sys.path.insert(0, mca_maya)

            # Use headless startup instead of normal startup
            # This skips all Qt/UI operations and only initializes core functionality
            from mca.mya.startup import headless_startup
            headless_startup.init(skip_logging=False)
            log("\u2713 MCA framework initialized (headless)", log_file)

            # Now import animation exporter modules
            from mca.mya.rigging import frag
            from mca.mya.tools.animationexporter import animationexporter_utils as ae_utils
            log("\u2713 Animation exporter modules imported", log_file)
        except Exception as e:
            log(f"\u2717 ERROR initializing MCA framework: {e}", log_file)
            import traceback
            log(traceback.format_exc(), log_file)
            return 1

        # Find FRAG rigs in scene
        log("Finding FRAG rigs...", log_file)
        all_frag_roots = frag.get_all_frag_roots()
        log(f"Found {len(all_frag_roots)} FRAG roots in scene", log_file)

        # Match rigs by name
        rigs_to_export = []
        for frag_root in all_frag_roots:
            frag_rig = frag_root.get_rig()
            if not frag_rig:
                continue

            # Get rig name
            try:
                rig_name = frag_rig.name()
            except:
                rig_name = str(frag_rig)

            if rig_name in rig_names:
                rigs_to_export.append(frag_rig)
                log(f"\u2713 Found rig: {rig_name}", log_file)

        if not rigs_to_export:
            log("\u2717 ERROR: No matching rigs found in scene", log_file)
            return 1

        log(f"Exporting {len(rigs_to_export)} rig(s)", log_file)

        # Load FBX plugin (required for export)
        log("Loading FBX plugin...", log_file)
        try:
            if not cmds.pluginInfo('fbxmaya', query=True, loaded=True):
                cmds.loadPlugin('fbxmaya')
            log("\u2713 FBX plugin loaded", log_file)
        except Exception as e:
            log(f"\u2717 WARNING: Could not load FBX plugin: {e}", log_file)
            log("Attempting export anyway...", log_file)

        # Export animations
        log("Exporting animations...", log_file)
        try:
            ae_utils.export_frag_sequences_cmd(
                frag_rig_list=rigs_to_export,
                sequences_to_skip=sequences_to_skip
            )
            log("\u2713 Export completed", log_file)
        except Exception as e:
            log(f"\u2717 ERROR during export: {e}", log_file)
            import traceback
            log(traceback.format_exc(), log_file)
            return 1

        log("=" * 60, log_file)
        log("SUCCESS: Animation export completed", log_file)
        log("=" * 60, log_file)

        # Cleanup temp files
        cleanup_temp_files(params_file, log_file)

        return 0

    except Exception as e:
        log(f"\u2717 ERROR: {str(e)}", log_file)
        import traceback
        log(traceback.format_exc(), log_file)

        # Cleanup temp files even on error
        cleanup_temp_files(params_file, log_file)

        return 1


def cleanup_temp_files(params_file, log_file):
    """
    Clean up temporary parameter and MEL script files.

    :param str params_file: Path to params JSON file.
    :param str log_file: Path to log file (for logging cleanup).
    """
    # Clean up params file
    if os.path.exists(params_file):
        try:
            os.remove(params_file)
            log(f"Cleaned up params file: {params_file}", log_file)
        except Exception as e:
            log(f"Could not remove params file: {e}", log_file)

    # Clean up MEL script (same directory, same timestamp)
    params_dir = os.path.dirname(params_file)
    params_basename = os.path.basename(params_file)
    # Extract timestamp from params filename (anim_export_params_TIMESTAMP.json)
    if params_basename.startswith('anim_export_params_'):
        timestamp = params_basename.replace('anim_export_params_', '').replace('.json', '')
        mel_script = os.path.join(params_dir, f"anim_export_batch_{timestamp}.mel")
        if os.path.exists(mel_script):
            try:
                os.remove(mel_script)
                log(f"Cleaned up MEL script: {mel_script}", log_file)
            except Exception as e:
                log(f"Could not remove MEL script: {e}", log_file)


# Entry point when called from MEL
if __name__ == '__main__' or __name__ == '__builtin__':
    try:
        exit_code = run_batch_export()
    except Exception as e:
        print(f"FATAL ERROR in batch runner: {e}")
        import traceback
        traceback.print_exc()
        exit_code = 1

    # Force quit Maya - multiple methods to ensure it exits
    print(f"Exiting Maya with code {exit_code}")
    try:
        from maya import cmds
        cmds.quit(force=True, exitCode=exit_code)
    except:
        # If cmds.quit fails, try standalone
        import sys
        sys.exit(exit_code)
