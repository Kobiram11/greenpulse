"""Read-only weather and mailbox retrieval. No message sending or marking read."""
import email
from email import policy
from email.header import decode_header, make_header
import imaplib
import os
import re
import time
from datetime import datetime, timedelta, timezone


class Context:
    def __init__(self):
        self.cache = {}

    def cached(self, key, fn):
        entry = self.cache.get(key)
        if entry and time.monotonic() - entry[0] < 600:
            return entry[1]
        try:
            result = fn()
        except Exception:
            result = {"status": "unavailable", "reason": f"{key} retrieval failed"}
        self.cache[key] = (time.monotonic(), result)
        return result

    def weather(self):
        def fetch():
            import requests
            lat, lon = os.getenv("WEATHER_LATITUDE"), os.getenv("WEATHER_LONGITUDE")
            if not lat or not lon:
                return {"status": "not_configured"}
            if not -90 <= float(lat) <= 90 or not -180 <= float(lon) <= 180:
                return {"status": "unavailable", "reason": "Invalid coordinates"}
            response = requests.get("https://api.open-meteo.com/v1/forecast", timeout=10,
                params={"latitude": lat, "longitude": lon, "timezone": "UTC",
                        "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code"})
            response.raise_for_status()
            data = response.json()
            return {"status": "ok", "source": "Open-Meteo", "fetched_ts": int(time.time()),
                    "current": data.get("current"), "units": data.get("current_units")}
        return self.cached("weather", fetch)

    def mailbox(self):
        def fetch():
            if os.getenv("EMAIL_ENABLED", "false").lower() != "true":
                return {"status": "not_configured", "messages": []}
            host, user, password = (os.getenv(k) for k in
                                    ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD"))
            if not all((host, user, password)):
                return {"status": "not_configured", "messages": []}
            keywords = [k.strip().lower() for k in os.getenv(
                "EMAIL_KEYWORDS", "plant,watering,garden,weather").split(",") if k.strip()]
            since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%d-%b-%Y")
            found = []
            with imaplib.IMAP4_SSL(host, timeout=10) as box:
                box.login(user, password)
                if box.select("INBOX", readonly=True)[0] != "OK":
                    raise RuntimeError("Cannot open mailbox")
                status, ids = box.uid("search", None, "SINCE", since)
                if status != "OK":
                    raise RuntimeError("Mailbox search failed")
                # Bound traffic; inspect only the newest 20 messages, return at most 5.
                for uid in reversed(ids[0].split()[-20:]):
                    status, chunks = box.uid("fetch", uid, "(BODY.PEEK[])")
                    if status != "OK":
                        continue
                    raw = next((c[1] for c in chunks if isinstance(c, tuple)), b"")
                    msg = email.message_from_bytes(raw, policy=policy.default)
                    subject = str(make_header(decode_header(str(msg.get("Subject", "")))))
                    body = msg.get_body(preferencelist=("plain", "html")) if msg.is_multipart() else msg
                    text = body.get_content() if body else ""
                    if not isinstance(text, str):
                        text = ""
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"\s+", " ", text)[:1200]
                    if any(k in (subject + " " + text).lower() for k in keywords):
                        found.append({"subject": subject[:160], "date": str(msg.get("Date", "")),
                                      "excerpt": text})
                    if len(found) >= 5:
                        break
            return {"status": "ok", "messages": found, "fetched_ts": int(time.time())}
        return self.cached("email", fetch)
