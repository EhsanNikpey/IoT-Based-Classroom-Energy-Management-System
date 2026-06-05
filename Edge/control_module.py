import paho.mqtt.client as mqtt
import json, time, os, signal, sys, threading

BROKER = os.getenv("MQTT_BROKER", "localhost").strip()
ROOM_ID = os.getenv("ROOM_ID", "classroom1").strip()
DEFAULT_AC_PRECOOL_TEMP = int(os.getenv("DEFAULT_AC_PRECOOL_TEMP", "21").strip())
THRESHOLD_BASE = float(os.getenv("THRESHOLD_BASE", "24.0").strip())
HOLDUP_BAND = float(os.getenv("HOLDUP_BAND", "1.5").strip())
MANUAL_MODE_HOLD_SECONDS = int(os.getenv("MANUAL_MODE_HOLD_SECONDS", "120").strip())
EVAL_FAST = int(os.getenv("EVAL_INTERVAL_FAST", "1").strip())
EVAL_MEDIUM = int(os.getenv("EVAL_INTERVAL_MEDIUM", "3").strip())
EVAL_SLOW = int(os.getenv("EVAL_INTERVAL_SLOW", "10").strip())
OCC_HIGH = int(os.getenv("OCCUPANCY_HIGH_THRESHOLD", "20").strip())

state = {
    "last_motion_time": time.time(),
    "lamp_front_is_on": False,
    "lamp_back_is_on": False,
    "lamp_front_manual": None,
    "lamp_back_manual": None,
    "ac_is_on": False,
    "ac_fan_speed": "LOW",
    "ac_custom_state": None,
    "current_temp": 25.0,
    "current_motion": 0,
    "current_occupancy": 0,
    "last_occupancy_update": 0,
    "is_scheduled": False,
    "schedule_start_time": 0,
    "ac_precool_active": False,
    "ac_precool_source": None,
    "ac_precool_target_temp": DEFAULT_AC_PRECOOL_TEMP,
    "ac_precool_expires": 0,
    "ventilation_suggested": False,
    "ventilation_active": False,
    "outside_temp": 25.0,
    "outside_temp_updated": 0,
    "ventilation_cooldown_period": 0,
    "last_state_report": 0,
    "threshold_base": THRESHOLD_BASE,
    "holdup_band": HOLDUP_BAND,
    "last_manual_command_time": 0,
    "system_mode": "predictive",
    "ac_on_since": 0,
    "ac_duty_off_until": 0,
    "ac_manual_override": False,
    "ac_manual_target": None,
    "ventilation_manual_override": False
}

running = True
state_lock = threading.RLock()

def locked_action(func):
    def wrapper(*args, **kwargs):
        with state_lock:
            return func(*args, **kwargs)
    return wrapper

def signal_handler(sig, frame):
    global running
    print("🛑 Shutting down controller...", flush=True)
    running = False

def log_manual_command(topic, payload):
    state["last_manual_command_time"] = time.time()
    print(f"🖐️ Received manual command on {topic}: {payload}", flush=True)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ==================== RULE RESOLVERS ====================
