import os
from datetime import datetime
import threading
import time
import json
import requests
import telebot
from flask import Flask, request, jsonify

TOKEN = os.getenv("TELEGRAM_TOKEN")
UI_BASE_URL = os.getenv("UI_BASE_URL", "http://localhost:5000").rstrip("/")

bot = telebot.TeleBot(TOKEN) if TOKEN else None
app = Flask(__name__)

manager_chat_id = os.getenv("TELEGRAM_CHAT_ID") or None
muted_rooms = {}  # Maps room_id -> expiration_timestamp
daily_report_time = "08:00"  # Default report time


def _api_get(path, params=None, timeout=6):
    try:
        res = requests.get(f"{UI_BASE_URL}{path}", params=params, timeout=timeout)
        if res.ok:
            return res.json()
    except Exception:
        return None
    return None


def _api_post_form(path, data, timeout=8):
    try:
        res = requests.post(f"{UI_BASE_URL}{path}", data=data, timeout=timeout)
        payload = {}
        try:
            payload = res.json()
        except Exception:
            payload = {}
        return res.status_code, payload
    except Exception as e:
        return 503, {"error": str(e)}


def _api_post_json(path, data, timeout=8):
    try:
        res = requests.post(f"{UI_BASE_URL}{path}", json=data, timeout=timeout)
        payload = {}
        try:
            payload = res.json()
        except Exception:
            payload = {}
        return res.status_code, payload
    except Exception as e:
        return 503, {"error": str(e)}


def _set_manager_chat(chat_id):
    global manager_chat_id
    manager_chat_id = str(chat_id)


def _get_manager_chat():
    return manager_chat_id


def _send_manager_message(text):
    chat_id = _get_manager_chat()
    if not (bot and chat_id):
        return False
    try:
        bot.send_message(chat_id, text)
        return True
    except Exception:
        return False


def _parse_timestamp(raw):
    if not raw:
        return None
    value = str(raw).strip()
    if not value:
        return None
    value = value.replace("T", " ")
    value = value.split(".")[0]
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _seconds_since(raw):
    ts = _parse_timestamp(raw)
    if not ts:
        return None
    return max(0, int((datetime.utcnow() - ts).total_seconds()))


def _load_classrooms_map():
    data = _api_get("/api/classrooms") or {}
    rooms = data.get("classrooms", []) if isinstance(data, dict) else []
    return {(r.get("room_id") or "").strip(): r for r in rooms if (r.get("room_id") or "").strip()}


def _load_discovery_map():
    data = _api_get("/api/scan_devices")
    result = {}
    if not isinstance(data, list):
        return result
    for item in data:
        rid = (item.get("room_id") or "").strip()
        if not rid:
            continue
        types = item.get("types") or []
        result[rid] = {
            "types": [str(t).lower() for t in types],
            "motion_sensor": item.get("motion_sensor") or None,
            "temp_sensor": item.get("temp_sensor") or None,
        }
    return result


