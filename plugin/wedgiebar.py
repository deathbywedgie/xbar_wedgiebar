#!/usr/bin/env PYTHONIOENCODING=UTF-8 python3

# <xbar.title>wedgiebar</xbar.title>
# <xbar.version>v.0</xbar.version>
# <xbar.author>Chad Roberts</xbar.author>
# <xbar.author.github>deathbywedgie</xbar.author.github>
# <xbar.desc>Various helpful actions for all</xbar.desc>
# <xbar.image></xbar.image>
# <xbar.dependencies>See readme.md</xbar.dependencies>
# <xbar.abouturl>https://github.com/deathbywedgie/xbar_wedgiebar</xbar.abouturl>

import argparse
import base64
import collections.abc
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import traceback
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from numbers import Number
from pathlib import Path
from typing import Dict

import clipboard
import configobj
import psutil
from dataclasses_json import dataclass_json


# Global static variables

# Update 2023-09-12: Considered replacing the ini file with zshrc environment variables, but env vars are apparently not accessible to xbar
user_config_file = "xbar_wedgiebar.ini"

# Return either "Dark" or "Light" for the OS theme
OS_THEME: str = os.popen('defaults read -g AppleInterfaceStyle 2> /dev/null').read().strip() or "Light"


def get_args():
    # Range of available args and expected input
    parser = argparse.ArgumentParser(description="wedgiebar xbar plugin")

    # Inputs expected from user
    parser.add_argument("action", nargs='?', type=str, help="Name of an action to execute")

    # Optional args:
    parser.add_argument("-l", "--list", dest="list_actions", action="store_true", help="List available actions")

    # take in the arguments provided by user
    return parser.parse_args()


class Plugin:
    chromedriver = None

    # ToDo Add a param to ini file for a custom path for the driver
    chrome_driver_default_paths = [
        '/usr/bin/chromedriver',
        '/usr/local/bin/chromedriver',
    ]

    class errors:
        chrome_driver_error = None
        json2table_import_error = None


try:
    # import distutils.spawn
    from setuptools import distutils
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
except:
    Plugin.errors.chrome_driver_error = "selenium import failed"
else:
    Plugin.chromedriver = distutils.spawn.find_executable("chromedriver")
    if not Plugin.chromedriver:
        for _path in Plugin.chrome_driver_default_paths:
            if os.path.exists(_path):
                Plugin.chromedriver = _path
                break

if not Plugin.chromedriver:
    Plugin.errors.chrome_driver_error = "Chrome driver not found"

try:
    import json2html
except ModuleNotFoundError:
    Plugin.errors.json2table_import_error = True


class Log:
    """
    Simple class for debug logging for the time being. May eventually replace with a real Logger
    """
    debug_enabled = False  # Will be updated if enabled via the config file

    def debug(self, msg):
        if self.debug_enabled:
            print(f"[DEBUG] {msg}")


