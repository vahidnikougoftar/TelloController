# Tello Controller

This project talks to a DJI Tello over its UDP SDK and exposes a pygame cockpit UI with optional face/YOLO overlays. The codebase is organized into reusable modules with examples for quick experiments.

## Requirements
- Python 3.9+
- DJI Tello, powered on, with your computer connected to the `TELLO-XXXXXX` Wi-Fi network

## Setup
```bash
cd ~/Desktop/TelloController
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running the pygame cockpit
```bash
python3 scripts/cockpit.py --vision none
```
Optional vision overlays:
- `--vision face`
- `--vision yolo --yolo-model tello_controller/assets/yolov8m.pt --vision-device cpu`
Snapshot: press `P` or click the Snapshot button to save a frame to `camera_feed/images/`.

## Examples
```bash
python3 examples/face_detection_webcam.py
python3 examples/yolo_detection_webcam.py
python3 examples/basic_movements.py
python3 examples/keyboard_control.py
```

## Project layout
- `tello_controller/` reusable modules (drone client, vision, UI)
- `tello_controller/assets/` model weights and UI icons
- `scripts/` runnable entry points
- `examples/` small demos and experiments
- `tools/` legacy or experimental utilities

## Notes
- UDP commands are sent on port 8889 and the listener socket binds to local port 9000; adjust `TELLO_PORT`/`LOCAL_PORT` in `tools/legacy_web_ui.py` if they conflict with something else.
- Live video and the map overlay rely on OpenCV + FFmpeg to decode the drone’s UDP stream.