def _format_room_status(room_id):
    state = _api_get("/api/latest_state", params={"room_id": room_id}) or {}
    health = _api_get("/api/system_health", params={"room_id": room_id}) or {}
    discovery = _load_discovery_map().get(room_id, {})
    room_meta = _load_classrooms_map().get(room_id, {})

    # Data Freshness & Connection Status
    age_secs = _seconds_since(state.get("timestamp"))
    fresh_limit = int(health.get("fresh_data_max_age_seconds") or 30)
    sensors_fresh = age_secs is not None and age_secs <= fresh_limit

    ui_online = bool(health.get("ui_mqtt_connected"))
    edge_online = bool(health.get("edge_mqtt_connected"))
    edge_online_effective = sensors_fresh or edge_online

    # Sensor & Camera Health
    temp_state = discovery.get("temp_sensor") or ("fallback" if sensors_fresh else "offline")
    motion_state = discovery.get("motion_sensor") or ("fallback" if sensors_fresh else "offline")

    has_camera = int(room_meta.get("has_camera") or 0) == 1
    camera_discovered = "camera" in (discovery.get("types") or [])
    camera_state = "online" if (has_camera and camera_discovered) else ("not available" if not has_camera else "offline")

    if state and state.get("temperature") is not None and sensors_fresh:
        ac_raw = state.get("ac_state") or "OFF"
        try:
            # Handle if ac_state is a JSON string or already a dictionary
            ac_data = json.loads(ac_raw) if isinstance(ac_raw, str) and ac_raw.startswith('{') else ac_raw
            if not isinstance(ac_data, dict):
                ac_data = {"status": str(ac_raw)}
        except Exception:
            ac_data = {"status": str(ac_raw)}
        
        ac_status = str(ac_data.get("status", "OFF")).upper()
        # Extract 'reason' to show if it's MANUAL_OVERRIDE or DUTY_CYCLE
        ac_reason = str(ac_data.get("reason", "")).replace("_", " ").title()
        ac_display = f"{ac_status}" + (f" ({ac_reason})" if ac_reason else "")
        
        #ac_state_text = str(state.get("ac_state") or "OFF").upper()
        #ac_on = "ON" in ac_state_text and "OFF" not in ac_state_text
        
        vent_state = str(state.get("vent_state") or "CLOSE").upper()
        
        # Format System Mode (e.g., "manual" -> "Manual")
        system_mode = str(state.get("system_mode") or "predictive").replace("_", " ").title()
        
        occupancy = max(0, int(state.get("occupancy_count") or 0))
        motion = int(state.get("motion") or 0)
        if occupancy == 0 and motion == 1:
            occupancy = 1

        return (
            f"📍 Room: {room_id}\n"
            f"🌡️ Temp: {state.get('temperature')}°C | 👥 Occ: {occupancy} | ⚙️ Mode: {system_mode}\n"
            f"❄️ AC: {ac_display} | 💡 Lamp: {state.get('lamp_state', 'OFF')} | 🌬️ Vent: {vent_state}\n"
            f"📡 Edge: {'✅ Online' if edge_online_effective else '❌ Offline'} | ☁️ MQTT: {'✅ Online' if ui_online else '❌ Offline'}\n"
            f"🛠️ Sensors: [Temp: {temp_state}] [Motion: {motion_state}] [Cam: {camera_state}]"
        )

    return (
            f"📍 Room: {room_id}\n"
            f"⚠️ No fresh telemetry (Last seen: {age_secs if age_secs else 'N/A'}s ago).\n"
            f"📡 Edge: {'✅ Online' if edge_online_effective else '❌ Offline'} | ☁️ MQTT: {'✅ Online' if ui_online else '❌ Offline'}"
        )


def _format_alert(alert):
    severity = str(alert.get("severity") or "warning").upper()
    room_id = str(alert.get("room_id") or "-")
    msg = str(alert.get("message") or "Alert")
    ts = str(alert.get("timestamp") or "")
    icon = "🚨" if severity == "DANGER" else "⚠️"
    suffix = f" ({ts})" if ts else ""
    return f"{icon} [{severity}] {room_id}: {msg}{suffix}"


@app.route('/api/alert', methods=['POST'])
def receive_internal_alert():
    data = request.get_json(silent=True) or {}
    msg = data.get("message")
    if not msg:
        return jsonify({"error": "No message provided"}), 400
    
    success = _send_manager_message(f"🚨 INTERNAL ALERT 🚨\n{msg}")
    if success:
        return jsonify({"status": "Alert sent"}), 200
    else:
        return jsonify({"error": "Failed to send alert (bot not linked or chat ID missing)"}), 503


def _generate_report_text():
    data = _api_get("/api/report")
    if data and isinstance(data, dict) and "report_text" in data:
        return data["report_text"]
    return "📊 *System Report*\n\n⚠️ Unable to fetch report from UI service right now."


