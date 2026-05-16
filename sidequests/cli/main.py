"""Shim for sidequests.cli.main -> campy.cli.main."""
from campy.cli.main import *

if __name__ == "__main__":
    from campy.cli.main import app
    app()
