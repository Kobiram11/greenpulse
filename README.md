# GreenPulse implementation package

This package extends your working soil-probe and DHT11 project with AWS IoT Core, a Python LangChain backend, DynamoDB logging, Node-RED, a 16x2 LCD and three priority LEDs. Your BLE app still receives exactly its original seven CSV fields with the same BLE name and UUIDs. Air readings are added to MQTT JSON, not to the BLE CSV.

Start with one milestone: real sensor readings appearing on AWS IoT Core. Then start storage, dashboard and AI in that order. The code is prepared for configuration and hardware verification; it has not been deployed to your account or tested on your physical ESP32.

## What is included

| Path | Purpose |
|---|---|
| `firmware/greenpulse/` | Combined real-sensor, BLE and AWS firmware with LCD and LEDs |
| `firmware/i2c_scanner/` | Find the LCD's actual I2C address |
| `backend/` | Python MQTT subscriber, DynamoDB storage, LangChain care agent, weather and read-only email |
| `node-red/greenpulse-flow.json` | Importable FlowFuse Dashboard 2 flow |
| `docker-compose.yml` | Cloud-server backend and dashboard deployment |
| `aws/dynamodb.yaml` | CloudFormation DynamoDB table |
| `scripts/generate_policies.py` | Create policies for your account, region and Thing |
| `tests/` | Local behavior checks without cloud credentials |
| `TESTING.md` | Hardware and end-to-end acceptance checklist |

## 1 Confirm your working hardware

| Hardware | ESP32 connection |
|---|---|
| RS485 DE and active-low RE joined | D4 / GPIO4 |
| RS485 DI | TX2 / GPIO17 |
| RS485 RO | RX2 / GPIO16, with appropriate voltage reduction for a 5 V output |
| DHT11 OUT | D18 / GPIO18 |
| DHT11 power | 3V3 and GND, as in your working setup |
| LCD SDA | D21 / GPIO21 through voltage-compatible I2C wiring |
| LCD SCL | D22 / GPIO22 through voltage-compatible I2C wiring |
| Green LED | GPIO25 through a 330-ohm resistor to LED anode; cathode to GND |
| Yellow LED | GPIO26 through its own 330-ohm resistor; cathode to GND |
| Red LED | GPIO27 through its own 330-ohm resistor; cathode to GND |

Preserve the probe's proven power and A/B wiring. The ESP32, RS485 module and non-isolated probe supply share signal ground. Do not connect the probe's 12 V to ESP32 or MAX485 logic pins. A genuine MAX485 requires 5 V; a 3.3 V transceiver needs its specified supply.

Many LCD I2C backpacks use 5 V and pull SDA/SCL up to 5 V. For such a backpack, use a bidirectional I2C level shifter: ESP32 side at 3.3 V, LCD side at 5 V, shared GND. Do not assume the backpack is safe to connect directly. Confirm your LCD module before powering it.

The LED implementation is for three separate LEDs or a common-cathode RGB LED with three resistors. A common-anode RGB LED requires inverted outputs and the correct common-pin supply. Do not enable the included LED configuration for a common-anode module without adjusting it.

## 2 Prepare AWS permissions and certificates

Use the exact Thing name already used by your successful MQTT test. Use the same name as `THING_NAME` in firmware and `DEVICE_ID` in the backend.

Create separate, active IoT client certificates for the backend and dashboard. Do not reuse the ESP32 MQTT client ID on a second client: a duplicate client ID can disconnect the original connection. Register and attach the relevant policies to each certificate.

Generate policies locally, substituting your non-secret account and region details:

```bash
python scripts/generate_policies.py --account-id YOUR_12_DIGIT_ACCOUNT_ID --region YOUR_REGION --thing YOUR_EXISTING_THING_NAME
```

Attach `aws/device-policy.json` to the ESP32 certificate, `aws/backend-policy.json` to the backend certificate and `aws/dashboard-policy.json` to the dashboard certificate. Policies use `greenpulse-backend` and `greenpulse-dashboard` as the cloud client IDs. If you change those IDs, regenerate/update the policies too.

Topics for device `YOUR_EXISTING_THING_NAME`:

| Topic suffix | Publisher | Subscribers |
|---|---|---|
| `/sensors` | ESP32 | Backend, dashboard |
| `/status` | ESP32 or its MQTT Last Will | Dashboard |
| `/llm-input` | Backend | Dashboard |
| `/care` | Backend | ESP32, dashboard |
| `/alerts` | Backend | ESP32, dashboard |

All topics start with `greenpulse/device/YOUR_EXISTING_THING_NAME`. The additional `/llm-input` topic exposes the actual context sent to the LLM, including selected mailbox excerpts, for the assignment's dashboard evidence. Keep broker permissions and dashboard access restricted to your project participants.

The ESP32 publishes live readings every 10 seconds at QoS 0. Cloud responses use QoS 1. The firmware does not replay readings generated while offline; the backend's durable spool protects messages it has already received if DynamoDB is temporarily unavailable. QoS 1 may produce duplicates; this is not an exactly-once system.

## 3 Upload real-sensor firmware

