import cv2

from tello_controller.vision import YOLOv8Detector


def main() -> None:
    cap = cv2.VideoCapture(0)
    detector = YOLOv8Detector(device="mps")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.flip(frame, 1)
        annotated, detections = detector.annotate(frame)
        cv2.imshow("YOLOv8", annotated)

        if cv2.waitKey(1) & 0xFF == 27:
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
