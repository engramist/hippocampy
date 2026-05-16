"""HippoCampy daemon entry point for installed packages.

Console scripts:
  campy-daemon = "campy.daemon:main"
  sidequests-daemon = "campy.daemon:main"  # legacy alias
"""


def main():
    """Start the HippoCampy daemon."""
    from campy import brain_daemon

    brain_daemon.main()