1. Back up your currently working sketch and its secrets locally.
2. Open `firmware/greenpulse/greenpulse.ino`. Use the same ESP32 board package version that compiled your working BLE project.
3. Install ModbusMaster, Adafruit DHT sensor library, Adafruit Unified Sensor, PubSubClient, ArduinoJson **version 7**, and LiquidCrystal_I2C compatible with the johnrickman library's `init()` API.
4. Copy `secrets.example.h` to `secrets.h` in the same folder. Fill Wi-Fi details, endpoint, Thing name, Amazon Root CA 1, and your existing ESP32 certificate/private key locally.
5. Keep `ENABLE_LCD` and `ENABLE_LEDS` at `0` for the first cloud test.
6. Select ESP32 Dev Module and your ESP32 USB port, upload, and open Serial Monitor at 115200 baud.
7. In AWS IoT Core's MQTT test client subscribe to `greenpulse/device/YOUR_EXISTING_THING_NAME/#`. Confirm `/sensors` contains **real** readings and the exact device ID.
8. Check the BLE mobile app still shows its original soil readings.

The firmware keeps your proven 4800 baud, address 1, holding-register start 0 and count 7. It also preserves your unsigned temperature conversion for BLE compatibility. If the probe supports negative temperatures, confirm its signed encoding in the manual before changing this. The software range checks are not calibration and cannot prove NPK accuracy.

Failed sensor readings are published as JSON `null`, not zero or previous successful readings. NTP supplies Unix timestamps and TLS certificate date checks. If time synchronization fails, BLE and sensor reading continue but MQTT waits for valid time.

## 4 Create DynamoDB storage

Deploy `aws/dynamodb.yaml` through AWS CloudFormation in your chosen region, or use the CLI:

```bash
aws cloudformation deploy --template-file aws/dynamodb.yaml --stack-name greenpulse-storage --parameter-overrides TableName=GreenPulseEvents
```

The table uses string partition key `pk` and string sort key `sk`, with on-demand billing. Sensor records use `DEVICE#<id>` plus `SENSOR#<received-seconds>#<event-id>`. Care records use `CARE#...` and store the exact input context and output JSON. Different events in the same second receive different event IDs.

On EC2 attach an instance role granting the generated `aws/backend-role-policy.json` DynamoDB permission. IoT certificates authorize MQTT only; they do not give permission to write DynamoDB. For local testing use your configured AWS SDK credentials/profile instead. Set a data-retention practice for the table; this template does not delete records automatically.

## 5 Configure and test the Python backend

Requirements: Python 3.12, AWS credentials for DynamoDB, a separate backend IoT certificate, your actual Thing name and endpoint. Commands below run from the project root unless specified.

```bash
python -m venv .venv
```

Activate the virtual environment using `.venv/bin/activate` on Linux/macOS, or `.venv\Scripts\Activate.ps1` in Windows PowerShell. Then:

```bash
python -m pip install -r backend/requirements.txt
```

Copy `backend/.env.example` to `backend/.env`. Fill endpoint, region, device ID, table name and the certificate paths. For local testing, copy the backend certificate files to `backend/certs/` or set absolute paths in `.env`.

Start first without an OpenAI key or email access. This tests real MQTT and DynamoDB using a visibly labelled rule fallback:

```bash
cd backend
python main.py
```

Expected sequence: `MQTT connected`, new `SENSOR` items in DynamoDB, then `Care published`. With an unavailable LLM, `/care` explicitly says `llm_status: not_configured` or `unavailable`; it does not claim AI success.

### Enable the LLM and real context

- Put your OpenAI API key in `OPENAI_API_KEY`; select an available structured-output/tool-capable model using `OPENAI_MODEL`.
- Set `PLANT_NAME` to the actual species and set the plant's real latitude/longitude. Open-Meteo retrieves current outdoor weather; the agent does not assume outdoor rain waters an indoor plant.
- Set `EMAIL_ENABLED=true` and configure your own real account's IMAP host, user and an appropriate app password if that provider supports it. This implementation uses IMAP over TLS, opens INBOX read-only and fetches with `BODY.PEEK`; it does not send email, delete messages or mark them read. If your account requires OAuth instead of app-password IMAP, an OAuth integration is still needed for that account.
- Set keywords to identify gardening/weather reminders. Only the newest 20 messages from the last seven days are inspected, and at most five relevant excerpts are passed to the model. Real selected excerpts are sent to the configured LLM provider and stored with the model input in your AWS table.
- Weather/mailbox context is cached for 10 minutes. LLM care generation defaults to once every 5 minutes, rather than once for every 10-second reading. Missing services remain explicit.

The bounded agent can call read-only weather and gardening-notification tools, then produces a structured care message, original quote and summaries. Priority comes from configurable deterministic moisture rules. Defaults of 20% and 35% are **demonstration thresholds**, not universal plant-care limits. Calibrate against your probe, potting medium and plant species. No automatic watering or fertilizer dosing is implemented.

## 6 Deploy backend and Node-RED on a cloud server

