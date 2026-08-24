"""A control window for the OPDS catalog server.

    python opdsserve.py --gui

Shows the catalog URL to type into Readest, the password, how many titles
are being served, and a live log of what readers are doing. Also runs the
cover-propagation tool, since "my shelf is full of blank tiles" is the
problem you notice the moment you open an OPDS reader.
"""

import logging
import os
import socket
import threading
import time

logger = logging.getLogger(__name__)


class OpdsController:
    """Starts the OPDS server and owns its log. The window's JS API."""

    def __init__(self, host="0.0.0.0", port=None, token=None,
                 no_auth=False, verbose=None):
        from . import opdsserve, servercfg

        self._serve = opdsserve
        self._cfg = servercfg
        self.host = host
        self._override_port = port
        self._override_token = token
        self.no_auth = no_auth

        stored = servercfg.load_server_settings()
        self.log = opdsserve.OpdsLog(
            verbose=stored["verbose"] if verbose is None else bool(verbose))
        self._thread = None
        self._server_holder = {}
        self._running = False
        self._url = ""
        self.window = None

        self.log.add("info", "Ready. The catalog starts automatically.")

    # ----------------------------------------------------------- state

    def get_state(self):
        from . import opds
        from .server import local_ip, tailscale_ip

        stored = self._cfg.load_server_settings()
        rows = opds.library_rows()
        ts = tailscale_ip()
        port = int(self._override_port or self._serve.opds_port())
        return {
            "ok": True,
            "running": self._running,
            "url": self._url,
            "token": "" if self.no_auth else (self._override_token
                                              or stored["token"]),
            "port": port,
            "verbose": self.log.verbose,
            "no_auth": self.no_auth,
            "titles": len(rows),
            "with_covers": sum(1 for r in rows if r["cover"]),
            "host_ip": local_ip(),
            "tailscale_ip": ts,
            "tailscale_url": f"http://{ts}:{port}/opds" if ts else "",
        }

    @staticmethod
    def _host_ip():
        from .server import local_ip
        return local_ip()

    # -------------------------------------------------------- settings

    def save_port(self, port):
        from .config import update_settings

        try:
            value = int(port)
        except (TypeError, ValueError):
            return {"ok": False, "message": "Port must be a number.",
                    "state": self.get_state()}
        if not (1024 <= value <= 65535):
            return {"ok": False,
                    "message": "Use 1024-65535; lower ports need admin rights.",
                    "state": self.get_state()}
        update_settings({"opds_port": value})
        self._override_port = None
        self.log.add("info", f"Port set to {value}.")
        if self._running:
            self.log.add("warn", "Restart to move ports.")
        return {"ok": True, "message": "Saved.", "state": self.get_state()}

    def set_verbose(self, on):
        self.log.verbose = bool(on)
        self._cfg.save_server_settings(verbose=bool(on))
        self.log.add("info", "Verbose logging "
                             + ("on - every request is listed."
                                if on else "off - errors only."))
        return {"ok": True, "state": self.get_state()}

    # --------------------------------------------------------- control

    def start(self):
        if self._running:
            return {"ok": False, "error": "Already running",
                    "state": self.get_state()}
        port = self.get_state()["port"]
        if not self._port_free(port):
            message = (f"Port {port} is in use - another copy of the OPDS "
                       "server is probably running.")
            self.log.add("error", message)
            return {"ok": False, "error": message, "state": self.get_state()}

        ready = threading.Event()

        def on_ready(url, _app, _log):
            self._url = url
            ready.set()

        def run():
            try:
                self._serve.serve(host=self.host, port=port,
                                  token=self._override_token,
                                  no_auth=self.no_auth,
                                  verbose=self.log.verbose, log=self.log,
                                  on_ready=on_ready,
                                  server_instance_holder=self._server_holder)
            except Exception as exc:
                self.log.add("error", f"Server stopped: {exc}")
            finally:
                self._running = False
                ready.set()

        self._thread = threading.Thread(target=run, name="readerm-opds",
                                        daemon=True)
        self._running = True
        self._thread.start()
        ready.wait(timeout=10)
        if not self._running:
            return {"ok": False, "error": "The server could not start",
                    "state": self.get_state()}
        return {"ok": True, "state": self.get_state()}

    def stop(self):
        """Stop serving."""
        if not self._running:
            return {"ok": False, "error": "Not running"}
        try:
            if self._server_holder and self._server_holder.get("server"):
                srv = self._server_holder["server"]
                srv.shutdown()
                if hasattr(srv, "server_close"):
                    srv.server_close()
            self._running = False
            self.log.add("info", "OPDS catalog stopped.")
            return {"ok": True, "state": self.get_state()}
        except Exception as exc:
            self.log.add("error", f"Could not stop OPDS catalog: {exc}")
            return {"ok": False, "error": str(exc), "state": self.get_state()}

    def get_log(self, since=0):
        try:
            since = int(since)
        except (TypeError, ValueError):
            since = 0
        cursor, lines = self.log.since(since)
        return {"ok": True, "cursor": cursor, "lines": lines,
                "running": self._running, "url": self._url}

    def clear_log(self):
        self.log.clear()
        self.log.add("info", "Log cleared.")
        return {"ok": True}

    def copy_link(self):
        state = self.get_state()
        return {"ok": True,
                "url": self._url or self._serve.build_url(
                    self.host, state["port"])}

    def open_in_browser(self):
        import webbrowser

        state = self.get_state()
        url = self._url or self._serve.build_url(self.host, state["port"])
        try:
            webbrowser.open(url)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # -------------------------------------------------------- file & folder import

    def choose_file(self):
        """Open a native file picker dialog."""
        if not self.window:
            return None
        import webview
        paths = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=("Comic & Book Files (*.cbz;*.epub;*.pdf;*.zip;*.cbr)", "All Files (*.*)")
        )
        return paths[0] if paths else None

    def choose_folder(self):
        """Open a native directory picker dialog."""
        if not self.window:
            return None
        import webview
        dirs = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        return dirs[0] if dirs else None

    def import_file(self, file_path=None):
        """Import a CBZ, EPUB, PDF, or ZIP file into the OPDS catalog library."""
        from . import library
        import shutil
        file_path = file_path or self.choose_file()
        if not file_path:
            return {"ok": False, "cancelled": True}
        if not os.path.isfile(file_path):
            return {"ok": False, "error": f"File not found: {file_path}"}

        out_dir = self.default_library_root()
        name = os.path.basename(file_path)
        title = os.path.splitext(name)[0].strip()
        series_dir = os.path.join(out_dir, title)
        os.makedirs(series_dir, exist_ok=True)
        dest = os.path.join(series_dir, name)

        try:
            if os.path.abspath(file_path) != os.path.abspath(dest):
                shutil.copy2(file_path, dest)
            library.scan_library_folders([out_dir])
            self.log.add("info", f"Imported '{name}' to OPDS catalog.")
            return {"ok": True, "file": dest, "state": self.get_state()}
        except Exception as e:
            self.log.add("error", f"Failed importing file: {e}")
            return {"ok": False, "error": str(e), "state": self.get_state()}

    def rescan_library(self):
        """Rescan all library directories and update OPDS catalog immediately."""
        from . import library
        out_dir = self.default_library_root()
        res = library.scan_library_folders([out_dir] if out_dir else None)
        self.log.add("info", f"Rescanned library: {res.get('total_series', 0)} series indexed ({res.get('discovered', 0)} new).")
        return {"ok": True, "state": self.get_state()}

    # -------------------------------------------------------- folder organizer

    def get_folders(self):
        from . import opds
        return {"ok": True, "folders": opds.load_opds_folders()}

    def add_folder(self, name, filter_spec="", folder_type="shelf"):
        from . import opds
        import re
        name = str(name or "").strip()
        if not name:
            return {"ok": False, "error": "Folder name cannot be empty"}
        folder_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "folder"
        folders = opds.load_opds_folders()
        base_id = folder_id
        idx = 2
        while any(f.get("id") == folder_id for f in folders):
            folder_id = f"{base_id}-{idx}"
            idx += 1
        new_entry = {
            "id": folder_id,
            "name": name,
            "type": folder_type,
            "enabled": True,
            "filter": filter_spec or f"shelf:{name}",
        }
        folders.append(new_entry)
        opds.save_opds_folders(folders)
        self.log.add("info", f"Added OPDS section '{name}'.")
        return {"ok": True, "folders": folders}

    def toggle_folder(self, folder_id, enabled):
        from . import opds
        folders = opds.load_opds_folders()
        for f in folders:
            if f.get("id") == folder_id:
                f["enabled"] = bool(enabled)
        opds.save_opds_folders(folders)
        return {"ok": True, "folders": folders}

    def remove_folder(self, folder_id):
        from . import opds
        folders = opds.load_opds_folders()
        folders = [f for f in folders if f.get("id") != folder_id]
        opds.save_opds_folders(folders)
        self.log.add("info", f"Removed OPDS section '{folder_id}'.")
        return {"ok": True, "folders": folders}

    def reorder_folders(self, folder_ids):
        from . import opds
        current = {f.get("id"): f for f in opds.load_opds_folders()}
        reordered = []
        for fid in folder_ids:
            if fid in current:
                reordered.append(current.pop(fid))
        reordered.extend(current.values())
        opds.save_opds_folders(reordered)
        return {"ok": True, "folders": reordered}

    # ---------------------------------------------------------- covers

    def default_library_root(self):
        from .config import load_settings
        return load_settings().get("output_dir") or ""

    def preview_covers(self, root=None, overwrite=False):
        from . import covers as covers_mod

        root = root or self.default_library_root()
        rows = covers_mod.scan_image_folders(root, overwrite=bool(overwrite))
        self.log.add("info",
                     f"{len(rows)} folder(s) under {root} need a cover.")
        return {"ok": True, "root": root, "count": len(rows),
                "folders": [{"directory": r["directory"], "images": r["count"],
                             "first": os.path.basename(r["first"])}
                            for r in rows[:200]]}

    def apply_covers(self, root=None, overwrite=False, source="first"):
        from . import covers as covers_mod

        root = root or self.default_library_root()
        self.log.add("info", f"Adding covers under {root}…")
        result = covers_mod.propagate_covers(root, overwrite=bool(overwrite),
                                             source=source)
        self.log.add("info", f"Created {len(result['created'])} cover(s), "
                             f"{len(result['failed'])} failed.")
        for failure in result["failed"][:5]:
            self.log.add("error", f"{failure['directory']}: {failure['error']}")
        return {"ok": True, "created": len(result["created"]),
                "failed": len(result["failed"]), "state": self.get_state()}

    @staticmethod
    def _port_free(port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("", int(port)))
            return True
        except OSError:
            return False
        finally:
            sock.close()


