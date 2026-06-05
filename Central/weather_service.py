import time, os, requests, sqlite3, signal, sys, json
import paho.mqtt.client as mqtt
from flask import Flask, jsonify

API_KEY = os.getenv("OPENWEATHER_API_KEY")
CITY = os.getenv("WEATHER_CITY", "Torino")
DB_FILE = "/app/data/classroom_data.db"
TELEGRAM_BOT_URL = "http://localhost:5004/api/alert"
BROKER = os.getenv("MQTT_BROKER", "localhost")
running = True

app = Flask(__name__)

def signal_handler(sig, frame):
    global running;
    print("🛑 Weather stopping...");
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def get_db():
    if not os.path.exists(DB_FILE): return None
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;");
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    if not conn:
        return
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS weather_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            outside_temp REAL,
            city TEXT
        )''')
        conn.commit()
    finally:
        conn.close()

def get_outside_temp():
    if not API_KEY: return 25.0
    try:
        res = requests.get(f"http://api.openweathermap.org/data/2.5/weather?q={CITY}&appid={API_KEY}&units=metric",
                           timeout=10)
        return res.json()["main"]["temp"] if res.status_code == 200 else 25.0
    except:
        return 25.0

@app.route('/api/weather', methods=['GET'])
def get_weather():
    temp = get_outside_temp()
    return jsonify({"outside_temperature": temp, "city": CITY})

def persist_weather_sample(conn, outside_temp):
    conn.execute(
        'INSERT INTO weather_history (outside_temp, city) VALUES (?, ?)',
        (outside_temp, CITY)
    )
    conn.commit()

def suggest_ventilation(mqtt_client):
    outside = get_outside_temp()
    conn = get_db()
    if not conn: return
    try:
        persist_weather_sample(conn, outside)
    except Exception:
        pass
    if mqtt_client:
        mqtt_client.publish("system/weather",
                            json.dumps({"outside_temp": outside, "city": CITY, "timestamp": time.time()}), retain=True)

    query = "SELECT s.room_id, s.temperature, m.has_ventilation FROM sensor_history s JOIN classroom_metadata m ON s.room_id = m.room_id WHERE m.has_ventilation = 1 ORDER BY s.timestamp DESC"
    seen = set()
    for row in conn.execute(query).fetchall():
        rid = row['room_id']
        if rid in seen: continue
        seen.add(rid)
        if row['temperature'] and outside < row['temperature'] and row['temperature'] > 24:
            msg = f"🌬️ Ventilation Alert for {rid}: Outside {outside}°C, Inside {row['temperature']}°C."
            print(msg)
            try:
                requests.post(TELEGRAM_BOT_URL, json={"message": msg}, timeout=3)
            except:
                pass
            mqtt_client.publish(f"{rid}/ventilation/suggest", json.dumps({
                "action": "activate", "outside_temp": outside, "inside_temp": row['temperature'],
                "priority": "high" if (row['temperature'] - outside) > 5 else "normal"
            }), retain=False)
    conn.close()

if __name__ == "__main__":
    print("🌍 Weather service started.")
    init_db()
    client = mqtt.Client("Weather_Service")
    try:
        client.connect(BROKER);
        client.loop_start()
    except Exception as e:
        print(f"⚠️ MQTT failed: {e}"); client = None
    
    # Start Flask app in a separate thread
    from threading import Thread
    flask_thread = Thread(target=lambda: app.run(host='0.0.0.0', port=5005))
    flask_thread.daemon = True
    flask_thread.start()

    while running:
        if client: suggest_ventilation(client)
        time.sleep(3600)
    if client: client.loop_stop(); client.disconnect()