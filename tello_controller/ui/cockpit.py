"""Pygame cockpit UI for controlling a DJI Tello with keyboard or on-screen buttons."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np
import pygame

from tello_controller.drone import DroneClient
from tello_controller.vision import FaceDetector, YOLOv8Detector

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
ICON_DIR = Path(__file__).resolve().parents[1] / "assets" / "icons"
LETTER_LABELS = {
    pygame.K_w: "W",
    pygame.K_a: "A",
    pygame.K_s: "S",
    pygame.K_d: "D",
    pygame.K_e: "E",
    pygame.K_p: "P",
    pygame.K_q: "Q",
    pygame.K_x: "X",
}
FPS = 30
DEFAULT_RC_SPEED = 50
MIN_RC_SPEED = 10
MAX_RC_SPEED = 100
SLIDER_HEIGHT = 15


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


@dataclass(frozen=True)
class Calibration:
    """Flight calibration values for map tracking."""

    forward_speed_cm_s: float = 117 / 10.0
    angular_speed_deg_s: float = 360 / 10.0
    interval_s: float = 0.2

    @property
    def distance_per_interval(self) -> float:
        return self.forward_speed_cm_s * self.interval_s

    @property
    def angle_per_interval(self) -> float:
        return self.angular_speed_deg_s * self.interval_s


@dataclass
class MapTracker:
    """Simple 2D map tracker for movement visualization."""

    size: tuple[int, int] = (1000, 1000)
    origin: tuple[int, int] = (500, 500)
    angle: float = -90.0
    x: float = 0.0
    y: float = 0.0
    points: list[tuple[int, int]] = field(default_factory=lambda: [(500, 500)])

    def update(self, lr: int, fb: int, yv: int, calibration: Calibration) -> None:
        if fb != 0:
            self.x += calibration.distance_per_interval * fb / abs(fb) * np.cos(np.radians(self.angle))
            self.y += calibration.distance_per_interval * fb / abs(fb) * np.sin(np.radians(self.angle))
        if yv != 0:
            self.angle = (self.angle + calibration.angle_per_interval * yv / abs(yv)) % 360
        if lr != 0:
            self.x += calibration.distance_per_interval * lr / abs(lr) * np.cos(np.radians(self.angle + 90))
            self.y += calibration.distance_per_interval * lr / abs(lr) * np.sin(np.radians(self.angle + 90))
        head = (int(self.origin[0] + self.x), int(self.origin[1] + self.y))
        self.points.append(head)

    def render(self, draw_path: bool) -> np.ndarray:
        canvas = np.zeros((self.size[1], self.size[0], 3), dtype=np.uint8)
        head = self.points[-1]
        if draw_path:
            for point in self.points:
                cv2.circle(canvas, point, 2, (255, 255, 255), 3)
        cv2.circle(canvas, head, 3, (0, 0, 255), 5)
        indicator = (
            int(head[0] + 8 * np.cos(np.radians(self.angle))),
            int(head[1] + 8 * np.sin(np.radians(self.angle))),
        )
        cv2.circle(canvas, indicator, radius=1, color=(0, 0, 255), thickness=3)
        cv2.putText(
            canvas,
            f"{(head[0] - self.origin[0], -head[1] + self.origin[1])}",
            (head[0] + 10, head[1] + 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 255),
            1,
        )
        return canvas


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


def build_buttons(
    layout: Layout,
    drone: DroneClient,
    stop_callback: Callable[[], None],
    snapshot_callback: Callable[[], None],
) -> list[Button]:
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
        ("Up (W)", pygame.K_w, (wasd_mid, top_row_y), (0, 0, 1, 0), "up.svg"),
        ("Spin CCW (A)", pygame.K_a, (wasd_left, bottom_row_y), (0, 0, 0, -1), "spin_ccw.svg"),
        ("Down (S)", pygame.K_s, (wasd_mid, bottom_row_y), (0, 0, -1, 0), "down.svg"),
        ("Spin CW (D)", pygame.K_d, (wasd_right, bottom_row_y), (0, 0, 0, 1), "spin_cw.svg"),
        ("Forward", pygame.K_UP, (arrow_mid, top_row_y), (0, 1, 0, 0), "forward.svg"),
        ("Left", pygame.K_LEFT, (arrow_left, bottom_row_y), (-1, 0, 0, 0), "left.svg"),
        ("Backward", pygame.K_DOWN, (arrow_mid, bottom_row_y), (0, -1, 0, 0), "backward.svg"),
        ("Right", pygame.K_RIGHT, (arrow_right, bottom_row_y), (1, 0, 0, 0), "right.svg"),
        ("Takeoff (E)", pygame.K_e, (actions_x, actions_y + (layout.button_h + layout.button_gap) * 0), None, "takeoff.svg"),
        ("Land (Q)", pygame.K_q, (actions_x, actions_y + (layout.button_h + layout.button_gap) * 1), None, "land.svg"),
        ("Snapshot (P)", pygame.K_p, (actions_x, actions_y + (layout.button_h + layout.button_gap) * 2), None, None),
        ("Exit (X)", pygame.K_x, (actions_x, actions_y + (layout.button_h + layout.button_gap) * 3), None, "exit.svg"),
    ]

    buttons: list[Button] = []
    for label, key, (x, y), control, icon in rows:
        rect = pygame.Rect(x, y, layout.button_w - 8, layout.button_h)
        if key == pygame.K_e:
            buttons.append(Button(label, key, rect, on_tap=drone.takeoff, icon_name=icon))
        elif key == pygame.K_q:
            buttons.append(Button(label, key, rect, on_tap=drone.land, icon_name=icon))
        elif key == pygame.K_p:
            buttons.append(Button(label, key, rect, on_tap=snapshot_callback, icon_name=icon))
        elif key == pygame.K_x:
            buttons.append(Button(label, key, rect, on_tap=stop_callback, icon_name=icon))
        else:
            buttons.append(Button(label, key, rect, control=control, icon_name=icon))
    return buttons


def compute_control_vector(buttons: list[Button], pressed, speed: int) -> tuple[int, int, int, int]:
    """Aggregate active button control vectors from keyboard and mouse."""
    lr = fb = ud = yv = 0
    for btn in buttons:
        if btn.is_control and btn.active(pressed):
            d_lr, d_fb, d_ud, d_yv = btn.control  # type: ignore[misc]
            lr += d_lr
            fb += d_fb
            ud += d_ud
            yv += d_yv
    return int(lr * speed), int(fb * speed), int(ud * speed), int(yv * speed)


def clamp_speed(value: int) -> int:
    return max(MIN_RC_SPEED, min(MAX_RC_SPEED, value))


def speed_from_position(x: int, rect: pygame.Rect) -> int:
    """Convert an x coordinate inside the slider to a speed value."""
    ratio = (x - rect.left) / rect.width
    ratio = max(0.0, min(1.0, ratio))
    return int(MIN_RC_SPEED + ratio * (MAX_RC_SPEED - MIN_RC_SPEED))


def draw_speed_slider(
    screen: pygame.Surface,
    font: pygame.font.Font,
    label_font: pygame.font.Font,
    rect: pygame.Rect,
    speed: int,
) -> None:
    """Render the speed slider and current value."""
    pygame.draw.rect(screen, OUTLINE_COLOR, rect.inflate(0, 6), border_radius=6)
    fill_ratio = (clamp_speed(speed) - MIN_RC_SPEED) / (MAX_RC_SPEED - MIN_RC_SPEED)
    fill_width = max(0, int(rect.width * fill_ratio))
    if fill_width:
        fill_rect = pygame.Rect(rect.left, rect.top, fill_width, rect.height)
        pygame.draw.rect(screen, ACTIVE_COLOR, fill_rect, border_radius=6)

    knob = pygame.Rect(0, 0, 12, 16)
    knob_center_x = rect.left + fill_width
    knob_center_x = max(
        rect.left + knob.width // 2,
        min(rect.right - knob.width // 2, knob_center_x),
    )
    knob.center = (knob_center_x, rect.centery)
    pygame.draw.rect(screen, BUTTON_COLOR, knob, border_radius=4)
    pygame.draw.rect(screen, OUTLINE_COLOR, knob, width=1, border_radius=4)

    label_surface = label_font.render("Speed", True, TEXT_COLOR)
    value_surface = font.render(f"{speed}", True, TEXT_COLOR)
    screen.blit(label_surface, (rect.left, rect.top - 20))
    screen.blit(value_surface, (rect.right - value_surface.get_width(), rect.top - 20))


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


def frame_to_surface(frame, video_size: tuple[int, int], mirror: bool = False) -> Optional[pygame.Surface]:
    """Convert a cv2 frame to a pygame surface sized to the video viewport."""
    if frame is None:
        return None
    try:
        rgb = cv2.resize(frame, video_size)
        if mirror:
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
    parser.add_argument(
        "--vision",
        choices=["none", "face", "yolo"],
        default="none",
        help="Annotate frames with vision modules (face or YOLOv8)",
    )
    parser.add_argument(
        "--yolo-model",
        default=str(Path(__file__).resolve().parents[1] / "assets" / "yolov8m.pt"),
        help="Path to YOLOv8 weights when --vision yolo is enabled",
    )
    parser.add_argument(
        "--vision-device",
        default="cpu",
        help="Device for vision models (cpu, cuda, mps)",
    )
    parser.add_argument(
        "--yolo-conf",
        type=float,
        default=0.25,
        help="Confidence threshold for YOLOv8 detections",
    )
    return parser.parse_args()


def setup_logging(level: str) -> None:
    """Configure root logger output."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def build_vision_module(args: argparse.Namespace):
    """Instantiate the selected vision module if requested."""
    try:
        if args.vision == "face":
            return FaceDetector()
        if args.vision == "yolo":
            return YOLOv8Detector(
                model_path=Path(args.yolo_model),
                device=args.vision_device,
                conf=args.yolo_conf,
            )
    except Exception as exc:  # noqa: BLE001
        logging.error("Vision module failed to initialize (%s): %s", args.vision, exc)
    return None


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
    vision_module = build_vision_module(args)
    vision_mode = args.vision if vision_module else "none"
    running = True
    last_battery_poll_ms = 0
    speed_value = DEFAULT_RC_SPEED
    dragging_speed = False
    calibration = Calibration()
    map_tracker = MapTracker()
    last_frame: Optional[np.ndarray] = None

    def stop_app() -> None:
        nonlocal running
        running = False

    def snapshot() -> None:
        if last_frame is None:
            logging.warning("No frame available for snapshot.")
            return
        images_dir = Path("camera_feed/images")
        images_dir.mkdir(parents=True, exist_ok=True)
        filename = images_dir / f"tello_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        if cv2.imwrite(str(filename), last_frame):
            logging.info("Saved snapshot to %s", filename)
        else:
            logging.warning("Snapshot save failed.")

    buttons = build_buttons(layout, drone, stop_app, snapshot)
    video_rect = pygame.Rect(
        layout.padding,
        layout.padding,
        layout.video_size[0],
        layout.video_size[1],
    )
    slider_rect = pygame.Rect(
        layout.padding + layout.video_size[0] + layout.button_gap,
        layout.padding + int((layout.button_h + layout.button_gap) * 3) + 10,
        layout.button_w - 8,
        SLIDER_HEIGHT,
    )

    while running:
        clock.tick(FPS)
        pressed = pygame.key.get_pressed()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if slider_rect.collidepoint(event.pos):
                    dragging_speed = True
                    speed_value = speed_from_position(event.pos[0], slider_rect)
                else:
                    for btn in buttons:
                        if btn.rect.collidepoint(event.pos):
                            if btn.is_action:
                                btn.handle_click()
                            elif btn.is_control:
                                btn.mouse_active = True
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if dragging_speed:
                    speed_value = speed_from_position(event.pos[0], slider_rect)
                    dragging_speed = False
                for btn in buttons:
                    btn.mouse_active = False
            elif event.type == pygame.MOUSEMOTION and dragging_speed:
                speed_value = speed_from_position(event.pos[0], slider_rect)
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
                elif event.key == pygame.K_p:
                    for btn in buttons:
                        if btn.key == pygame.K_p and btn.is_action:
                            btn.handle_click()

        lr, fb, ud, yv = compute_control_vector(buttons, pressed, speed_value)
        drone.send_rc_control(lr, fb, ud, yv)
        status = drone.status
        now_ms = pygame.time.get_ticks()
        if now_ms - last_battery_poll_ms >= 5000:
            drone.refresh_battery()
            last_battery_poll_ms = now_ms

        vision_detections = []
        frame = drone.read_frame()
        if frame is not None:
            if vision_module:
                frame, vision_detections = vision_module.annotate(frame)
            last_frame = frame.copy()

        screen.fill(BG_COLOR)
        pygame.draw.rect(screen, VIDEO_BG, video_rect, border_radius=12)

        frame_surface = frame_to_surface(frame, layout.video_size)
        if frame_surface:
            screen.blit(frame_surface, video_rect)
        else:
            placeholder = text_font.render(status or "Waiting for video...", True, TEXT_COLOR)
            screen.blit(placeholder, placeholder.get_rect(center=video_rect.center))

        title = f"Tello Cockpit ({drone.battery_label()})"
        screen.blit(title_font.render(title, True, TEXT_COLOR), (video_rect.left, video_rect.bottom + 12))
        screen.blit(text_font.render(status, True, TEXT_COLOR), (video_rect.left, video_rect.bottom + 40))
        if vision_module:
            vision_label = f"Vision: {vision_mode} ({len(vision_detections)} detections)"
            screen.blit(text_font.render(vision_label, True, TEXT_COLOR), (video_rect.left, video_rect.bottom + 60))

        draw_speed_slider(screen, text_font, label_font, slider_rect, speed_value)
        draw_buttons(screen, text_font, label_font, buttons, pressed)
        pygame.display.flip()

        map_tracker.update(lr, fb, yv, calibration)
        map_frame = map_tracker.render(draw_path=drone.debug)
        cv2.imshow("Tello Mapping", map_frame)

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
