"""Pygame cockpit UI for controlling a DJI Tello with keyboard or on-screen buttons.

Controls mirror common flight mappings:
- Arrow keys: left/right/forward/back
- W/S: up/down
- A/D: yaw left/right
- E: takeoff
- Q: land
- X: exit the app

The UI embeds the Tello video feed, highlights active controls (keyboard or mouse),
and supports a `--debug` flag to iterate without a connected drone.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import cv2
import numpy as np
import pygame
from djitellopy import tello

# Display layout
WINDOW_WIDTH, WINDOW_HEIGHT = 800, 630
VIDEO_SIZE = (600, 400)
PADDING = 24
BUTTON_W, BUTTON_H = 110, 54
BUTTON_GAP = 12
BG_COLOR = (16, 18, 24)
VIDEO_BG = (26, 29, 36)
TEXT_COLOR = (230, 233, 240)
BUTTON_COLOR = (48, 54, 68)
ACTIVE_COLOR = (88, 148, 255)
HOVER_COLOR = (68, 94, 128)
OUTLINE_COLOR = (90, 95, 110)
ICON_DIR = Path(__file__).parent / "icons"
LETTER_LABELS = {
    pygame.K_w: "W",
    pygame.K_a: "A",
    pygame.K_s: "S",
    pygame.K_d: "D",
    pygame.K_e: "E",
    pygame.K_q: "Q",
    pygame.K_x: "X",
}
FPS = 30
RC_SPEED = 50


@dataclass(frozen=True)
class Layout:
    """UI sizing and spacing configuration."""

    window_width: int = WINDOW_WIDTH
    window_height: int = WINDOW_HEIGHT
    video_size: tuple[int, int] = VIDEO_SIZE
    padding: int = PADDING
    button_w: int = BUTTON_W
    button_h: int = BUTTON_H
    button_gap: int = BUTTON_GAP


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


def load_icon_surface(icon_name: Optional[str], rect: pygame.Rect) -> Optional[pygame.Surface]:
    """Load and scale an icon SVG/bitmap to fit the button rect."""
    if not icon_name:
        return None
    icon_path = ICON_DIR / icon_name
    try:
        surface = pygame.image.load(str(icon_path)).convert_alpha()
    except Exception as exc:  # noqa: BLE001
        logging.warning("Failed to load icon %s: %s", icon_path, exc)
        return None

    max_w = rect.width - 14
    max_h = rect.height - 14
    w, h = surface.get_size()
    if w == 0 or h == 0 or max_w <= 0 or max_h <= 0:
        return None
    scale = min(max_w / w, max_h / h, 1)
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    try:
        return pygame.transform.smoothscale(surface, new_size)
    except Exception as exc:  # noqa: BLE001
        logging.warning("Failed to scale icon %s: %s", icon_path, exc)
        return None


class Button:
    """Interactive UI button mapping to keyboard key and drone control vector."""

    def __init__(
        self,
        label: str,
        key: int,
        rect: pygame.Rect,
        control: Optional[tuple[int, int, int, int]] = None,
        on_tap: Optional[Callable[[], None]] = None,
        icon_name: Optional[str] = None,
    ):
        self.label = label
        self.key = key
        self.rect = rect
        self.control = control
        self.on_tap = on_tap
        self.mouse_active = False
        self.icon_surface = load_icon_surface(icon_name, rect)

    @property
    def is_control(self) -> bool:
        return self.control is not None

    @property
    def is_action(self) -> bool:
        return self.on_tap is not None

    def active(self, pressed) -> bool:
        return pressed[self.key] or self.mouse_active

    def handle_click(self) -> None:
        if self.on_tap:
            self.on_tap()


def build_buttons(layout: Layout, drone: DroneClient, stop_callback: Callable[[], None]) -> list[Button]:
    """Create button objects with positions, icons, and behaviors."""
    bottom_row_y = layout.window_height - layout.padding - layout.button_h
    top_row_y = bottom_row_y - layout.button_h - layout.button_gap

    # WASD cluster on the left (mirrors keyboard arrangement)
    wasd_left = layout.padding
    wasd_mid = wasd_left + layout.button_w + layout.button_gap
    wasd_right = wasd_mid + layout.button_w + layout.button_gap

    # Arrow cluster on the right (mirrors keyboard arrangement)
    arrow_left = layout.window_width - layout.padding - (layout.button_w * 3 + layout.button_gap * 2)
    arrow_mid = arrow_left + layout.button_w + layout.button_gap
    arrow_right = arrow_mid + layout.button_w + layout.button_gap

    # Action buttons stacked to the right of the video frame
    actions_x = layout.padding + layout.video_size[0] + layout.button_gap
    actions_y = layout.padding

    rows = [
        ("Up (W)", pygame.K_w, (wasd_mid, top_row_y), (0, 0, RC_SPEED, 0), "up.svg"),
        ("Spin CCW (A)", pygame.K_a, (wasd_left, bottom_row_y), (0, 0, 0, -RC_SPEED), "spin_ccw.svg"),
        ("Down (S)", pygame.K_s, (wasd_mid, bottom_row_y), (0, 0, -RC_SPEED, 0), "down.svg"),
        ("Spin CW (D)", pygame.K_d, (wasd_right, bottom_row_y), (0, 0, 0, RC_SPEED), "spin_cw.svg"),
        ("Forward", pygame.K_UP, (arrow_mid, top_row_y), (0, RC_SPEED, 0, 0), "forward.svg"),
        ("Left", pygame.K_LEFT, (arrow_left, bottom_row_y), (-RC_SPEED, 0, 0, 0), "left.svg"),
        ("Backward", pygame.K_DOWN, (arrow_mid, bottom_row_y), (0, -RC_SPEED, 0, 0), "backward.svg"),
        ("Right", pygame.K_RIGHT, (arrow_right, bottom_row_y), (RC_SPEED, 0, 0, 0), "right.svg"),
        ("Takeoff (E)", pygame.K_e, (actions_x, actions_y + (layout.button_h + layout.button_gap) * 0), None, "takeoff.svg"),
        ("Land (Q)", pygame.K_q, (actions_x, actions_y + (layout.button_h + layout.button_gap) * 1), None, "land.svg"),
        ("Exit (X)", pygame.K_x, (actions_x, actions_y + (layout.button_h + layout.button_gap) * 2), None, "exit.svg"),
    ]

    buttons: list[Button] = []
    for label, key, (x, y), control, icon in rows:
        rect = pygame.Rect(x, y, layout.button_w - 8, layout.button_h)
        if key == pygame.K_e:
            buttons.append(Button(label, key, rect, on_tap=drone.takeoff, icon_name=icon))
        elif key == pygame.K_q:
            buttons.append(Button(label, key, rect, on_tap=drone.land, icon_name=icon))
        elif key == pygame.K_x:
            buttons.append(Button(label, key, rect, on_tap=stop_callback, icon_name=icon))
        else:
            buttons.append(Button(label, key, rect, control=control, icon_name=icon))
    return buttons


def compute_control_vector(buttons: list[Button], pressed) -> tuple[int, int, int, int]:
    """Aggregate active button control vectors from keyboard and mouse."""
    lr = fb = ud = yv = 0
    for btn in buttons:
        if btn.is_control and btn.active(pressed):
            d_lr, d_fb, d_ud, d_yv = btn.control  # type: ignore[misc]
            lr += d_lr
            fb += d_fb
            ud += d_ud
            yv += d_yv
    return lr, fb, ud, yv


def draw_buttons(
    screen: pygame.Surface,
    font: pygame.font.Font,
    label_font: pygame.font.Font,
    buttons: list[Button],
    pressed,
) -> None:
    """Render control buttons with hover/active states."""
    mouse_pos = pygame.mouse.get_pos()
    for button in buttons:
        base_color = BUTTON_COLOR
        if button.rect.collidepoint(mouse_pos):
            base_color = HOVER_COLOR
        if button.active(pressed):
            base_color = ACTIVE_COLOR

        pygame.draw.rect(screen, base_color, button.rect, border_radius=8)
        pygame.draw.rect(screen, OUTLINE_COLOR, button.rect, width=1, border_radius=8)

        if button.icon_surface:
            icon_rect = button.icon_surface.get_rect(center=button.rect.center)
            screen.blit(button.icon_surface, icon_rect)

            label_text = LETTER_LABELS.get(button.key)
            if label_text:
                label_surface = label_font.render(label_text, True, TEXT_COLOR)
                label_rect = label_surface.get_rect()
                label_rect.bottomright = button.rect.bottomright - pygame.Vector2(8, 6)
                screen.blit(label_surface, label_rect)
        else:
            label_surface = font.render(button.label, True, TEXT_COLOR)
            label_rect = label_surface.get_rect(center=button.rect.center)
            screen.blit(label_surface, label_rect)


def frame_to_surface(frame, video_size: tuple[int, int]) -> Optional[pygame.Surface]:
    """Convert a cv2 frame to a pygame surface sized to the video viewport."""
    if frame is None:
        return None
    try:
        rgb = cv2.resize(frame, video_size)
        rgb = cv2.flip(rgb, 1)
        rotated = np.rot90(rgb)
        return pygame.surfarray.make_surface(rotated)
    except Exception:
        return None


def parse_args() -> argparse.Namespace:
    """CLI entry point arguments."""
    parser = argparse.ArgumentParser(description="Minimalist Tello pygame cockpit UI")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Run without connecting to a drone (no RC output or video required)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity for diagnostics",
    )
    return parser.parse_args()


def setup_logging(level: str) -> None:
    """Configure root logger output."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)

    pygame.init()
    layout = Layout()
    screen = pygame.display.set_mode((layout.window_width, layout.window_height))
    pygame.display.set_caption("Tello Cockpit")
    title_font = pygame.font.SysFont("Arial", 22)
    text_font = pygame.font.SysFont("Arial", 16)
    label_font = pygame.font.SysFont("Arial", 14)
    clock = pygame.time.Clock()

    drone = DroneClient(debug=args.debug)
    status = drone.connect()
    running = True
    last_battery_poll_ms = 0

    def stop_app() -> None:
        nonlocal running
        running = False

    buttons = build_buttons(layout, drone, stop_app)
    video_rect = pygame.Rect(
        layout.padding,
        layout.padding,
        layout.video_size[0],
        layout.video_size[1],
    )

    while running:
        clock.tick(FPS)
        pressed = pygame.key.get_pressed()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for btn in buttons:
                    if btn.rect.collidepoint(event.pos):
                        if btn.is_action:
                            btn.handle_click()
                        elif btn.is_control:
                            btn.mouse_active = True
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                for btn in buttons:
                    btn.mouse_active = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_x:
                    running = False
                elif event.key == pygame.K_e:
                    for btn in buttons:
                        if btn.key == pygame.K_e and btn.is_action:
                            btn.handle_click()
                elif event.key == pygame.K_q:
                    for btn in buttons:
                        if btn.key == pygame.K_q and btn.is_action:
                            btn.handle_click()

        lr, fb, ud, yv = compute_control_vector(buttons, pressed)
        drone.send_rc_control(lr, fb, ud, yv)
        status = drone.status
        now_ms = pygame.time.get_ticks()
        if now_ms - last_battery_poll_ms >= 5000:
            drone.refresh_battery()
            last_battery_poll_ms = now_ms

        screen.fill(BG_COLOR)
        pygame.draw.rect(screen, VIDEO_BG, video_rect, border_radius=12)

        frame_surface = frame_to_surface(drone.read_frame(), layout.video_size)
        if frame_surface:
            screen.blit(frame_surface, video_rect)
        else:
            placeholder = text_font.render(status or "Waiting for video...", True, TEXT_COLOR)
            screen.blit(placeholder, placeholder.get_rect(center=video_rect.center))

        title = f"Tello Cockpit ({drone.battery_label()})"
        screen.blit(title_font.render(title, True, TEXT_COLOR), (video_rect.left, video_rect.bottom + 12))
        screen.blit(text_font.render(status, True, TEXT_COLOR), (video_rect.left, video_rect.bottom + 40))

        draw_buttons(screen, text_font, label_font, buttons, pressed)
        pygame.display.flip()

    drone.shutdown()
    pygame.quit()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pygame.quit()
        sys.exit()
    except Exception as exc:  # noqa: BLE001
        logging.exception("Fatal error: %s", exc)
        pygame.quit()
        sys.exit(1)
