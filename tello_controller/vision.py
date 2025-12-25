"""
Lightweight vision modules for reusing face detection and YOLOv8 object
annotation across the project (webcam or drone feeds).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np


@dataclass(frozen=True)
class Detection:
    label: str
    score: float
    box: Tuple[int, int, int, int]  # (x1, y1, x2, y2)


class FaceDetector:
    """Haar-cascade face detector with simple annotations."""

    def __init__(
        self,
        cascade_path: Optional[Path] = None,
        border_ratio: float = 0.3,
    ):
        default_path = Path(__file__).resolve().parent / "assets" / "haarcascade_frontalface_default.xml"
        self.cascade_path = cascade_path or default_path
        self.border_ratio = border_ratio
        self.cascade = cv2.CascadeClassifier(str(self.cascade_path))
        if self.cascade.empty():
            raise FileNotFoundError(f"Could not load cascade from {self.cascade_path}")

    def annotate(self, frame: np.ndarray) -> tuple[np.ndarray, List[Detection]]:
        annotated = frame.copy()
        gray = cv2.cvtColor(annotated, cv2.COLOR_BGR2GRAY)
        faces = self.cascade.detectMultiScale(gray, 1.2, 8)

        detections: List[Detection] = []
        if len(faces) == 0:
            return annotated, detections

        image_height, image_width = annotated.shape[:2]
        left_border = int(image_width * self.border_ratio)
        right_border = int(image_width * (1 - self.border_ratio))
        cv2.line(annotated, (left_border, 0), (left_border, image_height), (0, 0, 255), 5)
        cv2.line(annotated, (right_border, 0), (right_border, image_height), (0, 0, 255), 5)

        for (x, y, w, h) in faces:
            cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 0, 255), 3)
            center = (x + w // 2, y + h // 2)
            cv2.circle(annotated, center, 5, (255, 0, 0), -1)
            cv2.putText(
                annotated,
                f"{w * h:,.1f}",
                (center[0] + 2, center[1]),
                fontFace=cv2.FONT_HERSHEY_SIMPLEX,
                fontScale=0.8,
                color=(255, 255, 255),
                thickness=2,
            )
            detections.append(Detection("face", 1.0, (x, y, x + w, y + h)))

        return annotated, detections


class YOLOv8Detector:
    """YOLOv8 object detector with bounding box annotations."""

    def __init__(
        self,
        model_path: Optional[Path] = None,
        device: str = "cpu",
        conf: float = 0.25,
    ):
        try:
            from ultralytics import YOLO
        except Exception as exc:  # noqa: BLE001
            raise ImportError("ultralytics must be installed to use YOLOv8Detector") from exc

        default_path = Path(__file__).resolve().parent / "assets" / "yolov8m.pt"
        self.model_path = model_path or default_path
        self.device = device
        self.conf = conf
        self.model = YOLO(str(self.model_path))

    def annotate(self, frame: np.ndarray) -> tuple[np.ndarray, List[Detection]]:
        results = self.model(frame, device=self.device, conf=self.conf, verbose=False)
        annotated = frame.copy()
        detections: List[Detection] = []

        if not results or len(results) == 0:
            return annotated, detections

        boxes = results[0].boxes
        names = getattr(self.model, "names", {}) or {}

        for box, cls_id, score in zip(boxes.xyxy, boxes.cls, boxes.conf):
            x1, y1, x2, y2 = map(int, box)
            label = names.get(int(cls_id), str(int(cls_id)))
            detections.append(Detection(label, float(score), (x1, y1, x2, y2)))
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), 2)
            cv2.putText(
                annotated,
                f"{label} {float(score):.2f}",
                (x1, max(15, y1 - 8)),
                fontFace=cv2.FONT_HERSHEY_SIMPLEX,
                fontScale=0.6,
                color=(0, 0, 255),
                thickness=2,
            )

        return annotated, detections