def resolve_manual_rule(client, ctx, resolved):
    manual_recent = ctx["manual_recent"]

    # 1. Manual AC latch (highest priority while fresh)
    if state.get("ac_manual_override") and manual_recent and not state["ac_precool_active"]:
        target = str(state.get("ac_manual_target") or "OFF").upper()
        if state["ventilation_active"]:
            state["ventilation_active"] = False
            state["ventilation_cooldown_period"] = time.time() + 300
            client.publish(f"{ROOM_ID}/ventilation/state", "CLOSED", retain=True)

        if target == "OFF":
            if state["ac_is_on"]:
                state["ac_is_on"] = False
                state["ac_fan_speed"] = "LOW"
                client.publish(f"{ROOM_ID}/ac/state", json.dumps({"status": "OFF", "reason": "MANUAL_OVERRIDE"}), retain=True)
        else:
            desired_fan = "HIGH" if target == "ON" else (target if target in {"LOW", "MEDIUM", "HIGH"} else "HIGH")
            should_publish = (not state["ac_is_on"]) or (state["ac_fan_speed"] != desired_fan)
            state["ac_is_on"] = True
            state["ac_fan_speed"] = desired_fan
            if should_publish:
                if not state["ac_on_since"]: state["ac_on_since"] = time.time()
                client.publish(f"{ROOM_ID}/ac/state", json.dumps({"status": "ON", "temp": DEFAULT_AC_PRECOOL_TEMP, "fan": desired_fan, "reason": "MANUAL_OVERRIDE"}), retain=True)
        resolved["ac"] = True

    # 2. Manual AC Custom State vs Auto Ventilation
    if state["ac_custom_state"] is not None:
        fresh_weather = (time.time() - state["outside_temp_updated"]) < 7200
        diff = state["current_temp"] - state["outside_temp"]
        cooldown_ok = time.time() > state["ventilation_cooldown_period"]

        if manual_recent: use_vent = False
        else:
            desired_vent = (fresh_weather and state["ventilation_suggested"] and diff > 2.0 and 
                            state["current_temp"] > 24.0 and state["outside_temp"] < 26.0)
            use_vent = desired_vent if cooldown_ok else state["ventilation_active"]

        if use_vent:
            print("🌬️ Ventilation overriding manual AC for free cooling ", flush=True)
            state["ac_custom_state"] = None
        resolved["ac"] = True
        resolved["vent"] = True

    # 3. Manual Ventilation
    if state.get("ventilation_manual_override") and manual_recent:
        desired_vent = state["ventilation_suggested"]
        state["ventilation_active"] = desired_vent
        state["ventilation_cooldown_period"] = time.time() + 300
        client.publish(f"{ROOM_ID}/ventilation/state", "OPEN" if desired_vent else "CLOSED", retain=True)
        #print(f"🌬️ Manual Vent Physical Command: {'OPENING' if desired_vent else 'CLOSING'} ", flush=True)
        resolved["vent"] = True

def resolve_precool_rule(client, ctx, resolved):
    if resolved["ac"]: return
    if state["ac_precool_active"]:
        if time.time() > state["ac_precool_expires"] + 300:
            print("⚠️ Precool safety timeout hit. Forcing OFF. ", flush=True)
            state["ac_precool_active"] = False; state["ac_precool_source"] = None; state["ac_is_on"] = False; state["ac_fan_speed"] = "LOW"; state["ac_custom_state"] = None
        if state["is_scheduled"]:
            state["ac_precool_active"] = False; state["ac_precool_source"] = None; state["ac_custom_state"] = None
            print("🔄 Precool ended, returning control to automation. ", flush=True)
        elif state["current_temp"] > state["ac_precool_target_temp"]:
            if not state["ac_is_on"]:
                state["ac_is_on"] = True; state["ac_on_since"] = time.time(); state["ac_fan_speed"] = "HIGH"
            client.publish(f"{ROOM_ID}/ac/state", json.dumps({"status": "PRECOOL", "target": state["ac_precool_target_temp"]}), retain=True)
        else:
            state["ac_is_on"] = False
            client.publish(f"{ROOM_ID}/ac/state", json.dumps({"status": "OFF", "reason": "PRECOOL_REACHED"}), retain=True)
        resolved["ac"] = True; resolved["vent"] = True