Use a Linux EC2 server with Docker Engine and Compose v2 installed, adequate memory for Python plus Node-RED, and an attached DynamoDB instance role. Upload this project directory. Allow inbound SSH only from your own IP. The Compose file binds Node-RED to the server's loopback interface; it is accessed through an SSH tunnel.

Place these files in the project's `certs/` folder on the server:

```text
AmazonRootCA1.pem
backend-certificate.pem.crt
backend-private.pem.key
dashboard-certificate.pem.crt
dashboard-private.pem.key
```

Allow container UID 10001 to read the backend key and UID 1000 to read the dashboard key. Certificates may be readable by both; private keys should remain restricted. Example Linux commands:

```bash
sudo chown 10001:10001 certs/backend-private.pem.key
sudo chown 1000:1000 certs/dashboard-private.pem.key
sudo chmod 600 certs/backend-private.pem.key certs/dashboard-private.pem.key
chmod 644 certs/AmazonRootCA1.pem certs/backend-certificate.pem.crt certs/dashboard-certificate.pem.crt
```

Fill `backend/.env` on the server; do not put keys in source code or the public report. Compose overrides MQTT certificate paths with container paths. Start services:

```bash
docker compose --env-file backend/.env up -d --build
docker compose --env-file backend/.env logs -f backend
```

This Compose file uses Linux host networking for the backend so the AWS SDK can use the EC2 instance role. For Docker Desktop/local deployments, use the Python local-testing method first; the instance role is not available there.

From your computer open a tunnel (replace placeholders):

```bash
ssh -i YOUR_EC2_KEY.pem -L 1880:127.0.0.1:1880 ubuntu@YOUR_SERVER_IP
```

Open `http://localhost:1880`. Import `node-red/greenpulse-flow.json` via Menu > Import. The container already includes `@flowfuse/node-red-dashboard`; if using another Node-RED installation, install that package using Manage Palette first.

Open the AWS MQTT broker configuration and confirm the endpoint, port 8883, MQTT 3.1.1 and client ID `greenpulse-dashboard`. Open TLS configuration and select **Use key and certificates from local files** with the paths under `/data/certs/`; keep server certificate verification enabled. The generated flow includes these paths, but check the editor for your installed Node-RED version. Deploy.

Open `http://localhost:1880/dashboard/plant`. The dashboard displays all nine readings, care priority, quote, weather/message summaries, full subscribed/published payloads, topic names, receive times, and broker/device/backend freshness status. Sensitive email content is text-escaped, not rendered as HTML. Leave the editor and dashboard behind the SSH tunnel for this demo; any public deployment needs authentication and HTTPS.

## 7 Add LCD and LEDs

After checking power and I2C level shifting, run `firmware/i2c_scanner/i2c_scanner.ino`. Note the detected address (often 0x27 or 0x3F, but do not assume it). This scanner upload temporarily replaces the main firmware; upload the main sketch again afterwards.

Set `LCD_ADDRESS` in `hardware_config.h`, change `ENABLE_LCD` to `1`, and upload the combined sketch. The display rotates through soil, air, pH/EC and NPK pages and shows MQTT status. It never displays care messages, email excerpts or MQTT JSON.

Add three LEDs with the specified resistors, set `ENABLE_LEDS` to `1` and re-upload. On a fresh backend response: green=low, yellow=medium, red=high. All LEDs are off when disconnected, response expired, or priority is unknown. Care responses expire after 10 minutes. LEDs indicate urgency only; no pump or actuator is controlled.

## Validation performed for this package

Dependency-free unit tests cover invalid/missing readings, threshold boundaries, stale/future timestamps, mismatched devices, durable spool restart and DynamoDB Decimal conversion. Python syntax and Node-RED Function/Vue script syntax are checked. Firmware, dependency installation, actual FlowFuse rendering, IMAP access, cloud deployment and end-to-end communication still require your local/account/hardware tests. See `TESTING.md`.

## Reference documentation

- AWS IoT resource setup: https://docs.aws.amazon.com/iot/latest/developerguide/create-iot-resources.html
- AWS IoT MQTT and TLS: https://docs.aws.amazon.com/iot/latest/developerguide/protocols.html
- Paho MQTT Python: https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html
- DynamoDB Boto3 guide: https://docs.aws.amazon.com/boto3/latest/guide/dynamodb.html
- LangChain ChatOpenAI: https://docs.langchain.com/oss/python/integrations/chat/openai
- Open-Meteo: https://open-meteo.com/en/docs
- FlowFuse ui-template: https://dashboard.flowfuse.com/nodes/widgets/ui-template.html
- Node-RED environment variables: https://nodered.org/docs/user-guide/environment-variables
- Adafruit DHT: https://github.com/adafruit/DHT-sensor-library
- LiquidCrystal_I2C: https://github.com/johnrickman/LiquidCrystal_I2C

Your proposal mentions DHT22 and PostgreSQL. This implementation uses your actual DHT11 and the DynamoDB AWS storage you requested. Update the final report to match implemented hardware/software and distinguish implemented features from proposed ones. The commercialization video, final 4-6 page report and live demo remain submission tasks after deployment is verified.
