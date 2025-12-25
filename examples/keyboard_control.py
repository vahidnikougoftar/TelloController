"""Keyboard control example with video preview and optional snapshot capture."""

from __future__ import annotations

from datetime import datetime as dt
from pathlib import Path
import sys
from time import sleep

import cv2
from djitellopy import tello

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from tello_controller import keyboard as kp  # noqa: E402


def get_keyboard_input(drone: tello.Tello, latest_frame) -> list[int]:
    lr = fb = ud = yv = 0
    speed = 50
    if kp.get_key_events("LEFT"):
        lr = -speed
    elif kp.get_key_events("RIGHT"):
        lr = speed

    if kp.get_key_events("UP"):
        fb = speed
    elif kp.get_key_events("DOWN"):
        fb = -speed

    if kp.get_key_events("w"):
        ud = speed
    elif kp.get_key_events("s"):
        ud = -speed

    if kp.get_key_events("a"):
        yv = -speed
    elif kp.get_key_events("d"):
        yv = speed

    if kp.get_key_events("q"):
        drone.land()
        sleep(3)
    if kp.get_key_events("e"):
        drone.takeoff()
        sleep(2)

    if kp.get_key_events("z") and latest_frame is not None:
        images_dir = Path("camera_feed/images")
        images_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(images_dir / f"drone_image_{dt.now()}.jpg"), latest_frame)
        sleep(0.3)

    return [lr, fb, ud, yv]


def main() -> None:
    kp.init()
    drone = tello.Tello()
    drone.connect()
    drone.streamon()

    while True:
        frame = drone.get_frame_read().frame
        values = get_keyboard_input(drone, frame)
        print(values)
        drone.send_rc_control(values[0], values[1], values[2], values[3])
        frame = cv2.resize(frame, (360, 240))
        cv2.imshow("Drone Camera", frame)
        if cv2.waitKey(1) & 0xFF == ord("x"):
            drone.streamoff()
            break


if __name__ == "__main__":
    main()
