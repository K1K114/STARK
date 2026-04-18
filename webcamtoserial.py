"""
Simple Python script to send webcam frames to ESP32-P4
over serial connection.

Detects if frame has any non-black content and sends data.
"""

import cv2
import serial
import time
import threading
from queue import Empty, Queue

# Configuration
SERIAL_PORT = '/dev/tty.usbmodem5B140758861'      # Windows: COM3, COM4, etc.
                         # Linux/Mac: /dev/ttyACM0, /dev/tty.usbmodem*
BAUD_RATE = 921600        # Must match ESP32's baud rate!

# Camera settings
CAMERA_INDEX = 0        # 0 = default webcam
FRAME_WIDTH = 160         # Small size for fast transmission
FRAME_HEIGHT = 120

# Detection threshold (how dark is "black"?)
BLACK_THRESHOLD = 5       # Pixels darker than this are "black"


def serial_sender_worker(frame_queue, stop_event, stats):
    """Send frames to the ESP32 without blocking the preview loop."""
    import numpy as np

    while not stop_event.is_set():
        try:
            frame = frame_queue.get(timeout=0.1)
        except Empty:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        min_val = np.min(gray)

        if min_val <= BLACK_THRESHOLD:
            continue

        ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
        if not ok:
            continue

        payload = buf.tobytes()
        try:
            stats['ser'].write(len(payload).to_bytes(4, 'little'))
            stats['ser'].write(payload)
            stats['ser'].flush()
            stats['sent_frames'] += 1
        except serial.SerialException:
            stop_event.set()
            break


def queue_latest(frame_queue, frame):
    """Keep only the newest frame so the sender cannot fall behind."""
    try:
        frame_queue.get_nowait()
    except Empty:
        pass

    try:
        frame_queue.put_nowait(frame)
    except Exception:
        pass

def main():
    print("=" * 50)
    print("  ESP32-P4 Camera Sender")
    print("=" * 50)
    
    # Initialize camera
    print(f"\n[1] Opening webcam (index {CAMERA_INDEX})...")
    cap = cv2.VideoCapture(CAMERA_INDEX)
    
    if not cap.isOpened():
        print("ERROR: Could not open webcam!")
        return
    
    # Set resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    
    # Open serial port
    print(f"[2] Opening serial port {SERIAL_PORT} at {BAUD_RATE} baud...")
    
    try:
        ser = serial.Serial(
            port=SERIAL_PORT,
            baudrate=BAUD_RATE,
            timeout=1,
            write_timeout=1
        )
        print("✓ Serial port opened successfully!")
        
        # Wait for ESP32 to initialize
        time.sleep(2)
        
    except serial.SerialException as e:
        print(f"ERROR: Cannot open serial port: {e}")
        print("\nPossible solutions:")
        print("  - Check if correct COM port selected")
        print("  - Make sure Arduino IDE/PlatformIO is NOT using the port")
        print("  - Try different baud rate")
        cap.release()
        return
    
    print("\n[3] Starting video stream...")
    print("Press Ctrl+C to stop\n")
    
    frame_count = 0
    start_time = time.time()
    stop_event = threading.Event()
    frame_queue = Queue(maxsize=1)
    serial_stats = {'ser': ser, 'sent_frames': 0}
    sender_thread = threading.Thread(
        target=serial_sender_worker,
        args=(frame_queue, stop_event, serial_stats),
        daemon=True,
    )
    sender_thread.start()
    
    try:
        while True:
            # Read frame
            ret, frame = cap.read()
            
            if not ret:
                print("Warning: Failed to read frame")
                continue
            
            queue_latest(frame_queue, frame)
            frame_count += 1

            elapsed = time.time() - start_time
            fps = frame_count / elapsed if elapsed > 0 else 0

            status_frame = frame.copy()
            status_text = f"Preview FPS: {fps:.1f} | Frame #{frame_count}"
            cv2.putText(
                status_frame,
                status_text,
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )

            cv2.imshow('ESP32-P4 Camera Feed', status_frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                raise KeyboardInterrupt
            
    except KeyboardInterrupt:
        print("\n\nStopping...")
        stop_event.set()
    
    finally:
        stop_event.set()
        sender_thread.join(timeout=2)
        # Cleanup
        cap.release()
        ser.close()
        cv2.destroyAllWindows()
        
        print(f"\n[STATISTICS]")
        print(f"Total preview frames: {frame_count}")
        print(f"Total frames sent: {serial_stats['sent_frames']}")
        elapsed = time.time() - start_time
        if elapsed > 0:
            print(f"Average preview FPS: {frame_count / elapsed:.1f}")
        print("Done!")

if __name__ == "__main__":
    # Check for numpy (needed for fast array operations)
    try:
        import numpy as np
    except ImportError:
        print("Note: Install numpy for better performance:")
        print("      pip install numpy opencv-python")
        print("Continuing without numpy...\n")
    
    main()