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
Edit `wifi_config.json` (ignored by git) to set your Tello credentials plus the SSID/password of your home network. The server reads that file on startup to pre-fill the UI and to know which network to jump back to when you're done flying.

## Running the web UI
```bash
python3 tello_web.py --host 127.0.0.1 --port 8765
```
Then open `http://127.0.0.1:8765` in your browser.

### Workflow
1. Fill in the Wi-Fi interface (usually `en0`), confirm the SSID field (pre-filled to `TELLO-9A5430`), and enter a password if your drone has one, then click **Connect to Drone**. macOS will prompt for your administrator password via an AppleScript dialog (the app runs `networksetup` behind the scenes); approve it to jump to the Tello Wi-Fi. The server automatically sends the `command` instruction right after connecting so the drone is ready for further commands.
2. Hit **Start Video Stream** to turn on the drone’s camera feed (requires the `opencv-python` dependency). Once the overlay shows “Streaming,” you’ll see a ~15 fps live view centered on the dashboard.
3. Press **Takeoff** and drive the drone with the four directional buttons (each sends a 50 cm move).
4. Hit **Land** whenever you need to bring the drone down. All responses show up in the on-page log, which polls the Python backend every second.
5. When you’re finished, click **Return to Home Wi-Fi**. That stops any active video stream, shuts down the command socket, and uses the credentials from `wifi_config.json` to reconnect your Mac to the specified home network.

## Notes
- UDP commands are sent on port 8889 and the listener socket binds to local port 9000; adjust `TELLO_PORT`/`LOCAL_PORT` in the Python scripts if they conflict with something else.
- Movement distance defaults to 50 cm; edit `MOVE_DISTANCE_CM` in `tello_web.py` to change it.
- Live video relies on OpenCV + FFmpeg to decode the drone’s UDP stream. If you don’t plan on using the camera, you can skip installing `opencv-python`.
- The `wifi_config.json` file holds sensitive SSIDs/passwords and is ignored by git; keep it locally and run `git status` before committing to verify nothing leaks.
