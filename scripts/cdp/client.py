"""Standalone CDP client - launches its own Chrome, on its own debug port, and never touches
the user's browser. This is ROADMAP.md 2.1: it replaces browser-harness as the transport for
scripts/apply_harness.py and scripts/apply_driver.py, which are unmodified by this file - they
still call bare-name js/cdp/click_at_xy/page_info/goto_url/wait/wait_for_load/switch_tab/
press_key/drain_events/new_tab, exactly as browser-harness pre-imports them. Only those eleven
names are implemented here; this is a transport swap, not a general CDP library.

    with Browser() as browser:
        browser.goto_url("https://example.com")
        browser.wait_for_load()
        print(browser.js("document.title"))

See scripts/run_apply_standalone.py for how the two driven files get exec'd against this.
"""

import itertools
import json
import os
import platform
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request

from .ws import WebSocket, WebSocketError

DEFAULT_STARTUP_TIMEOUT = float(os.environ.get("CDP_STARTUP_TIMEOUT", "20"))
DEFAULT_RESPONSE_TIMEOUT = float(os.environ.get("CDP_RESPONSE_TIMEOUT", "30"))


def _find_chrome():
    override = os.environ.get("CDP_CHROME_BINARY")
    if override:
        return override
    if platform.system() == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    else:
        candidates = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]
    for c in candidates:
        if os.path.isabs(c):
            if os.path.exists(c):
                return c
        else:
            found = shutil.which(c)
            if found:
                return found
    raise RuntimeError("no Chrome/Chromium binary found - set CDP_CHROME_BINARY to its path")