def resolve_predictive_rule(client, ctx, resolved):
    occupied = ctx["occupied"]
    timeout = ctx["timeout"]
    time_empty = ctx["time_empty"]
    threshold_on = ctx["threshold_on"]
    threshold_off = ctx["threshold_off"]
    manual_recent = ctx["manual_recent"]

    #print(f"🔍 [PRED] Entering. Resolved={resolved}, Occupied={occupied}, Scheduled={state['is_scheduled']}", flush=True)

    # Lamps Logic
    if not resolved["lamps"]:
        #print(f"🔍 [LAMP] Evaluating. Current Front={state['lamp_front_is_on']}, Back={state['lamp_back_is_on']}", flush=True)
        if occupied or state["is_scheduled"]:
            desired_front = state.get("lamp_front_manual") if state.get("lamp_front_manual") is not None else True
            desired_back = state.get("lamp_back_manual") if state.get("lamp_back_manual") is not None else True
            #print(f"🔍 [LAMP] Occupied/Scheduled. Desired Front={desired_front}, Back={desired_back}", flush=True)

            if state["lamp_front_is_on"] != desired_front:
                client.publish(f"{ROOM_ID}/lamp/front/state", "ON" if desired_front else "OFF", retain=True)
                state["lamp_front_is_on"] = desired_front
                #print("💡 [LAMP] Publishing Front ON ", flush=True)
            if state["lamp_back_is_on"] != desired_back:
                client.publish(f"{ROOM_ID}/lamp/back/state", "ON" if desired_back else "OFF", retain=True)
                state["lamp_back_is_on"] = desired_back
                #print("💡 [LAMP] Publishing Back ON ", flush=True)
        elif time_empty > timeout:
            state["lamp_front_manual"] = None
            state["lamp_back_manual"] = None
            if state["lamp_front_is_on"]:
                client.publish(f"{ROOM_ID}/lamp/front/state", "OFF", retain=True)
                state["lamp_front_is_on"] = False
            if state["lamp_back_is_on"]:
                client.publish(f"{ROOM_ID}/lamp/back/state", "OFF", retain=True)
                state["lamp_back_is_on"] = False
        resolved["lamps"] = True

    if resolved["ac"] and resolved["vent"]: return

    # Ventilation vs AC Balance
    if not resolved["vent"]:
        fresh_weather = (time.time() - state["outside_temp_updated"]) < 7200
        diff = state["current_temp"] - state["outside_temp"]
        cooldown_ok = time.time() > state["ventilation_cooldown_period"]
        desired_vent = (fresh_weather and state["ventilation_suggested"] and diff > 2.0 and
                        state["current_temp"] > 24.0 and state["outside_temp"] < 26.0)
        use_vent = desired_vent if cooldown_ok else state["ventilation_active"]
    else: use_vent = state["ventilation_active"]

    if use_vent:
        if not state["ventilation_active"]:
            state["ventilation_active"] = True
            state["ventilation_cooldown_period"] = time.time() + 300
            client.publish(f"{ROOM_ID}/ventilation/state", "OPEN", retain=True)
        if state["ac_is_on"]:
            state["ac_is_on"] = False; state["ac_fan_speed"] = "LOW"
            client.publish(f"{ROOM_ID}/ac/state", json.dumps({"status": "OFF", "reason": "VENT_ACTIVE"}), retain=True)
    else:
        if state["ventilation_active"] and not resolved["vent"]:
            state["ventilation_active"] = False
            state["ventilation_cooldown_period"] = time.time() + 300
            client.publish(f"{ROOM_ID}/ventilation/state", "CLOSED", retain=True)
        if not resolved["ac"] and not state.get("ac_manual_override") and not use_vent:
            if occupied or state["is_scheduled"]:
                if not state["ac_is_on"] and state["current_temp"] > threshold_on:
                    if time.time() > state["ac_duty_off_until"]:
                        state["ac_is_on"] = True; state["ac_on_since"] = time.time()
                        state["ac_fan_speed"] = "HIGH" if state["current_occupancy"] > OCC_HIGH else ("MEDIUM" if state["current_occupancy"] > 10 else "LOW")
                        client.publish(f"{ROOM_ID}/ac/state", json.dumps({"status": "ON", "temp": DEFAULT_AC_PRECOOL_TEMP, "fan": state["ac_fan_speed"]}), retain=True)
                elif state["ac_is_on"]:
                    if state["current_temp"] < threshold_off:
                        state["ac_is_on"] = False; state["ac_fan_speed"] = "LOW"
                        client.publish(f"{ROOM_ID}/ac/state", json.dumps({"status": "OFF"}), retain=True)
                    elif time.time() - state["ac_on_since"] >= 1200:
                        print("⏳ Duty Cycle: AC max continuous run-time reached. Resting compressor for 5 mins. ", flush=True)
                        state["ac_is_on"] = False; state["ac_fan_speed"] = "LOW"
                        state["ac_duty_off_until"] = time.time() + 300
                        client.publish(f"{ROOM_ID}/ac/state", json.dumps({"status": "OFF", "reason": "DUTY_CYCLE"}), retain=True)
            elif time_empty > timeout and state["ac_is_on"]:
                state["ac_is_on"] = False; state["ac_fan_speed"] = "LOW"
                client.publish(f"{ROOM_ID}/ac/state", json.dumps({"status": "OFF"}), retain=True)

