"""Mangasurf - High-performance manga reader, downloader, and omnibar search engine."""

import os as _os
import sys as _sys

# When this package's directory ends up on ``sys.path`` -- which happens when
# you run ``python mangasurf/server.py`` directly (Python puts the script's
# directory at sys.path[0]) or when an IDE like PyCharm adds the package
# folder to its source roots -- the package's own modules shadow the stdlib.
# Because Mangasurf has a ``http.py`` and a ``server.py``, a bare
# ``import http`` then resolves to **our** http.py, not the stdlib package,
# and third-party libraries that do ``from http.cookies import SimpleCookie``
# (curl_cffi) or ``from xml.sax import ...`` (opds) blow up -- which surfaces
# as a bogus "partially initialized module" / circular-import traceback.
# Drop the package directory so the stdlib always wins.
_THIS_DIR = _os.path.dirname(_os.path.abspath(__file__))
try:
    _sys.path.remove(_THIS_DIR)
except ValueError:
    pass
del _THIS_DIR

from . import paths

__version__ = "1.7.3"
__app_name__ = "Mangasurf"
__author__ = "Mangasurf Team"

# Backwards compatibility alias
__all__ = ["__version__", "__app_name__", "paths"]
