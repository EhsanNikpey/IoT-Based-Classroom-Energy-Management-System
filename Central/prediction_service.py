import time, sqlite3, os, signal, sys, json
from datetime import datetime, timedelta
import paho.mqtt.client as mqtt

BROKER = os.getenv("MQTT_BROKER", "localhost")
DB_FILE = "/app/data/classroom_data.db"
DEFAULT_AC_PRECOOL_TEMP = int(os.getenv("DEFAULT_AC_PRECOOL_TEMP", "21"))
running = True


def signal_handler(sig, frame): global running; print("🛑 Prediction stopping...", flush=True); running = False


signal.signal(signal.SIGINT, signal_handler);
signal.signal(signal.SIGTERM, signal_handler)


def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=10.0);
    conn.execute("PRAGMA journal_mode=WAL;");
    conn.row_factory = sqlite3.Row
    return conn


def check_schedule_and_precool(client):
    conn = get_db();
    now = datetime.now()
    
    now_str, now_time, today = now.strftime('%Y-%m-%d %H:%M:%S'), now.strftime('%H:%M:%S'), now.strftime('%Y-%m-%d')
    lookahead = (now + timedelta(minutes=60)).strftime('%Y-%m-%d %H:%M:%S')

    query = """SELECT s.room_id, m.thermal_loss_rate, s.start_time, s.end_time
               FROM course_schedule s \
                        JOIN classroom_metadata m ON s.room_id = m.room_id
               WHERE s.status != 'cancelled' AND ((datetime(s.start_time) > datetime(?) AND datetime(s.start_time) <= datetime(?)) \
                  OR (s.days IS NOT NULL AND s.days != '' AND strftime('%H:%M:%S', s.start_time) > ? AND strftime('%H:%M:%S', s.start_time) <= ?))"""

    c = conn.execute(query, (now_str, lookahead, now_time, (now + timedelta(minutes=60)).strftime('%H:%M:%S')))
    for r in c.fetchall():
        latest = conn.execute("SELECT temperature FROM sensor_history WHERE room_id=? ORDER BY timestamp DESC LIMIT 1",
                              (r['room_id'],)).fetchone()
        current_temp = latest['temperature'] if latest else 25.0
        thermal_loss = r['thermal_loss_rate'] or 0.0
        
        if today >= str(r['start_time'])[:10] and today <= str(r['end_time'])[:10] and thermal_loss < 0.5 and current_temp > DEFAULT_AC_PRECOOL_TEMP:
            try:
                raw_start = str(r['start_time'])
                time_part = raw_start.split()[1] if ' ' in raw_start else raw_start
                class_start = datetime.strptime(f"{today} {time_part}", '%Y-%m-%d %H:%M:%S')
            except Exception:
                continue
                
            mins_to_start = (class_start - now).total_seconds() / 60.0
            
            temp_diff = current_temp - DEFAULT_AC_PRECOOL_TEMP
            
            dynamic_duration = min(60, max(5, int(temp_diff * 3.0 * (1.0 + thermal_loss))))
            
            if 0 < mins_to_start <= dynamic_duration:
                print(f"Prediction: Pre-cooling {r['room_id']} for {dynamic_duration}m (Temp {current_temp}°C)", flush=True)
                client.publish(
                    f"{r['room_id']}/ac/precool",
                    json.dumps({"target_temp": DEFAULT_AC_PRECOOL_TEMP, "duration_minutes": dynamic_duration, "source": "schedule"})
                )

    for r in conn.execute("SELECT DISTINCT room_id FROM classroom_metadata").fetchall():
        rid = r['room_id']
        # FIX: The query for active schedule was flawed. It used `datetime(end_time) > datetime(?)` where `?` was `now_str`.
        # But `now_str` includes seconds. If a class ends at 20:00:00, and it's 20:00:01, it's over.
        # The logic `datetime(start_time) <= datetime(now) AND datetime(end_time) > datetime(now)` is generally correct.
        # Let's use a simpler query to check if it's currently active.
        count = conn.execute("""SELECT COUNT(*)
                                FROM course_schedule
                                WHERE room_id = ? AND status != 'cancelled'
                                  AND (
                                    (datetime(start_time) <= datetime(?) AND datetime(end_time) > datetime(?)) 
                                    OR (days IS NOT NULL AND days != '' 
                                        AND strftime('%H:%M:%S', start_time) <= ? 
                                        AND strftime('%H:%M:%S', end_time) > ? 
                                        AND ? >= substr(start_time, 1, 10) 
                                        AND ? <= substr(end_time, 1, 10))
                                  )""",
                             (rid, now_str, now_str, now_time, now_time, today, today)).fetchone()[0]
        
        status = "ON" if count > 0 else "OFF"
        print(f"Publishing schedule status {status} for {rid} (Count: {count})", flush=True)
        client.publish(f"{rid}/schedule", status, retain=True)
    conn.close()


if __name__ == "__main__":
    print("Prediction service started.", flush=True)
    client = mqtt.Client("Prediction_Service");
    client.reconnect_delay_set(min_delay=1, max_delay=60)
    try:
        client.connect(BROKER); client.loop_start()
    except Exception as e:
        print(f"MQTT connect error: {e}", flush=True)
        sys.exit(1)
    while running:
        try:
            check_schedule_and_precool(client)
        except Exception as e:
            print(f"Error in prediction loop: {e}", flush=True)
        time.sleep(10)
    client.loop_stop();
    client.disconnect()
