import cv2
from ultralytics import YOLO

def run_inference():
    # Load your custom trained YOLO weights
    model = YOLO("best.pt")

    # Run real-time streaming inference from local webcam (source 0)
    # imgsz set to 960 to match optimized small-object resolution
    results = model(source=0, stream=True, imgsz=960, conf=0.25)

    print("Starting webcam stream. Press 'q' in the display window to quit.")

    for r in results:
        # Draw bounding boxes and labels on the frame
        annotated_frame = r.plot()

        # Display the live feed
        cv2.imshow("YOLO Construction Safety Detection", annotated_frame)

        # Break loop when 'q' key is pressed
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Clean up display windows and camera access
    cv2.destroyAllWindows()

if __name__ == "__main__":
    run_inference()