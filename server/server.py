"""
SoundGuard server
-----------------
1. Listens on MQTT for sound events from the audio node.
2. Takes photos (webcam or ESP32-S3 camera node).
3. Recognises faces -> name or "Unknown".
4. Saves the event in SQLite and sends a Telegram alert with the photo.
5. Shows all events on a web dashboard: http://localhost:5000

Run:  python server.py
"""

import csv
import io
import json
import os
import queue
import sqlite3
import threading
import time
from datetime import datetime

import cv2
import face_recognition
import numpy as np
import paho.mqtt.client as mqtt
import requests
from flask import Flask, Response, jsonify, send_from_directory

import config as C

os.makedirs(C.EVENTS_DIR, exist_ok=True)
os.makedirs(C.KNOWN_FACES_DIR, exist_ok=True)
event_queue = queue.Queue()


# ======================= Database =======================
def db():
    con = sqlite3.connect(C.DB_FILE)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at TEXT,
            sound_class TEXT,
            confidence REAL,
            names TEXT,
            photo TEXT,
            alert_sent INTEGER,
            processing_ms REAL,      -- server: event received -> alert sent
            end_to_end_ms REAL       -- device timestamp -> alert sent (if available)
        )""")
        # timing breakdown columns (added to older databases if missing)
        cols = [r[1] for r in con.execute("PRAGMA table_info(events)")]
        for col in ("capture_ms", "face_ms", "telegram_ms"):
            if col not in cols:
                con.execute(f"ALTER TABLE events ADD COLUMN {col} REAL")


# ======================= Faces =======================
known_encodings, known_names = [], []


def load_known_faces():
    """Each sub-folder of known_faces/ is one person, containing their photos."""
    for person in sorted(os.listdir(C.KNOWN_FACES_DIR)):
        folder = os.path.join(C.KNOWN_FACES_DIR, person)
        if not os.path.isdir(folder):
            continue
        n = 0
        for f in os.listdir(folder):
            if not f.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            img = face_recognition.load_image_file(os.path.join(folder, f))
            encs = face_recognition.face_encodings(img)
            if encs:
                known_encodings.append(encs[0])
                known_names.append(person)
                n += 1
        print(f"  enrolled {person}: {n} photo(s)")
    print(f"Known faces loaded: {len(set(known_names))} person(s)")


def recognise(frame_bgr):
    """Returns list of (name, box) for every face in the frame."""
    # detect on a smaller copy (much faster), then scale the boxes back
    scale = getattr(C, "FACE_SCALE", 0.5)
    small = cv2.resize(frame_bgr, (0, 0), fx=scale, fy=scale)
    rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    boxes = face_recognition.face_locations(rgb, model="hog")
    encs = face_recognition.face_encodings(rgb, boxes)
    boxes = [tuple(int(v / scale) for v in b) for b in boxes]
    results = []
    for enc, box in zip(encs, boxes):
        name = "Unknown"
        if known_encodings:
            dist = face_recognition.face_distance(known_encodings, enc)
            best = int(np.argmin(dist))
            if dist[best] <= C.FACE_TOLERANCE:
                name = known_names[best]
        results.append((name, box))
    return results


def draw(frame, faces):
    for name, (top, right, bottom, left) in faces:
        color = (0, 200, 0) if name != "Unknown" else (0, 0, 255)
        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
        cv2.rectangle(frame, (left, bottom), (right, bottom + 25), color, -1)
        cv2.putText(frame, name, (left + 4, bottom + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return frame


# ======================= Camera =======================
webcam = None
latest_frame = None
frame_lock = threading.Lock()


def camera_loop():
    """Reads the webcam continuously so a fresh, colour-corrected frame is always ready."""
    global latest_frame
    while True:
        ok, frame = webcam.read()
        if ok:
            with frame_lock:
                latest_frame = frame
        else:
            time.sleep(0.05)


def open_camera():
    global webcam
    if isinstance(C.CAMERA_SOURCE, int):
        webcam = cv2.VideoCapture(C.CAMERA_SOURCE, cv2.CAP_DSHOW)  # CAP_DSHOW = fast on Windows
        if not webcam.isOpened():
            print("!! Webcam could not be opened - check CAMERA_SOURCE in config.py")
            return
        threading.Thread(target=camera_loop, daemon=True).start()
        time.sleep(2)  # let auto-exposure / white balance settle
        print("Webcam ready")


def capture_photos(n):
    frames = []
    for _ in range(n):
        if isinstance(C.CAMERA_SOURCE, int):
            with frame_lock:
                frame = None if latest_frame is None else latest_frame.copy()
            if frame is not None:
                frames.append(frame)
        else:                            # ESP32-S3 camera node over HTTP
            try:
                r = requests.get(C.CAMERA_SOURCE, timeout=3)
                arr = np.frombuffer(r.content, np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    frames.append(frame)
            except requests.RequestException as e:
                print("!! camera node not reachable:", e)
        time.sleep(0.15)
    return frames


# ======================= Telegram =======================
def send_telegram(photo_path, caption):
    if "PASTE" in C.TELEGRAM_TOKEN:
        print("  (Telegram not configured - skipping)")
        return False
    url = f"https://api.telegram.org/bot{C.TELEGRAM_TOKEN}/sendPhoto"
    try:
        if photo_path:
            with open(photo_path, "rb") as f:
                r = requests.post(url, data={"chat_id": C.TELEGRAM_CHAT_ID, "caption": caption},
                                  files={"photo": f}, timeout=10)
        else:
            r = requests.post(f"https://api.telegram.org/bot{C.TELEGRAM_TOKEN}/sendMessage",
                              data={"chat_id": C.TELEGRAM_CHAT_ID, "text": caption}, timeout=10)
        if not r.ok:
            print("  !! Telegram error:", r.text)
        return r.ok
    except requests.RequestException as e:
        print("  !! Telegram not reachable:", e)
        return False


# ======================= Event handling =======================
def handle_event(evt, t_received):
    sound = str(evt.get("class", "unknown"))
    conf = float(evt.get("confidence", 0))
    print(f"\n[EVENT] {sound}  confidence={conf:.2f}")

    # 1. photos + face recognition
    t0 = time.time()
    frames = capture_photos(C.PHOTOS_PER_EVENT)
    t1 = time.time()
    names, best_frame, best_faces = set(), None, []
    for fr in frames:
        faces = recognise(fr)
        names.update(n for n, _ in faces)
        if best_frame is None or len(faces) > len(best_faces):
            best_frame, best_faces = fr, faces
    names_txt = ", ".join(sorted(names)) if names else "No face visible"
    t2 = time.time()
    print(f"  people: {names_txt}")

    photo_name = None
    if best_frame is not None:
        photo_name = datetime.now().strftime("event_%Y%m%d_%H%M%S_%f.jpg")
        cv2.imwrite(os.path.join(C.EVENTS_DIR, photo_name), draw(best_frame.copy(), best_faces))

    # 2. alert
    t3 = time.time()
    sent = False
    if conf >= C.MIN_CONFIDENCE:
        caption = (f"SoundGuard ALERT\n"
                   f"Sound: {sound.upper()}\n"
                   f"Confidence: {conf:.0%}\n"
                   f"People: {names_txt}\n"
                   f"Time: {datetime.now():%Y-%m-%d %H:%M:%S}")
        sent = send_telegram(os.path.join(C.EVENTS_DIR, photo_name) if photo_name else None, caption)
        print("  Telegram alert sent" if sent else "  Telegram alert NOT sent")
    else:
        print("  confidence below threshold - logged only")

    # 3. latency
    t_done = time.time()
    capture_ms, face_ms, telegram_ms = (t1 - t0) * 1000, (t2 - t1) * 1000, (t_done - t3) * 1000
    processing_ms = (t_done - t_received) * 1000
    end_to_end_ms = None
    ts = evt.get("timestamp")
    if isinstance(ts, (int, float)) and ts > 1e9:       # real Unix time sent by the device
        end_to_end_ms = (t_done - ts) * 1000
    print(f"  timing: capture {capture_ms:.0f} ms | faces {face_ms:.0f} ms | telegram {telegram_ms:.0f} ms")
    print(f"  processing time: {processing_ms:.0f} ms"
          + (f" | end-to-end: {end_to_end_ms:.0f} ms" if end_to_end_ms else ""))

    # 4. store
    with db() as con:
        con.execute("""INSERT INTO events (received_at, sound_class, confidence, names, photo,
                       alert_sent, processing_ms, end_to_end_ms, capture_ms, face_ms, telegram_ms)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (datetime.fromtimestamp(t_received).strftime("%Y-%m-%d %H:%M:%S"),
                     sound, conf, names_txt, photo_name, int(sent), processing_ms, end_to_end_ms,
                     capture_ms, face_ms, telegram_ms))


