import cv2
from vision import FaceDetector

def main() -> None:
    cap = cv2.VideoCapture(0)
    detector = FaceDetector()

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.flip(frame, 1)
        annotated, faces = detector.annotate(frame)
        cv2.imshow("Face Detection", annotated)

        if cv2.waitKey(1) & 0xFF == 27:
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
