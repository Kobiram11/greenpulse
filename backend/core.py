"""Dependency-free validation and deterministic care-priority rules."""
import math
import re
import time

SOIL_LIMITS = {"moisture": (0, 100), "temperature": (-40, 85),
               "ph": (0, 14), "ec": (0, 65535),
               "n": (0, 65535), "p": (0, 65535), "k": (0, 65535)}
AIR_LIMITS = {"temperature": (-40, 85), "humidity": (0, 100)}


def validate_reading(payload, expected_device):
    if not isinstance(payload, dict) or payload.get("device_id") != expected_device:
        raise ValueError("Device ID does not match configured topic")
    ts = payload.get("ts")
    if type(ts) is not int or not 1700000000 <= ts <= 4102444800:
        raise ValueError("Expected Unix timestamp in seconds")
    result = dict(payload)
    invalid = []
    for section, limits in (("soil", SOIL_LIMITS), ("air", AIR_LIMITS)):
        incoming = payload.get(section)
        if not isinstance(incoming, dict):
            raise ValueError(f"Missing {section} object")
        clean = {}
        for key, (lo, hi) in limits.items():
            value = incoming.get(key)
            if value is None:
                clean[key] = None
            elif (type(value) not in (int, float) or not math.isfinite(value)
                  or not lo <= value <= hi):
                clean[key] = None
                invalid.append(f"{section}.{key}")
            else:
                clean[key] = value
        result[section] = clean
    result["invalid_fields"] = invalid
    return result


def priority(reading, dry=20, warning=35, now=None):
    """Demo thresholds only. Adjust to your plant and calibrated soil probe."""
    now = time.time() if now is None else now
    if not -60 <= now - reading["ts"] <= 120:
        return "unknown", "Sensor timestamp is stale or in the future"
    moisture = reading["soil"]["moisture"]
    if moisture is None:
        return "unknown", "Soil moisture is unavailable; inspect the sensor"
    if moisture < dry:
        return "high", "Moisture is below the configured dry threshold; check soil before watering"
    if moisture < warning:
        return "medium", "Moisture is below the configured warning threshold; check the plant soon"
    return "low", "Moisture is above the configured warning threshold"


def device_id(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("DEVICE_ID must use 1-64 letters, numbers, underscores or hyphens")
    return value