# ==================== MAIN EVALUATION LOOP ====================
@locked_action
def evaluate_logic(client):
    occ_fresh = (time.time() - state["last_occupancy_update"]) < 360
    occupied = state["current_motion"] == 1 or (state["current_occupancy"] > 0 and occ_fresh)
    timeout = 300 if state["is_scheduled"] else 15
    holdup = state["holdup_band"] * (0.8 if state["is_scheduled"] else 1.0) + min(state["current_occupancy"]*0.05, 2.0)
    adaptive_base = state["threshold_base"]
    if state["outside_temp"] > 32.0: adaptive_base += 1.5
    elif state["outside_temp"] < 15.0: adaptive_base -= 1.0
        
    threshold_on = adaptive_base + (holdup/2)
    threshold_off = adaptive_base - (holdup/2)
    time_empty = time.time() - state["last_motion_time"]

    if occupied or state["is_scheduled"]:
        state["last_motion_time"] = time.time()

    manual_recent = (time.time() - state.get("last_manual_command_time", 0)) <= MANUAL_MODE_HOLD_SECONDS

    # 🔍 FIX: Clear manual lamp overrides when manual hold window expires
    if not manual_recent:
        if state.get("lamp_front_manual") is not None:
            state["lamp_front_manual"] = None
        if state.get("lamp_back_manual") is not None:
            state["lamp_back_manual"] = None

    #print(f"🔍 [EVAL] Occupied={occupied} | Motion={state['current_motion']} Occ={state['current_occupancy']} OccFresh={occ_fresh}", flush=True)
    #print(f"🔍 [EVAL] ManualRecent={manual_recent} | LastCmdTime={state.get('last_manual_command_time',0)} | Mode={state['system_mode']}", flush=True)

    # Expire manual latch only if window elapses AND room is empty
    if not manual_recent and not occupied and state.get("ac_manual_override"):
        print("🔄 Manual hold expired + Room empty → clearing Manual Latch ", flush=True)
        state["ac_manual_override"] = False
        state["ventilation_manual_override"] = False
        state["ac_manual_target"] = None

    # Mode Tracking & Auto-Revert
    if state["system_mode"] == "manual" and not occupied and not manual_recent and not state["is_scheduled"]:
        print("🔄 Room empty + Manual window closed → reverting to Predictive mode ", flush=True)
        state["ac_custom_state"] = None
        state["ac_is_on"] = False
        state["ac_fan_speed"] = "LOW"
        state["system_mode"] = "predictive"
        client.publish(f"{ROOM_ID}/ac/state", json.dumps({"status": "OFF", "reason": "AUTO_REVERT_IDLE"}), retain=True)

    if state["ac_precool_active"]:
        source = str(state.get("ac_precool_source") or "schedule").lower()
        state["system_mode"] = "manual" if source == "manual" else "scheduled_precool"
    elif manual_recent or (state.get("ac_manual_override") and manual_recent) or state["ac_custom_state"] is not None:
        state["system_mode"] = "manual"
    else:
        state["system_mode"] = "predictive"

    ctx = {"occupied": occupied, "timeout": timeout, "time_empty": time_empty, "threshold_on": threshold_on, "threshold_off": threshold_off, "manual_recent": manual_recent}
    resolved = {"ac": False, "vent": False, "lamps": False}

    resolve_manual_rule(client, ctx, resolved)
    resolve_precool_rule(client, ctx, resolved)
    resolve_predictive_rule(client, ctx, resolved)

    now = time.time()
    if now - state.get("last_state_report", 0) >= 5:
        ac_status = json.dumps({"status": "ON", "fan": state["ac_fan_speed"]}) if state["ac_is_on"] else json.dumps({"status": "OFF"})
        lamp_front_status = "ON" if state["lamp_front_is_on"] else "OFF"
        lamp_back_status = "ON" if state["lamp_back_is_on"] else "OFF"
        lamp_status = "ON" if (state["lamp_front_is_on"] or state["lamp_back_is_on"]) else "OFF"
        vent_status = "OPEN" if state["ventilation_active"] else "CLOSED"
        ac_on = bool(state["ac_is_on"])
        ac_fan = state["ac_fan_speed"] if ac_on else "OFF"

        print(f"🎛️ Control Data - AC: {'ON' if ac_on else 'OFF'} | Fan: {ac_fan} | Lamps: Front={lamp_front_status}, Back={lamp_back_status} | Vent: {vent_status} | Mode: {state['system_mode'].upper()} ", flush=True)
        client.publish(f"{ROOM_ID}/state/history", json.dumps({"motion": state["current_motion"], "occupancy_count": state["current_occupancy"], "temperature": state["current_temp"], "outside_temp": state["outside_temp"], "lamp_state": lamp_status, "lamp_front_state": lamp_front_status, "lamp_back_state": lamp_back_status, "ac_state": ac_status, "system_mode": state["system_mode"]}))
        state["last_state_report"] = now

