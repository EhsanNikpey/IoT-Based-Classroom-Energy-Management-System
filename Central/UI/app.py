from flask import Flask, render_template, request, redirect, jsonify, flash, url_for
import sqlite3, os, paho.mqtt.client as mqtt, signal, sys, time, json, requests
from datetime import datetime
from room_selector import RoomSelector

# --- Configuration (Trailing spaces removed to prevent DB/MQTT path errors) ---
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "iot-dashboard-secret").strip()
DB_FILE = os.getenv("DB_FILE", "/app/data/classroom_data.db").strip()
BROKER = os.getenv("MQTT_BROKER", "localhost").strip()
STATS_SERVICE = os.getenv("STATS_SERVICE", "http://localhost:5003").strip()
DB_SERVICE = os.getenv("DB_SERVICE", "http://localhost:5002").strip()
WEATHER_SERVICE = os.getenv("WEATHER_SERVICE", "http://localhost:5005").strip()
FRESH_DATA_MAX_AGE_SECONDS = int(os.getenv("FRESH_DATA_MAX_AGE_SECONDS", "30").strip())
MANUAL_HOLD_THRESHOLD = int(os.getenv("MANUAL_HOLD_THRESHOLD", "60").strip())

selector = RoomSelector(db_path=DB_FILE)

# --- UI MQTT Client ---
ui_mqtt = mqtt.Client(client_id=f"UI_Control_{os.getpid()}_{int(time.time())}")
ui_mqtt.reconnect_delay_set(min_delay=1, max_delay=60)

def _on_ui_connect(client, userdata, flags, rc):
    if rc == 0:
        client.subscribe("+/control/ack")

def _on_ui_disconnect(client, userdata, rc):
    if rc != 0:
        print(f"[UI] MQTT disconnected unexpectedly (rc={rc})", flush=True)

def _on_ui_message(client, userdata, msg):
    topic = (msg.topic or '').strip()
    if not topic.endswith('/control/ack'):
        return
    room_id = topic.split('/')[0].strip()
    if not room_id:
        return
    try:
        payload = json.loads(msg.payload.decode().strip())
    except Exception:
        return
    device = str(payload.get('device', '')).strip()
    action = str(payload.get('action', '')).strip().upper()
    if not device:
        return
    conn = get_db()
    try:
        row = conn.execute(
            '''SELECT id FROM control_logs WHERE room_id = ? AND status = 'pending'
               AND action = ? AND (device = ? OR device LIKE ? OR ? LIKE '%' || device || '%')
               ORDER BY datetime(timestamp) DESC, id DESC LIMIT 1''',
            (room_id, action, device, f"%{device}%", device)
        ).fetchone()
        if row:
            conn.execute("UPDATE control_logs SET status='acknowledged', edge_ack=? WHERE id=?",
                         (json.dumps(payload), row['id']))
            conn.commit()
    finally:
        conn.close()

ui_mqtt.on_connect = _on_ui_connect
ui_mqtt.on_message = _on_ui_message
ui_mqtt.on_disconnect = _on_ui_disconnect
try:
    ui_mqtt.connect_async(BROKER)
    ui_mqtt.loop_start()
except Exception as e:
    print(f"⚠️ MQTT Start Failed: {e}", flush=True)

# --- DB Helpers ---
def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn

