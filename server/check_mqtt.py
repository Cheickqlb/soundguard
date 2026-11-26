"""
Finds which public MQTT broker / port works on YOUR network.
Run:  python check_mqtt.py
Then copy the suggested lines into config.py.
"""
import threading

import paho.mqtt.client as mqtt

CANDIDATES = [
    # host,                port, transport
    ("broker.emqx.io",     1883, "tcp"),
    ("broker.hivemq.com",  1883, "tcp"),
    ("test.mosquitto.org", 1883, "tcp"),
    ("broker.emqx.io",     8083, "websockets"),
    ("broker.hivemq.com",  8000, "websockets"),
    ("test.mosquitto.org", 8080, "websockets"),
]


def try_broker(host, port, transport):
    done = threading.Event()
    result = {"ok": False}

    def on_connect(c, u, f, rc, p):
        result["ok"] = not rc.is_failure
        done.set()

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport=transport)
    if transport == "websockets":
        c.ws_set_options(path="/mqtt")
    c.on_connect = on_connect
    try:
        c.connect(host, port, keepalive=10)
        c.loop_start()
        done.wait(6)
        c.loop_stop()
        c.disconnect()
    except Exception:
        return False
    return result["ok"]


working = []
for host, port, transport in CANDIDATES:
    ok = try_broker(host, port, transport)
    print(f"{'OK     ' if ok else 'BLOCKED'}  {host}:{port} ({transport})")
    if ok:
        working.append((host, port, transport))

if working:
    host, port, transport = working[0]
    print("\nPut these lines in config.py:")
    print(f'MQTT_HOST = "{host}"')
    print(f"MQTT_PORT = {port}")
    print(f'MQTT_TRANSPORT = "{transport}"')
    print("\nTell Alberic to use host", host, "port 1883 (normal MQTT) from Wokwi,")
    print("with the same topic as MQTT_TOPIC in config.py.")
else:
    print("\nNo public broker reachable from this network.")
    print("Try another network (e.g. your phone's hotspot), or install Mosquitto locally.")
