import os
from dataclasses import dataclass
from core import device_id


@dataclass
class Settings:
    endpoint: str
    device: str
    region: str
    table: str
    ca: str
    cert: str
    key: str
    interval: int
    dry: float
    warning: float

    @classmethod
    def load(cls):
        from dotenv import load_dotenv
        load_dotenv()
        required = ["AWS_IOT_ENDPOINT", "DEVICE_ID", "AWS_REGION", "DYNAMODB_TABLE",
                    "MQTT_CA_PATH", "MQTT_CERT_PATH", "MQTT_KEY_PATH"]
        missing = [key for key in required if not os.getenv(key)]
        if missing:
            raise ValueError("Configure: " + ", ".join(missing))
        for key in required[-3:]:
            if not os.path.isfile(os.environ[key]):
                raise ValueError(f"Certificate file not found: {key}")
        dry = float(os.getenv("DRY_THRESHOLD", "20"))
        warning = float(os.getenv("WARNING_THRESHOLD", "35"))
        if not 0 <= dry < warning <= 100:
            raise ValueError("Require 0 <= DRY_THRESHOLD < WARNING_THRESHOLD <= 100")
        interval = int(os.getenv("CARE_INTERVAL_SECONDS", "300"))
        if interval < 30:
            raise ValueError("CARE_INTERVAL_SECONDS must be at least 30")
        return cls(os.environ[required[0]], device_id(os.environ[required[1]]),
                   os.environ[required[2]], os.environ[required[3]],
                   *(os.environ[k] for k in required[-3:]), interval, dry, warning)
