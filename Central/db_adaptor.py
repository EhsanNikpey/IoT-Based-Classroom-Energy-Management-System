import paho.mqtt.client as mqtt
from flask import Flask, jsonify, request
import json, threading, sqlite3, os, atexit, time

app = Flask(__name__)
BROKER = os.getenv("MQTT_BROKER", "localhost").strip()
DB_FILE = os.getenv("DB_FILE", "/app/data/classroom_data.db").strip()
mqtt_client = None
mqtt_connected = False

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS sensor_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        room_id TEXT, motion INTEGER, occupancy_count INTEGER, temperature REAL,
        outside_temp REAL,
        lamp_state TEXT,
        lamp_front_state TEXT,
        lamp_back_state TEXT,
        ac_state TEXT, system_mode TEXT DEFAULT 'predictive')''')
    c.execute('''CREATE TABLE IF NOT EXISTS classroom_metadata (
        room_id TEXT PRIMARY KEY, capacity INTEGER, has_projector BOOLEAN, has_pcs BOOLEAN,
        has_ventilation BOOLEAN, has_camera BOOLEAN, avg_efficiency_score REAL, thermal_loss_rate REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS course_schedule (
        id INTEGER PRIMARY KEY AUTOINCREMENT, course_name TEXT, start_time DATETIME,
        end_time DATETIME, room_id TEXT, student_count INTEGER DEFAULT 0,
        req_pcs BOOLEAN DEFAULT 0, req_projector BOOLEAN DEFAULT 0, days TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS control_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        room_id TEXT, device TEXT, action TEXT, status TEXT DEFAULT 'pending', edge_ack TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS efficiency_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        room_id TEXT, efficiency_score REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS weather_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        outside_temp REAL,
        city TEXT)''')
    conn.commit()
    conn.close()

def on_connect(client, userdata, flags, rc):
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        client.subscribe([("+/state/history", 0), ("+/control/ack", 0)])
        print("✅ MQTT DB Adaptor connected & subscribed", flush=True)
    else:
        mqtt_connected = False
        print(f"⚠️ MQTT DB connect failed with code {rc}", flush=True)

def on_disconnect(client, userdata, rc):
    global mqtt_connected
    mqtt_connected = False
    print("🔌 MQTT DB Disconnected", flush=True)

def on_message(client, userdata, msg):
    topic = msg.topic.strip()
    try: 
        payload_str = msg.payload.decode().strip()
    except: 
        return

    if topic.endswith("/state/history"):
        try:
            data = json.loads(payload_str)
            room_id = topic.split('/')[0].strip() # Clean room_id
            system_mode = data.get("system_mode", "predictive")
            ac_state_raw = data.get("ac_state", "OFF")
            if isinstance(ac_state_raw, dict): ac_state_raw = json.dumps(ac_state_raw)
            
            conn = get_db()
            conn.execute('''INSERT INTO sensor_history
                (room_id, motion, occupancy_count, temperature, outside_temp, lamp_state, lamp_front_state, lamp_back_state, ac_state, system_mode)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (room_id, data.get("motion", 0), data.get("occupancy_count", 0),
                 data.get("temperature", 25.0), data.get("outside_temp"), data.get("lamp_state", "OFF"),
                 data.get("lamp_front_state", data.get("lamp_state", "OFF")),
                 data.get("lamp_back_state", data.get("lamp_state", "OFF")),
                 ac_state_raw,
                 system_mode))
            conn.commit()
            conn.close()
        except Exception as e: 
            print(f"⚠️ DB Insert Error: {e} ", flush=True)

    elif topic.endswith("/control/ack"):
        try:
            data = json.loads(payload_str)
            room_id = topic.split('/')[0].strip()
            dev = data.get("device", "unknown")
            conn = get_db()
            pending = conn.execute(
                '''SELECT id FROM control_logs WHERE room_id = ? AND status = 'pending'
                   AND (device = ? OR device LIKE ? OR ? LIKE '%' || device || '%')
                   ORDER BY datetime(timestamp) DESC, id DESC LIMIT 1''',
                (room_id, dev, f"%{dev}%", dev)
            ).fetchone()
            if pending:
                conn.execute("UPDATE control_logs SET status='acknowledged', edge_ack=? WHERE id=?", (json.dumps(data), pending['id']))
            conn.commit()
            conn.close()
        except Exception as e: 
            print(f"⚠️ ACK Update Error: {e} ", flush=True)

def start_mqtt():
    global mqtt_client
    mqtt_client = mqtt.Client("Central_DB_Adaptor")
    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.on_message = on_message
    mqtt_client.reconnect_delay_set(min_delay=1, max_delay=120)
    try:
        mqtt_client.connect(BROKER)
        mqtt_client.loop_forever()
    except Exception as e:
        print(f"❌ MQTT DB Error: {e}", flush=True)

@app.route('/api/data/history')
def get_history():
    rid = request.args.get('room_id')
    conn = get_db()
    try:
        c = conn.cursor()
        q = 'SELECT * FROM sensor_history ORDER BY timestamp DESC LIMIT 100'
        p = ()
        if rid: 
            q = 'SELECT * FROM sensor_history WHERE room_id = ? ORDER BY timestamp DESC LIMIT 100'
            p = (rid,)
        c.execute(q, p)
        return jsonify({"history": [dict(r) for r in c.fetchall()]})
    finally: 
        conn.close()

@app.route('/api/latest_state')
def get_latest_state():
    rid = request.args.get('room_id')
    if not rid: 
        return jsonify({})
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT * FROM sensor_history WHERE room_id = ? ORDER BY timestamp DESC LIMIT 1', (rid,))
        res = c.fetchone()
        return jsonify(dict(res) if res else {})
    finally: 
        conn.close()

@app.route('/api/health')
def get_health():
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT MAX(timestamp) as last_ts FROM sensor_history')
        res = c.fetchone()
        last_ts = res['last_ts'] if res and res['last_ts'] else None
        return jsonify({"mqtt_connected": mqtt_connected, "last_db_timestamp": last_ts, "service": "db_adaptor"})
    finally: 
        conn.close()

def shutdown_mqtt():
    if mqtt_client:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()

atexit.register(shutdown_mqtt)

if __name__ == "__main__":
    init_db()
    threading.Thread(target=start_mqtt, daemon=True).start()
    app.run(host='0.0.0.0', port=5002)