def _free_port():
    """An ephemeral port free at this instant. TOCTOU race exists (closed before Chrome binds
    it) but is acceptable here - Chrome's own /json/version poll below is the real readiness
    check, and a bind failure surfaces as that poll never succeeding rather than silently."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Browser:
    """One launched Chrome process plus the single flattened-session CDP connection to it.

    One Run at a time - concurrency (ROADMAP 2.4) is a separate later change, not this one.
    """

    def __init__(self, port=None, headless=None, user_data_dir=None):
        self.port = port or int(os.environ.get("CDP_PORT", "0")) or _free_port()
        self.headless = (os.environ.get("CDP_HEADLESS") == "1") if headless is None else headless
        self._own_profile_dir = user_data_dir is None
        self.user_data_dir = user_data_dir or tempfile.mkdtemp(prefix="cdp-profile-")
        self.proc = None
        self.ws = None
        self._id_counter = itertools.count(1)
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._events = []
        self._events_lock = threading.Lock()
        self._reader_thread = None
        self._stop_reader = False
        self.session_id = None
        self.target_id = None

    # --- lifecycle -------------------------------------------------------------------------

    def launch(self, startup_timeout=DEFAULT_STARTUP_TIMEOUT):
        binary = _find_chrome()
        args = [
            binary,
            "--remote-debugging-port=%d" % self.port,
            "--remote-allow-origins=*",
            "--user-data-dir=%s" % self.user_data_dir,
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-popup-blocking",
            "--disable-features=Translate",
        ]
        if self.headless:
            args.append("--headless=new")
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        deadline = time.time() + startup_timeout
        info, last_err = None, None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        "http://127.0.0.1:%d/json/version" % self.port, timeout=1) as resp:
                    info = json.loads(resp.read())
                    break
            except Exception as e:
                last_err = e
                time.sleep(0.25)
        if info is None:
            self.kill()
            raise RuntimeError(
                "Chrome on port %d never answered /json/version within %ss: %r"
                % (self.port, startup_timeout, last_err))

        self.ws = WebSocket(info["webSocketDebuggerUrl"])
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()
        self._attach_first_page()
        return self

    def kill(self):
        self._stop_reader = True
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self._own_profile_dir:
            shutil.rmtree(self.user_data_dir, ignore_errors=True)

    def __enter__(self):
        return self.launch()

    def __exit__(self, exc_type, exc, tb):
        self.kill()

    # --- transport ---------------------------------------------------------------------------

    def _read_loop(self):
        while not self._stop_reader:
            try:
                text = self.ws.recv_message()
            except (WebSocketError, OSError):
                # OSError covers the shutdown race: kill() closes the socket from the main
                # thread while this thread is blocked in recv() on it.
                return
            try:
                msg = json.loads(text)
            except ValueError:
                continue
            if "id" in msg:
                with self._pending_lock:
                    slot = self._pending.pop(msg["id"], None)
                if slot is not None:
                    slot["response"] = msg
                    slot["event"].set()
            else:
                with self._events_lock:
                    self._events.append(msg)

    def send(self, method, session_id=None, timeout=DEFAULT_RESPONSE_TIMEOUT, **params):
        """Raw send/receive by message id. `session_id` routes to one attached tab under CDP's
        flattened-session mode - omit it only for browser-level methods (Target.*)."""
        msg_id = next(self._id_counter)
        payload = {"id": msg_id, "method": method, "params": params}
        if session_id:
            payload["sessionId"] = session_id
        slot = {"event": threading.Event(), "response": None}
        with self._pending_lock:
            self._pending[msg_id] = slot
        self.ws.send_text(json.dumps(payload))
        if not slot["event"].wait(timeout):
            with self._pending_lock:
                self._pending.pop(msg_id, None)
            raise TimeoutError("%s timed out after %ss (id=%s)" % (method, timeout, msg_id))
        resp = slot["response"]
        if "error" in resp:
            raise RuntimeError("%s failed: %s" % (method, resp["error"]))
        return resp.get("result", {})

    # --- attach --------------------------------------------------------------------------

    def _attach_first_page(self):
        targets = self.send("Target.getTargets")["targetInfos"]
        pages = [t for t in targets if t["type"] == "page"]
        tid = pages[0]["targetId"] if pages else self.send(
            "Target.createTarget", url="about:blank")["targetId"]
        self.switch_tab(tid)

    def switch_tab(self, target_id):
        """Attach to `target_id` and make it the current session for every primitive below.

        Enables Page/DOM/Runtime/Network on every attach, not just the first: a fresh CDP
        session starts with all domains disabled, and drain_events()/wait_for_load() need
        Network and Page events flowing on whichever tab is current right now."""
        result = self.send("Target.attachToTarget", targetId=target_id, flatten=True)
        self.session_id = result["sessionId"]
        self.target_id = target_id
        for domain in ("Page", "DOM", "Runtime", "Network"):
            self.send("%s.enable" % domain, session_id=self.session_id)
        return self.session_id

    # --- the eleven primitives apply_harness.py/apply_driver.py actually call -----------------

    def cdp(self, method, **params):
        if method.startswith("Target."):
            return self.send(method, **params)
        return self.send(method, session_id=self.session_id, **params)

    def js(self, expression):
        result = self._runtime_evaluate(expression)
        exc = result.get("exceptionDetails")
        if exc and "Illegal return statement" in json.dumps(exc):
            result = self._runtime_evaluate("(function(){ %s })()" % expression)
            exc = result.get("exceptionDetails")
        if exc:
            raise RuntimeError("js() threw: %s" % json.dumps(exc))
        return result.get("result", {}).get("value")

    def _runtime_evaluate(self, expression):
        return self.send("Runtime.evaluate", session_id=self.session_id,
                          expression=expression, returnByValue=True, awaitPromise=True)

    def click_at_xy(self, x, y, button="left", clicks=1):
        self.send("Input.dispatchMouseEvent", session_id=self.session_id,
                  type="mousePressed", x=x, y=y, button=button, clickCount=clicks)
        self.send("Input.dispatchMouseEvent", session_id=self.session_id,
                  type="mouseReleased", x=x, y=y, button=button, clickCount=clicks)

    def page_info(self):
        return json.loads(self.js("JSON.stringify({url: location.href, title: document.title})"))

    def goto_url(self, url):
        return self.send("Page.navigate", session_id=self.session_id, url=url)

    def wait(self, seconds=1.0):
        time.sleep(seconds)

    def wait_for_load(self, timeout=15.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.js("document.readyState") == "complete":
                return True
            time.sleep(0.3)
        return False

    _KEYS = {"Enter": (13, "Enter"), "Tab": (9, "Tab"), "Escape": (27, "Escape")}

    def press_key(self, key):
        vk, code = self._KEYS.get(key, (0, key))
        base = {"key": key, "code": code, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
        self.send("Input.dispatchKeyEvent", session_id=self.session_id, type="keyDown", **base)
        self.send("Input.dispatchKeyEvent", session_id=self.session_id, type="keyUp", **base)

    def drain_events(self):
        with self._events_lock:
            out, self._events = self._events, []
        return out

    def new_tab(self, url="about:blank"):
        """Reuse the currently attached tab rather than create a new target.

        apply_driver.py's run_apply() always calls this immediately after
        new_incognito_tab(), which already created and attached a fresh blank tab inside
        its own browser context. Target.createTarget with no browserContextId lands in
        Chrome's default context, not that one - creating a target here would silently
        break the one-context-per-Run isolation apply_driver.py depends on. Reusing the
        attached tab in place avoids the whole question.
        """
        if self.session_id is None:
            tid = self.send("Target.createTarget", url="about:blank")["targetId"]
            self.switch_tab(tid)
        if url != "about:blank":
            self.goto_url(url)
        return self.target_id
