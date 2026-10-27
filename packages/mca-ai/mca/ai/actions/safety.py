"""
Safety Configuration for Tool Calling

This module provides configurable safety settings for the action system.

The safety system controls:
- Which commands are allowed to execute
- Whether user confirmation is required
- Dry-run mode for previewing commands without execution
- Logging of all command execution attempts

Classes:
    SafetyConfig - Configuration container for safety settings

Usage:
    from mca.ai.actions.safety import SafetyConfig

    # Create default config
    config = SafetyConfig()

    # Enable dry-run mode
    config.set_dry_run(True)

    # Check if command is allowed
    if config.is_allowed("polyCube"):
        ...
"""


class SafetyConfig:
    """
    Configuration for tool-calling safety controls.

    Controls dry-run mode, command whitelisting, and logging.
    This is a singleton configuration shared across the action system.
    """

    # Singleton instance
    _instance = None

    # Default configuration
    _dry_run = False
    _log_all_commands = True
    _require_confirm_for_unknown = True

    # Custom whitelist/blacklist overrides
    _custom_whitelist = set()
    _custom_blacklist = set()

    def __new__(cls):
        """Singleton pattern - return existing instance if available."""
        if cls._instance is None:
            cls._instance = super(SafetyConfig, cls).__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls):
        """
        Get the singleton instance.

        :return: SafetyConfig instance.
        :rtype: SafetyConfig
        """
        if cls._instance is None:
            cls._instance = SafetyConfig()
        return cls._instance

    @classmethod
    def is_dry_run(cls):
        """
        Check if dry-run mode is enabled.

        In dry-run mode, commands are validated but not executed.

        :return: True if dry-run mode is enabled.
        :rtype: bool
        """
        return cls._dry_run

    @classmethod
    def set_dry_run(cls, enabled):
        """
        Enable or disable dry-run mode.

        :param bool enabled: True to enable dry-run mode.
        """
        cls._dry_run = enabled

    @classmethod
    def should_log_commands(cls):
        """
        Check if command logging is enabled.

        :return: True if commands should be logged.
        :rtype: bool
        """
        return cls._log_all_commands

    @classmethod
    def set_log_commands(cls, enabled):
        """
        Enable or disable command logging.

        :param bool enabled: True to enable logging.
        """
        cls._log_all_commands = enabled

    @classmethod
    def requires_confirm_for_unknown(cls):
        """
        Check if unknown commands require confirmation.

        :return: True if unknown commands need user confirmation.
        :rtype: bool
        """
        return cls._require_confirm_for_unknown

    @classmethod
    def set_require_confirm_for_unknown(cls, enabled):
        """
        Set whether unknown commands require confirmation.

        :param bool enabled: True to require confirmation.
        """
        cls._require_confirm_for_unknown = enabled

    @classmethod
    def add_to_whitelist(cls, command):
        """
        Add a command to the custom whitelist.

        Commands on the whitelist are always treated as SAFE.

        :param str command: Command name to whitelist.
        """
        cls._custom_whitelist.add(command)
        # Remove from blacklist if present
        cls._custom_blacklist.discard(command)

    @classmethod
    def add_to_blacklist(cls, command):
        """
        Add a command to the custom blacklist.

        Commands on the blacklist are always blocked.

        :param str command: Command name to blacklist.
        """
        cls._custom_blacklist.add(command)
        # Remove from whitelist if present
        cls._custom_whitelist.discard(command)

    @classmethod
    def is_whitelisted(cls, command):
        """
        Check if a command is on the custom whitelist.

        :param str command: Command name.
        :return: True if whitelisted.
        :rtype: bool
        """
        return command in cls._custom_whitelist

    @classmethod
    def is_blacklisted(cls, command):
        """
        Check if a command is on the custom blacklist.

        :param str command: Command name.
        :return: True if blacklisted.
        :rtype: bool
        """
        return command in cls._custom_blacklist

    @classmethod
    def get_whitelist(cls):
        """
        Get the custom whitelist.

        :return: Set of whitelisted command names.
        :rtype: set
        """
        return cls._custom_whitelist.copy()

    @classmethod
    def get_blacklist(cls):
        """
        Get the custom blacklist.

        :return: Set of blacklisted command names.
        :rtype: set
        """
        return cls._custom_blacklist.copy()

    @classmethod
    def clear_custom_lists(cls):
        """Clear custom whitelist and blacklist."""
        cls._custom_whitelist.clear()
        cls._custom_blacklist.clear()

    @classmethod
    def reset(cls):
        """Reset all settings to defaults."""
        cls._dry_run = False
        cls._log_all_commands = True
        cls._require_confirm_for_unknown = True
        cls._custom_whitelist.clear()
        cls._custom_blacklist.clear()

    @classmethod
    def to_dict(cls):
        """
        Serialize current settings to a dictionary.

        :return: Settings dict.
        :rtype: dict
        """
        return {
            'dry_run': cls._dry_run,
            'log_all_commands': cls._log_all_commands,
            'require_confirm_for_unknown': cls._require_confirm_for_unknown,
            'custom_whitelist': list(cls._custom_whitelist),
            'custom_blacklist': list(cls._custom_blacklist),
        }

    @classmethod
    def from_dict(cls, data):
        """
        Load settings from a dictionary.

        :param dict data: Settings dict.
        """
        if 'dry_run' in data:
            cls._dry_run = data['dry_run']
        if 'log_all_commands' in data:
            cls._log_all_commands = data['log_all_commands']
        if 'require_confirm_for_unknown' in data:
            cls._require_confirm_for_unknown = data['require_confirm_for_unknown']
        if 'custom_whitelist' in data:
            cls._custom_whitelist = set(data['custom_whitelist'])
        if 'custom_blacklist' in data:
            cls._custom_blacklist = set(data['custom_blacklist'])
