"""Drone connectivity helpers for the DJI Tello."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
from djitellopy import tello


@dataclass
class DroneClient:
    """Wrapper around djitellopy for resilient usage and debug bypass."""

    debug: bool
    drone: Optional[tello.Tello] = None
    frame_reader: Optional[Any] = None
    status: str = "Not connected."
    battery: Optional[int] = None

    def connect(self) -> str:
        if self.debug:
            self.status = "Debug mode: drone connection skipped."
            logging.info(self.status)
            return self.status
        try:
            self.drone = tello.Tello()
            self.drone.connect()
            self.drone.streamon()
            self.frame_reader = self.drone.get_frame_read()
            self.battery = self.drone.get_battery()
            self.status = f"Connected (battery: {self.battery}%)"
            logging.info(self.status)
        except Exception as exc:  # noqa: BLE001
            self.drone = None
            self.frame_reader = None
            self.status = f"Drone unavailable: {exc}"
            logging.error(self.status)
        return self.status

    def read_frame(self) -> Optional[np.ndarray]:
        if self.debug or not self.frame_reader:
            return None
        try:
            return self.frame_reader.frame  # type: ignore[no-any-return]
        except Exception:
            return None

    def send_rc_control(self, lr: int, fb: int, ud: int, yv: int) -> None:
        if self.debug or not self.drone:
            return
        try:
            self.drone.send_rc_control(lr, fb, ud, yv)
        except Exception as exc:  # noqa: BLE001
            logging.warning("RC control unavailable: %s", exc)
            self.status = "RC control unavailable; check connection."

    def takeoff(self) -> None:
        if self.debug or not self.drone:
            return
        try:
            self.drone.takeoff()
        except Exception as exc:  # noqa: BLE001
            logging.error("Takeoff failed: %s", exc)

    def land(self) -> None:
        if self.debug or not self.drone:
            return
        try:
            self.drone.land()
        except Exception as exc:  # noqa: BLE001
            logging.error("Landing failed: %s", exc)

    def shutdown(self) -> None:
        if not self.drone:
            return
        try:
            self.drone.send_rc_control(0, 0, 0, 0)
            self.drone.streamoff()
        except Exception as exc:  # noqa: BLE001
            logging.error("Error during shutdown: %s", exc)

    def refresh_battery(self) -> None:
        """Update cached battery level if possible."""
        if self.debug or not self.drone:
            return
        try:
            self.battery = self.drone.get_battery()
        except Exception as exc:  # noqa: BLE001
            logging.warning("Battery read failed: %s", exc)

    def battery_label(self) -> str:
        if self.battery is None:
            return "N/A" if self.debug else "?"
        return f"{self.battery}%"
