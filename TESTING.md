# GreenPulse acceptance checks

Record observed results and screenshots after testing. Do not claim cloud or hardware success based on the included local tests alone.

| Check | Expected result |
|---|---|
| Original BLE mobile app | Original seven soil fields parse unchanged; same name and UUIDs |
| Soil probe | Values match working sketch; raw register map verified against probe documentation |
| DHT11 | Air values are plausible and match a nearby reference thermometer/hygrometer within the sensor's specified accuracy |
| Real MQTT payload | Correct device_id, Unix seconds ts, real soil/air values, no dummy random readings |
| Sensor disconnected | Failed fields are null; no old successful values masquerade as new |
| TLS | Server verification enabled; valid client cert/policy required; no insecure TLS override |
| Wi-Fi lost | BLE/sensor collection continues; MQTT status OFF; LEDs off |
| Wi-Fi restored | MQTT reconnects and subscribes again; new readings resume |
| DynamoDB | SENSOR records include receive time and readings; CARE records include exact LLM input/output |
| DynamoDB temporarily unavailable | Received jobs remain in local spool; recover when permissions/connectivity restored |
| Backend restarted | Durable spool remains available in the Docker volume |
| LLM enabled | llm_status=ok; original quote and context-based advice appear |
| LLM key missing/API fails | Explicit not_configured/unavailable; rule fallback labelled; no invented AI result |
| Weather | Actual configured coordinates, real API source/time; outage is explicit |
| Email | Own real account, selected relevant messages; no sending/deleting/marking read |
| Node-RED | Nine values, broker/device/backend status, five topic payloads, timestamps, summaries |
| LCD | Only sensor readings and MQTT/Wi-Fi status; no LLM text or MQTT payloads |
| LEDs | Fresh low/medium/high maps green/yellow/red; invalid/stale/disconnected is all off |

For repeatable LED checks, temporarily publish a care payload from the authorized backend with the correct device_id, current ts and expires_ts in the future. Do not overwrite real sensor values to fabricate a successful demo. Restore normal backend control after testing.

Run local checks from the project root:

```bash
python -m unittest discover -s tests -v
python -m compileall -q backend scripts
node tests/test_flow.cjs
```

Capture the successful Arduino compile output, actual installed dependency versions, selected region, device ID, dashboard screenshot and DynamoDB item screenshot for the final report. Include failed readings/reconnection behavior as evidence of error handling.
