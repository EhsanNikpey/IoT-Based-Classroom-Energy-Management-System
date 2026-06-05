from flask import Flask, jsonify, request
import sqlite3, os, requests, statistics, threading, time, atexit

app = Flask(__name__)  # ✅ Fixed: was Flask(name)
DB_FILE = os.getenv("DB_FILE", "/app/data/classroom_data.db")
TELEGRAM_BOT_URL = os.getenv("TELEGRAM_BOT_URL", "http://localhost:5004/api/alert")
UPDATE_METRICS_INTERVAL_SECONDS = max(30, int(os.getenv("UPDATE_METRICS_INTERVAL_SECONDS", "300")))
SENSITIVITY = float(os.getenv("EFFICIENCY_SENSITIVITY", "10.0"))

_update_lock = threading.Lock()
_scheduler_stop_event = threading.Event()


def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn


@app.route('/api/statistics')
def get_global_stats():
    conn = get_db()
    try:
        res = conn.execute("SELECT AVG(temperature) AS avg_temp FROM sensor_history").fetchone()
        avg = round(res['avg_temp'], 2) if res and res['avg_temp'] else 25.0
        return jsonify({"average_temperature_celsius": avg})
    finally:
        conn.close()


@app.route('/api/update_metrics', methods=['POST'])
def update_metrics():
    result, status_code = run_efficiency_update()
    return jsonify(result), status_code


def run_efficiency_update():
    if not _update_lock.acquire(blocking=False):
        return {"status": "Skipped", "message": "Update already in progress", "rooms_processed": 0}, 200

    conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS efficiency_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            room_id TEXT,
            efficiency_score REAL
        )''')

        # Only process rooms with metadata (JOIN ensures fallback safety)
        rooms = conn.execute("""
                             SELECT DISTINCT s.room_id
                             FROM sensor_history s
                                      JOIN classroom_metadata m ON s.room_id = m.room_id
                             """).fetchall()

        updated_count = 0
        for row in rooms:
            rid = row['room_id']

            #   (system_mode != "manual")' to filter out manual overrides
            # This prevents standard deviation spikes caused by human adjustments
            # Fetch 20 samples for stable statistics
            query = """
                SELECT temperature 
                FROM sensor_history 
                WHERE room_id=? 
                  AND temperature IS NOT NULL 
                  AND system_mode != 'manual' 
                ORDER BY timestamp DESC 
                LIMIT 20
            """
            
            temps = [t['temperature'] for t in conn.execute(query, (rid,)).fetchall()]
            
            # We need at least 3 automatic samples to calculate a meaningful standard deviation
            if len(temps) < 3:
                continue
            
            # Efficiency calculation: 100 is perfect stability. 
            # Every degree of standard deviation drops the score by 10 points.
            temp_stdev = statistics.stdev(temps)
            new_score = max(0.0, 100.0 - (temp_stdev * SENSITIVITY))
            rounded_score = round(new_score, 1)

            conn.execute(
                "INSERT INTO efficiency_history (room_id, efficiency_score) VALUES (?, ?)",
                (rid, rounded_score)
            )

            prev = conn.execute("SELECT avg_efficiency_score FROM classroom_metadata WHERE room_id=?",
                                (rid,)).fetchone()
            old_score = prev['avg_efficiency_score'] if prev and prev['avg_efficiency_score'] is not None else 100.0

            # Only commit if meaningful change
            if abs(old_score - new_score) >= 1.0:
                # NEVER overwrite thermal_loss_rate (physical building constant)
                conn.execute("UPDATE classroom_metadata SET avg_efficiency_score=? WHERE room_id=?",
                             (rounded_score, rid))

                if (old_score - new_score) > 15.0:
                    msg = f"🚨 Efficiency Drop: {rid} fell from {old_score:.1f} to {new_score:.1f}. Check HVAC/Sensors."
                    try:
                        requests.post(TELEGRAM_BOT_URL, json={"message": msg}, timeout=3)
                    except Exception as e:
                        print(f"⚠️ Telegram alert failed: {e}", flush=True)
                updated_count += 1

        conn.commit()
        return {"status": "Updated", "rooms_processed": updated_count}, 200

    except Exception as e:
        conn.rollback()
        return {"status": "Error", "message": str(e), "rooms_processed": 0}, 500
    finally:
        conn.close()
        _update_lock.release()


def scheduler_loop():
    print(
        f"⏱️ Auto metrics scheduler enabled: every {UPDATE_METRICS_INTERVAL_SECONDS} seconds",
        flush=True
    )
    while not _scheduler_stop_event.wait(UPDATE_METRICS_INTERVAL_SECONDS):
        result, status_code = run_efficiency_update()
        if status_code >= 400:
            print(f"⚠️ Scheduled metrics update failed: {result}", flush=True)
        elif result.get('status') != 'Skipped':
            print(f"✅ Scheduled metrics update: {result}", flush=True)


def stop_scheduler():
    _scheduler_stop_event.set()


atexit.register(stop_scheduler)


if __name__ == '__main__':  # ✅ Fixed: was if name == 'main':
    threading.Thread(target=scheduler_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=5003)