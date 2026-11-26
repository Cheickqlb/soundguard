"""
Sends fake sound events to the server (stand-in for the audio node while the
model is not ready). Also used for the latency test in the report.

  python fake_event.py              -> one "scream" event
  python fake_event.py gunshot      -> one "gunshot" event
  python fake_event.py test 20      -> 20 random events, 8 s apart (latency test)
"""
import json
import random
import sys
import time

import paho.mqtt.client as mqtt

import config as C

transport = getattr(C, "MQTT_TRANSPORT", "tcp")
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport=transport)
if transport == "websockets":
    client.ws_set_options(path=getattr(C, "MQTT_WS_PATH", "/mqtt"))
client.connect(C.MQTT_HOST, C.MQTT_PORT)
client.loop_start()


def send(sound, conf):
    msg = {"class": sound, "confidence": round(conf, 2), "timestamp": time.time()}
    client.publish(C.MQTT_TOPIC, json.dumps(msg)).wait_for_publish()
    print("sent:", msg)


args = sys.argv[1:]
if args and args[0] == "test":
    n = int(args[1]) if len(args) > 1 else 10
    for i in range(n):
        send(random.choice(["gunshot", "scream"]), random.uniform(0.82, 0.99))
        time.sleep(8)  # leave time for photos + Telegram (avoids Telegram rate limits)
else:
    send(args[0] if args else "scream", 0.91)

time.sleep(0.5)
client.loop_stop()
