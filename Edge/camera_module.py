import paho.mqtt.client as mqtt
import time, os, json, random, signal, sys
from datetime import datetime

BROKER = os.getenv("MQTT_BROKER", "localhost")
ROOM_ID = os.getenv("ROOM_ID", "classroom001")
HAS_CAMERA = os.getenv("HAS_CAMERA", "false").lower() == "true"
MOTION_SENSOR_TIMEOUT = int(os.getenv("MOTION_SENSOR_TIMEOUT", "300"))
CAMERA_ACTIVE_SECONDS = int(os.getenv("CAMERA_ACTIVE_SECONDS", "30"))
CAMERA_SLEEP_SECONDS = int(os.getenv("CAMERA_SLEEP_SECONDS", "60"))

last_sensor_heartbeat = time.time()
model, _cap = None, None
is_scheduled, last_motion_time, last_occupancy_count = False, time.time(), 0
current_motion = 0
model_loaded = False
sensor_was_stale = False
running = True


def signal_handler(sig, frame):
    global running, _cap
    print("🛑 Shutting down camera module...", flush=True)
    running = False
    if _cap and _cap.isOpened(): _cap.release()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def load_yolo_model():
    global model, model_loaded
    if not HAS_CAMERA: return
    try:
        from ultralytics import YOLO
        model = YOLO("yolov8n.pt")
        model_loaded = True
    except Exception as e:
        print(f"❌ YOLO load error: {e}", flush=True)
        model_loaded = False


def get_occupancy_count():
    global model, model_loaded, _cap
    if not model_loaded: return 0
    if _cap is None or not _cap.isOpened():
        import cv2
        _cap = cv2.VideoCapture(0)
        if not _cap.isOpened(): return 0

    ret, frame = _cap.read()
    if not ret:
        _cap.release();
        _cap = None;
        return 0
    try:
        results = model(frame, imgsz=640, verbose=False)
        has_people = len(results[0].boxes) > 0
        return sum(1 for box in results[0].boxes if int(box.cls[0]) == 0)
    except Exception as e:
        print(f"📷 Inference error: {e}", flush=True)
        return 0


def on_message(client, userdata, msg):
    global is_scheduled, last_motion_time, last_sensor_heartbeat, current_motion
    topic = msg.topic.strip()
    
    try:
        payload_str = msg.payload.decode().strip()
    except Exception:
        return

    if topic == "system/discover":
        client.publish(f"system/discover/{ROOM_ID}/response", json.dumps({
            "room_id": ROOM_ID, "type": "camera", "status": "online"
        }), retain=False)
        return
    if not HAS_CAMERA: return
    if topic == f"{ROOM_ID}/schedule":
        is_scheduled = payload_str.upper() == "ON"
    elif topic == f"{ROOM_ID}/sensors":
        try:
            data = json.loads(payload_str)
            current_motion = int(data.get("motion", 0))
            if current_motion == 1: last_motion_time = time.time()
            last_sensor_heartbeat = time.time()
        except:
            pass


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"✅ Connected to Central ({BROKER})", flush=True)
        client.subscribe([
            ("system/discover", 0),
            (f"{ROOM_ID}/sensors", 0),
            (f"{ROOM_ID}/schedule", 0)
        ])
        print("📡 Subscribed to camera topics", flush=True)
    else:
        print(f"⚠️ Failed to connect to Central ({BROKER}), rc={rc}", flush=True)


def on_disconnect(client, userdata, rc):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    if rc == 0:
        print(f"[{ts}] 🔌 Disconnected from Central ({BROKER})", flush=True)
    else:
        print(f"[{ts}] ⚠️ Lost connection to Central ({BROKER}), reconnecting... (rc={rc})", flush=True)


def main():
    global last_occupancy_count, last_motion_time, is_scheduled, sensor_was_stale, current_motion
    if HAS_CAMERA: load_yolo_model()

    client = mqtt.Client(f"{ROOM_ID}_Camera")
    client.on_message = on_message
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=120)

    while running:
        try:
            client.connect(BROKER)
            client.loop_start()
            break
        except Exception as e:
            print(f"❌ MQTT failed: {e}. Retrying in 5s...", flush=True)
            time.sleep(5)

    print("⏳ Camera module running...", flush=True)

    last_print_time = 0
    duty_cycle_start = time.time()

    while running:
        if not HAS_CAMERA:
            time.sleep(1);
            continue

        sensor_is_stale = (time.time() - last_sensor_heartbeat) > MOTION_SENSOR_TIMEOUT

        now = time.time()
        has_people = last_occupancy_count > 0

        if is_scheduled and not has_people:
            # If scheduled but room is empty, force continuous scanning.
            camera_active = True
            duty_cycle_start = now
        elif sensor_is_stale:
            # Fallback: force active scans when sensor feed is stale.
            camera_active = True
            if not sensor_was_stale:
                print("⚠️ Motion sensor stale! FORCING continuous camera scan as fallback.", flush=True)
                sensor_was_stale = True
            duty_cycle_start = now
        elif current_motion == 0 and not has_people and not is_scheduled:
            # Deep sleep until either schedule starts or motion is detected.
            camera_active = False
            sensor_was_stale = False # Reset flag once sensor is healthy
            duty_cycle_start = now
        elif has_people:
            # People present: run 1-min active / 4-min sleep repeating cycle.
            cycle_seconds = max(1, CAMERA_ACTIVE_SECONDS + CAMERA_SLEEP_SECONDS)
            cycle_elapsed = (now - duty_cycle_start) % cycle_seconds
            camera_active = cycle_elapsed < max(0, CAMERA_ACTIVE_SECONDS)
        else:
            # Wake scan mode (motion=1 or scheduled with no people yet).
            camera_active = True
            duty_cycle_start = now

        current_time = time.time()
        if current_time - last_print_time >= 5:
            print(f"DEBUG: is_scheduled={is_scheduled}, has_people={has_people}, camera_active={camera_active}", flush=True)
            if camera_active:
                c = get_occupancy_count()
                last_occupancy_count = c
                print(f"📷 Camera Data - Occupancy Detected: {c} people", flush=True)
                client.publish(f"{ROOM_ID}/camera/occupancy", json.dumps({"occupancy_count": c}))
            else:
                print(f"📷 Camera Data - Occupancy: {last_occupancy_count} (Sleep phase: duty cycle)", flush=True)
            last_print_time = current_time

        time.sleep(1)

    client.loop_stop();
    client.disconnect()


if __name__ == "__main__":
    main()