# ==================== MQTT HANDLERS ====================
@locked_action
def on_message(client, userdata, msg):
    topic = msg.topic.strip()
    try: payload = msg.payload.decode().strip()
    except: return

    if topic == "system/discover":
        client.publish(f"system/discover/{ROOM_ID}/response", json.dumps({"room_id": ROOM_ID, "type": "controller", "status": "online"}), retain=False); return
    if topic == f"{ROOM_ID}/request_state":
        ac_val = json.dumps({"status": "ON", "temp": DEFAULT_AC_PRECOOL_TEMP, "fan": state["ac_fan_speed"]}) if state["ac_is_on"] else json.dumps({"status": "OFF"})
        client.publish(f"{ROOM_ID}/ac/state", ac_val, retain=True)
        client.publish(f"{ROOM_ID}/lamp/front/state", "ON" if state["lamp_front_is_on"] else "OFF", retain=True)
        client.publish(f"{ROOM_ID}/lamp/back/state", "ON" if state["lamp_back_is_on"] else "OFF", retain=True); return
    if topic == f"{ROOM_ID}/config/threshold":
        try:
            cfg = json.loads(payload)
            if "base" in cfg: state["threshold_base"] = float(cfg["base"])
            if "holdup" in cfg: state["holdup_band"] = float(cfg["holdup"])
        except: pass; return
    if topic == f"{ROOM_ID}/ac/control":
        log_manual_command(topic, payload); command = payload.upper(); state["ac_manual_override"] = True; state["ac_manual_target"] = command
        if command == "OFF": state["ac_is_on"] = False; state["ac_fan_speed"] = "LOW"; state["ac_custom_state"] = None; state["ac_precool_active"] = False; state["ac_precool_source"] = None
        elif command in {"LOW", "MEDIUM", "HIGH"}:
            state["ac_fan_speed"] = command; state["ac_is_on"] = True; state["ac_on_since"] = time.time() if not state["ac_is_on"] else state["ac_on_since"]; state["ac_custom_state"] = None; state["ac_precool_active"] = False; state["ac_precool_source"] = None
        else:
            state["ac_is_on"] = True; state["ac_on_since"] = time.time() if not state["ac_is_on"] else state["ac_on_since"]; state["ac_fan_speed"] = "HIGH" if command == "ON" else state["ac_fan_speed"]; state["ac_custom_state"] = None; state["ac_precool_active"] = False; state["ac_precool_source"] = None
        client.publish(f"{ROOM_ID}/control/ack", json.dumps({"device": "ac", "action": command, "status": "executed"}))
        if command == "OFF": ac_payload = json.dumps({"status": "OFF", "reason": "MANUAL_OVERRIDE"})
        else: ac_payload = json.dumps({"status": "ON", "temp": DEFAULT_AC_PRECOOL_TEMP, "fan": command if command in {"LOW","MEDIUM","HIGH"} else "HIGH", "reason": "MANUAL_OVERRIDE"})
        client.publish(f"{ROOM_ID}/ac/state", ac_payload, retain=True); evaluate_logic(client); return
    if topic == f"{ROOM_ID}/ac/precool":
        try:
            data = json.loads(payload)
            target = data.get("target_temp", DEFAULT_AC_PRECOOL_TEMP)
            source = str(data.get("source", "schedule")).strip().lower() or "schedule"
            if source not in {"manual", "schedule"}: source = "schedule"
            if source == "manual": log_manual_command(topic, payload)
            if state["current_temp"] <= target:
                print("⚠️ Precool skipped ", flush=True)
                client.publish(f"{ROOM_ID}/control/ack", json.dumps({"device": "ac", "action": "PRECOOL", "status": "skipped", "reason": "already_below_target", "source": source})); return
            state["ac_precool_active"] = True; state["ac_precool_source"] = source; state["ac_manual_override"] = False; state["ac_manual_target"] = None; state["ac_custom_state"] = None
            state["ac_precool_target_temp"] = target; state["ac_precool_expires"] = time.time() + (data.get("duration_minutes", 15) * 60)
            state["ac_is_on"] = True; state["ac_fan_speed"] = "HIGH"
            client.publish(f"{ROOM_ID}/ac/state", json.dumps({"status": "PRECOOL", "target": target, "expires": state["ac_precool_expires"], "source": source}), retain=True)
            client.publish(f"{ROOM_ID}/control/ack", json.dumps({"device": "ac", "action": "PRECOOL", "status": "executed", "target": target, "source": source}))
        except Exception as e: client.publish(f"{ROOM_ID}/control/ack", json.dumps({"device": "ac", "action": "PRECOOL", "status": "failed", "error": str(e)}))
        evaluate_logic(client); return
    if topic == f"{ROOM_ID}/ventilation/suggest":
        try:
            d = json.loads(payload); log_manual_command(topic, payload)
            state["ventilation_manual_override"] = True; state["ventilation_suggested"] = (d.get("action") == "activate")
            evaluate_logic(client)
            client.publish(f"{ROOM_ID}/control/ack", json.dumps({"device": "ventilation", "action": "OPEN" if state["ventilation_suggested"] else "CLOSE", "status": "executed"}))
        except: pass; return
    if "lamp" in topic and topic.endswith("/control"):
        log_manual_command(topic, payload)
        dev = topic.split("/")[-2]; action = str(payload).strip().upper(); val = action == "ON"
        if dev == "front": state["lamp_front_is_on"] = val; state["lamp_front_manual"] = val
        elif dev == "back": state["lamp_back_is_on"] = val; state["lamp_back_manual"] = val
        client.publish(f"{ROOM_ID}/lamp/{dev}/state", action, retain=True)
        client.publish(f"{ROOM_ID}/control/ack", json.dumps({"device": f"lamp/{dev}", "action": action, "status": "executed"})); evaluate_logic(client); return
    if topic == "system/weather":
        try:
            d = json.loads(payload)
            out_t = d.get("outside_temp", d.get("outside_temperature"))
            if out_t is not None: state["outside_temp"] = float(out_t); state["outside_temp_updated"] = time.time(); evaluate_logic(client)
        except: pass; return
    if topic == f"{ROOM_ID}/sensors":
        try:
            d = json.loads(payload)
            state["current_motion"] = d.get("motion", 0) if isinstance(d, dict) else (d if isinstance(d, int) else 0)
            state["current_temp"] = d.get("temperature", 25.0) if isinstance(d, dict) else 25.0
            if state["current_motion"] == 1: state["last_motion_time"] = time.time()
            evaluate_logic(client)
        except Exception as e: print(f"⚠️ Sensor Parse Error: {e} | Payload: {payload}", flush=True); return
    if topic == f"{ROOM_ID}/schedule":
        state["is_scheduled"] = payload.upper() == "ON"
        if state["is_scheduled"]: state["schedule_start_time"] = time.time()
        return
    if topic == f"{ROOM_ID}/camera/occupancy":
        try:
            #print(f"🔍 [CAM] Raw Payload: {payload}", flush=True)
            d = json.loads(payload)
            occ = d if isinstance(d, int) else (d.get("occupancy_count", d.get("count", d.get("people", 0))) if isinstance(d, dict) else 0)
            state["current_occupancy"] = max(0, occ)
            state["last_occupancy_update"] = time.time()
            #print(f"🔍 [CAM] Updated Occupancy: {state['current_occupancy']} (OccFresh={(time.time() - state['last_occupancy_update']) < 360})", flush=True)
            evaluate_logic(client)
        except Exception as e: print(f"⚠️ [CAM] Parse Error: {e} | Payload: {payload}", flush=True); return

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"✅ Connected to Central ({BROKER}) ", flush=True)
        client.subscribe([("system/discover", 0), ("system/weather", 0), (f"{ROOM_ID}/request_state", 0), (f"{ROOM_ID}/sensors", 0), (f"{ROOM_ID}/camera/occupancy", 0), (f"{ROOM_ID}/ac/control", 0), (f"{ROOM_ID}/ac/precool", 0), (f"{ROOM_ID}/lamp/+/control", 0), (f"{ROOM_ID}/config/threshold", 0), (f"{ROOM_ID}/schedule", 0), (f"{ROOM_ID}/ventilation/suggest", 0)])
        print("📡 Subscribed to control topics ", flush=True)
    else: print(f"⚠️ Failed to connect to Central ({BROKER}), rc={rc} ", flush=True)

