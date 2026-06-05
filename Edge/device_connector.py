import paho.mqtt.client as mqtt
import time, json, os, glob, random, signal, sys

BROKER = os.getenv("MQTT_BROKER", "localhost")
ROOM_ID = os.getenv("ROOM_ID", "classroom001")
PIR_GPIO_PIN = 17
W1_DEVICE_ID = os.getenv("W1_DEVICE_ID", "")

temp_mode = os.getenv("TEMP_MODE", "normal") # "low", "normal", "high"
motion_start_hour = int(os.getenv("MOTION_START_HOUR", "8"))
motion_end_hour = int(os.getenv("MOTION_END_HOUR", "18"))

pir = None
using_mock_motion = False
using_mock_temp = False

ac_is_on = False
vent_is_open = False
current_occupancy = 0
last_fake_update = 0
current_fake_temp = 22.0
current_fake_motion = 0

def data_generator():
    global current_fake_temp, current_fake_motion, last_fake_update
    global ac_is_on, vent_is_open, current_occupancy, temp_mode, motion_start_hour, motion_end_hour
    
    now = time.time()
    if now - last_fake_update < 1.0:
        return round(current_fake_temp, 1), current_fake_motion
        
    last_fake_update = now
    
    # Motion
    current_hour = time.localtime().tm_hour
    if motion_start_hour < motion_end_hour:
        is_active = motion_start_hour <= current_hour < motion_end_hour
    else:
        is_active = current_hour >= motion_start_hour or current_hour < motion_end_hour
        
    if is_active:
        current_fake_motion = 1
    else:
        #current_fake_motion = 0
        current_fake_motion = 1
        
    # Temperature
    if temp_mode == "low": target_temp = 3.0
    elif temp_mode == "high": target_temp = 31.0
    else: target_temp = 22.0
    
    # Apply effects
    if ac_is_on:
        target_temp -= 5.0
    if vent_is_open:
        target_temp = (target_temp + 20.0) / 2.0
        
    target_temp += (current_occupancy * 0.05)
    
    # Move fake_temp smoothly towards target_temp
    current_fake_temp += (target_temp - current_fake_temp) * 0.1
    current_fake_temp += random.uniform(-0.1, 0.1)
    
    if temp_mode == "low": current_fake_temp = max(1.0, min(5.0, current_fake_temp))
    elif temp_mode == "high": current_fake_temp = max(22.0, min(35.0, current_fake_temp))
    else: current_fake_temp = max(12.0, min(25.0, current_fake_temp))
    
    return round(current_fake_temp, 1), current_fake_motion


try:
    from gpiozero import MotionSensor
    from gpiozero.pins.mock import MockFactory
    import gpiozero
    # Use Mock factory if we're not actually on a Pi (avoids the loud warnings and crash if run on x86)
    is_pi = False
    try:
        with open("/proc/cpuinfo", "r") as f:
            cpuinfo = f.read()
            if "Raspberry Pi" in cpuinfo or "BCM" in cpuinfo:
                is_pi = True
    except:
        pass
        
    if not is_pi:
        gpiozero.Device.pin_factory = MockFactory()
        using_mock_motion = True
        
    pir = MotionSensor(PIR_GPIO_PIN)
    if using_mock_motion:
        print(f"⚠️ No motion sensor detected, using fallback.", flush=True)
    else:
        print(f"✅ PIR Motion Sensor initialized on GPIO {PIR_GPIO_PIN}", flush=True)
except Exception as e:
    using_mock_motion = True
    print(f"⚠️ No motion sensor detected, using fallback.", flush=True)

def get_w1_device_path():
    global W1_DEVICE_ID
    if not W1_DEVICE_ID:
        devices = glob.glob("/sys/bus/w1/devices/28*")
        if devices:
            W1_DEVICE_ID = os.path.basename(devices[0])
        else:
            return None
    return f"/sys/bus/w1/devices/{W1_DEVICE_ID}/w1_slave"

