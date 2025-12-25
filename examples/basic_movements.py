"""Basic movement and video stream example using djitellopy."""

from __future__ import annotations

from time import sleep

import cv2
from djitellopy import tello


def main() -> None:
    drone = tello.Tello()
    drone.connect()

    print(drone.get_battery())

    drone.takeoff()
    drone.send_rc_control(0, 50, 0, 0)  # Move forward at speed 50
    sleep(0.5)
    drone.send_rc_control(0, 0, 0, 0)  # Stop movement
    drone.land()

    drone.streamon()
    frame_read = drone.get_frame_read()
    while True:
        frame = frame_read.frame
        frame = cv2.resize(frame, (360, 240))
        cv2.imshow("Drone Camera", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    drone.streamoff()


if __name__ == "__main__":
    main()
