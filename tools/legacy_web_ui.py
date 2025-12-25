#!/usr/bin/env python3
from __future__ import annotations

"""Legacy web UI for sending commands to a DJI Tello drone."""

import argparse
import json
import os
import platform
import shlex
import socket
import subprocess
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from pathlib import Path
from typing import Any

try:  # Optional dependency for video streaming
    import cv2  # type: ignore
except ImportError:  # pragma: no cover
    cv2 = None

TELLO_IP = "192.168.10.1"
TELLO_PORT = 8889
LOCAL_PORT = 9000
MOVE_DISTANCE_CM = 50
NETWORKSETUP_PATH = "/usr/sbin/networksetup" if os.path.exists("/usr/sbin/networksetup") else "networksetup"
TELLO_STREAM_URL = "udp://@0.0.0.0:11111"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "wifi_config.json"

log_lock = threading.Lock()
log_lines: list[str] = []


def append_log(message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {message}"
    with log_lock:
        log_lines.append(line)


def load_wifi_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
                return data if isinstance(data, dict) else {}
        except Exception as exc:  # noqa: BLE001
            append_log(f"wifi_config.json error: {exc}")
    else:
        append_log("wifi_config.json not found; using defaults.")
    return {
        "interface": "en0",
        "tello": {"ssid": "TELLO-9A5430", "password": ""},
        "home": {"ssid": "", "password": ""},
    }


WIFI_CONFIG = load_wifi_config()
DEFAULT_INTERFACE = str(WIFI_CONFIG.get("interface", "en0"))
DEFAULT_TELLO_SSID = (
    WIFI_CONFIG.get("tello", {}).get("ssid") or "TELLO-9A5430"
)
DEFAULT_TELLO_PASSWORD = WIFI_CONFIG.get("tello", {}).get("password") or ""
HOME_WIFI = WIFI_CONFIG.get("home")
if not isinstance(HOME_WIFI, dict):
    HOME_WIFI = {}


class TelloController:
    """Minimal UDP interface for the Tello SDK."""

    def __init__(self):
        self.sock: socket.socket | None = None
        self.receiver_thread: threading.Thread | None = None
        self.running = False
        self.lock = threading.Lock()

    def start(self) -> None:
        with self.lock:
            if self.sock:
                return
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("", LOCAL_PORT))
            sock.settimeout(2.0)
            self.sock = sock
            self.running = True
            self.receiver_thread = threading.Thread(target=self._listen, daemon=True)
            self.receiver_thread.start()
            append_log("UDP socket ready on port 9000.")

    def stop(self) -> None:
        with self.lock:
            self.running = False
            if self.sock:
                try:
                    self.sock.close()
                finally:
                    self.sock = None
            append_log("Socket closed.")

    def _listen(self) -> None:
        while self.running and self.sock:
            try:
                response, _ = self.sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            else:
                decoded = response.decode("utf-8", errors="ignore")
                append_log(f"<<< {decoded}")

    def send_command(self, command: str) -> bool:
        self.start()
        try:
            assert self.sock is not None
            self.sock.sendto(command.encode("utf-8"), (TELLO_IP, TELLO_PORT))
            append_log(f">>> {command}")
            return True
        except OSError as exc:
            append_log(f"Send failed: {exc}")
            return False


class AppState:
    def __init__(self):
        self._command_mode = False
        self._lock = threading.Lock()

    def set_command_mode(self, enabled: bool) -> None:
        with self._lock:
            self._command_mode = enabled

    def in_command_mode(self) -> bool:
        with self._lock:
            return self._command_mode


controller = TelloController()
state = AppState()