def read_temperature():
    global using_mock_temp
    path = get_w1_device_path()
    if not path:
        if not using_mock_temp:
            print(f"⚠️ No temp sensor detected, using fallback.", flush=True)
            using_mock_temp = True
        temp, _ = data_generator()
        return temp
    try:
        with open(path, "r") as f:
            lines = f.readlines()
            if "YES" in lines[0]:
                temp_pos = lines[1].find("t=")
                if temp_pos != -1:
                    return round(float(lines[1][temp_pos + 2:]) / 1000.0, 1)
    except Exception as e:
        if not using_mock_temp:
            print(f"⚠️ No temp sensor detected, using fallback.", flush=True)
            using_mock_temp = True
    temp, _ = data_generator()
    return temp

def read_motion():
    if pir and not using_mock_motion:
        try:
            return 1 if pir.motion_detected else 0
        except Exception as e:
            pass # fallback to simulated below
    _, motion = data_generator()
    return motion

client = mqtt.Client(f"{ROOM_ID}_Connector")
client.reconnect_delay_set(min_delay=1, max_delay=120)

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"✅ Connected to Central ({BROKER})", flush=True)
        client.subscribe([
            ("system/discover", 0),
            (f"{ROOM_ID}/state/history", 0),
            (f"{ROOM_ID}/ventilation/state", 0)
        ])
        print("📡 Subscribed to discovery and feedback topics", flush=True)
    else:
        print(f"⚠️ Failed to connect to Central ({BROKER}), rc={rc}", flush=True)

def on_disconnect(client, userdata, rc):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    if rc == 0:
        print(f"[{ts}] 🔌 Disconnected from Central ({BROKER})", flush=True)
    else:
        print(f"[{ts}] ⚠️ Lost connection to Central ({BROKER}), reconnecting... (rc={rc})", flush=True)

def on_message(client, userdata, msg):
    global ac_is_on, vent_is_open, current_occupancy
    topic = msg.topic
    
    try:
        payload_str = msg.payload.decode().strip()
    except Exception:
        return

    if topic == "system/discover":
        client.publish(f"system/discover/{ROOM_ID}/response", json.dumps({
            "room_id": ROOM_ID,
            "type": "sensor",
            "status": "online",
            "motion_sensor": "fallback" if using_mock_motion else "online",
            "temp_sensor": "fallback" if using_mock_temp else "online"
        }), retain=False)
    elif topic == f"{ROOM_ID}/state/history":
        try:
            data = json.loads(payload_str)
            current_occupancy = data.get("occupancy_count", 0)
            
            ac_state = data.get("ac_state", "{}")
            if isinstance(ac_state, str):
                try: ac_state = json.loads(ac_state)
                except: ac_state = {"status": ac_state}
            
            ac_is_on = ac_state.get("status", "OFF") != "OFF"
        except:
            pass
    elif topic == f"{ROOM_ID}/ventilation/state":
        vent_is_open = (payload_str == "OPEN")

client.on_message = on_message
client.on_connect = on_connect
client.on_disconnect = on_disconnect

def signal_handler(sig, frame):
    print("🛑 Stopping sensor connector...", flush=True)
    client.loop_stop()
    client.disconnect()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# We need to loop forever to handle reconnects properly
client.loop_start()

while True:
    try:
        client.connect(BROKER, 1883, 60)
        break
    except Exception as e:
        print(f"⚠️ MQTT connection failed: {e}. Retrying in 5s...", flush=True)
        time.sleep(5)



print(f"📡 Starting real sensor polling for {ROOM_ID}", flush=True)
try:
    while True:
        temp_val = read_temperature()
        motion_val = read_motion()
        
        print(f"📊 Sending Data - Temp: {temp_val}°C | Motion: {'Detected' if motion_val else 'None'}", flush=True)
        
        payload = json.dumps({
            "motion": motion_val,
            "temperature": temp_val
        })
        try:
            client.publish(f"{ROOM_ID}/sensors", payload)
        except Exception as e:
            pass # ignore if currently disconnected
        time.sleep(5)
except KeyboardInterrupt:
    pass
