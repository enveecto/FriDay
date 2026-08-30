"""Compatibility launcher for older FRIDAY shortcuts.

The maintained application lives in main.py. Keeping this file means existing
shortcuts continue to work without retaining the insecure legacy implementation.
"""

from main import run


if __name__ == "__main__":
    run()
