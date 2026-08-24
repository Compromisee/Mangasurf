"""A small control window for the LAN server.

    python server.py --gui

Deliberately plain: one page, no build step, no framework. It does the four
things you actually need when serving to a phone — start and stop, set the
token, copy the link, and watch what the phone is doing.

The window is pywebview, the same engine the main app uses, so this adds no
new dependency beyond the one the GUI already needs. The server itself runs
on a background thread; the window only talks to it through
:class:`ServerController`.
"""

import logging
import socket
import threading
import time

logger = logging.getLogger(__name__)


class ServerController:
    """Starts and stops the Flask server, and owns its log.

    Exposed to the page as the pywebview JS API. Every method returns a
    dict, because that is the shape the page already handles.
    """

    def __init__(self, host="0.0.0.0", port=None, token=None,
                 no_auth=False, verbose=None):
        from . import server as server_module
        from mangasurf import servercfg

        self._server = server_module
        self._cfg = servercfg
        self.host = host
        self._override_port = port
        self._override_token = token
        self.no_auth = no_auth

        stored = servercfg.load_server_settings()
        self.log = server_module.ServerLog(
            verbose=stored["verbose"] if verbose is None else bool(verbose))
        self._thread = None
        self._running = False
        self._url = ""
        self._flask = None
        self._server_holder = {}
        self.window = None

        self.log.add("info", "Ready. Press Start to serve.")

    # ----------------------------------------------------------- state

    def get_state(self):
        stored = self._cfg.load_server_settings()
        ts = self._server.tailscale_ip()
        port = int(self._override_port or stored["port"])
        return {
            "ok": True,
            "running": self._running,
            "url": self._url,
            "token": "" if self.no_auth else (self._override_token
                                              or stored["token"]),
            "port": port,
            "verbose": self.log.verbose,
            "no_auth": self.no_auth,
            "min_length": self._cfg.MIN_TOKEN_LENGTH,
            "host_ip": self._server.local_ip(),
            "tailscale_ip": ts,
            "tailscale_url": f"http://{ts}:{port}" if ts else "",
        }

    # -------------------------------------------------------- settings

    def save_token(self, token):
        ok, message, _ = self._cfg.save_server_settings(token=token)
        self.log.add("info" if ok else "error",
                     f"Token: {message}" if ok else message)
        if ok and self._running:
            self.log.add("warn", "Restart the server for the new token to "
                                 "take effect.")
        self._override_token = None if ok else self._override_token
        return {"ok": ok, "message": message, "state": self.get_state()}

    def generate_token(self):
        token = self._cfg.generate_token()
        ok, message, _ = self._cfg.save_server_settings(token=token)
        if ok:
            self.log.add("info", "Generated a new token.")
            if self._running:
                self.log.add("warn", "Restart the server for it to take "
                                     "effect.")
        self._override_token = None
        return {"ok": ok, "message": message, "token": token,
                "state": self.get_state()}

    def save_port(self, port):
        ok, message, _ = self._cfg.save_server_settings(port=port)
        if ok:
            self.log.add("info", f"Port set to {port}.")
            if self._running:
                self.log.add("warn", "Restart the server to move ports.")
            self._override_port = None
        else:
            self.log.add("error", message)
        return {"ok": ok, "message": message, "state": self.get_state()}

    def set_verbose(self, on):
        self.log.verbose = bool(on)
        self._cfg.save_server_settings(verbose=bool(on))
        self.log.add("info", "Verbose logging "
                             + ("on - every API call is listed."
                                if on else "off - errors only."))
        return {"ok": True, "state": self.get_state()}

    # --------------------------------------------------------- control

    def start(self):
        if self._running:
            return {"ok": False, "error": "Already running",
                    "state": self.get_state()}

        state = self.get_state()
        port = state["port"]

        # Check the port here rather than letting Flask fail on a background
        # thread, where the traceback would never reach the window.
        if not self._port_free(port):
            message = (f"Port {port} is already in use - another copy of the "
                       "server is probably running.")
            self.log.add("error", message)
            return {"ok": False, "error": message, "state": self.get_state()}

        ready = threading.Event()

        def on_ready(url, flask_app, _log):
            self._url = url
            self._flask = flask_app
            ready.set()

        def run():
            try:
                self._server.serve(
                    host=self.host, port=port,
                    token=self._override_token, no_auth=self.no_auth,
                    verbose=self.log.verbose, log=self.log,
                    on_ready=on_ready,
                    server_instance_holder=self._server_holder)
            except Exception as exc:
                self.log.add("error", f"Server stopped: {exc}")
            finally:
                self._running = False
                ready.set()

        self._thread = threading.Thread(target=run, name="mangasurf-flask",
                                        daemon=True)
        self._running = True
        self._thread.start()
        ready.wait(timeout=10)
        # serve() sets _running False again if it fell over immediately.
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
            self.log.add("info", "Server stopped.")
            return {"ok": True, "state": self.get_state()}
        except Exception as exc:
            self.log.add("error", f"Could not stop server: {exc}")
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
        """Put the phone URL on the host's clipboard.

        pywebview has no clipboard API, so this is done in the page with
        navigator.clipboard and this endpoint only supplies the text -- one
        source of truth for what the link actually is.
        """
        state = self.get_state()
        url = self._url or self._server.build_url(
            self.host, state["port"], state["token"])
        return {"ok": True, "url": url}

    def open_in_browser(self):
        import webbrowser
        state = self.get_state()
        url = self._url or self._server.build_url(
            self.host, state["port"], state["token"])
        try:
            webbrowser.open(url)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

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