class VideoStreamer:
    """Handles pulling frames from the Tello UDP stream via OpenCV."""

    def __init__(self, controller: TelloController):
        self.controller = controller
        self.running = False
        self.thread: threading.Thread | None = None
        self.frame_lock = threading.Lock()
        self.latest_frame: bytes | None = None
        self.stream_enabled = False

    def start(self) -> tuple[bool, str]:
        if cv2 is None:
            append_log("OpenCV not installed. Video disabled.")
            return False, "Install opencv-python to enable video streaming."
        if not state.in_command_mode():
            append_log("Video requested before command mode.")
            return False, "Enter command mode before starting the video stream."

        if not self.stream_enabled:
            if not self.controller.send_command("streamon"):
                append_log("Failed to send streamon command.")
                return False, "Drone rejected the streamon command."
            self.stream_enabled = True
            append_log("Drone video stream enabled.")

        if self.running:
            return True, "Video stream already running."

        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        return True, "Video stream starting."

    def _capture_loop(self) -> None:
        append_log("Connecting to Tello video feed...")
        cap = cv2.VideoCapture(TELLO_STREAM_URL) if cv2 else None
        if not cap or not cap.isOpened():
            append_log("Unable to open the video stream. Check OpenCV/FFmpeg support.")
            self.running = False
            self.stream_enabled = False
            return

        while self.running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05)
                continue
            ret, buffer = cv2.imencode(".jpg", frame)
            if ret:
                with self.frame_lock:
                    self.latest_frame = buffer.tobytes()
            else:
                time.sleep(0.01)

        cap.release()

    def get_frame(self) -> bytes | None:
        with self.frame_lock:
            return self.latest_frame

    def stop(self) -> None:
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)
        if self.stream_enabled:
            try:
                self.controller.send_command("streamoff")
            finally:
                self.stream_enabled = False


video_streamer = VideoStreamer(controller)


def reset_drone_session() -> None:
    video_streamer.stop()
    controller.stop()
    state.set_command_mode(False)


def ensure_command_mode() -> tuple[bool, str]:
    if state.in_command_mode():
        return True, "Command mode already active."
    if controller.send_command("command"):
        state.set_command_mode(True)
        append_log("Command mode engaged.")
        return True, "Command mode engaged."
    append_log("Failed to engage command mode.")
    return False, "Unable to enter command mode."

def connect_wifi(interface: str, ssid: str, password: str) -> str:
    if platform.system() != "Darwin":
        raise RuntimeError("Automatic Wi-Fi connection only works on macOS.")

    cmd = [NETWORKSETUP_PATH, "-setairportnetwork", interface, ssid]
    if password:
        cmd.append(password)

    append_log(f"Connecting {interface} to {ssid}...")
    if os.geteuid() == 0:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
    else:
        applescript_cmd = " ".join(shlex.quote(arg) for arg in cmd)
        script = (
            'do shell script "{command}" with administrator privileges'.format(
                command=applescript_cmd.replace("\\", "\\\\").replace('"', '\\"')
            )
        )
        completed = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, check=True
        )

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if stdout:
        append_log(stdout)
    if stderr:
        append_log(stderr)
    return stdout or "Connected"


