"""Minimalist pygame cockpit UI for driving the Tello with keyboard or on-screen buttons.

This script reuses the project's key_press_module for pygame setup and mirrors the
keyboard mappings from keyboardControl.py:
  - Arrow keys: left/right/forward/back
  - W/S: up/down
  - A/D: yaw left/right
  - E: takeoff
  - Q: land
  - X: exit the app

It embeds the Tello video feed into the UI and highlights any control that is active
from either keyboard input or mouse clicks on the on-screen buttons.
"""

from __future__ import annotations

import sys
from typing import Callable, Optional

import cv2
import numpy as np
import pygame
from djitellopy import tello

import key_press_module as kp

# Display layout
WINDOW_WIDTH, WINDOW_HEIGHT = 1000, 750
VIDEO_SIZE = (880, 500)
PADDING = 24
BUTTON_W, BUTTON_H = 110, 54
BG_COLOR = (16, 18, 24)
VIDEO_BG = (26, 29, 36)
TEXT_COLOR = (230, 233, 240)
BUTTON_COLOR = (48, 54, 68)
ACTIVE_COLOR = (88, 148, 255)
HOVER_COLOR = (68, 94, 128)
OUTLINE_COLOR = (90, 95, 110)


class Button:
    def __init__(
        self,
        label: str,
        key: int,
        rect: pygame.Rect,
        control: Optional[tuple[int, int, int, int]] = None,
        on_tap: Optional[Callable[[], None]] = None,
    ):
        self.label = label
        self.key = key
        self.rect = rect
        self.control = control
        self.on_tap = on_tap
        self.mouse_active = False

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


def connect_drone() -> tuple[Optional[tello.Tello], str]:
    """Connect to the drone and start the video stream."""
    try:
        drone = tello.Tello()
        drone.connect()
        drone.streamon()
        return drone, f"Connected (battery: {drone.get_battery()}%)"
    except Exception as exc:  # noqa: BLE001
        return None, f"Drone unavailable: {exc}"


def build_buttons(drone: Optional[tello.Tello], stop_callback: Callable[[], None]) -> list[Button]:
    """Create button objects with positions and behaviors."""
    speed = 50
    left = PADDING
    bottom = WINDOW_HEIGHT - PADDING - BUTTON_H
    rows = [
        ("LEFT", pygame.K_LEFT, (left + BUTTON_W * 0, bottom), (-speed, 0, 0, 0)),
        ("DOWN", pygame.K_DOWN, (left + BUTTON_W * 1, bottom), (0, -speed, 0, 0)),
        ("RIGHT", pygame.K_RIGHT, (left + BUTTON_W * 2, bottom), (speed, 0, 0, 0)),
        ("UP", pygame.K_UP, (left + BUTTON_W * 3, bottom), (0, speed, 0, 0)),
        ("W", pygame.K_w, (left + BUTTON_W * 4, bottom), (0, 0, speed, 0)),
        ("S", pygame.K_s, (left + BUTTON_W * 5, bottom), (0, 0, -speed, 0)),
        ("A", pygame.K_a, (left + BUTTON_W * 6, bottom), (0, 0, 0, -speed)),
        ("D", pygame.K_d, (left + BUTTON_W * 7, bottom), (0, 0, 0, speed)),
        ("E", pygame.K_e, (left + BUTTON_W * 8, bottom), None),
        ("Q", pygame.K_q, (left + BUTTON_W * 9, bottom), None),
        ("X", pygame.K_x, (left + BUTTON_W * 10, bottom), None),
    ]

    def takeoff() -> None:
        if drone:
            try:
                drone.takeoff()
            except Exception:
                pass

    def land() -> None:
        if drone:
            try:
                drone.land()
            except Exception:
                pass

    buttons: list[Button] = []
    for label, key, (x, y), control in rows:
        rect = pygame.Rect(x, y, BUTTON_W - 8, BUTTON_H)
        if label == "E":
            buttons.append(Button(label, key, rect, on_tap=takeoff))
        elif label == "Q":
            buttons.append(Button(label, key, rect, on_tap=land))
        elif label == "X":
            buttons.append(Button(label, key, rect, on_tap=stop_callback))
        else:
            buttons.append(Button(label, key, rect, control=control))
    return buttons


def draw_buttons(screen: pygame.Surface, font: pygame.font.Font, buttons: list[Button], pressed) -> None:
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

        label_surface = font.render(button.label, True, TEXT_COLOR)
        label_rect = label_surface.get_rect(center=button.rect.center)
        screen.blit(label_surface, label_rect)


def frame_to_surface(frame) -> Optional[pygame.Surface]:
    if frame is None:
        return None
    try:
        rgb = cv2.resize(frame, VIDEO_SIZE)
        rgb = cv2.flip(rgb,1)
        rotated = np.rot90(rgb)
        return pygame.surfarray.make_surface(rotated)
    except Exception:
        return None


def main() -> None:
    kp.init()  # Reuse existing setup; we'll override the window to our custom size next.
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Tello Cockpit")
    font = pygame.font.SysFont("Arial", 22)
    small_font = pygame.font.SysFont("Arial", 16)
    clock = pygame.time.Clock()

    drone, status = connect_drone()
    frame_reader = drone.get_frame_read() if drone else None
    running = True

    def stop_app() -> None:
        nonlocal running
        running = False

    buttons = build_buttons(drone, stop_app)
    video_rect = pygame.Rect(
        PADDING,
        PADDING,
        VIDEO_SIZE[0],
        VIDEO_SIZE[1],
    )

    while running:
        clock.tick(30)
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
                        if btn.label == "E":
                            btn.handle_click()
                elif event.key == pygame.K_q:
                    for btn in buttons:
                        if btn.label == "Q":
                            btn.handle_click()

        # Calculate control vector based on active buttons
        lr = fb = ud = yv = 0
        for btn in buttons:
            if btn.is_control and btn.active(pressed):
                d_lr, d_fb, d_ud, d_yv = btn.control  # type: ignore[misc]
                lr += d_lr
                fb += d_fb
                ud += d_ud
                yv += d_yv

        if drone:
            try:
                drone.send_rc_control(lr, fb, ud, yv)
            except Exception:
                status = "RC control unavailable; check connection."

        # Draw background and video
        screen.fill(BG_COLOR)
        pygame.draw.rect(screen, VIDEO_BG, video_rect, border_radius=12)
        frame_surface = frame_to_surface(frame_reader.frame if frame_reader else None)
        if frame_surface:
            screen.blit(frame_surface, video_rect)
        else:
            placeholder = small_font.render(status or "Waiting for video...", True, TEXT_COLOR)
            screen.blit(placeholder, placeholder.get_rect(center=video_rect.center))

        # UI text
        screen.blit(font.render("Tello Cockpit", True, TEXT_COLOR), (video_rect.left, video_rect.bottom + 12))
        screen.blit(small_font.render(status, True, TEXT_COLOR), (video_rect.left, video_rect.bottom + 40))

        draw_buttons(screen, font, buttons, pressed)
        pygame.display.flip()

    if drone:
        try:
            drone.send_rc_control(0, 0, 0, 0)
            drone.streamoff()
        except Exception:
            pass
    pygame.quit()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pygame.quit()
        sys.exit()