if bot:
    @bot.message_handler(commands=['start'])
    def handle_start(message):
        _set_manager_chat(message.chat.id)
        bot.reply_to(
            message,
            "✅ **Telegram control linked.**\n"
            "Use /help for commands."
        )

    @bot.message_handler(commands=['help'])
    def handle_help(message):
        bot.reply_to(
            message,
            "📋 **Available Commands:**\n\n"
            "🏫 /rooms - List all configured classrooms\n"
            "🔍 /status <room_id> - View live telemetry & health\n"
            "🎮 /control <room_id> <device> <action> - Send manual command\n\n"
            "**Supported Devices:**\n"
            "❄️ `ac`, 🌬️ `ventilation`, 💡 `lamp_front`, 💡 `lamp_back`\n\n"
            "**Supported Actions:**\n"
            "🔹 AC: `ON`, `OFF`, `LOW`, `MEDIUM`, `HIGH`, `PRECOOL`\n"
            "🔹 Vent: `OPEN`, `CLOSE`\n"
            "🔹 Lamp: `ON`, `OFF`\n\n"
            "🔔 /alerts - Show current system alerts\n"
            "🔇 /mute <room_id> [mins] - Silence a room\n"
            "🔊 /unmute <room_id> - Restore room alerts\n"
            "📊 /report - Generate an instant system summary\n"
            "⚙️ /settings report_time <HH:MM> - Set daily report time"
        )

    @bot.message_handler(commands=['rooms'])
    def handle_rooms(message):
        rooms_map = _load_classrooms_map()
        rooms = sorted([rid for rid in rooms_map.keys() if rid])
        if not rooms:
            bot.reply_to(message, "No classrooms configured.")
            return
        bot.reply_to(message, "Classrooms:\n" + "\n".join(f"- {rid}" for rid in rooms))

    @bot.message_handler(commands=['status'])
    def handle_status(message):
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            bot.reply_to(message, "⌨️ Usage: /status <room_id>")
            return
        room_id = parts[1].strip()
        bot.reply_to(message, _format_room_status(room_id))

    @bot.message_handler(commands=['alerts'])
    def handle_alerts(message):
        data = _api_get("/api/alerts") or {}
        alerts = data.get("alerts", []) if isinstance(data, dict) else []
        if not alerts:
            bot.reply_to(message, "✅ No active alerts.")
            return
        lines = [_format_alert(a) for a in alerts[:10]]
        bot.reply_to(message, "🔔 **Current Alerts:**\n" + "\n".join(lines))

    @bot.message_handler(commands=['control'])
    def handle_control(message):
        parts = (message.text or "").split()
        if len(parts) < 4:
            bot.reply_to(message, "⌨️ Usage: /control <room_id> <device> <action>")
            return

        room_id = parts[1].strip()
        device = parts[2].strip().lower().replace("/", "_")  # Change / to _ for lamp/front -> lamp_front
        action = parts[3].strip().upper()

        valid_devices = {"ac", "ventilation", "lamp_front", "lamp_back"}
        if device not in valid_devices:
            bot.reply_to(message, "❌ Invalid device. Use: ac, ventilation, lamp_front, lamp_back")
            return

        status_code, payload = _api_post_form(
            "/api/control",
            {"room_id": room_id, "device": device, "action": action}
        )
        if status_code == 200:
            bot.reply_to(message, f"✅ **Command sent:** {room_id} {device} {action}")
            return

        err = payload.get("error") if isinstance(payload, dict) else "Unknown error"
        bot.reply_to(message, f"❌ **Command failed ({status_code}):** {err}")

    @bot.message_handler(commands=['mute'])
    def handle_mute(message):
        parts = (message.text or "").split()
        if len(parts) < 2:
            bot.reply_to(message, "⌨️ Usage: /mute <room_id> [duration_minutes]\nExample: /mute room001 60")
            return
            
        room_id = parts[1].strip()
        duration_mins = 60  # Default to 1 hour
        if len(parts) >= 3:
            try:
                duration_mins = int(parts[2].strip())
            except ValueError:
                bot.reply_to(message, "Duration must be an integer (minutes).")
                return
                
        muted_rooms[room_id] = time.time() + (duration_mins * 60)
        bot.reply_to(message, f"🔇 Alerts for {room_id} are muted for {duration_mins} minutes.")

    @bot.message_handler(commands=['unmute'])
    def handle_unmute(message):
        parts = (message.text or "").split()
        if len(parts) < 2:
            bot.reply_to(message, "⌨️ Usage: /unmute <room_id>")
            return
        room_id = parts[1].strip()
        muted_rooms.pop(room_id, None)
        bot.reply_to(message, f"🔊 Alerts for {room_id} have been unmuted.")

    @bot.message_handler(commands=['settings'])
    def handle_settings(message):
        global daily_report_time
        parts = (message.text or "").split()
        if len(parts) < 3:
            bot.reply_to(message, "⌨️ Usage: /settings report_time HH:MM\nExample: /settings report_time 08:00")
            return
            
        setting_key = parts[1].lower()
        setting_val = parts[2]
        
        if setting_key == "report_time":
            try:
                datetime.strptime(setting_val, "%H:%M")
                daily_report_time = setting_val
                _api_post_json("/api/settings", {"report_time": setting_val})
                bot.reply_to(message, f"✅ Daily report time updated to {daily_report_time}.")
            except ValueError:
                bot.reply_to(message, "⚠️ Invalid time format. Use HH:MM (24-hour format).")
        else:
            bot.reply_to(message, f"⚠️ Unknown setting: {setting_key}")

    @bot.message_handler(commands=['report'])
    def handle_report(message):
        msg = bot.reply_to(message, "⏳ Generating report, please wait...")
        report_text = _generate_report_text()
        bot.edit_message_text(report_text, chat_id=message.chat.id, message_id=msg.message_id, parse_mode="Markdown")