def connect_home_wifi() -> str:
    ssid = (HOME_WIFI.get("ssid") or "").strip()
    password = HOME_WIFI.get("password") or ""
    interface = HOME_WIFI.get("interface") or DEFAULT_INTERFACE
    if not ssid:
        raise RuntimeError("Home Wi-Fi SSID missing in wifi_config.json.")
    append_log(f"Switching {interface} back to home Wi-Fi: {ssid}")
    return connect_wifi(interface, ssid, password)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Tello Controller</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 0; background: #f5f6f8; }
    main { max-width: 960px; margin: 0 auto; padding: 24px; }
    h1 { margin-top: 0; }
    section { background: #fff; padding: 16px 20px; margin-bottom: 18px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.06); }
    label { display: block; font-weight: 600; margin-bottom: 4px; }
    input { width: 100%; padding: 8px; margin-bottom: 12px; border-radius: 6px; border: 1px solid #ccc; font-size: 14px; }
    button { padding: 10px 18px; border: none; border-radius: 6px; background: #006be6; color: #fff; font-size: 15px; font-weight: 600; cursor: pointer; margin-right: 8px; margin-bottom: 8px; }
    button.secondary { background: #00a86b; }
    button.danger { background: #d7263d; }
    button:disabled { opacity: 0.6; cursor: not-allowed; }
    #movement-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; max-width: 360px; }
    #log { width: 100%; height: 220px; border: 1px solid #ccc; border-radius: 6px; padding: 10px; font-family: 'SFMono-Regular', Consolas, monospace; font-size: 13px; background: #0b1421; color: #e0f3ff; overflow-y: auto; }
    #status { margin-top: 8px; font-weight: 600; }
    #video-section { text-align: center; }
    .video-wrapper { position: relative; border-radius: 12px; overflow: hidden; background: #020b16; min-height: 260px; }
    #videoFeed { width: 100%; min-height: 260px; display: block; object-fit: cover; background: #020b16; }
    #videoOverlay { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: #e0f3ff; font-weight: 600; text-shadow: 0 0 10px rgba(0,0,0,0.7); pointer-events: none; }
  </style>
</head>
<body>
  <main>
    <h1>Tello Controller</h1>
    <section>
      <h2>Wi-Fi</h2>
      <label for="interface">Interface (usually en0)</label>
      <input id="interface" value="__DEFAULT_INTERFACE__" />
      <label for="ssid">SSID (e.g. TELLO-XXXXXX)</label>
      <input id="ssid" value="__DEFAULT_TELLO_SSID__" />
      <label for="password">Password (leave empty for stock drones)</label>
      <input id="password" type="password" value="__DEFAULT_TELLO_PASSWORD__" />
      <div>
        <button id="connectBtn">Connect to Drone</button>
        <button id="homeBtn" type="button">Return to Home Wi-Fi</button>
      </div>
    </section>

    <section id="video-section">
      <h2>Live Camera</h2>
      <div class="video-wrapper">
        <img id="videoFeed" alt="Tello video feed" />
        <div id="videoOverlay">Video idle</div>
      </div>
      <button id="videoBtn" class="secondary">Start Video Stream</button>
    </section>

    <section>
      <h2>Flight Controls</h2>
      <div>
        <button data-command="takeoff" class="secondary">Takeoff</button>
        <button data-command="land" class="danger">Land</button>
      </div>
      <p>Directional buttons send __MOVE_DISTANCE__ cm moves.</p>
      <div id="movement-grid">
        <div></div>
        <button data-move="forward">Forward</button>
        <div></div>
        <button data-move="left">Left</button>
        <div></div>
        <button data-move="right">Right</button>
        <div></div>
        <button data-move="back">Backward</button>
        <div></div>
      </div>
    </section>

    <section>
      <h2>Log</h2>
      <pre id="log"></pre>
      <div id="status"></div>
    </section>
  </main>
  <script>
    const connectBtn = document.getElementById('connectBtn');
    const statusEl = document.getElementById('status');
    const logEl = document.getElementById('log');
    const videoBtn = document.getElementById('videoBtn');
    const videoFeed = document.getElementById('videoFeed');
    const videoOverlay = document.getElementById('videoOverlay');
    const homeBtn = document.getElementById('homeBtn');
    let logIndex = 0;
    let videoTimer = null;

    function setStatus(message, isError=false) {
      statusEl.textContent = message;
      statusEl.style.color = isError ? '#d7263d' : '#006be6';
    }

    function setVideoStatus(message, isError=false) {
      if (!videoOverlay) return;
      videoOverlay.textContent = message;
      videoOverlay.style.color = isError ? '#ff9b9b' : '#e0f3ff';
    }

    function startVideoLoop() {
      if (!videoFeed || videoTimer) return;
      const refresh = () => {
        videoFeed.src = `/video.jpg?ts=${Date.now()}`;
      };
      refresh();
      videoTimer = setInterval(refresh, 250);
    }

    function stopVideoLoop() {
      if (videoTimer) {
        clearInterval(videoTimer);
        videoTimer = null;
      }
      if (videoFeed) {
        videoFeed.src = '';
      }
      setVideoStatus('Video idle');
      if (videoBtn) {
        videoBtn.disabled = false;
      }
    }

    async function postJSON(path, payload) {
      const res = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload || {})
      });
      if (!res.ok) {
        const msg = await res.text();
        throw new Error(msg || 'Request failed');
      }
      return res.json();
    }

    if (videoFeed) {
      videoFeed.addEventListener('load', () => setVideoStatus('Streaming'));
      videoFeed.addEventListener('error', () => setVideoStatus('Waiting for frames...', true));
    }

    connectBtn.addEventListener('click', async () => {
      const iface = document.getElementById('interface').value.trim() || 'en0';
      const ssid = document.getElementById('ssid').value.trim();
      const password = document.getElementById('password').value;
      if (!ssid) {
        setStatus('Enter the SSID before connecting.', true);
        return;
      }
      connectBtn.disabled = true;
      setStatus('Connecting...');
      try {
        const result = await postJSON('/api/wifi', { interface: iface, ssid, password });
        setStatus(result.message || 'Connected');
      } catch (err) {
        setStatus(err.message, true);
      } finally {
        connectBtn.disabled = false;
      }
    });

    if (videoBtn) {
      videoBtn.addEventListener('click', async () => {
        setVideoStatus('Starting video...');
        videoBtn.disabled = true;
        try {
          const result = await postJSON('/api/video/start', {});
          setStatus(result.message || 'Video starting');
          setVideoStatus(result.message || 'Connecting...');
          startVideoLoop();
        } catch (err) {
          setStatus(err.message, true);
          setVideoStatus(err.message, true);
          videoBtn.disabled = false;
        }
      });
    }

    if (homeBtn) {
      homeBtn.addEventListener('click', async () => {
        homeBtn.disabled = true;
        setStatus('Returning to home Wi-Fi...');
        stopVideoLoop();
        try {
          const result = await postJSON('/api/wifi/home', {});
          setStatus(result.message || 'Home Wi-Fi connected');
        } catch (err) {
          setStatus(err.message, true);
        } finally {
          homeBtn.disabled = false;
        }
      });
    }

    document.querySelectorAll('[data-command]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const command = btn.dataset.command;
        setStatus(`Sending ${command}...`);
        try {
          const result = await postJSON('/api/command', { command });
          setStatus(result.message || 'Sent');
        } catch (err) {
          setStatus(err.message, true);
        }
      });
    });

    document.querySelectorAll('[data-move]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const direction = btn.dataset.move;
        setStatus(`Sending ${direction}...`);
        try {
          const result = await postJSON('/api/move', { direction });
          setStatus(result.message || 'Sent');
        } catch (err) {
          setStatus(err.message, true);
        }
      });
    });

    async function pollLogs() {
      try {
        const res = await fetch(`/api/logs?from=${logIndex}`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.lines && data.lines.length) {
          logEl.textContent += data.lines.join('\n') + '\n';
          logEl.scrollTop = logEl.scrollHeight;
        }
        logIndex = data.next;
      } catch (_) {
        // ignore
      } finally {
        setTimeout(pollLogs, 1000);
      }
    }

    pollLogs();
  </script>
