import sqlite3, os, statistics
from datetime import datetime

DB_FILE = "/app/data/classroom_data.db"


def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=10.0);
    conn.execute("PRAGMA journal_mode=WAL;");
    conn.row_factory = sqlite3.Row
    return conn


def calculate_thermal_loss(room_id, days=30):
    """Calculate thermal loss rate during overnight stable periods (AC OFF)."""
    conn = get_db()
    # Safety guard: Skip if latest state shows AC ON
    latest_ac = conn.execute("SELECT ac_state FROM sensor_history WHERE room_id=? ORDER BY timestamp DESC LIMIT 1",
                             (room_id,)).fetchone()
    if latest_ac and "ON" in latest_ac['ac_state'].upper():
        conn.close();
        return None

    data = conn.execute("""SELECT timestamp, temperature
                           FROM sensor_history
                           WHERE room_id=?
                             AND time (timestamp) BETWEEN '02:00'
                             AND '05:00'
                             AND timestamp
                               > datetime('now'
                               , ?)
                           ORDER BY timestamp""",
                        (room_id, f'-{days} days')).fetchall()
    if len(data) < 10: conn.close(); return None

    decay_rates = []
    for i in range(len(data) - 1):
        t1, t2 = data[i]['temperature'], data[i + 1]['temperature']
        
        try:
            dt1 = datetime.strptime(data[i]['timestamp'].split('.')[0], '%Y-%m-%d %H:%M:%S')
            dt2 = datetime.strptime(data[i + 1]['timestamp'].split('.')[0], '%Y-%m-%d %H:%M:%S')
            hours = (dt2 - dt1).total_seconds() / 3600.0
        except Exception:
            continue
            
        if hours > 0: 
            decay_rates.append(abs(t1 - t2) / hours)

    if not decay_rates: conn.close(); return None
    avg_decay = statistics.mean(decay_rates)
    loss_rate = min(1.0, max(0.0, avg_decay / 2.0))

    conn.execute("UPDATE classroom_metadata SET thermal_loss_rate=? WHERE room_id=?", (round(loss_rate, 2), room_id))
    conn.commit();
    conn.close()
    return loss_rate


if __name__ == "__main__":
    import sys, glob

    conn = get_db()
    rooms = conn.execute("SELECT room_id FROM classroom_metadata").fetchall()
    conn.close()
    for r in rooms:
        print(f"Modeling {r['room_id']}...")
        res = calculate_thermal_loss(r['room_id'])
        print(f" -> Loss Rate: {res}")