def run_server_window(host="0.0.0.0", port=None, token=None,
                      no_auth=False, verbose=None):
    """Open the control window. Returns a process exit code."""
    try:
        import webview
    except ImportError:
        print("The server window needs pywebview:\n\n"
              "    pip install pywebview\n\n"
              "Or run without it:  python server.py")
        return 1

    controller = ServerController(host=host, port=port, token=token,
                                  no_auth=no_auth, verbose=verbose)

    window = webview.create_window(
        "Mangasurf server", html=PAGE, js_api=controller,
        width=760, height=680, min_size=(560, 520),
        background_color="#0b0a12")
    controller.window = window

    # Auto-start: opening this window is the act of asking for a server.
    def _boot():
        time.sleep(0.4)
        try:
            controller.start()
        except Exception:
            logger.exception("could not auto-start the server")

    threading.Thread(target=_boot, daemon=True).start()

    try:
        webview.start()
    except Exception as exc:
        logger.exception("server window failed")
        print(f"Could not open the window: {exc}")
        return 1
    return 0


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Mangasurf server</title>
<style>
:root{
  --bg:#0b0a12; --panel:#16151f; --panel-2:#1c1b28; --line:#26243a;
  --ink:#f2f0ff; --ink-2:#a8a3c4; --ink-3:#6f6a90;
  --a:#ff5f8f; --b:#7c6bff; --c:#3ddad7; --d:#ffb648; --err:#ff6b6b;
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:var(--bg);color:var(--ink);
  font:14px/1.55 'Segoe UI',system-ui,-apple-system,sans-serif;
  padding:18px;display:flex;flex-direction:column;gap:14px;height:100vh;
}
h1{font-size:17px;font-weight:700;letter-spacing:-.2px;
   display:flex;align-items:center;gap:9px}
.dot{width:9px;height:9px;border-radius:50%;background:var(--ink-3);
     box-shadow:0 0 0 3px rgba(255,255,255,.05);flex:none}
.dot.on{background:var(--c);box-shadow:0 0 0 3px rgba(61,218,215,.18);
        animation:pulse 2.4s ease-in-out infinite}
@keyframes pulse{50%{opacity:.45}}
.card{background:var(--panel);border:1px solid var(--line);
      border-radius:12px;padding:14px}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