class Browser:
    driver = None
    window_size = "1920,1080"
    download_dir = None

    def __init__(self, window_size=None, download_dir=None):
        if window_size:
            self.window_size = window_size.strip().replace(" ", "")
        if download_dir:
            assert os.path.exists(download_dir)
        self.download_dir = os.path.abspath(download_dir) if download_dir else tempfile.gettempdir()

        if not self.driver:
            self.driver = self.make_driver()
            # Disabled for troubleshooting but found it still works. Maybe just needed when capturing actual URLs? [shrug]
            # self.enable_download_in_headless_chrome()

    def make_driver(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument(f"--window-size={self.window_size}")
        return webdriver.Chrome(executable_path=Plugin.chromedriver, options=chrome_options)

    def enable_download_in_headless_chrome(self):
        # add missing support for chrome "send_command" to selenium webdriver
        self.driver.command_executor._commands["send_command"] = ("POST", '/session/$sessionId/chromium/send_command')
        params = {'cmd': 'Page.setDownloadBehavior', 'params': {'behavior': 'allow', 'downloadPath': self.download_dir}}
        self.driver.execute("send_command", params)

    def generate_screenshot_file(self, url, save_path=None):
        temp_target = Reusable.generate_temp_file_path("png", prefix="screenshot")

        self.driver.get(url)
        _ = self.driver.save_screenshot(temp_target)
        # Try moving the file to the requested path. If it fails, simply print that the target failed, so the file can instead be found at the temp file path.
        if not save_path:
            save_path = self.download_dir if self.download_dir else temp_target

        if save_path != temp_target:
            try:
                shutil.move(temp_target, save_path)
            except Exception as e:
                print(f"Failed to move file to requested location: {save_path}\n\nException:\n{str(e)}\n\n")
                save_path = temp_target

        return save_path


class Reusable:
    # Class for static reusable methods, mainly just to group these together to better organize for readability

    @staticmethod
    def run_cli_command(command: str or bytes or list or tuple, timeout: int = 30, test: bool = True, capture_output: bool = True):
        """
        Reusable method to standardize CLI calls

        :param command: Command to execute (can be string or list)
        :param timeout: Timeout in seconds (default 30)
        :type timeout: int or None
        :param bool test: Whether to test that the command completed successfully (default True)
        :param bool capture_output: Whether to capture the output or allow it to pass to the terminal. (Usually True, but False for things like prompting for the sudo password)
        :return:
        """

        def _validate_command(cmd: str or bytes or list or tuple):
            """
            Verify command format. Accepts string, bytes, list of strings, or tuple of strings,
            and returns a formatted command ready for the subprocess.run() method
            :param cmd: Desired shell command in any supported format
            :return formatted_cmd: List of split command parts
            """
            if type(cmd) is bytes:
                # convert to a string; further convert as a string in the next step
                cmd = cmd.decode('utf-8')
            if type(cmd) is str:
                cmd = cmd.strip()
            if not cmd:
                raise ValueError("No command provided")
            elif "|" in cmd or (isinstance(cmd, (list, tuple)) and "|" in ','.join(cmd)):
                raise ValueError("Pipe commands not supported at this time")
            elif isinstance(cmd, (list, tuple)):
                # If the command is already a list or tuple, then assume it is already ready to be used
                return cmd
            # At this point the command must be a string format to continue.
            if type(cmd) is str:
                # Use shlex to split into a list for subprocess input
                formatted_cmd = shlex.split(cmd.strip())
                if not formatted_cmd or type(formatted_cmd) is not list:
                    raise ValueError("Command failed to parse into a valid list of parts")
            else:
                raise TypeError(f"Command validation failed: type {type(cmd).__name} not supported")
            return formatted_cmd

        # Also tried these, but settled on subprocess.run:
        # subprocess.call("command1")
        # subprocess.call(["command1", "arg1", "arg2"])
        # or
        # import os
        # os.popen("full command string")
        if isinstance(timeout, Number) and timeout <= 0:
            timeout = None
        log.debug(f"Executing command: {command}")
        _cmd = _validate_command(command)
        _result = subprocess.run(_cmd, capture_output=capture_output, universal_newlines=True, timeout=timeout)
        if test:
            _result.check_returncode()
        return _result

    @staticmethod
    def run_shell_command_with_pipes(command, print_result=True, indent: int = 5):
        """Simple version for now. May revisit later to improve it."""
        log.debug(f"Executing command: {command}")
        _output = subprocess.getoutput(command)
        if print_result:
            if indent > 0:
                for _line in _output.split('\n'):
                    print(" " * indent + _line)
            else:
                print(_output)
        return _output

    @staticmethod
    def do_prompt_for_sudo():
        # If a sudo session is not already active, auth for sudo and start the clock.
        # This function can be called as many times as desired to and will not cause re-prompting unless the timeout has been exceeded.
        _ = Reusable.run_cli_command('sudo -v -p "sudo password: "', timeout=-1, test=True, capture_output=False)

    @staticmethod
    def convert_boolean(_var):
        if type(_var) is str:
            _var2 = _var.strip().lower()
            if _var2 in ["yes", "true"]:
                return True
            elif _var2 in ["no", "false"]:
                return False
        return _var

    @staticmethod
    def dict_merge(*args, add_keys=True):
        """
        Deep (recursive) merge for dicts, because dict.update() only merges
        top-level keys. This version makes a copy of the original dict so that the
        original remains unmodified.

        The optional argument ``add_keys``, determines whether keys which are
        present in ``merge_dict`` but not ``dct`` should be included in the
        new dict. It also merges list entries instead of overwriting with a new list.
        """
        assert len(args) >= 2, "dict_merge requires at least two dicts to merge"
        rtn_dct = args[0].copy()
        merge_dicts = args[1:]
        for merge_dct in merge_dicts:
            if add_keys is False:
                merge_dct = {key: merge_dct[key] for key in set(rtn_dct).intersection(set(merge_dct))}
            for k, v in merge_dct.items():
                if not rtn_dct.get(k):
                    rtn_dct[k] = v
                elif v is None:
                    pass
                elif k in rtn_dct and not isinstance(v, type(rtn_dct[k])):
                    raise TypeError(
                        f"Overlapping keys exist with different types: original is {type(rtn_dct[k]).__name__}, new value is {type(v).__name__}")
                elif isinstance(rtn_dct[k], dict) and isinstance(merge_dct[k], collections.abc.Mapping):
                    rtn_dct[k] = Reusable.dict_merge(rtn_dct[k], merge_dct[k], add_keys=add_keys)
                elif isinstance(v, list):
                    for list_value in v:
                        if list_value not in rtn_dct[k]:
                            rtn_dct[k].append(list_value)
                else:
                    rtn_dct[k] = v
        return rtn_dct

    @staticmethod
    def generate_temp_file_path(file_ext, prefix=None, name_only=False):
        assert file_ext
        if prefix and not prefix.endswith("_"):
            prefix = prefix + "_"
        _temp_file_name = f"{prefix or ''}{datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S-%f')[:-3]}"
        if file_ext:
            _temp_file_name += "." + file_ext
        if name_only:
            return _temp_file_name
        return os.path.join(tempfile.gettempdir(), _temp_file_name)

    @staticmethod
    def write_text_to_temp_file(text_str, file_ext, file_name_prefix=None):
        _temp_file = Reusable.generate_temp_file_path(file_ext=file_ext, prefix=file_name_prefix)
        with open(_temp_file, 'w') as _f:
            _f.write(text_str)
        return os.path.abspath(_temp_file)

    @staticmethod
    def sort_dict_by_values(input_text, reverse=False):
        # return sorted(input_text.items(), key=lambda x: x[1], reverse=reverse)
        return {k: v for k, v in sorted(input_text.items(), key=lambda x: x[1], reverse=reverse)}

    @staticmethod
    def time_epoch_to_str(time_number, utc=False, time_format=None):
        _time = float(time_number)
        # If the number is in milliseconds, convert to seconds
        if len(str(int(_time))) > 10:
            _time = _time / 1000
        time_format = time_format if time_format else '%Y-%m-%d %I:%M:%S %p %Z'
        time_func = datetime.utcfromtimestamp if utc is True else datetime.fromtimestamp
        return time_func(_time).strftime(time_format)

    @staticmethod
    def flatten_list(var_list):
        if isinstance(var_list, (list, tuple)):
            return [r for v in var_list for r in Reusable.flatten_list(v)]
        return var_list

    @staticmethod
    def sort_list_treating_numbers_by_value(var_list: list):
        """
        borrowed and modified from here:
        https://stackoverflow.com/questions/67918688/sorting-a-list-of-strings-based-on-numeric-order-of-numeric-part
        """

        def build_key():
            def key(x):
                return [(j, int(i)) if i != '' else (j, i)
                        for i, j in rx.findall(x)]

            rx = re.compile(r'(\d+)|(.)')
            return key

        return sorted(var_list, key=build_key())


# Use everywhere that images are read or displayed
class Icon:
    def __init__(self, image_path):
        self.path = os.path.realpath(image_path)
        self.location = os.path.dirname(self.path)
        self.name = os.path.basename(self.path)

    def to_base64_string(self):
        with open(self.path, "rb") as image_file:
            image_bytes = image_file.read()
            image_b64 = base64.b64encode(image_bytes)
        return image_b64.decode("unicode_escape")


@dataclass
class Icons:
    # Class for centralizing all logos used by the plugin

    image_dir: str
    menu_icon_networking: str = "menu_ssh.png"
    file_status_small: str = "status_small.png"
    file_status_small_dark: str = "status_small_dark.png"
    file_status_large: str = "status_large.png"
    file_status_large_dark: str = "status_large_dark.png"
    file_status_xlarge: str = "status_xlarge.png"
    file_status_xlarge_dark: str = "status_xlarge_dark.png"

    __supported_image_extensions = ["ico", "png", "jpg"]

    def __post_init__(self):
        if not self.file_status_small:
            raise IOError("At least a small status icon must be defined")
        self.files = {}
        for f in os.listdir(self.image_dir):

            if re.match(rf'^.*\.({"|".join(self.__supported_image_extensions)})$', f.lower()):
                self.files[f] = Icon(os.path.join(self.image_dir, f))

        # If no "large" is provided, clone small
        self.file_status_large = self.file_status_large or self.file_status_small

        # If no "xlarge" is provided, clone large
        self.file_status_xlarge = self.file_status_xlarge or self.file_status_large

        # In case the "dark" images are passed as empty/None, clone the Light theme values
        self.file_status_small_dark = self.file_status_small_dark or self.file_status_small
        self.file_status_large_dark = self.file_status_large_dark or self.file_status_large
        self.file_status_xlarge_dark = self.file_status_xlarge_dark or self.file_status_xlarge

        self.logos_by_os_theme = {
            "Dark": {
                "small": Icon(os.path.join(self.image_dir, self.file_status_small_dark)),
                "large": Icon(os.path.join(self.image_dir, self.file_status_large_dark)),
                "xl":    Icon(os.path.join(self.image_dir, self.file_status_xlarge_dark)),
            },
            "Light": {
                "small": Icon(os.path.join(self.image_dir, self.file_status_small)),
                "large": Icon(os.path.join(self.image_dir, self.file_status_large)),
                "xl":    Icon(os.path.join(self.image_dir, self.file_status_xlarge)),
            }
        }

    def get_icon(self, image_name):
        return self.files[image_name]

    def get_logo_for_theme(self, icon_size):
        return self.logos_by_os_theme.get(OS_THEME, "Light")[icon_size]


@dataclass_json
@dataclass
class ConfigMain:
    # Path to the code repo. No default here, as this is a required field.
    repo_path: str

    # Local user ID. If not provided, user will be drawn from USER environment variable
    local_user: str = os.environ.get("USER")

    # Default SSH username. If not provided, user will be drawn from USER environment variable
    ssh_user: str = os.environ.get("USER")

    # SSH keys are assumed to be located in ~/.ssh unless a full path is provided
    ssh_key: str = "id_rsa"

    # Usually "lo0"
    default_loopback_interface: str = "lo0"

    # Define how this plugin should appear in the status bar
    # Options: logo, text, both, custom
    status_bar_style: str = "logo"

    # Text for the notification label (not used if status_bar_style is set to logo)
    # Default is "<PROJECT_NAME>"
    # If status_bar_style is set to "custom", you can specify additional formatting criteria according to xbar's plugin API
    status_bar_label: str = "wedgiebar"

    # Choose the logo: small, large, xl
    status_bar_icon_size: str = "small"

    # Override the color of the text in the status bar (ignored if text is disabled by the selected style)
    status_bar_text_color: str = "black"

    # Generate a popup notification every time the clipboard gets updated
    clipboard_update_notifications: bool = True

    # Show debug output
    debug_output_enabled: bool = False

    # default Jira prefix (project name)
    jira_default_prefix: str = None

    # Jira web server hostname, e.g. subdomain.domain.com
    jira_server_hostname: str = None

    def __post_init__(self):
        self.clipboard_update_notifications = Reusable.convert_boolean(self.clipboard_update_notifications)
        self.debug_output_enabled = Reusable.convert_boolean(self.debug_output_enabled)


@dataclass_json
@dataclass
class ConfigMenuNetworking:
    configs: dict


# ToDo Finish this new feature
@dataclass_json
@dataclass
class ConfigMenuCustom:
    def __post_init__(self):
        pass


@dataclass_json
@dataclass
class Config:
    main: ConfigMain = None
    menu_custom: ConfigMenuCustom = None
    menu_networking: ConfigMenuNetworking = None

    def __post_init__(self):
        config_sections = ["main", "menu_networking"]

        # initialize a config obj for the user's ini config file
        self.user_settings_dict = configobj.ConfigObj(os.path.join(os.environ.get("HOME"), user_config_file))
        if not self.user_settings_dict:
            print(f"{user_config_file} not found")
            sys.exit(1)
        else:
            for k in config_sections:
                if k not in self.user_settings_dict:
                    self.user_settings_dict[k] = {}

        self.get_config_main()
        if self.main.debug_output_enabled:
            Log.debug_enabled = self.main.debug_output_enabled

        if not self.main.repo_path:
            print(f"repo_path not set in {user_config_file}")
            sys.exit(1)

        self.get_config_menu_networking_params(**self.user_settings_dict.get("menu_networking", {}))
        # ToDo Still not used; implement custom commands
        self.menu_custom = ConfigMenuCustom()

        # Find the path to the home directory
        self.dir_user_home = os.environ.get("HOME")

        self.default_loopback_interface = self.main.default_loopback_interface
        self.local_user = self.main.local_user
        self.default_ssh_key = self.main.ssh_key
        if "/" not in self.default_ssh_key:
            self.default_ssh_key = os.path.join(self.dir_user_home, ".ssh", self.default_ssh_key)

        self.image_file_path = os.path.join(self.main.repo_path, "supporting_files/images")
        self.icons = Icons(image_dir=self.image_file_path)

        self.status_bar_logo = self.icons.get_logo_for_theme(icon_size=self.main.status_bar_icon_size)
        self.menu_icon_networking = self.icons.get_icon(image_name=Icons.menu_icon_networking)

    def get_config_main(self):
        self.main = ConfigMain(**{
            k: v for k, v in self.user_settings_dict.get("main", {}).items()
            if v not in ['', None]
        })

    def get_config_menu_networking_params(self, **kwargs):
        self.menu_networking = ConfigMenuNetworking(kwargs)


@dataclass
class ActionObject:
    id: str
    name: str
    action: classmethod


class Actions:
    # Static items
    loopback_interface = None

    # Defaults
    ssh_tunnel_configs = []
    port_redirect_configs = []
    __reserved_keyboard_shortcuts = {}

    def __init__(self, config: Config):
        me = psutil.Process()
        parent = psutil.Process(me.ppid())
        self.parent = parent.name()
        self.menu_type = self.parent if self.parent in ('BitBar', 'xbar') else 'pystray'

        self.title_default = "wedgiebar"
        self.script_name = os.path.abspath(sys.argv[0])
        self.status = ""
        self.menu_output = ""

        self.config = config

        self.url_jira = rf"https://{self.config.main.jira_server_hostname}/browse/{{}}"
        self.url_uws = r"https://www.ultimatewindowssecurity.com/securitylog/encyclopedia/event.aspx?eventID={}"
        self.url_nmap = r"https://nmap.org/nsedoc/scripts/{}"

        self.set_status_bar_display()
        self.loopback_interface = self.config.default_loopback_interface

        # dict to store all the actions
        self.action_list: Dict[str, ActionObject] = {}

        self.add_menu_section(":pencil: Clipboard Editing | size=20 color=blue")
        self.print_in_menu("Text Editing")
        self.add_menu_section("Sorting", text_color="blue", menu_depth=1)

        self.make_action("Sort Lines (no duplicates)", self.text_sort_lines_no_duplicates,
                         keyboard_shortcut="CmdOrCtrl+shift+s")
        self.make_action("Sort Lines (allow duplicates)", self.text_sort_lines_allow_duplicates,
                         keyboard_shortcut="CmdOrCtrl+OptionOrAlt+s")
        self.make_action("Sort Words and Phrases (no duplicates)", self.text_sort_words_and_phrases_no_duplicates)
        self.make_action("Sort Words and Phrases (allow duplicates)", self.text_sort_words_and_phrases_allow_duplicates)

        self.add_menu_section("Editing", text_color="blue", menu_depth=1)

        self.make_action("Text to Uppercase", self.text_make_uppercase, keyboard_shortcut="CmdOrCtrl+OptionOrAlt+u")
        self.make_action("Text to Lowercase", self.text_make_lowercase, keyboard_shortcut="CmdOrCtrl+OptionOrAlt+l")
        self.make_action("Trim Text in Clipboard", self.text_trim_string)
        self.make_action("Remove Text Formatting", self.text_remove_formatting)
        self.make_action("URL Encoding: Encode (from clipboard)", self.encode_url_encoding,
                         action_id="encode_url_encoding")
        self.make_action("URL Encoding: Decode (from clipboard)", self.decode_url_encoding,
                         action_id="decode_url_encoding")
        self.make_action("Base64: Encode", self.action_encode_base_64)
        self.make_action("Base64: Decode", self.action_decode_base_64)
        self.make_action("Strip non-ascii characters", self.remove_non_ascii_characters)
        self.make_action("White space to underscores", self.white_space_to_underscores,
                         keyboard_shortcut="CmdOrCtrl+shift+u")

        self.add_menu_section("Spaced Strings", text_color="blue", menu_depth=1)

        self.make_action("Tabs to commas", self.spaced_string_to_commas, keyboard_shortcut="CmdOrCtrl+shift+t")
        self.make_action("Tabs to commas (force lowercase)", self.spaced_string_to_commas_lowercase, alternate=True)

        self.make_action("Tabs to commas (sorted)", self.spaced_string_to_commas_sorted)
        self.make_action("Tabs to commas (sorted, force lowercase)", self.spaced_string_to_commas_sorted_lowercase, alternate=True)

        self.make_action("Tabs to commas & quotes", self.spaced_string_to_commas_and_quotes)
        self.make_action("Tabs to commas & quotes (force lowercase)", self.spaced_string_to_commas_and_quotes_lowercase, alternate=True)

        self.make_action("Tabs to commas & quotes (sorted)", self.spaced_string_to_commas_and_quotes_sorted)
        self.make_action("Tabs to commas & quotes (sorted, force lowercase)", self.spaced_string_to_commas_and_quotes_sorted_lowercase, alternate=True)

        self.print_in_menu("Time Conversion")
        self.add_menu_section("Time", text_color="blue", menu_depth=1)

        self.make_action("Show epoch time as local time (leave clipboard)", self.action_epoch_time_to_str, action_id="epoch_time_as_local_time", keyboard_shortcut="CmdOrCtrl+shift+e")
        self.make_action("Convert epoch time as local time (update clipboard)", self.epoch_time_as_local_time_convert, alternate=True)

        # ------------ Menu Section: TECH ------------ #

        self.add_menu_section(":wrench: TECH | size=20 color=blue")

        self.print_in_menu("JSON")
        self.make_action("Validate", self.action_json_validate)

        self.make_action("Format", self.action_json_format, keyboard_shortcut="CmdOrCtrl+shift+f")
        self.make_action("Format (sorted)", self.action_json_format_sorted, alternate=True)

        self.make_action("Compact", self.action_json_compact)
        self.make_action("Compact (sorted)", self.action_json_compact_sorted, alternate=True)

        self.make_action("Semi-Compact", self.action_json_semi_compact)
        self.make_action("Semi-Compact (sorted)", self.action_json_semi_compact_sorted, alternate=True)

        self.make_action("Sort by Values", self.action_json_sort_by_values)
        self.make_action("Sort by Values (Reversed)", self.action_json_sort_by_values_reversed, alternate=True)

        self.add_menu_divider_line(menu_depth=1)

        self.make_action("Fix (escaped strings to dicts/lists)", self.action_json_fix)
        self.make_action("Sort by keys and values (recursive)", self.action_json_sort)

        if not Plugin.errors.json2table_import_error:
            self.make_action("JSON to HTML Table (clipboard)", self.action_json_to_html)
            self.make_action("JSON to HTML Table (open in browser)", self.action_json_to_html_as_file)
        else:
            self.make_action("JSON to HTML Table: install package json2html", None)

        self.print_in_menu("HTML")
        self.make_action("Open as a file", self.action_html_to_temp_file, keyboard_shortcut="CmdOrCtrl+shift+h")

        if not Plugin.errors.chrome_driver_error:
            self.make_action("Generate screenshot", self.action_html_to_screenshot)
            self.make_action("Generate screenshot (low res)", self.action_html_to_screenshot_low_res, alternate=True)
        else:
            self.make_action(f"Screenshot unavailable ({Plugin.errors.chrome_driver_error})", None)

        self.print_in_menu("SQL")
        self.make_action("Pretty Print SQL", self.sql_pretty_print, keyboard_shortcut="CmdOrCtrl+shift+p")
        self.make_action("Pretty Print SQL options", action=None, alternate=True)
        self.make_action("Wrapped at 80 characters", self.sql_pretty_print_sql, menu_depth=2)
        self.make_action("Compact", self.sql_pretty_print_compact, menu_depth=2)

        self.make_action("SQL Start from spaced strings", self.sql_start_from_tabs)
        self.make_action("SQL Start from spaced strings (sorted)", self.sql_start_from_tabs_sorted)
        self.make_action("SQL Start from spaced strings (distinct)", self.sql_start_from_tabs_distinct)

        self.make_action("SQL Start from spaced strings (join with left columns)", self.sql_start_from_tabs_join_left)
        self.make_action("SQL Start from spaced strings (join, left columns only)", self.sql_start_from_tabs_join_left_columns_only, alternate=True)

        self.make_action("SQL Start from spaced strings (join with right columns)", self.sql_start_from_tabs_join_right)
        self.make_action("SQL Start from spaced strings (join, right columns only)", self.sql_start_from_tabs_join_right_columns_only, alternate=True)

        self.print_in_menu("Link Makers")

        if not self.config.main.jira_server_hostname and not self.config.main.jira_default_prefix:
            self.make_action("Jira hostname and default project prefix not set", None)
        elif not self.config.main.jira_server_hostname:
            self.make_action("Jira hostname not set", None)
        elif not self.config.main.jira_default_prefix:
            self.make_action("Jira default project prefix not set", None)
        else:
            self.make_action("Jira: Open Link from ID", self.make_link_jira_and_open,
                             keyboard_shortcut="CmdOrCtrl+shift+j")
            self.make_action("Jira: Make Link from ID", self.make_link_jira, alternate=True)
        self.make_action("UWS: Open link from Windows event ID", self.make_link_uws_and_open)
        self.make_action("UWS: Make link from Windows event ID", self.make_link_uws, alternate=True)
        self.make_action("Nmap: Open link to script documentation", self.make_link_nmap_script_and_open)
        self.make_action("Nmap: Make link to script documentation", self.make_link_nmap_script, alternate=True)

        self.print_in_menu("Shell Commands (general)")

        # Visual Mode, Permanent
        self.make_action("vim: visual mode - disable permanently", self.shell_vim_visual_mode_disable_permanently)
        self.make_action("vim: visual mode - enable permanently", self.shell_vim_visual_mode_enable_permanently,
                         alternate=True)

        # Visual Mode, Temporary (within an active session)
        self.make_action("vim: visual mode - disable within a session",
                         self.shell_vim_visual_mode_disable_within_session)
        self.make_action("vim: visual mode - enable within a session", self.shell_vim_visual_mode_enable_within_session,
                         alternate=True)

        # Show Line Numbers, Permanent
        self.make_action("vim: line numbers - enable permanently", self.shell_vim_line_numbers_enable_permanently)
        self.make_action("vim: line numbers - disable permanently", self.shell_vim_line_numbers_disable_permanently,
                         alternate=True)

        # Show Line Numbers, Temporary (within an active session)
        self.make_action("vim: line numbers - enable within a session",
                         self.shell_vim_line_numbers_enable_within_session)
        self.make_action("vim: line numbers - disable within a session",
                         self.shell_vim_line_numbers_disable_within_session, alternate=True)

        # Disable visual mode AND enable line numbers all at once
        self.make_action("vim: Set both permanently", self.shell_vim_set_both_permanently)

        # ------------ Menu Section: Networking ------------ #

        # First check whether there are any custom networking configs (i.e. ssh tunnels or port redirects)
        self.check_for_custom_networking_configs()

        if self.port_redirect_configs or self.ssh_tunnel_configs:
            self.add_menu_section(f"Networking | image={self.config.menu_icon_networking.to_base64_string()} size=20 color=blue")

            self.print_in_menu("Reset")
            self.make_action("Terminate SSH tunnels", self.action_terminate_tunnels, terminal=True)
            self.make_action("Terminate Local Port Redirection", self.action_terminate_port_redirection, terminal=True)
            self.make_action("Terminate All", self.action_terminate_all, terminal=True)

            self.print_in_menu("Port Redirection")
            # If custom redirect configs are defined in the ini config, then add actions for each
            for _config in self.port_redirect_configs:
                self.make_action(_config[0], self.port_redirect_custom, terminal=True, action_id=_config[1])

            self.print_in_menu("SSH Tunnels (custom)")
            # If custom ssh configs are defined in the ini config, then add actions for each
            for _config in self.ssh_tunnel_configs:
                self.make_action(_config[0], self.ssh_tunnel_custom, terminal=True, action_id=_config[1])

        # Added to help with troubleshooting, but for now I'm disabling until/unless it is needed again
        # self.print_in_menu(f"---")
        # self.print_in_menu(f"Parent: {self.parent}")
        # if self.menu_type in ('BitBar', 'xbar'):
        #     # Lastly, attempt to get the BitBar/xbar version and print it as an FYI
        #     # ToDo Try changing this to read XML instead of relying on regex!
        #     try:
        #         with open(f"/Applications/{self.menu_type}.app/Contents/Info.plist", "r") as app_file:
        #             _app_info = app_file.read()
        #             version_info = re.findall(r'<key>CFBundleVersion<[\s\S]*?<string>(.*?)</string>', _app_info)
        #             app_version = version_info[0] if version_info else '-'
        #             if app_version:
        #                 self.print_in_menu(f"{self.menu_type} version: {app_version}")
        #     except:
        #         pass

    ############################################################################
    # Reusable functions
    ############################################################################

    def add_menu_section(self, label, menu_depth=0, text_color=None):
        """
        Print a divider line as needed by the plugin menu, then print a label for the new section
        :param label:
        :param menu_depth: 0 for top level, 1 for submenu, 2 for first nested submenu, etc.
        :param text_color:
        :return:
        """
        assert label, "New menu section requested without providing a label"
        if text_color and ' color=' not in label:
            label += f"| color={text_color}"
        self.add_menu_divider_line(menu_depth=menu_depth)
        self.print_in_menu("--" * menu_depth + label)

    def add_menu_divider_line(self, menu_depth=0):
        """
        Print a divider line in the plugin menu
        Menu depth of 0 for top level menu, 1 for first level submenu, 2 for a nested submenu, etc.
        :param menu_depth:
        :return:
        """
        _divider_line = "---" + "--" * menu_depth
        self.print_in_menu(_divider_line)

    def display_notification(self, content, title=None):
        content = content.replace('"', '\\"')
        if not title:
            title = self.title_default
        # subprocess.call(["osascript", "-e", f'display notification "{content}" with title "{title}"'])
        _output = os.popen(f'osascript -e "display notification \\"{content}\\" with title \\"{title}\\""')

    def display_notification_error(self, content, title=None, print_stderr=False, error_prefix="Failed with error: "):
        if '"' in content:
            # self.display_notification_error("Error returned, but the error message contained a quotation mark, which is not allowed by xbar")
            content = content.replace('"', "'")
        error_prefix = error_prefix if error_prefix and isinstance(error_prefix, str) else ""
        _output = os.popen('osascript -e "beep"')
        _error = f"{error_prefix}{content}"
        if print_stderr:
            print(f"\n{_error}\n")
        self.display_notification(_error, title)
        sys.exit(1)

    def print_in_menu(self, msg):
        self.menu_output += f"{msg}\n"

    def fail_action_with_exception(
            self, trace: traceback.format_exc = None,
            exception: BaseException = None, print_stderr=False):
        if not trace:
            trace = traceback.format_exc()
        self.write_clipboard(trace, skip_notification=True)
        error_msg = "Failed with an exception"
        if exception and isinstance(exception, BaseException):
            error_msg += f" ({type(exception).__name__})"
        error_msg += ": check traceback in clipboard"
        if exception:
            error_msg = f"Failed with an exception ({type(exception).__name__}): check traceback in clipboard"
        self.display_notification_error(error_msg, error_prefix="", print_stderr=print_stderr)

    def _get_full_image_path(self, file_name):
        return os.path.join(self.config.image_file_path, file_name)

    # ToDo Can this be replaced with Icon object? (Icon.to_base64_string)
    def image_to_base64_string(self, file_name):
        file_path = self._get_full_image_path(file_name)
        with open(file_path, "rb") as image_file:
            image_bytes = image_file.read()
            image_b64 = base64.b64encode(image_bytes)
        return image_b64.decode("unicode_escape")

    def set_status_bar_display(self):
        # Ignore status_bar_label is status_bar_style is only the logo
        status_bar_label = "" if self.config.main.status_bar_style == "logo" else self.config.main.status_bar_label
        # If the status bar style is "custom," then whatever is passed in status_bar_label is the final product
        if self.config.main.status_bar_style != "custom":
            status_bar_label += "|"
            if self.config.main.status_bar_style in ["logo", "both"]:
                status_bar_label += f" image={self.config.status_bar_logo.to_base64_string()}"
            if self.config.main.status_bar_style in ["text", "both"]:
                status_bar_label += f" color={self.config.main.status_bar_text_color}"
        self.status = status_bar_label

        # Set status bar text and/or logo
        self.print_in_menu(self.status)

    def make_action(
            self, name, action, action_id=None, menu_depth=1, alternate=False,
            terminal=False, text_color=None, keyboard_shortcut="", shell=None):
        menu_line = name
        if menu_depth:
            menu_line = '--' * menu_depth + ' ' + menu_line
        action_string = ''
        if alternate:
            action_string = action_string + ' alternate=true'
        if keyboard_shortcut:
            if keyboard_shortcut in self.__reserved_keyboard_shortcuts:
                raise ValueError(f'Keyboard shortcut "{keyboard_shortcut}" already assigned to action "{self.__reserved_keyboard_shortcuts[keyboard_shortcut]}" and cannot be mapped to action {name}')
            self.__reserved_keyboard_shortcuts[keyboard_shortcut] = name
            action_string += ' | key=' + keyboard_shortcut
        menu_line += f' | {action_string}'
        if not action:
            if text_color:
                menu_line += f' color={text_color}'
            self.print_in_menu(menu_line)
            return

        if not action_id:
            action_id = re.sub(r'\W', "_", name)

        action_obj = ActionObject(id=action_id, name=name, action=action)
        self.action_list[action_id] = action_obj
        terminal = str(terminal).lower()
        menu_line += f' | bash="{self.script_name}" | param1="{action_id}" | terminal={terminal}'
        if shell:
            menu_line += f' | shell={shell}'
        self.print_in_menu(menu_line)
        return action_obj

    @staticmethod
    def read_clipboard(trim_input=True, lower=False, upper=False, strip_carriage_returns=True) -> str:
        if lower and upper:
            raise ValueError("The \"lower\" and \"upper\" parameters in Actions.read_clipboard are mutually exclusive. Use one or the other, not both.")
        input_text = clipboard.paste()
        if trim_input:
            input_text = input_text.strip()
        if lower is True:
            input_text = input_text.lower()
        if upper is True:
            input_text = input_text.upper()
        if strip_carriage_returns:
            # strip return characters (Windows formatting)
            input_text = re.sub(r'\r', '', input_text)
        return input_text

    def write_clipboard(self, text, skip_notification=False):
        clipboard.copy(text)
        if self.config.main.clipboard_update_notifications and not skip_notification:
            self.display_notification("Clipboard updated")

    def copy_file_contents_to_clipboard(self, file_path, file_name=None):
        """
        Standardized method for reading a file and copying its contents to the
        clipboard. If only a file_path is passed, assume that it is a full path
        to a file. If file_name is provided, assume file_path is its location,
        and join them automatically before reading the file's contents.

        :param file_path: Location of the file to read
        :param file_name: (optional) Name of the file. If a value is provided,
        file_path will be assumed to be a directory and joined with file_name,
        otherwise file_path will be treated as a full path to a file.
        :return:
        """
        if file_name.strip():
            file_path = os.path.join(file_path, file_name)
        if not os.path.isfile(file_path):
            self.display_notification_error("Invalid path to supporting script")
        with open(file_path, "rU") as f:
            output = f.read()
        self.write_clipboard(output)

    def _clipboard_to_temp_file(self, file_ext, static_text=None):
        if static_text:
            input_text = static_text
        else:
            input_text = self.read_clipboard()
        return Reusable.write_text_to_temp_file(input_text, file_ext, file_ext + "_text")

    def _split_spaced_string(self, force_lower=False, sort=False, quote=False, update_clipboard=True):
        input_text = self.read_clipboard()

        # Remove commas and quotes in case the user clicked the wrong xbar option and wants to go right back to processing it
        # Remove pipes too so this can be used on postgresql headers as well
        input_text = re.sub('[,"|\']+', ' ', input_text)

        if force_lower:
            input_text = input_text.lower()
        _columns = [i.strip() for i in input_text.split() if i.strip()]
        if sort:
            _columns = sorted(_columns)
        output_pattern = '"{}"' if quote else "{}"
        join_pattern = '", "' if quote else ", "
        final_output = output_pattern.format(join_pattern.join(_columns))
        if update_clipboard:
            self.write_clipboard(final_output)
        else:
            return final_output

    ############################################################################
    # Section:
    #   Networking
    ############################################################################

    def check_for_custom_networking_configs(self):
        if self.config.menu_networking:
            for _var in self.config.menu_networking.configs:
                if isinstance(self.config.menu_networking.configs[_var], dict):
                    if self.config.menu_networking.configs[_var].get("type") == "ssh":
                        self.ssh_tunnel_configs.append(
                            (self.config.menu_networking.configs[_var].get("name", _var), f"ssh_tunnel_custom_{_var}"))
                    elif self.config.menu_networking.configs[_var].get("type") == "redirect":
                        self.port_redirect_configs.append(
                            (self.config.menu_networking.configs[_var].get("name"), f"port_redirect_custom_{_var}"))

    ############################################################################
    # Networking -> Reset

    def do_terminate_tunnels(self, loopback_ip=None, loopback_port=None):
        """Terminate SSH tunnels"""

        # Get PID for all open SSH tunnels
        _cmd_result = Reusable.run_cli_command("ps -ef")
        pid_pattern = re.compile(r"^\s*\d+\s+(\d+)")
        specific_loopback = (loopback_ip.strip() if loopback_ip else "") + ":"
        if specific_loopback and loopback_port:
            specific_loopback += f"{loopback_port}:"
        tunnel_PIDs = {
            int(pid_pattern.findall(_line)[0]): _line
            for _line in _cmd_result.stdout.split('\n')
            if 'ssh' in _line and '-L' in _line and pid_pattern.match(_line) and specific_loopback in _line
        }

        # Check for an existing SSH tunnel. If none is found, abort, otherwise kill each process found.
        if not tunnel_PIDs:
            print("No existing SSH tunnels found")
            self.display_notification("No existing SSH tunnels found")
        else:
            # Validate sudo session
            Reusable.do_prompt_for_sudo()
            for PID in tunnel_PIDs:
                tunnel = tunnel_PIDs[PID]
                local_host_info, remote_host_info = re.findall(r"[^\s:]+:\d+(?=:|\s)", tunnel)[0:2]
                _tmp_ssh_server = re.findall(r'-f +(\S+)', tunnel)[0]
                print(f"Killing {local_host_info} --> {remote_host_info} via {_tmp_ssh_server} (PID {PID})")
                _ = Reusable.run_cli_command(f'sudo kill -9 {PID}')
            self.display_notification("Tunnels terminated")

    def action_terminate_tunnels(self):
        self.do_terminate_tunnels()

    def do_terminate_port_redirection(self):
        print("Resetting port forwarding/redirection...")
        Reusable.run_cli_command('sudo pfctl -f /etc/pf.conf')
        output_msg = "Port redirection terminated"
        print(output_msg)
        self.display_notification(output_msg)

    def action_terminate_port_redirection(self):
        Reusable.do_prompt_for_sudo()
        self.do_terminate_port_redirection()

    # ToDo Finish this or find an alternate way of helping with managing loopback aliases
    # Don't enable the following until this script is updated to take startup scripts into account
    def do_terminate_loopback_aliases(self):
        r"""
        from the old bash version:
            echo
            # When ready, add the following action to the bottom section:
            #echo "Terminate Loopback Aliases | bash='$0' param1=action_terminate_loopback_aliases terminal=true"
            #
            #    # Validate sudo session
            #    do_prompt_for_sudo
            #
            #    loopback_aliases=$(ifconfig -a | pcregrep -o 'inet \K127(?:\.\d+){3}' | pcregrep -v '127.0.0.1$' | sort -u)
            #    if [[ -z ${loopback_aliases} ]]; then
            #        echo "No loopback aliases found"
            #    else
            #        for loopback_alias in ${loopback_aliases}; do
            #            echo "Deleting loopback IP ${loopback_alias}"
            #            sudo ifconfig ${loopback_interface} ${loopback_alias} delete
            #        done
            #        display_notification "Loopback aliases terminated"
            #    fi
        """
        print("Feature not yet enabled")
        pass

    # ToDo Add an action for this function once it's operational
    def action_terminate_loopback_aliases(self):
        self.do_terminate_loopback_aliases()

    def action_terminate_all(self):
        # Validate sudo session
        Reusable.do_prompt_for_sudo()

        print("\nTerminating all SSH tunnels tunnels...\n")
        self.do_terminate_tunnels()

        print("\nTerminating port redirection...\n")
        self.do_terminate_port_redirection()

        print("\nTerminating all loopback aliases...\n")
        self.do_terminate_loopback_aliases()

        print("\nDone. You may close the terminal.\n")
        sys.exit()

    ############################################################################
    # Networking -> Port Redirects

    def do_execute_port_redirect(self, source_address, source_port, target_address, target_port):
        self.do_verify_loopback_address(source_address)
        log.debug(f"Making alias to redirect {source_address}:{source_port} --> {target_address}:{target_port}")

        _command = f'echo "rdr pass inet proto tcp from any to {source_address} port {source_port} -> {target_address} port {target_port}" | sudo -p "sudo password: " pfctl -ef -'
        print()
        _ = Reusable.run_shell_command_with_pipes(_command)
        result = f"Port Redirection Enabled:\n\n{source_address}:{source_port} --> {target_address}:{target_port}"
        print(f"\n{result}\n")
        self.display_notification(result)

    def port_redirect_custom(self):
        def get_var(var_name):
            var = (config_dict.get(var_name) or "").strip()
            if not var:
                self.display_notification_error(f"variable {var_name} not found in redirect config", print_stderr=True)
            return var

        # """ Custom port redirection based on entries in the ini config """
        config_name = re.sub('^port_redirect_custom_', '', sys.argv[1])
        config_dict = self.config.menu_networking.configs.get(config_name)
        if not config_dict:
            self.display_notification_error(f"Port redirect config [{config_name}] not found", print_stderr=True)

        source_address = get_var('source_address')
        source_port = get_var('source_port')
        target_address = get_var('target_address')
        target_port = get_var('target_port')
        optional_exit_message = config_dict.get("optional_exit_message")

        Reusable.do_prompt_for_sudo()
        print(f"\nSetting up redirection for config \"{config_dict['name']}\"...\n")

        self.do_execute_port_redirect(source_address, source_port, target_address, target_port)

        print("Done. You may close the terminal.\n")
        if optional_exit_message:
            print(optional_exit_message.replace("\\n", "\n").replace("\\t", "\t"))

    ############################################################################
    # Networking -> SSH Tunnels

    def do_verify_loopback_address(self, loopback_ip, allow_all_loopback_ips=False):
        assert loopback_ip, "No loopback address provided"
        assert re.match(r"^127\..*", loopback_ip), f"Invalid loopback address ({loopback_ip})"
        if not allow_all_loopback_ips:
            assert loopback_ip != "127.0.0.1", "Custom loopback IP is required. As a precaution, this script requires a loopback IP other than 127.0.0.1"

        # Trim input, just in case
        loopback_ip = loopback_ip.strip()
        interfaces_output = Reusable.run_cli_command("ifconfig -a")

        # Make sure loopback alias exists; create if needed.
        if re.findall(rf"\b{loopback_ip}\b", interfaces_output.stdout):
            log.debug(f"Existing loopback alias {loopback_ip} found")
        else:
            log.debug(f"Loopback alias {loopback_ip} not found; creating")
            # Validate sudo session
            Reusable.do_prompt_for_sudo()
            _ = Reusable.run_cli_command(f"sudo ifconfig {self.loopback_interface} alias ${loopback_ip}")

    def do_verify_ssh_tunnel_available(self, loopback_ip, loopback_port):
        print(f"Checking for existing tunnels {loopback_ip}:{loopback_port}...")
        self.do_terminate_tunnels(loopback_ip, loopback_port)

    def do_execute_ssh_tunnel(self, config_dict):
        """
        Execute an SSH tunnel based on a custom tunnel config from the ini config

        :param config_dict: dict containing SSH tunnel parameters
        :return:
        """
        ssh_config_name = config_dict.get("name")
        remote_address = config_dict.get("remote_ip")
        remote_port = config_dict.get("remote_port")
        local_address = config_dict.get("local_address")
        local_port = config_dict.get("local_port") or remote_port
        ssh_server_address = config_dict.get("ssh_server")
        ssh_server_port = config_dict.get("ssh_port") or 22
        ssh_user = config_dict.get("ssh_user") or self.config.local_user
        ssh_key = config_dict.get("ssh_key") or self.config.default_ssh_key
        ssh_options = config_dict.get("ssh_options", "").strip()

        # Ensure that required parameters are present
        assert ssh_config_name, "Error: SSH config must be given a name"
        assert ssh_server_address, "Error: SSH server address not provided"
        assert ssh_server_port, "Error: SSH port for SSH tunnel not provided"
        assert int(ssh_server_port), "Error: SSH port for SSH tunnel is not a number"
        assert remote_address, "Error: Remote address for SSH tunnel not provided"
        assert remote_port, "Error: Remote port for SSH tunnel not provided"
        assert int(remote_port), "Error: Remote port for SSH tunnel is not a number"
        assert local_address, "Error: Loopback address not provided"
        assert local_port, "Error: Loopback port not provided"
        assert int(local_port), "Error: Loopback port for SSH tunnel is not a number"

        # If the SSH server address is a loopback IP (like when tunneling over another tunnel)
        # Make sure the server port is not left at 22. Otherwise a tunnel to your own machine will be created and won't work.
        assert ssh_server_port != 22 or not re.match(r'^127\..*', ssh_server_address), \
            "Error: SSH server is a loopback IP, and the port is left at 22. This will create a tunnel to your own machine and won't work!"

        # Sanitize loopback address input, and verify that the address actually exists
        self.do_verify_loopback_address(local_address)

        # Kill existing tunnel if one is up already
        self.do_verify_ssh_tunnel_available(local_address, local_port)

        # Set default options (which includes skipping known_hosts)
        default_ssh_options = f"-i {ssh_key} -o StrictHostKeyChecking=no"

        # If ssh_options includes a specific ssh key already, then no key will be added
        if not ssh_options:
            # If SSH options were not provided, just point to the default SSH key
            ssh_options = default_ssh_options
        elif "-i" not in ssh_options:
            # If options were provided but no key was included, append the SSH key to use
            ssh_options = f"-i {ssh_key} {ssh_options}"

        # Initiate reverse SSH tunnel
        print(f"Redirecting for {ssh_config_name}\n")
        print(f"From Local:\n\t{local_address}:{local_port}\n")
        print(f"To Remote:\n\t{remote_address}:{remote_port}\n\n")

        # Define the SSH command
        #   * must use sudo in case the local port is below 1024
        ssh_command = f"ssh {ssh_options} -Y -L {local_address}:{local_port}:{remote_address}:{remote_port} -N -f {ssh_user}@{ssh_server_address} -p {ssh_server_port}"

        if int(local_port) <= 1023:
            # Validate sudo session
            Reusable.do_prompt_for_sudo()
            ssh_command = f"sudo {ssh_command}"

        print(f"Executing command:\n\n    {ssh_command}\n")

        # Run SSH command
        # Bash version for reference: eval "${ssh_command}"
        _ = Reusable.run_cli_command(ssh_command, capture_output=False, timeout=60)

        print(f"\nSSH tunnel complete\n\n")

    def ssh_tunnel_custom(self):
        """ Custom SSH tunnel based on entries in the ini config """
        config_name = re.sub('^ssh_tunnel_custom_', '', sys.argv[1])
        if not self.config.menu_networking.configs.get(config_name):
            self.display_notification_error(f"SSH tunnel config [{config_name}] not found", print_stderr=True)
        tunnel_config = self.config.menu_networking.configs[config_name]
        self.do_execute_ssh_tunnel(tunnel_config)

    ############################################################################
    # Section:
    #   TECH
    ############################################################################

    ############################################################################
    # TECH -> JSON

    # JSON: Reusable methods first

    @staticmethod
    def _fix_json(json_str):
        def run_fix(obj, step_count=None):
            step_count = 0 if step_count is None else step_count + 1
            if type(obj) is bytes:
                raise TypeError("JSON input cannot be bytes")
            if type(obj) is str:
                try:
                    obj = json.loads(obj)
                except (TypeError, json.JSONDecodeError):
                    if step_count:
                        return obj
                    else:
                        raise Exception("Initial input could not be parsed as valid JSON")

            # Loop through all entries in case there are nested dicts or strings.
            if type(obj) in (list, tuple):
                obj = [run_fix(entry, step_count=step_count) for entry in obj]
            elif isinstance(obj, dict):
                obj = {k: run_fix(obj[k], step_count=step_count) for k in obj.keys()}
            return obj

        return run_fix(json_str)

    def _sort_dicts_and_lists(self, input_value):
        """Sort dicts and lists recursively with a self-calling function"""
        _output = input_value
        # If the object is not a list or a dict, just return the value
        if type(_output) not in (list, dict):
            return _output
        if isinstance(_output, dict):
            # Crawl and sort dict values before sorting the dict itself
            _output = {k: self._sort_dicts_and_lists(v) for k, v in _output.items()}
            # Sort dict by keys
            _output = {k: _output[k] for k in sorted(_output.keys())}
        elif isinstance(_output, list):
            # Crawl and sort list values before sorting the list itself
            _output = [self._sort_dicts_and_lists(val) for val in _output]
            try:
                # Try to simply sort the list (will fail if entries are dicts or nested lists)
                _output = sorted(_output)
            except TypeError:
                # Map string versions of entries to their real values
                temp_map_input_as_strings = {}
                for k in _output:
                    try:
                        temp_map_input_as_strings[json.dumps(k)] = k
                    except:
                        temp_map_input_as_strings[str(k)] = k

                # Sort real values by their string versions
                _output = [temp_map_input_as_strings[k] for k in sorted(temp_map_input_as_strings.keys())]
        return _output

    def _process_json_clipboard(
            self, sort_output=None, format_output=False, fix_output=False,
            compact_spacing=False, format_auto=False, return_obj=False):
        """
        One method to standardize reading JSON from the clipboard, processing as needed, and updating the clipboard

        :param sort_output: Sort by keys and values
        :param format_output: Format JSON output with line breaks and indentation instead of a single line
        :param fix_output: Fix values where dicts or lists are stored as escaped strings
        :param compact_spacing: When converting JSON to a compact string, make it semi-compact (i.e. still include spaces after colons and commas)
        :param format_auto: If set to True, override "format_output" and check whether there are line breaks in the clipboard input and set format_output automatically
        :return:
        """

        # Read clipboard, convert from JSON
        json_loaded = self._json_notify_and_exit_when_invalid()

        # If fix_output is enabled, crawl for dicts or lists stored as escaped strings
        if fix_output:
            json_loaded = self._fix_json(json_loaded)

        # If sort_output is enabled, sort recursively by keys and values
        if sort_output:
            if sort_output == "values":
                json_loaded = Reusable.sort_dict_by_values(json_loaded)
            elif sort_output == "values_reversed":
                json_loaded = Reusable.sort_dict_by_values(json_loaded, reverse=True)
            else:
                json_loaded = self._sort_dicts_and_lists(json_loaded)

        if format_auto:
            # If there are newlines in the clipboard, assume that it is formatted JSON
            # If no newlines, then return compact JSON
            if '\n' in self.read_clipboard():
                format_output = True
                compact_spacing = True
            else:
                format_output = False

        if return_obj:
            return json_loaded

        if format_output is True:
            # Format output with line breaks and indentation
            _output = json.dumps(json_loaded, ensure_ascii=False, indent=2)
        else:
            separators = (', ', ': ') if compact_spacing is True else (',', ':')
            # Format output as a compact string on a single line
            _output = json.dumps(json_loaded, ensure_ascii=False, separators=separators)

        self.write_clipboard(_output)

    def _json_notify_and_exit_when_invalid(self, manual_input=None):
        """
        Reusable script to validate that what is in the clipboard is valid JSON,
        and raise an alert and exit if it is not.

        :return:
        """
        if manual_input:
            input_text = manual_input
        else:
            input_text = self.read_clipboard()
        if input_text.endswith('%'):
            input_text = input_text[:-1]
        try:
            new = json.loads(input_text, strict=False)
            for _try in range(5):
                if isinstance(new, (dict, list)):
                    break
                new = json.loads(new, strict=False)
            json_dict = new
        except ValueError:
            json_dict = None

        if not json_dict or not isinstance(json_dict, (dict, list)):
            self.display_notification_error('Invalid JSON !!!!!!!!!!')
            sys.exit(1)
        else:
            return json_dict

    # JSON: Menu actions next

    def action_json_validate(self):
        json_loaded = self._json_notify_and_exit_when_invalid()
        if isinstance(json_loaded, dict):
            self.display_notification("Valid JSON, type: dict")
        else:
            self.display_notification(f"Valid JSON, type: {type(json_loaded).__name__}")

    def action_json_format(self):
        """ JSON Format """
        self._process_json_clipboard(format_output=True)

    def action_json_format_sorted(self):
        """ JSON Format (sorted) """
        self._process_json_clipboard(sort_output=True, format_output=True)

    def action_json_compact(self):
        """ JSON Compact """
        self._process_json_clipboard()

    def action_json_compact_sorted(self):
        """ JSON Compact (sorted) """
        self._process_json_clipboard(sort_output=True)

    def action_json_semi_compact(self):
        """ JSON Semi-Compact (compact but with spacing after colons and commas)"""
        self._process_json_clipboard(compact_spacing=True)

    def action_json_sort_by_values(self, reverse=False):
        sort_type = "values_reversed" if reverse else "values"
        self._process_json_clipboard(sort_output=sort_type, format_output=True)

    def action_json_sort_by_values_reversed(self):
        self.action_json_sort_by_values(reverse=True)

    def action_json_semi_compact_sorted(self):
        """ JSON Semi-Compact (sorted) (compact but with spacing after colons and commas) """
        self._process_json_clipboard(sort_output=True, compact_spacing=True)

    def action_json_fix(self):
        """ JSON Fix """
        self._process_json_clipboard(fix_output=True, compact_spacing=True, format_auto=True)

    def action_json_sort(self):
        """ JSON Sort """
        self._process_json_clipboard(sort_output=True, compact_spacing=True, format_auto=True)

    def action_json_to_html(self, as_file=False):
        json_loaded = self._json_notify_and_exit_when_invalid()
        html_table = r"""<head>
<style>
.test_table {
    border: 2px solid black;
}
.test_table table, th, tr, td {
    margin:0;
    padding:1px;
}
.test_table th {
    background-color: #f0f1f2;
    border: 2px solid black;
}
.test_table td { border: 2px solid black; }
</style>
</head>
"""

        html_table += json2html.json2html.convert(
            json=json_loaded,
            table_attributes='class="test_table"'
        )
        if as_file:
            html_file = self._clipboard_to_temp_file(file_ext="html", static_text=html_table)
            _ = subprocess.run(["open", html_file])
        else:
            self.write_clipboard(html_table)

    def action_json_to_html_as_file(self):
        self.action_json_to_html(as_file=True)

    ############################################################################
    # TECH -> HTML

    def action_html_to_temp_file(self):
        """ HTML in clipboard to file """
        html_file = self._clipboard_to_temp_file(file_ext="html")
        _ = subprocess.run(["open", html_file])

    def action_html_to_screenshot(self, output_path=None, window_size=None):
        """ HTML in clipboard to screenshot """
        html_file = self._clipboard_to_temp_file(file_ext="html")
        chrome = Browser(download_dir=output_path, window_size=window_size)
        html_file_url = Path(html_file).as_uri()
        target_path = chrome.generate_screenshot_file(url=html_file_url, save_path=output_path)
        chrome.driver.quit()
        _ = subprocess.run(["open", target_path], capture_output=True, universal_newlines=True)

    def action_html_to_screenshot_low_res(self):
        """ HTML in clipboard to screenshot (low res version) """
        self.action_html_to_screenshot(window_size="800x600")

    ############################################################################
    # TECH -> Link Makers

    def make_link(self, url: str, open_url: bool = False, override_clipboard=None):
        """
        Standardized link making. Provide a URL with '{}' in place of the
        desired location for clipboard text. If open_url is enabled, the
        clipboard will be left intact, and the URL will be opened in the user's
        default browser.

        :param url:
        :param open_url:
        :param override_clipboard:
        :return:
        """
        input_text = override_clipboard if override_clipboard else self.read_clipboard()
        url = url.replace(r'{}', input_text)
        if open_url is True:
            subprocess.call(["open", url])
        else:
            self.write_clipboard(url)

    def add_default_jira_project_when_needed(self):
        input_text = self.read_clipboard(upper=True)
        if re.match(r"^\d+$", input_text):
            return f"{self.config.main.jira_default_prefix}-{input_text}"
        return input_text

    def make_link_jira_and_open(self):
        """
        Jira: Open Link from ID

        :return:
        """
        jira_issue = self.add_default_jira_project_when_needed()
        self.make_link(self.url_jira, override_clipboard=jira_issue, open_url=True)

    def make_link_jira(self):
        """
        Jira: Make Link from ID

        :return:
        """
        jira_issue = self.add_default_jira_project_when_needed()
        self.make_link(self.url_jira, override_clipboard=jira_issue)

    def make_link_uws_and_open(self):
        """
        Jira: UWS: Open link from Windows event ID

        :return:
        """
        self.make_link(self.url_uws, open_url=True)

    def make_link_uws(self):
        """
        Jira: UWS: Make link from Windows event ID

        :return:
        """
        self.make_link(self.url_uws)

    def make_link_nmap_script_and_open(self):
        """
        Nmap: Open link to script documentation

        :return:
        """
        self.make_link(self.url_nmap, open_url=True)

    def make_link_nmap_script(self):
        """
        Nmap: Make link to script documentation

        :return:
        """
        self.make_link(self.url_nmap)

    ############################################################################
    # TECH -> Shell Commands (general)

    # Visual Mode, Permanent
    def shell_vim_visual_mode_disable_permanently(self):
        """
        vim: visual mode - disable permanently

        :return:
        """
        self.write_clipboard(
            r"""if [[ -f ~/.vimrc ]]; then sed -E -i".$(date +'%Y%m%d_%H%M%S').bak" '/^set mouse/d' ~/.vimrc; else touch ~/.vimrc; fi ; echo 'set mouse-=a' >> ~/.vimrc""")

    def shell_vim_visual_mode_enable_permanently(self):
        """
        vim: visual mode - enable permanently

        :return:
        """
        self.write_clipboard(
            r"""if [[ -f ~/.vimrc ]]; then sed -E -i".$(date +'%Y%m%d_%H%M%S').bak" '/^set mouse/d' ~/.vimrc; else touch ~/.vimrc; fi ; echo 'set mouse=a' >> ~/.vimrc""")

    # Visual Mode, Temporary (within an active session)
    def shell_vim_visual_mode_disable_within_session(self):
        """
        vim: visual mode - disable within a session

        :return:
        """
        self.write_clipboard(r""":set mouse-=a""")

    def shell_vim_visual_mode_enable_within_session(self):
        """
        vim: visual mode - enable within a session

        :return:
        """
        self.write_clipboard(r""":set mouse=a""")

    # Show Line Numbers, Permanent
    def shell_vim_line_numbers_enable_permanently(self):
        """
        vim: line numbers - enable permanently

        :return:
        """
        self.write_clipboard(
            r"""if [[ -f ~/.vimrc ]]; then sed -E -i".$(date +'%Y%m%d_%H%M%S').bak" '/^set nonumber/d' ~/.vimrc; else touch ~/.vimrc; fi ; echo 'set number' >> ~/.vimrc""")

    def shell_vim_line_numbers_disable_permanently(self):
        """
        vim: line numbers - disable permanently

        :return:
        """
        self.write_clipboard(
            r"""if [[ -f ~/.vimrc ]]; then sed -E -i".$(date +'%Y%m%d_%H%M%S').bak" '/^set number/d' ~/.vimrc; else touch ~/.vimrc; fi ; echo 'set nonumber' >> ~/.vimrc""")

    # Show Line Numbers, Temporary (within an active session)
    def shell_vim_line_numbers_enable_within_session(self):
        """
        vim: line numbers - enable within a session

        :return:
        """
        self.write_clipboard(r""":set number""")

    def shell_vim_line_numbers_disable_within_session(self):
        """
        vim: line numbers - disable within a session

        :return:
        """
        self.write_clipboard(r""":set nonumber""")

    def shell_vim_set_both_permanently(self, return_string=False):
        """
        vim: Set both permanently

        :return:
        """
        _command = r"""if [[ -f ~/.vimrc ]]; then sed -E -i".$(date +'%Y%m%d_%H%M%S').bak" '/^ *set *((no)?number|mouse)/d' ~/.vimrc; fi; printf "set mouse-=a\nset number\n" >> ~/.vimrc"""
        if return_string:
            return _command
        self.write_clipboard(_command)

    def make_pretty_print_sql(self, input_str, wrap_after=0):
        """
        Reusable method to "pretty print" SQL

        :param input_str:
        :param wrap_after:
        :return:
        """
        try:
            import sqlparse

            # Strip leading and trailing ticks if present
            _output = re.sub(r'^\s*`|`\s*$', '', input_str).strip()

            # Replace line breaks with spaces, then trim leading and trailing whitespace
            _output = re.sub(r'[\n\r]+', ' ', _output).strip()

            _output = sqlparse.format(
                _output, reindent=True, keyword_case='upper', indent_width=4,
                wrap_after=wrap_after, identifier_case=None)

            # nit: if just selecting "*" then drop that initial newline. no reason to drop "FROM" to the next row.
            if re.match(r"^SELECT \*\nFROM ", _output):
                _output = re.sub(r"^SELECT \*\n", "SELECT * ", _output)

            # specific keyword replacements for forcing uppercase
            specific_functions_to_uppercase = [
                "get_json_object", "from_unixtime", "min(", "max(", "sum(",
                "count(", "coalesce(", "regexp_replace", "regexp_extract("
            ]
            for f in specific_functions_to_uppercase:
                if f in _output:
                    _output = _output.replace(f, f.upper())

            # Workaround for "result" and other fields always getting turned into uppercase by sqlparse
            override_caps = ["result", "temp", "version", "usage", "instance"]
            for cap_field in override_caps:
                if re.findall(fr"\b{cap_field.upper()}\b", _output) and not re.findall(fr"\b{cap_field.upper()}\b",
                                                                                       input_str):
                    _output = re.sub(fr"\b{cap_field.upper()}\b", cap_field.lower(), _output)

            # Workaround to space out math operations
            _output = re.sub(r'\b([-+*/])(\d)', " \1 \2", _output)
        except Exception as err:
            self.display_notification_error("Exception from sqlparse: {}".format(repr(err)))
        else:
            return _output

    def sql_pretty_print(self, **kwargs):
        """
        Pretty Print SQL

        :return:
        """
        input_text = self.read_clipboard()
        _output = self.make_pretty_print_sql(input_text, **kwargs)
        self.write_clipboard(_output)

    def sql_pretty_print_sql(self):
        """
        Pretty Print SQL: Wrapped at 80 characters

        :return:
        """
        self.sql_pretty_print(wrap_after=80)

    def sql_pretty_print_compact(self):
        """
        Pretty Print SQL: Compact

        :return:
        """
        self.sql_pretty_print(wrap_after=99999)

    def sql_start_from_tabs(self):
        _columns_formatted = self._split_spaced_string(update_clipboard=False)
        self.write_clipboard(f'SELECT {_columns_formatted}\nFROM ')

    def sql_start_from_tabs_sorted(self):
        _columns_formatted = self._split_spaced_string(update_clipboard=False, sort=True)
        self.write_clipboard(f'SELECT {_columns_formatted}\nFROM ')

    def sql_start_from_tabs_distinct(self):
        _columns_formatted = self._split_spaced_string(update_clipboard=False)
        self.write_clipboard(f'SELECT DISTINCT {_columns_formatted}\nFROM ')

    def sql_start_from_tabs_join_left_columns_only(self):
        input_text = self._split_spaced_string(update_clipboard=False)
        _columns = re.split(', *', input_text)
        self.write_clipboard("L.{}".format(", L.".join(_columns)))

    def sql_start_from_tabs_join_right_columns_only(self):
        input_text = self._split_spaced_string(update_clipboard=False)
        _columns = re.split(', *', input_text)
        self.write_clipboard("R.{}".format(", R.".join(_columns)))

    def sql_start_from_tabs_join_left(self):
        input_text = self._split_spaced_string(update_clipboard=False)
        _columns = re.split(', *', input_text)
        _columns_formatted = "L.{}".format(", L.".join(_columns))
        self.write_clipboard(f'SELECT {_columns_formatted}\nFROM xxxx L\nLEFT JOIN xxxx R\nON L.xxxx = R.xxxx')

    def sql_start_from_tabs_join_right(self):
        input_text = self._split_spaced_string(update_clipboard=False)
        _columns = re.split(', *', input_text)
        _columns_formatted = "R.{}".format(", R.".join(_columns))
        self.write_clipboard(f'SELECT {_columns_formatted}\nFROM xxxx L\nLEFT JOIN xxxx R\nON L.xxxx = R.xxxx')

    ############################################################################
    # Section:
    #   Clipboard Editing
    ############################################################################

    def _text_sort_lines(self, remove_duplicates: bool):
        """Sort Lines (reusable)"""
        # NOTE TO SELF: If I ever find that I need to support wrapped strings with linebreaks in them, redo this as csv
        input_text = self.read_clipboard(strip_carriage_returns=True)

        all_values = [row.strip() for row in re.split(r'\n', input_text) if row.strip()]
        if remove_duplicates:
            all_values = list(set(all_values))

        self.write_clipboard('\n'.join(Reusable.sort_list_treating_numbers_by_value(all_values)))

    ############################################################################
    # Clipboard Editing -> Text Editing

    def text_sort_lines_no_duplicates(self):
        """Sort Lines (no duplicates)"""
        self._text_sort_lines(remove_duplicates=True)

    def text_sort_lines_allow_duplicates(self):
        """Sort Lines (allow duplicates)"""
        self._text_sort_lines(remove_duplicates=False)

    def _text_sort_words_and_phrases(self, remove_duplicates: bool):
        """Sort Words and Phrases"""
        input_text = self.read_clipboard(trim_input=True, strip_carriage_returns=True)
        r = re.compile(r"([\"'`]+)(?P<quoted>(?s).*?)(?<!\\)\1|(?P<unquoted>\S+)")
        matches = [m.groupdict() for m in r.finditer(input_text)]
        all_values = [val for val in [tup.get(k) for tup in matches for k in ["quoted", "unquoted"]] if val]
        if remove_duplicates is True:
            all_values = list(set(all_values))
        self.write_clipboard('\t'.join(Reusable.sort_list_treating_numbers_by_value(all_values)))

    def text_sort_words_and_phrases_no_duplicates(self):
        """Sort Words and Phrases (allow duplicates)"""
        self._text_sort_words_and_phrases(remove_duplicates=True)

    def text_sort_words_and_phrases_allow_duplicates(self):
        """Sort Words and Phrases (allow duplicates)"""
        self._text_sort_words_and_phrases(remove_duplicates=False)

    def text_make_uppercase(self):
        """
        Text to Uppercase

        :return:
        """
        self.write_clipboard(self.read_clipboard(trim_input=False, upper=True))

    def text_make_lowercase(self):
        """
        Text to Lowercase

        :return:
        """
        self.write_clipboard(self.read_clipboard(trim_input=False, lower=True))

    def text_trim_string(self):
        """
        Trim Text in Clipboard

        :return:
        """
        self.write_clipboard(self.read_clipboard(trim_input=False).strip())

    def text_remove_formatting(self):
        """
        Remove Text Formatting
        (Merely copies text from clipboard back into clipboard, thus removing text formatting)

        :return:
        """
        self.write_clipboard(self.read_clipboard(trim_input=False))

    def encode_url_encoding(self):
        """ Decode URL Encoding (from clipboard) """
        input_text = self.read_clipboard()
        try:
            self.write_clipboard(urllib.parse.quote(input_text, safe=""))
        except:
            self.display_notification_error("URL encoding failed")

    def decode_url_encoding(self):
        """ Decode URL Encoding (from clipboard) """
        input_text = self.read_clipboard()
        try:
            self.write_clipboard(urllib.parse.unquote(input_text))
        except:
            self.display_notification_error("Failed to decode URL string")

    def action_encode_base_64(self):
        """Base64: Encode"""
        input_text = self.read_clipboard()
        encoded_str = base64.b64encode(str.encode(input_text, 'utf-8'))
        self.write_clipboard(encoded_str.decode())

    def action_decode_base_64(self):
        """Base64: Decode"""
        input_text = self.read_clipboard()
        encoded_str = base64.b64decode(input_text)
        self.write_clipboard(encoded_str.decode())

    def remove_non_ascii_characters(self):
        """Strip non-ascii characters"""
        input_text = self.read_clipboard()
        string_encode = input_text.encode("ascii", "ignore")
        string_decode = string_encode.decode()
        self.write_clipboard(string_decode)

    def white_space_to_underscores(self):
        """White space to underscores"""
        input_text = self.read_clipboard()
        self.write_clipboard(re.sub(r'\s+', '_', input_text))

    def spaced_string_to_commas(self):
        self._split_spaced_string()

    def spaced_string_to_commas_lowercase(self):
        self._split_spaced_string(force_lower=True)

    def spaced_string_to_commas_sorted(self):
        self._split_spaced_string(sort=True)

    def spaced_string_to_commas_sorted_lowercase(self):
        self._split_spaced_string(force_lower=True, sort=True)

    def spaced_string_to_commas_and_quotes(self):
        self._split_spaced_string(quote=True)

    def spaced_string_to_commas_and_quotes_lowercase(self):
        self._split_spaced_string(quote=True, force_lower=True)

    def spaced_string_to_commas_and_quotes_sorted(self):
        self._split_spaced_string(quote=True, sort=True)

    def spaced_string_to_commas_and_quotes_sorted_lowercase(self):
        self._split_spaced_string(quote=True, sort=True, force_lower=True)

    ############################################################################
    # Clipboard Editing -> Time Conversion

    def action_epoch_time_to_str(self, update_clipboard=False):
        """Show epoch time as local time"""
        input_text = self.read_clipboard().replace(',', '')
        try:
            _ = float(input_text)
        except ValueError:
            self.display_notification_error(f'"{input_text}" is not a valid number')
            return
        _output = Reusable.time_epoch_to_str(input_text).strip()
        self.display_notification(f'{input_text} = {_output}')
        if update_clipboard:
            self.write_clipboard(_output, skip_notification=True)

    def epoch_time_as_local_time_convert(self):
        self.action_epoch_time_to_str(update_clipboard=True)

    def print_menu_output(self):
        print(self.menu_output.strip())

    def execute_plugin(self, action):
        log.debug(f"Executing action: {action}")
        if not action:
            self.print_menu_output()
            return
        # Not required, but helps with testing to be able to paste in the
        # original name of an action rather than have to know what the sanitized
        # action name ends up being
        action = re.sub(r'\W', "_", action)
        if action not in self.action_list:
            raise Exception("Not a valid action")
        else:
            try:
                self.action_list[action].action()
            except Exception as err:
                # self.fail_action_with_exception(traceback.format_exc())
                self.fail_action_with_exception(exception=err)


log = Log()


def main():
    args = get_args()
    config = Config()
    bar = Actions(config)

    if args.list_actions:
        for a in sorted(bar.action_list.keys()):
            action_path = re.findall(r"Actions.\S+", str(bar.action_list[a].action))[0]
            print(f'{bar.action_list[a].name}:\n\tID: {bar.action_list[a].id}\n\tAction: {action_path}\n')
        exit(0)

    bar.execute_plugin(args.action)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nControl-C Pressed; stopping...")
        exit(1)