def on_disconnect(client, userdata, rc):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    if rc == 0: print(f"[{ts}] 🔌 Disconnected from Central ({BROKER})", flush=True)
    else: print(f"[{ts}] ⚠️ Lost connection to Central ({BROKER}), reconnecting... (rc={rc})", flush=True)

def on_log(client, userdata, level, buf):
    if "retrying" in buf.lower() or "reconnect" in buf.lower() or "connection refused" in buf.lower() or "socket error" in buf.lower():
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] 🔄 MQTT Paho Internal: {buf}", flush=True)

if __name__ == "__main__":
    client = mqtt.Client(f"{ROOM_ID}_Control")
    client.on_message = on_message
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_log = on_log
    client.reconnect_delay_set(min_delay=1, max_delay=120)
    while running:
        try: client.connect(BROKER); client.loop_start(); break
        except Exception as e: print(f"❌ MQTT failed: {e}. Retrying in 5s...", flush=True); time.sleep(5)

    while running:
        evaluate_logic(client)
        time_empty = time.time() - state["last_motion_time"]
        if state["current_motion"] == 1: time.sleep(EVAL_FAST)
        elif time_empty < 60: time.sleep(EVAL_MEDIUM)
        else: time.sleep(EVAL_SLOW)       
    client.loop_stop(); client.disconnect()