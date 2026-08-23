import cv2
from ultralytics import YOLO

def run_inference():
    model = YOLO("best.pt")

    results = model(source=0, stream=True, imgsz=960, conf=0.25)

    print("Starting webcam stream. Press 'q' in the display window to quit.")

    for r in results:
        annotated_frame = r.plot()

        cv2.imshow("YOLO Construction Safety Detection", annotated_frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cv2.destroyAllWindows()

if __name__ == "__main__":
    run_inference()
