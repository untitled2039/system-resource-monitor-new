"""Run this on a Windows computer you want to monitor from another PC.

The monitoring PC shows a 5-digit code under "Connect device"; type it here.
(File name kept so existing build and installer scripts keep working.)
"""
from monitor.remote_link import run_agent


if __name__ == "__main__":
    run_agent()
