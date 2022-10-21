# BitBar_LogicHub
BitBar/xbar plugin with handy features for frequent LogicHub users

# Required Software
* xbar (formerly BitBar): https://github.com/matryer/xbar
* git (install via brew)
* Python 3.6+ (must resolve via /usr/local/bin/python3)

# Required Python Packages
The following Python packages are required. (See requirements.txt for exact versions)

* clipboard
* configparser
* sqlparse
* configobj
* dataclasses-json
* psutil
* json2html
* selenium (only required if you want URL & HTML screenshot actions to work)

Note: since these packages must be installed for whatever installation of 
Python3 resolves from /usr/local/bin/python3, you may run into errors when just 
running "pip install" or "pip3 install" from its default location. In those 
cases you may need to provide the target location to install the package, like 
this:

`pip3 install --target /usr/local/lib/python3.7/site-packages <package_name>`


# Installation
1. Ensure that the requirements above are met
1. Clone this repo
   1. Open a terminal
   1. Navigate to the directory where you wish to store these files (home directory is okay)
   1. Run the following command: 
   `git clone git@github.com:deathbywedgie/BitBar_LogicHub.git`
1. Copy `logichub_tools.ini` from the BitBar_LogicHub directory to your home directory
1. Open `logichub_tools.ini` (vi or any text editor), and edit the "repo_path" variable to provide the path to the BitBar_LogicHub repo you just cloned
1. Add the plugin to xbar with one of the following methods:
   1. Option 1 (recommended): using the terminal, navigate to the existing plugin folder for xbar and create a symbolic link to this plugin so that updates are automatically in effect if you update with "git pull" `ln -s <path>/BitBar_LogicHub/plugin/LHUB.py LHUB.1h.py`
   1. Option 2: copy the plugin file: `cp <path>/BitBar_LogicHub/plugin/LHUB.py LHUB.1h.py`
1. If the plugin does not show up in your status bar right away, you may need to quit and re-launch xbar
1. For URL and HTML screenshot actions, you must install the Chrome driver and keep it in sync with the version of Chrome installed in MacOS. 
You may also have to run it once manually so that MacOS prompts you to allow it to run or it will be blocked when called by xbar.