def run_opds_window(host="0.0.0.0", port=None, token=None, no_auth=False,
                    verbose=None):
    """Open the control window. Returns a process exit code."""
    try:
        import webview
    except ImportError:
        print("The OPDS window needs pywebview:\n\n"
              "    pip install pywebview\n\n"
              "Or run without it:  python opdsserve.py")
        return 1

    controller = OpdsController(host=host, port=port, token=token,
                                no_auth=no_auth, verbose=verbose)
    logging.getLogger("pywebview").setLevel(logging.CRITICAL)

    window = webview.create_window(
        "Mangasurf OPDS catalog", html=PAGE, js_api=controller,
        width=780, height=720, min_size=(580, 540),
        background_color="#0b0a12")
    controller.window = window

    def boot():
        time.sleep(0.4)
        try:
            controller.start()
        except Exception:
            logger.exception("could not auto-start the OPDS server")

    threading.Thread(target=boot, daemon=True).start()

    try:
        webview.start()
    except Exception as exc:
        logger.debug("opds window failed", exc_info=True)
        print("\n" + "-" * 58)
        print("  The OPDS window could not open.")
        print(f"  {exc}")
        print("-" * 58)
        print("  Run it without a window instead:")
        print("    python opdsserve.py")
        print("-" * 58 + "\n")
        return 1
    return 0


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Mangasurf OPDS</title>
<style>
:root{
  --bg:#0b0a12; --panel:#16151f; --panel-2:#1c1b28; --line:#26243a;
  --ink:#f2f0ff; --ink-2:#a8a3c4; --ink-3:#6f6a90;
  --a:#ff5f8f; --b:#7c6bff; --c:#3ddad7; --d:#ffb648; --err:#ff6b6b;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);padding:18px;
  font:14px/1.55 'Segoe UI',system-ui,-apple-system,sans-serif;
  display:flex;flex-direction:column;gap:13px;height:100vh}
