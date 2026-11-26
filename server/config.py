"""
SoundGuard server - settings.
Fill in TELEGRAM_TOKEN and TELEGRAM_CHAT_ID.
DO NOT upload this file to GitHub with your real token inside.
"""

# ---------------- Telegram ----------------
TELEGRAM_TOKEN = "PASTE_YOUR_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID = "PASTE_YOUR_CHAT_ID_HERE"   # run get_chat_id.py to find it

# ---------------- MQTT ----------------
MQTT_HOST = "broker.emqx.io"     # free public broker (run check_mqtt.py to pick one that works on your network)
MQTT_PORT = 1883
MQTT_TRANSPORT = "tcp"           # "tcp" or "websockets" (websockets works when port 1883 is blocked)
MQTT_WS_PATH = "/mqtt"           # only used with websockets
MQTT_TOPIC = "soundguard/cheick-alberic/events"

# ---------------- Camera ----------------
# 0 = laptop webcam (stand-in for the OV2640 camera node)
# or the ESP32-S3 camera URL, e.g. "http://192.168.1.50/capture"
CAMERA_SOURCE = 0
PHOTOS_PER_EVENT = 3

# ---------------- Detection rules ----------------
MIN_CONFIDENCE = 0.80            # events below this are logged but no alert is sent
FACE_TOLERANCE = 0.50            # lower = stricter matching (0.6 is the library default)

# ---------------- Storage ----------------
KNOWN_FACES_DIR = "known_faces"  # one sub-folder per consenting person: known_faces/Cheick/*.jpg
EVENTS_DIR = "events"            # photos of each event are saved here
DB_FILE = "soundguard.db"

# ---------------- Dashboard ----------------
DASHBOARD_PORT = 5000            # open http://localhost:5000
FACE_SCALE = 0.5                 # face detection on a half-size copy (faster); use 1.0 if faces are far away