def worker():
    while True:
        evt, t_received = event_queue.get()
        try:
            handle_event(evt, t_received)
        except Exception as e:
            print("!! error while handling event:", e)


# ======================= MQTT =======================
def on_connect(client, userdata, flags, reason_code, properties):
    print(f"MQTT connected ({reason_code}), listening on '{C.MQTT_TOPIC}'")
    client.subscribe(C.MQTT_TOPIC)


def on_message(client, userdata, msg):
    t = time.time()
    try:
        evt = json.loads(msg.payload.decode())
    except ValueError:
        print("!! message is not valid JSON:", msg.payload[:100])
        return
    event_queue.put((evt, t))


def on_disconnect(client, userdata, flags, reason_code, properties):
    print(f"!! MQTT disconnected ({reason_code}) - retrying automatically...")


def make_mqtt_client():
    transport = getattr(C, "MQTT_TRANSPORT", "tcp")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport=transport)
    if transport == "websockets":
        client.ws_set_options(path=getattr(C, "MQTT_WS_PATH", "/mqtt"))
    return client


def start_mqtt():
    client = make_mqtt_client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=2, max_delay=30)
    print(f"Connecting to MQTT {C.MQTT_HOST}:{C.MQTT_PORT} ({getattr(C, 'MQTT_TRANSPORT', 'tcp')}) ...")
    # connect_async never crashes the server: if the broker is unreachable,
    # the dashboard still starts and the connection is retried in the background
    client.connect_async(C.MQTT_HOST, C.MQTT_PORT, keepalive=60)
    client.loop_start()