h1{font-size:17px;font-weight:700;display:flex;align-items:center;gap:9px}
.dot{width:9px;height:9px;border-radius:50%;background:var(--ink-3);flex:none}
.dot.on{background:var(--c);box-shadow:0 0 0 3px rgba(61,218,215,.18);
  animation:pulse 2.4s ease-in-out infinite}
@keyframes pulse{50%{opacity:.45}}
.card{background:var(--panel);border:1px solid var(--line);
  border-radius:12px;padding:14px}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
label{font-size:11px;font-weight:700;letter-spacing:.07em;
  text-transform:uppercase;color:var(--ink-3);display:block;margin-bottom:6px}
input[type=text],input[type=number]{background:var(--panel-2);
  border:1px solid var(--line);color:var(--ink);border-radius:8px;
  padding:9px 11px;font:13px 'Consolas',monospace;outline:none;flex:1;min-width:0}
input:focus{border-color:var(--b)}
button{background:var(--panel-2);color:var(--ink);border:1px solid var(--line);
  border-radius:8px;padding:9px 14px;font-size:13px;font-weight:600;
  cursor:pointer;white-space:nowrap}
button:hover{border-color:var(--b)}
button.primary{background:linear-gradient(135deg,var(--a),var(--b));
  border-color:transparent;color:#fff}
button:disabled{opacity:.45;cursor:default}
.url{font:12.5px 'Consolas',monospace;color:var(--c);word-break:break-all;
  background:var(--panel-2);border:1px solid var(--line);border-radius:8px;
  padding:10px 12px;flex:1;min-width:0}
.msg{font-size:12px;margin-top:7px;color:var(--ink-3);min-height:16px}
.msg.bad{color:var(--err)} .msg.good{color:var(--c)}
.stats{display:flex;gap:16px;font-size:12.5px;color:var(--ink-3);margin-top:8px}
.stats b{color:var(--ink);font-size:15px;display:block}
.logwrap{flex:1;display:flex;flex-direction:column;min-height:0}
.loghead{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.loghead h2{font-size:11.5px;font-weight:700;letter-spacing:.08em;
  text-transform:uppercase;color:var(--ink-3);flex:1}
#log{flex:1;overflow-y:auto;background:#0e0d17;border:1px solid var(--line);
  border-radius:10px;padding:10px 12px;font:11.5px/1.65 'Consolas',monospace;
  min-height:110px}
.line{display:flex;gap:8px}
.line .t{color:#4f4a70;flex:none}
.line.info .m{color:var(--ink-2)} .line.call .m{color:var(--ink-3)}
.line.warn .m{color:var(--d)} .line.error .m{color:var(--err)}
.check{display:flex;align-items:center;gap:7px;font-size:12.5px;
  color:var(--ink-2);cursor:pointer}
.hint{font-size:12px;color:var(--ink-3);margin-top:8px}
</style>
</head>
<body>

<h1><span class="dot" id="dot"></span> Mangasurf OPDS catalog</h1>

<div class="card">
  <label>Add this in Readest</label>
  <div class="row">
    <div class="url" id="url">Starting…</div>
    <button id="copyBtn">Copy</button>
    <button id="openBtn">Open</button>
  </div>
  <div class="stats">
    <div><b id="titles">0</b>titles</div>
    <div><b id="covers">0</b>with covers</div>
    <div><b id="portShow">-</b>port</div>
  </div>
  <div class="msg" id="urlMsg">Use the token as the password. Any username.</div>
</div>

<div class="card">
  <label>Catalog File & Manga Import</label>
  <div class="row">
    <button id="importFileBtn" class="primary" style="flex:1">📁 Import CBZ / EPUB / File</button>
    <button id="rescanLibBtn" style="flex:1">🔄 Rescan Library Folders</button>
  </div>
  <div class="hint">Copies any chosen CBZ or manga file directly into the OPDS catalog library.</div>
</div>

<div class="card">
  <div class="row">
    <div style="flex:0 0 110px">
      <label for="port">Port</label>
      <input type="number" id="port" min="1024" max="65535">
    </div>
    <button id="portBtn" style="align-self:flex-end">Save port</button>
    <span style="flex:1"></span>
    <label class="check" style="align-self:flex-end;text-transform:none;
      letter-spacing:0;font-weight:400">
      <input type="checkbox" id="verbose"> Verbose log
    </label>
  </div>
  <div class="hint">The password is the access token from
    Settings &rarr; Phone server.</div>
</div>

<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
    <label style="margin-bottom:0">Organise Catalog Shelves & Folders</label>
    <button class="primary" id="addFolderBtn" style="padding:4px 10px;font-size:12px">+ Add Section</button>
  </div>
  <div id="foldersList" style="display:flex;flex-direction:column;gap:6px;max-height:140px;overflow-y:auto;padding-right:4px">
    <!-- Populated by JS -->
  </div>
  <div id="addFolderForm" style="display:none;margin-top:10px;padding:10px;background:var(--panel-2);border-radius:8px;border:1px solid var(--line)">
    <label>New Section Name</label>
    <div class="row">
      <input type="text" id="newFolderName" placeholder="e.g. Action Favorites, Manhwa Vault">
      <button id="saveFolderBtn" class="primary">Add</button>
      <button id="cancelFolderBtn">Cancel</button>
    </div>
  </div>
  <div class="hint">Sections appear as top-level subsections in Readest, Panels, and Moon+ Reader.</div>
</div>

<div class="card">
  <label>Covers for image folders</label>
  <div class="row">
    <input type="text" id="root" placeholder="Folder to scan" spellcheck="false">
    <button id="scanBtn">Preview</button>
    <button id="applyBtn" class="primary">Add covers</button>
  </div>
  <div class="msg" id="coverMsg">Gives every folder of page images its own
    cover file, so shelves are not blank tiles.</div>
</div>

<div class="logwrap">
  <div class="loghead">
    <h2>Log</h2>
    <button id="clearBtn">Clear</button>
  </div>
  <div id="log"></div>
</div>

<script>
var api=null, cursor=0;
function el(id){return document.getElementById(id);}
function ready(fn){
  if(window.pywebview&&window.pywebview.api)return fn();
  window.addEventListener('pywebviewready',fn,{once:true});
}
function msg(id,text,kind){
  var n=el(id); n.textContent=text||''; n.className='msg'+(kind?' '+kind:'');
}
function paint(s){
  if(!s)return;
  el('dot').className='dot'+(s.running?' on':'');
  el('url').textContent=s.url||('http://'+s.host_ip+':'+s.port+'/opds');
  el('titles').textContent=s.titles;
  el('covers').textContent=s.with_covers;
  el('portShow').textContent=s.port;
  if(document.activeElement!==el('port'))el('port').value=s.port;
  el('verbose').checked=!!s.verbose;
  if(!el('root').value&&s.root)el('root').value=s.root;
}
function pump(){
  api.get_log(cursor).then(function(r){
    if(r&&r.ok){
      cursor=r.cursor;
      var box=el('log');
      var stuck=box.scrollTop+box.clientHeight>=box.scrollHeight-30;
      (r.lines||[]).forEach(function(l){
        var d=document.createElement('div');
        d.className='line '+l.level;
        d.innerHTML='<span class="t"></span><span class="m"></span>';
        d.children[0].textContent=l.time;
        d.children[1].textContent=l.text;
        box.appendChild(d);
      });
      if(stuck)box.scrollTop=box.scrollHeight;
      while(box.children.length>600)box.removeChild(box.firstChild);
      el('dot').className='dot'+(r.running?' on':'');
      if(r.url)el('url').textContent=r.url;
    }
    setTimeout(pump,800);
  }).catch(function(){setTimeout(pump,2200);});
}
function renderFolders(folders){
  var box = el('foldersList');
  if(!box) return;
  box.innerHTML = (folders||[]).map(function(f, idx){
    return '<div class="row" style="background:var(--panel-2);padding:6px 10px;border-radius:6px;font-size:12px;justify-content:space-between">'
      + '<div style="display:flex;align-items:center;gap:8px">'
      + '<input type="checkbox" '+(f.enabled?'checked':'')+' data-id="'+f.id+'" class="folder-chk">'
      + '<strong>'+(f.name||f.id)+'</strong>'
      + '<span style="font-size:10px;color:var(--ink-3);background:var(--panel);padding:1px 6px;border-radius:4px">'+(f.type||'shelf')+'</span>'
      + '</div>'
      + '<div style="display:flex;gap:4px">'
      + '<button class="folder-del-btn" data-id="'+f.id+'" style="padding:2px 6px;font-size:11px;color:var(--err)">✕</button>'
      + '</div>'
      + '</div>';
  }).join('');
  box.querySelectorAll('.folder-chk').forEach(function(chk){
    chk.addEventListener('change', function(e){
      api.toggle_folder(e.target.dataset.id, e.target.checked).then(function(r){
        if(r&&r.ok) renderFolders(r.folders);
      });
    });
  });
  box.querySelectorAll('.folder-del-btn').forEach(function(btn){
    btn.addEventListener('click', function(e){
      api.remove_folder(e.target.dataset.id).then(function(r){
        if(r&&r.ok) renderFolders(r.folders);
      });
    });
  });
}
ready(function(){
  api=window.pywebview.api;
  api.get_state().then(paint);
  api.get_folders().then(function(r){ if(r&&r.ok) renderFolders(r.folders); });
  api.default_library_root().then(function(p){ if(p) el('root').value=p; });
  pump();

  el('addFolderBtn').addEventListener('click', function(){
    el('addFolderForm').style.display = 'block';
    el('newFolderName').focus();
  });
  el('cancelFolderBtn').addEventListener('click', function(){
    el('addFolderForm').style.display = 'none';
  });
  el('saveFolderBtn').addEventListener('click', function(){
    var name = el('newFolderName').value.trim();
    if(!name) return;
    api.add_folder(name).then(function(r){
      if(r&&r.ok){
        renderFolders(r.folders);
        el('newFolderName').value = '';
        el('addFolderForm').style.display = 'none';
      }
    });
  });

  el('portBtn').addEventListener('click',function(){
    api.save_port(el('port').value).then(function(r){
      msg('urlMsg',r.message,r.ok?'good':'bad'); paint(r.state);
    });
  });
  el('verbose').addEventListener('change',function(e){
    api.set_verbose(e.target.checked).then(function(r){paint(r.state);});
  });
  el('copyBtn').addEventListener('click',function(){
    api.copy_link().then(function(r){
      if(!r.ok)return;
      var fail=function(){
        /* The clipboard API needs a secure context and this page is served
           from html=, so select the text as a fallback. */
        var range=document.createRange();
        range.selectNodeContents(el('url'));
        var sel=window.getSelection();
        sel.removeAllRanges(); sel.addRange(range);
        msg('urlMsg','Selected - press Ctrl+C.','good');
      };
      try{
        if(navigator.clipboard&&navigator.clipboard.writeText){
          navigator.clipboard.writeText(r.url).then(
            function(){msg('urlMsg','Link copied.','good');},fail);
        }else{fail();}
      }catch(e){fail();}
    });
  });
  el('importFileBtn').addEventListener('click', function(){
    api.import_file().then(function(r){
      if(r&&r.ok){
        msg('urlMsg','File imported to catalog.','good');
        paint(r.state);
      }
    });
  });
  el('rescanLibBtn').addEventListener('click', function(){
    api.rescan_library().then(function(r){
      if(r&&r.ok){
        msg('urlMsg','Catalog library rescanned.','good');
        paint(r.state);
      }
    });
  });
  el('openBtn').addEventListener('click',function(){api.open_in_browser();});
  el('clearBtn').addEventListener('click',function(){
    api.clear_log().then(function(){el('log').innerHTML='';cursor=0;});
  });
  el('scanBtn').addEventListener('click',function(){
    msg('coverMsg','Scanning…');
    api.preview_covers(el('root').value).then(function(r){
      msg('coverMsg',r.count?(r.count+' folder(s) would get a cover.')
                            :'Every folder already has a cover.','good');
    });
  });
  el('applyBtn').addEventListener('click',function(){
    msg('coverMsg','Working…');
    api.apply_covers(el('root').value).then(function(r){
      msg('coverMsg','Created '+r.created+' cover(s)'+
          (r.failed?', '+r.failed+' failed':'')+'.',r.failed?'bad':'good');
      paint(r.state);
    });
  });
  setInterval(function(){api.get_state().then(paint);},4000);
});
</script>
</body>
</html>
"""