label{font-size:11px;font-weight:700;letter-spacing:.07em;
      text-transform:uppercase;color:var(--ink-3);display:block;
      margin-bottom:6px}
input[type=text],input[type=number]{
  background:var(--panel-2);border:1px solid var(--line);color:var(--ink);
  border-radius:8px;padding:9px 11px;font:13px 'Consolas',monospace;
  outline:none;flex:1;min-width:0;
}
input:focus{border-color:var(--b)}
input.bad{border-color:var(--err)}
button{
  background:var(--panel-2);color:var(--ink);border:1px solid var(--line);
  border-radius:8px;padding:9px 14px;font-size:13px;font-weight:600;
  cursor:pointer;white-space:nowrap;
}
button:hover{border-color:var(--b)}
button.primary{background:linear-gradient(135deg,var(--a),var(--b));
               border-color:transparent;color:#fff}
button:disabled{opacity:.45;cursor:default}
.url{
  font:12.5px 'Consolas',monospace;color:var(--c);word-break:break-all;
  background:var(--panel-2);border:1px solid var(--line);
  border-radius:8px;padding:10px 12px;flex:1;min-width:0;
}
.msg{font-size:12px;margin-top:7px;color:var(--ink-3);min-height:16px}
.msg.bad{color:var(--err)}
.msg.good{color:var(--c)}
.hint{font-size:12px;color:var(--ink-3);margin-top:8px}
.logwrap{flex:1;display:flex;flex-direction:column;min-height:0}
.loghead{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.loghead h2{font-size:12px;font-weight:700;letter-spacing:.07em;
            text-transform:uppercase;color:var(--ink-3);flex:1}
#log{
  flex:1;overflow-y:auto;background:#0e0d17;border:1px solid var(--line);
  border-radius:10px;padding:10px 12px;font:12px/1.7 'Consolas',monospace;
  min-height:120px;
}
.line{display:flex;gap:9px}
.line .t{color:#4f4a70;flex:none}
.line.info .m{color:var(--ink-2)}
.line.call .m{color:var(--ink-3)}
.line.warn .m{color:var(--d)}
.line.error .m{color:var(--err)}
.check{display:flex;align-items:center;gap:7px;font-size:12.5px;
       color:var(--ink-2);cursor:pointer}
.warnbar{background:rgba(255,182,72,.1);border:1px solid rgba(255,182,72,.3);
         color:var(--d);border-radius:8px;padding:8px 11px;font-size:12px}
</style>
</head>
<body>

<h1><span class="dot" id="dot"></span> Mangasurf server</h1>

<div class="card">
  <label>Open this on your phone</label>
  <div class="row">
    <div class="url" id="url">Starting…</div>
    <button id="copyBtn">Copy</button>
    <button id="openBtn">Open here</button>
  </div>
  <div class="msg" id="urlMsg">Both devices must be on the same Wi-Fi.</div>
</div>

<div class="card">
  <label for="token">Access token</label>
  <div class="row">
    <input type="text" id="token" spellcheck="false" autocomplete="off">
    <button id="genBtn">Generate</button>
    <button id="saveBtn" class="primary">Save</button>
  </div>
  <div class="msg" id="tokenMsg"></div>
  <div class="row" style="margin-top:10px">
    <div style="flex:0 0 120px">
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
  <div class="hint">Also editable in the app under
    Settings &rarr; Phone server. Changes need a restart.</div>
</div>

<div class="warnbar" id="noauth" style="display:none">
  Running with no access token — anyone on this network can control Mangasurf.
</div>

<div class="logwrap">
  <div class="loghead">
    <h2>Log</h2>
    <button id="clearBtn">Clear</button>
  </div>
  <div id="log"></div>
</div>

<script>
var api = null, cursor = 0, minLen = 16;

function ready(fn){
  if (window.pywebview && window.pywebview.api) return fn();
  window.addEventListener('pywebviewready', fn, {once:true});
}

function el(id){ return document.getElementById(id); }

function setMsg(id, text, kind){
  var n = el(id);
  n.textContent = text || '';
  n.className = 'msg' + (kind ? ' ' + kind : '');
}

function paintState(s){
  if (!s) return;
  minLen = s.min_length || 16;
  el('dot').className = 'dot' + (s.running ? ' on' : '');
  el('url').textContent = s.url || ('http://' + s.host_ip + ':' + s.port +
                                    (s.token ? '/?token=' + s.token : '/'));
  if (document.activeElement !== el('token')) el('token').value = s.token || '';
  if (document.activeElement !== el('port')) el('port').value = s.port;
  el('verbose').checked = !!s.verbose;
  el('noauth').style.display = s.no_auth ? '' : 'none';
}

function pumpLog(){
  api.get_log(cursor).then(function(r){
    if (r && r.ok){
      cursor = r.cursor;
      var box = el('log');
      var stuck = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
      (r.lines || []).forEach(function(l){
        var d = document.createElement('div');
        d.className = 'line ' + l.level;
        d.innerHTML = '<span class="t"></span><span class="m"></span>';
        d.children[0].textContent = l.time;
        d.children[1].textContent = l.text;
        box.appendChild(d);
      });
      /* Only autoscroll when already at the bottom, so reading back
         through the log is not yanked away every second. */
      if (stuck) box.scrollTop = box.scrollHeight;
      while (box.children.length > 800) box.removeChild(box.firstChild);
      el('dot').className = 'dot' + (r.running ? ' on' : '');
      if (r.url) el('url').textContent = r.url;
    }
    setTimeout(pumpLog, 700);
  }).catch(function(){ setTimeout(pumpLog, 2000); });
}

ready(function(){
  api = window.pywebview.api;
  api.get_state().then(paintState);
  pumpLog();

  el('saveBtn').addEventListener('click', function(){
    var v = el('token').value.trim();
    api.save_token(v).then(function(r){
      el('token').className = r.ok ? '' : 'bad';
      setMsg('tokenMsg', r.message, r.ok ? 'good' : 'bad');
      paintState(r.state);
    });
  });

  el('genBtn').addEventListener('click', function(){
    api.generate_token().then(function(r){
      el('token').className = '';
      setMsg('tokenMsg', 'Generated and saved.', 'good');
      paintState(r.state);
    });
  });

  el('portBtn').addEventListener('click', function(){
    api.save_port(el('port').value).then(function(r){
      el('port').className = r.ok ? '' : 'bad';
      setMsg('tokenMsg', r.message, r.ok ? 'good' : 'bad');
      paintState(r.state);
    });
  });

  el('verbose').addEventListener('change', function(e){
    api.set_verbose(e.target.checked).then(function(r){ paintState(r.state); });
  });

  el('copyBtn').addEventListener('click', function(){
    api.copy_link().then(function(r){
      if (!r.ok) return;
      var done = function(){ setMsg('urlMsg', 'Link copied.', 'good'); };
      var fail = function(){
        /* Clipboard API needs a secure context, and this page is served
           from html= rather than https. Fall back to selecting the text so
           Ctrl+C still works. */
        var range = document.createRange();
        range.selectNodeContents(el('url'));
        var sel = window.getSelection();
        sel.removeAllRanges(); sel.addRange(range);
        setMsg('urlMsg', 'Selected - press Ctrl+C to copy.', 'good');
      };
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(r.url).then(done, fail);
        } else { fail(); }
      } catch (e) { fail(); }
    });
  });

  el('openBtn').addEventListener('click', function(){
    api.open_in_browser();
  });

  el('clearBtn').addEventListener('click', function(){
    api.clear_log().then(function(){ el('log').innerHTML = ''; cursor = 0; });
  });

  el('token').addEventListener('input', function(e){
    var n = e.target.value.trim().length;
    if (n && n < minLen) {
      setMsg('tokenMsg', n + ' of ' + minLen + ' characters minimum.', 'bad');
    } else {
      setMsg('tokenMsg', '');
    }
  });
});
</script>
</body>
</html>
"""
