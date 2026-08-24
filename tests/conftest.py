import importlib
import sys

# Pre-import and map all mangasurf modules to mangasurf in sys.modules
import mangasurf
import mangasurf.sources
import mangasurf.gui
import mangasurf.cli
import mangasurf.config
import mangasurf.covers
import mangasurf.database
import mangasurf.downloader
import mangasurf.features
import mangasurf.library
import mangasurf.metadata
import mangasurf.paths
import mangasurf.progress
import mangasurf.server
import mangasurf.tui

for name in list(sys.modules.keys()):
    if name.startswith("mangasurf"):
        mangasurf_name = "mangasurf" + name[9:]
        sys.modules[mangasurf_name] = sys.modules[name]

class AliasImporter:
    def find_spec(self, fullname, path, target=None):
        if fullname == "mangasurf" or fullname.startswith("mangasurf."):
            mangasurf_name = "mangasurf" + fullname[7:]
            try:
                mod = importlib.import_module(mangasurf_name)
                sys.modules[fullname] = mod
                return importlib.util.find_spec(mangasurf_name)
            except Exception:
                pass
        return None

sys.meta_path.insert(0, AliasImporter())
