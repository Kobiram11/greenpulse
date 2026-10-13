"""MQTT subscriber, durable local spool, DynamoDB logger and care agent."""
import json
import logging
import os
import signal
import sqlite3
import threading
import time
import uuid
from ai import CareAgent
from config import Settings
from core import priority, validate_reading
from storage import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("greenpulse")


class Spool:
    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, ts INTEGER, body TEXT)")
        self.db.commit()

    def add(self, body):
        with self.lock:
            self.db.execute("INSERT INTO jobs VALUES (?, ?, ?)",
                            (uuid.uuid4().hex, int(time.time()), json.dumps(body, allow_nan=False)))
            self.db.commit()

    def first(self):
        with self.lock:
            return self.db.execute("SELECT id, ts, body FROM jobs ORDER BY ts, rowid LIMIT 1").fetchone()

    def done(self, event):
        with self.lock:
            self.db.execute("DELETE FROM jobs WHERE id=?", (event,))
            self.db.commit()


def run():
    import paho.mqtt.client as mqtt
    cfg = Settings.load()
    base = f"greenpulse/device/{cfg.device}"
    spool = Spool(os.getenv("SPOOL_PATH", "./data/spool.db"))
    store = Store(cfg.region, cfg.table)
    agent = CareAgent()
    stop = threading.Event()
    # Use a separate AWS certificate and a distinct MQTT client ID for this backend.
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id=os.getenv("MQTT_CLIENT_ID", "greenpulse-backend"))
    client.tls_set(ca_certs=cfg.ca, certfile=cfg.cert, keyfile=cfg.key)
    client.reconnect_delay_set(1, 30)

    def connected(c, userdata, flags, reason_code, properties):
        if reason_code == 0:
            log.info("MQTT connected")
            c.subscribe(base + "/sensors", qos=1)
        else:
            log.error("MQTT rejected: %s", reason_code)

    def received(c, userdata, message):
        try:
            if message.retain:
                log.warning("Ignoring retained sensor payload")
                return
            if len(message.payload) > 8192:
                raise ValueError("Sensor payload too large")
            payload = json.loads(message.payload.decode(),
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
            reading = validate_reading(payload, cfg.device)
            spool.add(reading)
        except Exception as exc:
            log.error("Sensor message not queued (%s): %s", type(exc).__name__, exc)

    client.on_connect = connected
    client.on_message = received
    client.on_disconnect = lambda c, u, f, r, p: log.warning("MQTT disconnected: %s", r)
    client.connect_async(cfg.endpoint, 8883, keepalive=60)
    client.loop_start()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    last_care = 0.0
    try:
        while not stop.is_set():
            job = spool.first()
            if job is None:
                stop.wait(0.5)
                continue
            event, received_ts, body = job
            reading = json.loads(body)
            try:
                store.put(cfg.device, event, "SENSOR", received_ts, reading)
                level, reason = priority(reading, cfg.dry, cfg.warning)
                fresh = -60 <= time.time() - reading["ts"] <= 120
                due = time.monotonic() - last_care >= cfg.interval
                if fresh and due and client.is_connected():
                    advice, inputs = agent.generate(reading, level, reason)
                    # Bound care/alerts packets for the ESP32's 4096-byte MQTT buffer.
                    for field in ("care_message", "quote", "weather_summary", "notification_summary"):
                        advice[field] = advice[field].encode("utf-8")[:500].decode("utf-8", errors="ignore")
                    now = int(time.time())
                    # Recheck freshness after external API/LLM delays.
                    level, reason = priority(reading, cfg.dry, cfg.warning, now=now)
                    if level == "unknown":
                        advice["care_message"] = reason + ". Obtain a fresh valid reading before making a care decision."
                    care = {"device_id": cfg.device, "ts": now, "expires_ts": now + 600,
                            "sensor_ts": reading["ts"], "priority": level,
                            "priority_reason": reason, **advice,
                            "context_status": {"weather": inputs["weather"]["status"],
                                               "email": inputs["email"]["status"]}}
                    alerts = {"device_id": cfg.device, "ts": now, "expires_ts": now + 600,
                              "priority": level, "priority_reason": reason,
                              "weather_summary": care["weather_summary"],
                              "notification_summary": care["notification_summary"]}
                    # Persist the exact LLM context and responses before publishing.
                    store.put(cfg.device, event, "CARE", now,
                              {"input": inputs, "output": care, "alerts": alerts})
                    # Publish the exact model input so the required dashboard can inspect it.
                    llm_input = {"device_id": cfg.device, "ts": now, "input": inputs}
                    for topic, data in (("llm-input", llm_input), ("care", care), ("alerts", alerts)):
                        info = client.publish(base + "/" + topic,
                                              json.dumps(data, allow_nan=False, ensure_ascii=False), qos=1, retain=False)
                        info.wait_for_publish(timeout=10)
                        if not info.is_published():
                            raise RuntimeError("MQTT response not acknowledged")
                    last_care = time.monotonic()
                    log.info("Care published: priority=%s llm=%s", level, care["llm_status"])
                spool.done(event)
            except Exception as exc:
                log.error("Job retained for retry (%s): %s", type(exc).__name__, exc)
                stop.wait(10)
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    run()