# ======================= Dashboard =======================
app = Flask(__name__)

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="5"><title>SoundGuard Dashboard</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f4f6f9;color:#1f2933}
h1{margin:0 0 4px}.sub{color:#667;margin-bottom:18px}
.cards{display:flex;gap:12px;margin-bottom:18px;flex-wrap:wrap}
.card{background:#fff;border-radius:10px;padding:12px 18px;box-shadow:0 1px 3px #0002;min-width:120px}
.card b{display:block;font-size:24px}
table{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 3px #0002}
th,td{padding:8px 10px;border-bottom:1px solid #e3e7ec;text-align:left;font-size:14px}
th{background:#1f3a5f;color:#fff}img{height:90px;border-radius:6px}
.gunshot{color:#c0392b;font-weight:600}.scream{color:#d35400;font-weight:600}
</style></head><body>
<h1>SoundGuard</h1><div class="sub">Live event log (refreshes every 5 s) &middot;
<a href="/export.csv">export CSV</a></div>
<div class="cards">{cards}</div>
<table><tr><th>#</th><th>Time</th><th>Sound</th><th>Confidence</th><th>People</th>
<th>Alert</th><th>Processing (ms)</th><th>Photo</th></tr>{rows}</table></body></html>"""


@app.route("/")
def index():
    with db() as con:
        rows = con.execute("SELECT * FROM events ORDER BY id DESC LIMIT 100").fetchall()
        total = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        alerts = con.execute("SELECT COUNT(*) FROM events WHERE alert_sent=1").fetchone()[0]
        avg = con.execute("SELECT AVG(processing_ms) FROM events").fetchone()[0]
    cards = (f'<div class="card">Events<b>{total}</b></div>'
             f'<div class="card">Alerts sent<b>{alerts}</b></div>'
             f'<div class="card">Avg. processing<b>{(avg or 0):.0f} ms</b></div>')
    html_rows = ""
    for r in rows:
        img = f'<a href="/photo/{r["photo"]}"><img src="/photo/{r["photo"]}"></a>' if r["photo"] else "-"
        html_rows += (f'<tr><td>{r["id"]}</td><td>{r["received_at"]}</td>'
                      f'<td class="{r["sound_class"]}">{r["sound_class"]}</td>'
                      f'<td>{r["confidence"]:.0%}</td><td>{r["names"]}</td>'
                      f'<td>{"yes" if r["alert_sent"] else "no"}</td>'
                      f'<td>{r["processing_ms"]:.0f}</td><td>{img}</td></tr>')
    return PAGE.replace("{cards}", cards).replace("{rows}", html_rows)


@app.route("/photo/<path:name>")
def photo(name):
    return send_from_directory(C.EVENTS_DIR, name)


@app.route("/api/events")
def api_events():
    with db() as con:
        rows = con.execute("SELECT * FROM events ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/export.csv")
def export_csv():
    with db() as con:
        rows = con.execute("SELECT * FROM events ORDER BY id").fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    if rows:
        w.writerow(rows[0].keys())
        w.writerows([tuple(r) for r in rows])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=soundguard_events.csv"})


# ======================= Main =======================
if __name__ == "__main__":
    print("SoundGuard server starting...")
    init_db()
    load_known_faces()
    open_camera()
    threading.Thread(target=worker, daemon=True).start()
    start_mqtt()
    print(f"Dashboard: http://localhost:{C.DASHBOARD_PORT}")
    app.run(host="0.0.0.0", port=C.DASHBOARD_PORT, debug=False)