def alert_polling_loop():
    seen_alerts = set()
    while True:
        time.sleep(15)  # Poll for new alerts every 15 seconds
        if not _get_manager_chat():
            continue  # Wait until someone types /start to set the manager_chat_id
            
        data = _api_get("/api/alerts") or {}
        alerts = data.get("alerts", []) if isinstance(data, dict) else []
        
        for a in reversed(alerts):  # Process oldest to newest
            room_id = str(a.get('room_id') or "-")
            sig = f"{room_id}_{a.get('type')}_{a.get('timestamp')}"
            if sig not in seen_alerts:
                seen_alerts.add(sig)
                if len(seen_alerts) > 1000:
                    seen_alerts.clear()  # Prevent unbounded memory growth
                
                if time.time() < muted_rooms.get(room_id, 0):
                    continue  # Skip broadcasting, but it remains in seen_alerts
                
                msg = _format_alert(a)
                _send_manager_message(f"⚠️ AUTOMATIC ALERT ⚠️\n{msg}")


def daily_report_loop():
    global daily_report_time
    last_report_date = None
    
    settings = _api_get("/api/settings") or {}
    if "report_time" in settings:
        daily_report_time = settings["report_time"]
        
    while True:
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        # Send the report dynamically based on the configured daily_report_time
        if current_time == daily_report_time and now.date() != last_report_date:
            if _get_manager_chat():
                report_text = _generate_report_text()
                _send_manager_message(f"🌅 *Good Morning!*\nHere is your daily {daily_report_time} summary:\n\n{report_text}")
                last_report_date = now.date()
        time.sleep(30)  # Check the time every 30 seconds

if __name__ == "__main__":
    if not TOKEN:
        print("WARN: TELEGRAM_TOKEN not set. Bot disabled.")
    else:
        print("Starting Telegram background loops and Flask server...", flush=True)
        threading.Thread(target=alert_polling_loop, daemon=True).start()
        threading.Thread(target=daily_report_loop, daemon=True).start()
        
        # Start Flask in a thread to receive direct alerts
        threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5004), daemon=True).start()
        
        print("Starting Telegram bot polling...", flush=True)
        bot.infinity_polling(timeout=30, long_polling_timeout=30)