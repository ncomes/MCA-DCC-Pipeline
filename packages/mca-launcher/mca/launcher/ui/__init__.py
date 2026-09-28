"""
The windows. They call :mod:`mca.launcher.api` and nothing else.

No logic lives here: no path building, no version detection, no installing. If a button
needs something done, the API grows a function and the button calls it - which keeps the
command line and an agent exactly as capable as the window.
"""