</body>
</html>
"""

HTML_PAGE = (
    HTML_TEMPLATE
    .replace("__MOVE_DISTANCE__", str(MOVE_DISTANCE_CM))
    .replace("__DEFAULT_INTERFACE__", DEFAULT_INTERFACE)
    .replace("__DEFAULT_TELLO_SSID__", DEFAULT_TELLO_SSID)
    .replace("__DEFAULT_TELLO_PASSWORD__", DEFAULT_TELLO_PASSWORD)
)


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (framework method name)
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._send_response(HTTPStatus.OK, HTML_PAGE, "text/html; charset=utf-8")
            return
        if parsed.path == "/api/logs":
            query = parse_qs(parsed.query or "")
            start = int(query.get("from", ["0"])[0])
            with log_lock:
                lines = log_lines[start:]
                next_index = start + len(lines)
            payload = json.dumps({"lines": lines, "next": next_index})
            self._send_response(HTTPStatus.OK, payload, "application/json")
            return
        if parsed.path == "/video.jpg":
            frame = video_streamer.get_frame()
            if frame:
                self._send_response(HTTPStatus.OK, frame, "image/jpeg")
            else:
                self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "Video not ready")
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self):  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length) if content_length else b""
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON")
            return

        if self.path == "/api/wifi":
            self._handle_wifi(payload)
            return
        if self.path == "/api/wifi/home":
            self._handle_wifi_home()
            return
        if self.path == "/api/command":
            self._handle_command(payload)
            return
        if self.path == "/api/move":
            self._handle_move(payload)
            return
        if self.path == "/api/video/start":
            self._handle_video_start()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def log_message(self, format: str, *args):  # noqa: D401
        """Silence default stdout logging; we use the UI log instead."""
        return

    def _handle_wifi(self, payload: dict) -> None:
        interface = (payload.get("interface") or "en0").strip()
        ssid = (payload.get("ssid") or "").strip()
        password = payload.get("password") or ""
        if not ssid:
            self.send_error(HTTPStatus.BAD_REQUEST, "SSID required")
            return
        try:
            message = connect_wifi(interface, ssid, password)
            time.sleep(0.5)
            cmd_ok, cmd_msg = ensure_command_mode()
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            append_log(f"Wi-Fi connect failed: {detail}")
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, detail)
        except Exception as exc:  # noqa: BLE001
            append_log(f"Wi-Fi connect error: {exc}")
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
        else:
            combined = message
            if cmd_ok:
                combined = f"{message} ({cmd_msg})"
            self._send_json({"ok": True, "message": combined})

    def _handle_wifi_home(self) -> None:
        try:
            reset_drone_session()
            message = connect_home_wifi()
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            append_log(f"Home Wi-Fi connect failed: {detail}")
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, detail)
        except Exception as exc:  # noqa: BLE001
            append_log(f"Home Wi-Fi connect error: {exc}")
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
        else:
            self._send_json(
                {"ok": True, "message": message or "Connected to home Wi-Fi."}
            )

    def _handle_command(self, payload: dict) -> None:
        command = (payload.get("command") or "").strip()
        if not command:
            self.send_error(HTTPStatus.BAD_REQUEST, "Command required")
            return
        if command == "command":
            ok, message = ensure_command_mode()
            if ok:
                self._send_json({"ok": True, "message": message})
            else:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, message)
            return
        if not state.in_command_mode():
            self.send_error(HTTPStatus.BAD_REQUEST, "Enter command mode first.")
            return
        success = controller.send_command(command)
        if success:
            self._send_json({"ok": True, "message": "Command sent."})
        else:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Send failed.")

    def _handle_move(self, payload: dict) -> None:
        direction = (payload.get("direction") or "").strip()
        if direction not in {"left", "right", "forward", "back"}:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid direction")
            return
        if not state.in_command_mode():
            self.send_error(HTTPStatus.BAD_REQUEST, "Enter command mode first.")
            return
        command = f"{direction} {MOVE_DISTANCE_CM}"
        if controller.send_command(command):
            self._send_json({"ok": True, "message": f"{direction.title()} sent."})
        else:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Send failed.")

    def _handle_video_start(self) -> None:
        ok, message = video_streamer.start()
        if ok:
            self._send_json({"ok": True, "message": message})
        else:
            self.send_error(HTTPStatus.BAD_REQUEST, message)

    def _send_response(self, status: HTTPStatus, body, content_type: str) -> None:
        encoded = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, payload: dict) -> None:
        body = json.dumps(payload)
        self._send_response(HTTPStatus.OK, body, "application/json")


def run_server(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), RequestHandler)
    append_log(f"Web UI available at http://{host}:{port}")
    print(f"Tello web UI running at http://{host}:{port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        append_log("Shutting down web server...")
        print("\nStopping server...")
    finally:
        video_streamer.stop()
        controller.stop()
        server.server_close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DJI Tello web controller")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Listen port (default: 8765)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
