"""ReaderM reader — a manga-first fork of foliate-js.

Why a local HTTP server instead of loading the page off disk
------------------------------------------------------------
The reader is built out of ES modules, and browsers refuse to load those over
``file://``. Measured in Chromium:

    Access to script at 'file:///tmp/esm/mod.js' from origin 'null' has been
    blocked by CORS policy: Cross origin requests are only supported for
    protocol schemes: chrome, chrome-untrusted, data, http, https.

The old GUI pointed pywebview straight at ``web/index.html`` on disk, which is
fine for one big classic script but would break every ``import`` in the engine.
So the app serves its own assets from ``http://127.0.0.1:<port>``.

That server does double duty. It also streams book files and loose page images
to the reader, which is what lets the same UI show a finished ``.cbz`` and a
chapter that is still a folder of ``.jpg`` files coming off a download.

Everything is bound to 127.0.0.1 and gated behind a per-process token, so
nothing on the network can read the library through it.
"""

if __package__ in (None, ""):        # pragma: no cover - direct execution
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "readerm.reader"

from .assets import (ASSET_ROOT, AssetServer, LOOPBACK, MEDIA_TYPES,
                     content_type_for, is_safe_relative, new_token)

__all__ = [
    "ASSET_ROOT",
    "AssetServer",
    "LOOPBACK",
    "MEDIA_TYPES",
    "content_type_for",
    "is_safe_relative",
    "new_token",
]
