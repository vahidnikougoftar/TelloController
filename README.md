# Tello Controller

This project talks to a DJI Tello over its UDP SDK and exposes a UI with buttons for left/right/forward/backward movement plus helpers for entering command mode, takeoff, land, and connecting your Mac to the drone's Wi‑Fi.

## Requirements
- Python 3.9+ on macOS (Ventura or older versions have an outdated Tk build, so the web UI is now the default)
- DJI Tello, powered on, with your computer able to join the `TELLO-XXXXXX` Wi-Fi network

## Setup
```bash
cd ~/Desktop/TelloController
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running the web UI
```bash
python3 tello_web.py --host 127.0.0.1 --port 8765
```
Then open `http://127.0.0.1:8765` in your browser.

### Workflow
1. Fill in the Wi-Fi interface (usually `en0`), Tello SSID (for example `TELLO-123456`), and optional password, then click **Connect to Drone**. macOS will prompt for your administrator password via an AppleScript dialog (the app runs `networksetup` behind the scenes); approve it to jump to the Tello Wi-Fi.
2. Click **Enter Command Mode** to arm the SDK session once the Wi-Fi connect succeeds.
3. Press **Takeoff** and drive the drone with the four directional buttons (each sends a 50 cm move).
4. Hit **Land** whenever you need to bring the drone down. All responses show up in the on-page log, which polls the Python backend every second.

## Notes
- UDP commands are sent on port 8889 and the listener socket binds to local port 9000; adjust `TELLO_PORT`/`LOCAL_PORT` in the Python scripts if they conflict with something else.
- Movement distance defaults to 50 cm; edit `MOVE_DISTANCE_CM` in `tello_web.py` (and `tello_ui.py` if you keep using Tk) to change it.
- The legacy Tkinter app (`tello_ui.py`) still exists, but Apple's newer Python builds require macOS 12+ for Tk. On older releases you'll see the `macOS 26 (2601) or later required` crash, so stick with the browser UI unless you're on a newer OS.