def ensure_db():
    conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS sensor_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            room_id TEXT, motion INTEGER, occupancy_count INTEGER, temperature REAL,
            outside_temp REAL, lamp_state TEXT, lamp_front_state TEXT, lamp_back_state TEXT, ac_state TEXT)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS classroom_metadata (
            room_id TEXT PRIMARY KEY, capacity INTEGER, has_projector BOOLEAN,
            has_pcs BOOLEAN, has_ventilation BOOLEAN, has_camera BOOLEAN,
            avg_efficiency_score REAL, thermal_loss_rate REAL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS course_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT, course_name TEXT, start_time DATETIME,
            end_time DATETIME, room_id TEXT, student_count INTEGER DEFAULT 0,
            req_pcs BOOLEAN DEFAULT 0, req_projector BOOLEAN DEFAULT 0,
            days TEXT, status TEXT DEFAULT 'scheduled')''')
        conn.execute('''CREATE TABLE IF NOT EXISTS control_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            room_id TEXT, device TEXT, action TEXT, status TEXT DEFAULT 'pending', edge_ack TEXT)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS efficiency_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            room_id TEXT, efficiency_score REAL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS weather_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            outside_temp REAL, city TEXT)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY, value TEXT)''')
        
        # Migrations
        cols = [r['name'] for r in conn.execute("PRAGMA table_info(sensor_history)").fetchall()]
        if 'system_mode' not in cols: conn.execute("ALTER TABLE sensor_history ADD COLUMN system_mode TEXT DEFAULT 'predictive'")
        if 'outside_temp' not in cols: conn.execute("ALTER TABLE sensor_history ADD COLUMN outside_temp REAL")
        if 'lamp_front_state' not in cols: conn.execute("ALTER TABLE sensor_history ADD COLUMN lamp_front_state TEXT")
        if 'lamp_back_state' not in cols: conn.execute("ALTER TABLE sensor_history ADD COLUMN lamp_back_state TEXT")
        
        cols_cs = [r['name'] for r in conn.execute("PRAGMA table_info(course_schedule)").fetchall()]
        if 'status' not in cols_cs: conn.execute("ALTER TABLE course_schedule ADD COLUMN status TEXT DEFAULT 'scheduled'")
        conn.commit()
    finally:
        conn.close()

ensure_db()

def parse_bool(value): return str(value).lower() in {"1", "true", "on", "yes"}
def bool_to_int(value): return 1 if parse_bool(value) else 0
def normalize_datetime(date_value, time_value):
    if not date_value or not time_value: return None
    time_value = time_value.strip()
    if len(time_value.split(':')) == 2: time_value = f"{time_value}:00"
    return f"{date_value} {time_value}"

def parse_db_timestamp(value):
    if value is None: return None
    raw = str(value).strip().replace('T', ' ')
    if '.' in raw: raw = raw.split('.')[0]
    try: return datetime.strptime(raw, '%Y-%m-%d %H:%M:%S')
    except Exception: return None

def get_classrooms():
    conn = get_db()
    try: return conn.execute('SELECT * FROM classroom_metadata ORDER BY room_id').fetchall()
    finally: conn.close()

def get_schedules(day_filter=None, page=1, per_page=10):
    conn = get_db()
    try:
        query = "SELECT * FROM course_schedule"
        count_query = "SELECT COUNT(*) as cnt FROM course_schedule"
        params = []
        if day_filter:
            filter_clause = " WHERE (days LIKE '%' || ? || '%') OR (substr(start_time, 1, 10) = ?)"
            query += filter_clause; count_query += filter_clause
            params.extend([day_filter, day_filter])
        query += " ORDER BY datetime(start_time) ASC, course_name ASC LIMIT ? OFFSET ?"
        total = conn.execute(count_query, params).fetchone()['cnt']
        params.extend([per_page, (page - 1) * per_page])
        rows = conn.execute(query, params).fetchall()
        return rows, total
    finally: conn.close()

def expire_stale_pending_commands(conn, timeout_seconds=180):
    conn.execute("""UPDATE control_logs SET status = 'not_done' WHERE status = 'pending'
                    AND timestamp IS NOT NULL AND datetime(timestamp) <= datetime('now', '-' || ? || ' seconds')""",
                 (int(timeout_seconds),)); conn.commit()

def explain_assignment_failure(student_count, req_pcs=False, req_projector=False):
    conn = get_db()
    try:
        rooms = conn.execute('SELECT room_id, capacity, has_pcs, has_projector FROM classroom_metadata').fetchall()
        if not rooms: return 'No classrooms configured.'
        capacity_ok = [r for r in rooms if (r['capacity'] or 0) >= student_count]
        if not capacity_ok: return 'Not enough capacity in any classroom.'
        if req_pcs:
            pcs_ok = [r for r in capacity_ok if r['has_pcs']]
            if not pcs_ok: return 'No room with PCs for the required capacity.'
            capacity_ok = pcs_ok
        if req_projector:
            projector_ok = [r for r in capacity_ok if r['has_projector']]
            if not projector_ok: return 'No room with projector for the required capacity.'
        return 'No room matches the current requirements.'
    finally: conn.close()

def get_control_logs(room_id=None):
    conn = get_db()
    try:
        expire_stale_pending_commands(conn)
        if room_id:
            rows = conn.execute('SELECT * FROM control_logs WHERE room_id = ? ORDER BY datetime(timestamp) DESC, id DESC', (room_id,)).fetchall()
        else:
            rows = conn.execute('SELECT * FROM control_logs ORDER BY datetime(timestamp) DESC, id DESC').fetchall()
        display_rows = []
        now = datetime.utcnow()
        for row in rows:
            item = dict(row)
            status = str(item.get('status', '')).strip().lower()
            if status == 'pending':
                raw_ts = str(item.get('timestamp', '')).strip().replace('T', ' ')
                try:
                    parsed_ts = datetime.strptime(raw_ts.split('.')[0], '%Y-%m-%d %H:%M:%S')
                    if max(0, int((now - parsed_ts).total_seconds())) >= 180: item['status'] = 'not_done'
                except Exception: pass
            display_rows.append(item)
        return display_rows
    finally: conn.close()

# --- FIX: Robust Vent State Check ---
def get_latest_vent_state(room_id):
    if not room_id: return 'CLOSED'
    conn = get_db()
    try:
        # Check for the most recent command sent to this vent
        row = conn.execute('''SELECT action FROM control_logs 
                             WHERE room_id = ? AND device = "ventilation" 
                             ORDER BY datetime(timestamp) DESC, id DESC LIMIT 1''', (room_id,)).fetchone()
        if not row: return 'CLOSED'
        # Treat both 'OPEN' and 'ON' as active states
        return 'OPEN' if (row['action'] or '').upper() in {'OPEN', 'ON'} else 'CLOSED'
    finally: conn.close()

def get_latest_sensor_state(room_id):
    if not room_id: return None
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM sensor_history WHERE room_id = ? ORDER BY datetime(timestamp) DESC, id DESC LIMIT 1', (room_id,)).fetchone()
        return dict(row) if row else None
    finally: conn.close()

def parse_ac_state_value(ac_state):
    raw_value = (ac_state or '').strip()
    if not raw_value: return {'status': 'OFF', 'mode': 'predictive'}
    try: parsed = json.loads(raw_value) if raw_value.startswith('{') else None
    except json.JSONDecodeError: parsed = None
    status, mode = 'OFF', 'predictive'
    if parsed:
        status = str(parsed.get('status', 'OFF')).upper()
        reason = str(parsed.get('reason', '')).upper()
        mode = str(parsed.get('mode', 'predictive')).lower()
        if 'MANUAL' in reason or mode == 'manual': mode = 'manual'
    else:
        upper = raw_value.upper()
        if 'PRECOOL' in upper: status, mode = 'PRECOOL', 'schedule precool'
        elif 'ON' in upper and 'OFF' not in upper: status = 'ON'
        elif 'MANUAL' in upper: mode = 'manual'
    if status == 'PRECOOL' and mode == 'predictive': mode = 'schedule precool'
    return {'status': status, 'mode': mode}

def normalize_mode_value(mode_value):
    mode = str(mode_value or '').strip().lower().replace('_', ' ')
    if mode in {'manual', 'user manual', 'override'}: return 'manual'
    if mode in {'scheduled precool', 'schedule precool', 'precool'}: return 'schedule precool'
    return 'predictive'

def build_alerts(limit=25):
    conn = get_db(); alerts = []
    try:
        expire_stale_pending_commands(conn)
        classrooms = conn.execute('SELECT room_id, capacity FROM classroom_metadata ORDER BY room_id ASC').fetchall()
        for room in classrooms:
            rid = room['room_id']
            latest = conn.execute('SELECT * FROM sensor_history WHERE room_id = ? ORDER BY datetime(timestamp) DESC, id DESC LIMIT 1', (rid,)).fetchone()
            if not latest:
                alerts.append({'severity': 'warning', 'room_id': rid, 'message': f'{rid}: no sensor data received yet.', 'timestamp': None, 'type': 'missing-data'}); continue
            ts, temp = latest['timestamp'], latest['temperature']
            occupancy, capacity = latest['occupancy_count'] or 0, room['capacity'] or 0
            if temp is not None and temp >= 30: alerts.append({'severity': 'danger', 'room_id': rid, 'message': f'{rid}: high temperature at {temp}°C.', 'timestamp': ts, 'type': 'high-temp'})
            if temp is not None and temp <= 16: alerts.append({'severity': 'warning', 'room_id': rid, 'message': f'{rid}: low temperature at {temp}°C.', 'timestamp': ts, 'type': 'low-temp'})
            if capacity > 0 and occupancy > capacity: alerts.append({'severity': 'danger', 'room_id': rid, 'message': f'{rid}: occupancy {occupancy} exceeds capacity {capacity}.', 'timestamp': ts, 'type': 'over-capacity'})
        pending = conn.execute('''SELECT room_id, device, action, timestamp FROM control_logs WHERE status = 'pending' AND room_id IS NOT NULL AND TRIM(room_id) != '' ORDER BY datetime(timestamp) DESC, id DESC LIMIT 10''').fetchall()
        for log in pending:
            alerts.append({'severity': 'warning', 'room_id': log['room_id'], 'message': f"{log['room_id']}: command {log['device']} {log['action']} still pending.", 'timestamp': log['timestamp'], 'type': 'pending-command'})
        alerts.sort(key=lambda item: item['timestamp'] or '', reverse=True)
        return alerts[:limit]
    finally: conn.close()

def publish_control_command(room_id, device, action):
    action_upper = action.upper(); topic, payload = None, None
    if device == 'ac':
        if action_upper == 'PRECOOL': topic, payload = f"{room_id}/ac/precool", json.dumps({"target_temp": 21, "duration_minutes": 15, "source": "manual"})
        else: topic, payload = f"{room_id}/ac/control", action_upper
    elif device == 'ventilation':
        topic, payload = f"{room_id}/ventilation/suggest", json.dumps({"action": 'activate' if action_upper == 'OPEN' else 'deactivate'})
    elif device in {'lamp/front', 'lamp/back'}:
        topic, payload = f"{room_id}/{device}/control", action_upper
    if not topic: return False, f"Unsupported device '{device}'."
    if not ui_mqtt.is_connected():
        for _ in range(10):
            if ui_mqtt.is_connected(): break
            time.sleep(0.1)
    info = ui_mqtt.publish(topic, payload, qos=1)
    if info.rc != mqtt.MQTT_ERR_SUCCESS: return False, f"Failed to publish MQTT command (rc={info.rc}) to topic '{topic}'."
    return True, None

def log_control_command(room_id, device, action):
    conn = get_db()
    try:
        cursor = conn.execute('INSERT INTO control_logs (room_id, device, action, status) VALUES (?, ?, ?, ?)', (room_id, device, action.upper(), 'pending')); conn.commit()
        return cursor.lastrowid
    finally: conn.close()

def mark_control_log_failed(log_id, reason):
    if not log_id: return
    conn = get_db()
    try:
        conn.execute("UPDATE control_logs SET status='not_done', edge_ack=? WHERE id=?", (json.dumps({'publish_error': str(reason)}), log_id)); conn.commit()
    finally: conn.close()

def build_chart_payload(room_id=None):
    conn = get_db()
    try:
        if room_id:
            history = conn.execute('''SELECT * FROM (SELECT * FROM sensor_history WHERE room_id = ? ORDER BY datetime(timestamp) DESC, id DESC LIMIT 100) ORDER BY datetime(timestamp) ASC, id ASC''', (room_id,)).fetchall()
        else:
            history = conn.execute('''SELECT * FROM (SELECT * FROM sensor_history ORDER BY datetime(timestamp) DESC, id DESC LIMIT 100) ORDER BY datetime(timestamp) ASC, id ASC''').fetchall()
        
        labels, temperatures, outside_temperatures, occupancy, motion = [], [], [], [], []
        #ac_values, lamp_front_values, lamp_back_values, vent_values, mode_values, mode_labels = [], [], [], [], [], [], []
        ac_values, lamp_front_values, lamp_back_values, vent_values, mode_values, mode_labels, efficiency_series = [], [], [], [], [], [], []

        vent_logs = conn.execute('''SELECT timestamp, action FROM control_logs WHERE device = 'ventilation' AND room_id = ? ORDER BY datetime(timestamp) ASC''', (room_id,)).fetchall()
        
        current_vent_state = 0
        log_idx = 0
        
        #for log in vent_logs: latest_vent_by_room[log['room_id']] = 1 if (log['action'] or '').upper() in {'OPEN', 'ON'} else 0

        for row in history:
            sensor_ts = parse_db_timestamp(row['timestamp'])
            labels.append(row['timestamp'])
            temperatures.append(row['temperature'] if row['temperature'] is not None else None)
            outside_temperatures.append(row['outside_temp'] if 'outside_temp' in row.keys() and row['outside_temp'] is not None else None)
            occupancy.append(row['occupancy_count'] if row['occupancy_count'] is not None else 0)
            motion.append(row['motion'] if row['motion'] is not None else 0)
            
            while log_idx < len(vent_logs):
                log_ts = parse_db_timestamp(vent_logs[log_idx]['timestamp'])
                if log_ts and sensor_ts and log_ts <= sensor_ts:
                    current_vent_state = 1 if (vent_logs[log_idx]['action'] or '').upper() in {'OPEN', 'ON'} else 0
                    log_idx += 1
                else:
                    break
            vent_values.append(current_vent_state)

            ac_info = parse_ac_state_value(row['ac_state'])
            ac_values.append(1 if ac_info['status'] in {'ON', 'PRECOOL'} else 0)
            #ac_precool_values.append(1 if ac_info['status'] == 'PRECOOL' else 0)
            #is_precool = ac_info['status'] == 'PRECOOL'
            #ac_precool_values.append(1 if is_precool else 0)
            lamp_state = (row['lamp_state'] or '').upper()
            lamp_on = 1 if lamp_state == 'ON' else 0
            lamp_front_values.append(lamp_on); lamp_back_values.append(lamp_on)
            #rid = row['room_id']
            #vent_state = get_latest_vent_state(rid)
            #vent_values.append(1 if vent_state == 'OPEN' else 0)
            #vent_values.append(latest_vent_by_room.get(row['room_id'], 0))
            mode_from_row = row['system_mode'] if 'system_mode' in row.keys() else None
            mode = normalize_mode_value(mode_from_row or ac_info.get('mode', 'predictive'))
            if mode == 'manual': mode_values.append(2); mode_labels.append('Manual')
            elif mode == 'schedule precool' or mode == 'precool': mode_values.append(1); mode_labels.append('Precool')
            else: mode_values.append(0); mode_labels.append('Predictive')

        weather_rows = conn.execute('''SELECT timestamp, outside_temp FROM weather_history WHERE outside_temp IS NOT NULL ORDER BY datetime(timestamp) ASC, id ASC''').fetchall()
        parsed_weather_rows = [(parse_db_timestamp(r['timestamp']), r['outside_temp']) for r in weather_rows if parse_db_timestamp(r['timestamp']) is not None]
        
        if parsed_weather_rows:
            outside_temperatures, parsed_weather_rows = [], sorted(parsed_weather_rows, key=lambda x: x[0])
            w_idx, current_outside = 0, None
            for row in history:
                sensor_ts = parse_db_timestamp(row['timestamp'])
                while w_idx < len(parsed_weather_rows):
                    w_ts, w_temp = parsed_weather_rows[w_idx]
                    if sensor_ts is None or w_ts > sensor_ts: break
                    current_outside = w_temp; w_idx += 1
                outside_temperatures.append(current_outside)
        elif any(v is not None for v in outside_temperatures):
            last_seen = None
            for i, v in enumerate(outside_temperatures):
                if v is None and last_seen is not None: outside_temperatures[i] = last_seen
                elif v is not None: last_seen = v
            first_seen = next((v for v in outside_temperatures if v is not None), None)
            if first_seen is not None: outside_temperatures = [first_seen if v is None else v for v in outside_temperatures]

        efficiency, ranking, efficiency_labels, efficiency_series = None, None, [], []
        if room_id:
            room = conn.execute('SELECT room_id, avg_efficiency_score FROM classroom_metadata WHERE room_id = ?', (room_id,)).fetchone()
            if room and room['avg_efficiency_score'] is not None:
                efficiency = round(room['avg_efficiency_score'], 2)
                ranking = conn.execute('SELECT COUNT(*) AS count FROM classroom_metadata WHERE avg_efficiency_score IS NOT NULL AND avg_efficiency_score > ?', (room['avg_efficiency_score'],)).fetchone()['count'] + 1
            eff_rows = conn.execute('''SELECT timestamp, efficiency_score FROM (SELECT timestamp, efficiency_score, id FROM efficiency_history WHERE room_id = ? AND efficiency_score IS NOT NULL ORDER BY datetime(timestamp) DESC, id DESC LIMIT 100) ORDER BY datetime(timestamp) ASC, id ASC''', (room_id,)).fetchall()
            for row in eff_rows: efficiency_labels.append(row['timestamp']); efficiency_series.append(round(row['efficiency_score'], 2))
        else:
            scores = [r['avg_efficiency_score'] for r in conn.execute('SELECT avg_efficiency_score FROM classroom_metadata WHERE avg_efficiency_score IS NOT NULL').fetchall()]
            if scores: efficiency = round(sum(scores) / len(scores), 2)
            
        return {'labels': labels, 'temperatures': temperatures, 'outside_temperatures': outside_temperatures, 'occupancy': occupancy, 'motion': motion, 'ac': ac_values, 'lamp_front': lamp_front_values, 'lamp_back': lamp_back_values, 'vent': vent_values, 'mode': mode_values, 'mode_labels': mode_labels, 'efficiency': efficiency, 'ranking': ranking, 'efficiency_labels': efficiency_labels, 'efficiency_series': efficiency_series}
    finally: conn.close()

# ==================== PROXY ROUTES ====================
@app.route('/api/weather')
def proxy_weather():
    try: res = requests.get(f"{WEATHER_SERVICE}/api/weather", timeout=5); return jsonify(res.json()), res.status_code
    except requests.RequestException as e: return jsonify({"error": f"Weather service unavailable: {str(e)}"}), 503

@app.route('/api/weather/latest')
def api_weather_latest():
    conn = get_db()
    try:
        row = conn.execute('''SELECT outside_temp, city, timestamp FROM weather_history WHERE outside_temp IS NOT NULL ORDER BY datetime(timestamp) DESC, id DESC LIMIT 1''').fetchone()
        if not row: return jsonify({"outside_temperature": None, "city": None, "timestamp": None}), 200
        return jsonify({"outside_temperature": row['outside_temp'], "city": row['city'], "timestamp": row['timestamp']}), 200
    finally: conn.close()

@app.route('/api/statistics')
def proxy_statistics():
    try: res = requests.get(f"{STATS_SERVICE}/api/statistics", timeout=5); return jsonify(res.json()), res.status_code
    except requests.RequestException as e: return jsonify({"error": f"Statistics service unavailable: {str(e)}"}), 503

@app.route('/api/alerts')
def api_alerts():
    alerts = build_alerts(limit=25)
    return jsonify({'alerts': alerts, 'count': len(alerts)})

@app.route('/api/report')
@app.route('/api/report')
def api_report():
    conn = get_db()
    try:
        rooms = conn.execute('SELECT room_id FROM classroom_metadata').fetchall()
        total_temp, temp_count, total_occupancy, online_rooms = 0.0, 0, 0, 0
        active_acs, active_lamps, open_vents = 0, 0, 0
        
        for r in rooms:
            rid = r['room_id']
            
            # --- VENT COUNTING (Always check this regardless of sensor age) ---
            if get_latest_vent_state(rid) == 'OPEN':
                open_vents += 1
                
            # --- SENSOR DATA (Strict freshness check for temp/occupancy) ---
            state = get_latest_sensor_state(rid) or {}
            age_secs = None
            if state.get('timestamp'):
                raw = str(state.get('timestamp')).replace('T', ' ')
                try: 
                    ts = datetime.strptime(raw.split('.')[0], '%Y-%m-%d %H:%M:%S')
                    age_secs = max(0, int((datetime.utcnow() - ts).total_seconds()))
                except Exception: pass
            
            # Only include temp/occupancy/AC/Lamp if the data is recent
            if age_secs is not None and age_secs <= FRESH_DATA_MAX_AGE_SECONDS:
                total_temp += float(state.get('temperature') or 0)
                temp_count += 1
                occ = max(0, int(state.get('occupancy_count') or 0))
                if occ == 0 and int(state.get('motion') or 0) == 1: occ = 1
                total_occupancy += occ
                online_rooms += 1
                
                ac_info = parse_ac_state_value(state.get('ac_state'))
                if ac_info['status'] in {'ON', 'PRECOOL'}: active_acs += 1
                if str(state.get('lamp_state') or 'OFF').upper() == 'ON': active_lamps += 1

        # ... (Rest of weather/report string formatting remains the same)
        weather, out_temp = {}, None
        try: res = requests.get(f"{WEATHER_SERVICE}/api/weather", timeout=2); weather = res.json() if res.ok else {}
        except: pass
        out_temp = weather.get("outside_temperature")
        forecast = weather.get("forecast", "Clear conditions expected today.")
        weather_str = f"🌤️ Weather: {forecast} | Outside Temp: {out_temp:.1f}°C\n\n" if out_temp is not None else ""
        
        if temp_count > 0 or open_vents > 0: # Include open vents as valid report data
            avg_temp = total_temp / temp_count if temp_count > 0 else 0
            report = f"📊 *System Report*\n\n{weather_str}✅ Rooms Online: {online_rooms} / {len(rooms)}\n" \
                     f"🌡️ Average Temp: {avg_temp:.1f}°C\n👥 Total Occupancy: {total_occupancy} people\n" \
                     f"❄️ Active AC Units: {active_acs}\n💡 Active Lamps: {active_lamps}\n🌬️ Open Vents: {open_vents}"
        else:
            report = f"📊 *System Report*\n\n{weather_str}⚠️ No fresh sensor data available right now."
        
        return jsonify({"report_text": report})
    finally: conn.close()

@app.route('/api/classrooms')
def api_classrooms():
    return jsonify({'classrooms': [dict(r) for r in get_classrooms()], 'count': len(get_classrooms())})

@app.route('/api/update_metrics', methods=['POST'])
def proxy_update_metrics():
    try: payload = request.get_json(silent=True) or {}; res = requests.post(f"{STATS_SERVICE}/api/update_metrics", json=payload, timeout=10); return jsonify(res.json()), res.status_code
    except requests.RequestException as e: return jsonify({"error": f"Metrics update failed: {str(e)}"}), 503

@app.route('/api/chart_data')
def proxy_chart_data():
    try: return jsonify(build_chart_payload(request.args.get('room_id')))
    except requests.RequestException as e: return jsonify({"error": f"Chart data unavailable: {str(e)}"}), 503

@app.route('/api/schedules/today')
def api_schedules_today():
    conn = get_db()
    try:
        now, today_str, day_name = datetime.now(), datetime.now().strftime('%Y-%m-%d'), datetime.now().strftime('%A')
        rows = conn.execute('''SELECT * FROM course_schedule WHERE (substr(start_time, 1, 10) = ?) OR (days LIKE '%' || ? || '%') ORDER BY time(start_time) ASC''', (today_str, day_name)).fetchall()
        return jsonify([dict(r) for r in rows])
    finally: conn.close()

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    conn = get_db()
    try:
        if request.method == 'POST':
            payload = request.get_json(silent=True) or {}
            for k, v in payload.items(): conn.execute('REPLACE INTO system_settings (key, value) VALUES (?, ?)', (k, str(v)))
            conn.commit(); return jsonify({'status': 'ok'})
        return jsonify({r['key']: r['value'] for r in conn.execute('SELECT key, value FROM system_settings').fetchall()})
    finally: conn.close()

# ==================== CONTROL API ====================
@app.route('/api/latest_state')
def proxy_latest_state():
    rid = request.args.get('room_id'); payload = {}
    try:
        res = requests.get(f"{DB_SERVICE}/api/latest_state", params={'room_id': rid} if rid else {}, timeout=5)
        if res.ok and res.headers.get('Content-Type', '').startswith('application/json'): payload = res.json()
    except requests.RequestException: pass
    if not payload and rid: payload = get_latest_sensor_state(rid) or {}
    if isinstance(payload, dict) and rid:
        if not payload.get('vent_state'):
            try: payload['vent_state'] = get_latest_vent_state(rid)
            except Exception as e: payload['vent_state'] = 'CLOSED'
    return jsonify(payload)

@app.route('/api/system_health')
def api_system_health():
    room_id = request.args.get('room_id', '').strip(); db_health = {}
    try:
        res = requests.get(f"{DB_SERVICE}/api/health", timeout=4)
        if res.headers.get('Content-Type', '').startswith('application/json'): db_health = res.json()
    except requests.RequestException: db_health = {'mqtt_connected': False}
    latest = get_latest_sensor_state(room_id) if room_id else None; age_seconds = None
    if latest and latest.get('timestamp'):
        raw = str(latest.get('timestamp')).replace('T', ' ')
        try: age_seconds = max(0, int((datetime.utcnow() - datetime.strptime(raw.split('.')[0], '%Y-%m-%d %H:%M:%S')).total_seconds()))
        except Exception: pass
    room_data_fresh = bool(age_seconds is not None and age_seconds <= FRESH_DATA_MAX_AGE_SECONDS)
    return jsonify({'ui_mqtt_connected': ui_mqtt.is_connected(), 'edge_mqtt_connected': room_data_fresh if room_id else db_health.get('mqtt_connected', False), 'last_sensor_age_seconds': age_seconds, 'fresh_data_max_age_seconds': FRESH_DATA_MAX_AGE_SECONDS, 'room_data_fresh': room_data_fresh})

@app.route('/api/control', methods=['POST'])
def api_control():
    data = request.get_json(silent=True) or request.form
    room_id = (data.get('room_id') or '').strip()
    device = (data.get('device') or '').strip()
    action = (data.get('action') or '').strip()
    action_upper = action.upper()
    
    if not room_id or not device or not action:
        return jsonify({'error': 'room_id, device, and action are required'}), 400
        
    conn = get_db()
    try:
        last_manual = conn.execute('''SELECT timestamp FROM control_logs WHERE room_id = ? AND status = 'acknowledged' ORDER BY datetime(timestamp) DESC, id DESC LIMIT 1''', (room_id,)).fetchone()
        conn.close()
    except: conn.close(); last_manual = None
        
    is_manual_active = False
    if last_manual:
        parsed_ts = parse_db_timestamp(last_manual['timestamp'])
        if parsed_ts and (datetime.utcnow() - parsed_ts).total_seconds() <= MANUAL_HOLD_THRESHOLD: is_manual_active = True
        
    latest = get_latest_sensor_state(room_id) or {}
    ac_info = parse_ac_state_value(latest.get('ac_state', 'OFF'))
    vent_state = get_latest_vent_state(room_id)

    if device == 'ventilation' and action_upper == 'OPEN' and ac_info.get('status') in {'ON', 'PRECOOL'}:
        return jsonify({'error': 'Cannot OPEN ventilation while AC is ON. Turn AC OFF first.', 'manual_active': is_manual_active}), 409
    if device == 'ac' and action_upper in {'ON', 'PRECOOL'} and vent_state == 'OPEN':
        return jsonify({'error': 'Cannot start AC while vents are OPEN. Close vents first.', 'manual_active': is_manual_active}), 409

    dev_mapped = {'lamp_front': 'lamp/front', 'lamp_back': 'lamp/back'}.get(device, device)
    log_id = log_control_command(room_id, dev_mapped, action_upper)
    ok, err = publish_control_command(room_id, dev_mapped, action_upper)
    
    if not ok: mark_control_log_failed(log_id, err); return jsonify({'error': err}), 503
    return jsonify({'status': 'ok', 'log_id': log_id, 'manual_hold_active': is_manual_active})

@app.route('/api/control_logs')
def api_control_logs():
    room_id = request.args.get('room_id', '').strip() or None
    return jsonify([dict(row) for row in get_control_logs(room_id)])

@app.route('/api/delete_log', methods=['POST'])
def api_delete_log():
    payload = request.get_json(silent=True) or {}; log_id = payload.get('id')
    if not log_id: return jsonify({'error': 'id is required'}), 400
    conn = get_db()
    try: conn.execute('DELETE FROM control_logs WHERE id = ?', (log_id,)); conn.commit(); return jsonify({'status': 'ok'})
    finally: conn.close()

# ==================== UI ROUTES ====================
@app.route('/')
def index(): return render_template('index.html')
@app.route('/charts')
def charts(): return render_template('charts.html', classrooms=get_classrooms())

@app.route('/schedule', methods=('GET', 'POST'))
def schedule():
    if request.method == 'POST':
        conn = get_db()
        try:
            edit_id = request.form.get('edit_id', '').strip()
            course_name = request.form.get('course_name', '').strip()
            student_count = int(request.form.get('student_count', '0') or 0)
            start_time = normalize_datetime(request.form.get('start_date', '').strip(), request.form.get('start_time', '').strip())
            end_time = normalize_datetime(request.form.get('end_date', '').strip(), request.form.get('end_time', '').strip())
            days = request.form.get('days', '').strip()
            req_pcs, req_projector = bool_to_int(request.form.get('req_pcs')), bool_to_int(request.form.get('req_projector'))

            if not course_name or not start_time or not end_time: flash('Course name, start time, and end time are required.', 'error'); return redirect(url_for('schedule'))
            
            raw_st, raw_et = request.form.get('start_time', '')[:5], request.form.get('end_time', '')[:5]
            if request.form.get('start_date', '') > request.form.get('end_date', ''): flash('End Date must be >= Start Date.', 'error'); return redirect(url_for('schedule'))
            if not ("08:00" <= raw_st <= "20:00"): flash('Start Time should be between 8 am and 8 pm.', 'error'); return redirect(url_for('schedule'))
            if not ("08:00" <= raw_et <= "20:00"): flash('End Time should be between 8 am and 8 pm.', 'error'); return redirect(url_for('schedule'))

            requirements = []
            if req_pcs: requirements.append('has_pcs')
            if req_projector: requirements.append('has_projector')

            assigned_room = selector.find_best_room(student_count, requirements, req_start_date=request.form.get('start_date',''), req_end_date=request.form.get('end_date',''), req_start_time=raw_st, req_end_time=raw_et, req_days=days, exclude_schedule_id=edit_id or None)
            room_id = assigned_room['room_id'] if assigned_room else 'Unassigned'
            if not assigned_room: flash(f'Schedule could not be assigned automatically: {explain_assignment_failure(student_count, bool(req_pcs), bool(req_projector))}', 'error')

            if edit_id: conn.execute('''UPDATE course_schedule SET course_name=?, start_time=?, end_time=?, room_id=?, student_count=?, req_pcs=?, req_projector=?, days=? WHERE id=?''', (course_name, start_time, end_time, room_id, student_count, req_pcs, req_projector, days, edit_id)); flash('Schedule updated.', 'success')
            else: conn.execute('''INSERT INTO course_schedule (course_name, start_time, end_time, room_id, student_count, req_pcs, req_projector, days) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', (course_name, start_time, end_time, room_id, student_count, req_pcs, req_projector, days)); flash('Schedule saved.', 'success')
            conn.commit()
        except ValueError: flash('Student count must be a valid number.', 'error')
        except Exception as e: flash(f'Unable to save schedule: {str(e)}', 'error')
        finally: conn.close()
        return redirect(url_for('schedule'))

    day_filter = request.args.get('day_filter', '').strip()
    try: page = int(request.args.get('page', 1))
    except ValueError: page = 1
    schedules, total = get_schedules(day_filter, page, 10)
    return render_template('schedule.html', schedules=schedules, form_data=request.args.to_dict(), day_filter=day_filter, page=page, total_pages=max(1, (total + 9) // 10))

@app.route('/assign_schedule', methods=('POST',))
def assign_schedule():
    schedule_id = request.form.get('id', '').strip()
    if not schedule_id: flash('Missing schedule id.', 'error'); return redirect(url_for('schedule'))
    conn = get_db()
    try:
        row = conn.execute('SELECT student_count, req_pcs, req_projector, start_time, end_time, days FROM course_schedule WHERE id = ?', (schedule_id,)).fetchone()
        if not row: flash('Schedule not found.', 'error'); return redirect(url_for('schedule'))
        reqs = ['has_pcs'] if row['req_pcs'] else []
        if row['req_projector']: reqs.append('has_projector')
        sd, st = str(row['start_time']).split(' '); ed, et = str(row['end_time']).split(' ')
        room = selector.find_best_room(row['student_count'] or 0, reqs, req_start_date=sd, req_end_date=ed, req_start_time=st[:5], req_end_time=et[:5], req_days=row['days'], exclude_schedule_id=schedule_id)
        if not room: flash(f'Unable to assign schedule: {explain_assignment_failure(row["student_count"] or 0, bool(row["req_pcs"]), bool(row["req_projector"]))}', 'error'); return redirect(url_for('schedule'))
        conn.execute('UPDATE course_schedule SET room_id = ? WHERE id = ?', (room['room_id'], schedule_id)); conn.commit()
        flash(f'Schedule assigned to {room["room_id"]}.', 'success')
    except Exception as e: flash(f'Unable to assign schedule: {str(e)}', 'error')
    finally: conn.close()
    return redirect(url_for('schedule'))

@app.route('/update_schedule_status', methods=['POST'])
def update_schedule_status():
    schedule_id, status = request.form.get('id', '').strip(), request.form.get('status', '').strip()
    if not schedule_id or status not in ['scheduled', 'delayed', 'cancelled']: flash('Invalid request parameters.', 'error'); return redirect(url_for('schedule'))
    conn = get_db()
    try: conn.execute('UPDATE course_schedule SET status = ? WHERE id = ?', (status, schedule_id)); conn.commit(); flash(f'Schedule status updated to {status}.', 'success')
    except Exception as e: flash(f'Unable to update status: {str(e)}', 'error')
    finally: conn.close()
    return redirect(request.referrer or url_for('schedule'))

@app.route('/delete_schedule', methods=('POST',))
def delete_schedule():
    schedule_id = request.form.get('id', '').strip()
    conn = get_db()
    try: conn.execute('DELETE FROM course_schedule WHERE id = ?', (schedule_id,)); conn.commit(); flash('Schedule deleted.', 'success')
    except Exception as e: flash(f'Unable to delete schedule: {str(e)}', 'error')
    finally: conn.close()
    return redirect(url_for('schedule'))

@app.route('/control', methods=('GET', 'POST'))
def control_page():
    return render_template('control.html', classrooms=get_classrooms(), room=request.args.get('room', ''))

@app.route('/api/clear_logs', methods=['POST'])
def api_clear_logs():
    payload = request.get_json(silent=True) or {}
    room_id = payload.get('room_id')
    conn = get_db()
    try:
        if room_id:
            conn.execute('DELETE FROM control_logs WHERE room_id = ?', (room_id,))
        else:
            conn.execute('DELETE FROM control_logs')
        conn.commit()
        return jsonify({'status': 'ok'})
    finally:
        conn.close()
        
@app.route('/classrooms', methods=('GET', 'POST'))
def classrooms():
    conn = get_db()
    try:
        if request.method == 'POST':
            room_id = request.form.get('room_id', '').strip()
            if not room_id: flash('Room ID is required.', 'error'); return redirect(url_for('classrooms'))
            try: capacity = int(request.form.get('capacity', '').strip()); thermal_loss_rate = float(request.form.get('thermal_loss_rate', '').strip())
            except ValueError: flash('Capacity and thermal loss rate must be valid numbers.', 'error'); return redirect(url_for('classrooms'))
            if capacity <= 0: flash('Capacity must be greater than zero.', 'error'); return redirect(url_for('classrooms'))
            if capacity > 1000: flash('Capacity exceeds maximum allowed limit (1000).', 'error'); return redirect(url_for('classrooms'))
            if not (0.0 <= thermal_loss_rate <= 1.0): flash('Thermal loss rate must be between 0.0 and 1.0.', 'error'); return redirect(url_for('classrooms'))
            has_camera, has_projector = bool_to_int(request.form.get('has_camera')), bool_to_int(request.form.get('has_projector'))
            has_pcs, has_ventilation = bool_to_int(request.form.get('has_pcs')), bool_to_int(request.form.get('has_ventilation'))
            is_edit = parse_bool(request.form.get('is_edit'))
            if conn.execute('SELECT room_id FROM classroom_metadata WHERE room_id = ?', (room_id,)).fetchone() or is_edit:
                conn.execute('''UPDATE classroom_metadata SET capacity=?, has_projector=?, has_pcs=?, has_ventilation=?, has_camera=?, thermal_loss_rate=? WHERE room_id=?''', (capacity, has_projector, has_pcs, has_ventilation, has_camera, thermal_loss_rate, room_id)); flash(f'Classroom {room_id} updated.', 'success')
            else:
                conn.execute('''INSERT INTO classroom_metadata (room_id, capacity, has_projector, has_pcs, has_ventilation, has_camera, avg_efficiency_score, thermal_loss_rate) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', (room_id, capacity, has_projector, has_pcs, has_ventilation, has_camera, 100.0, thermal_loss_rate)); flash(f'Classroom {room_id} added.', 'success')
            conn.commit(); return redirect(url_for('classrooms'))
        return render_template('classrooms.html', classrooms=conn.execute('SELECT * FROM classroom_metadata ORDER BY room_id ASC').fetchall(), error_msg=None)
    finally: conn.close()

@app.route('/delete_classroom', methods=('POST',))
def delete_classroom():
    room_id = request.form.get('room_id', '').strip()
    if not room_id: flash('Missing room_id.', 'error'); return redirect(url_for('classrooms'))
    conn = get_db()
    try: conn.execute('DELETE FROM classroom_metadata WHERE room_id = ?', (room_id,)); conn.commit(); flash(f'Classroom {room_id} deleted.', 'success')
    except Exception as e: flash(f'Unable to delete classroom: {str(e)}', 'error')
    finally: conn.close()
    return redirect(url_for('classrooms'))

@app.route('/api/scan_devices')
def scan_devices():
    found_devices, connected = [], {'ok': False}
    def on_connect(client, userdata, flags, rc):
        if rc == 0: connected['ok'] = True; client.subscribe("system/discover/#")
    def on_message(client, userdata, msg):
        try:
            payload_str = msg.payload.decode().strip()
            if not payload_str: return
            device = json.loads(payload_str)
            if device.get("room_id"): found_devices.append(device)
        except Exception as e: print(f"⚠️ Scan error: {e}", flush=True)

    client = mqtt.Client(f"UI_Scan_{int(time.time())}")
    client.on_connect, client.on_message = on_connect, on_message
    try:
        client.loop_start(); client.connect(BROKER, 1883, 10)
        for _ in range(10):
            if connected['ok']: break
            time.sleep(0.2)
        client.publish("system/discover", json.dumps({"request": "identify"})); time.sleep(0.5)
        client.publish("system/discover", json.dumps({"request": "identify"})); time.sleep(3)
        client.loop_stop()
    except Exception as e: print(f"⚠️ Scan MQTT error: {e}", flush=True)
    finally: client.disconnect()

    unique_rooms = {}
    for d in found_devices:
        rid = d.get('room_id')
        if not rid: continue
        if rid not in unique_rooms: unique_rooms[rid] = {'room_id': rid, 'status': 'online', 'types': set(), 'motion_sensor': None, 'temp_sensor': None}
        for dt in [p.strip() for p in str(d.get('type', 'unknown')).lower().split(',') if p.strip()]:
            if dt in ('camera', 'sensor'): unique_rooms[rid]['types'].add(dt)
        ms, ts = d.get('motion_sensor'), d.get('temp_sensor')
        if ms in ('online', 'fallback'): unique_rooms[rid]['motion_sensor'] = ms; unique_rooms[rid]['types'].add('sensor')
        if ts in ('online', 'fallback'): unique_rooms[rid]['temp_sensor'] = ts; unique_rooms[rid]['types'].add('sensor')
    for r in unique_rooms.values(): r['types'] = sorted(list(r['types']))
    return jsonify(list(unique_rooms.values()))

def shutdown_handler(sig, frame):
    ui_mqtt.loop_stop(); ui_mqtt.disconnect(); sys.exit(0)

signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)