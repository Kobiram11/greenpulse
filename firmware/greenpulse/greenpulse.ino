#include <ModbusMaster.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <DHT.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <time.h>
#include <esp_random.h>
#include "secrets.h"
#include "hardware_config.h"

#define RS485_DIR 4
#define RXD2 16
#define TXD2 17
#define DHT_PIN 18
#define SERVICE_UUID "12345678-1234-1234-1234-1234567890ab"
#define CHARACTERISTIC_UUID "abcd1234-5678-90ab-cdef-1234567890ab"
#define TOPIC_BASE "greenpulse/device/" THING_NAME

ModbusMaster node;
DHT dht(DHT_PIN, DHT22);   // your sensor is a DHT22 (DHT11 setting gave 1.5 C / 9 %)
WiFiClientSecure net;
PubSubClient mqtt(net);
LiquidCrystal_I2C lcd(LCD_ADDRESS, 16, 2);
BLECharacteristic* pCharacteristic = nullptr;
bool deviceConnected = false;
bool lcdReady = false;
bool soilOK = false;
bool sampled = false;
float airTemperature = NAN, airHumidity = NAN;
uint16_t raw[7] = {};
unsigned long lastSensor = 0, lastPublish = 0, lastLCD = 0;
unsigned long lastWiFi = 0, lastMQTT = 0, lastStatus = 0;
uint32_t sampleTs = 0, sequence = 0;
char bootId[9];
String backendPriority = "unknown";
uint32_t priorityExpires = 0, priorityTs = 0;

class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* pServer) override {
    deviceConnected = true;
    Serial.println("BLE client connected");
  }
  void onDisconnect(BLEServer* pServer) override {
    deviceConnected = false;
    BLEDevice::startAdvertising();
  }
};

void preTransmission() { digitalWrite(RS485_DIR, HIGH); }
void postTransmission() { digitalWrite(RS485_DIR, LOW); }

void readSensors() {
  airHumidity = dht.readHumidity();
  airTemperature = dht.readTemperature();
  if (isnan(airHumidity) || isnan(airTemperature)) Serial.println("DHT22 read failed");
  else Serial.printf("DHT22: %.1f C, %.1f %%\n", airTemperature, airHumidity);
  uint8_t result = node.readHoldingRegisters(0x0000, 7);
  soilOK = result == node.ku8MBSuccess;
  if (soilOK) {
    for (int i = 0; i < 7; ++i) raw[i] = node.getResponseBuffer(i);
    // Preserve the ORIGINAL seven BLE fields and conversions exactly.
    char csv[80];
    snprintf(csv, sizeof(csv), "%.1f,%.1f,%d,%.1f,%d,%d,%d",
             raw[0] / 10.0, raw[1] / 10.0, (int)raw[2], raw[3] / 10.0,
             (int)raw[4], (int)raw[5], (int)raw[6]);
    Serial.printf("BLE: %s\n", csv);
    pCharacteristic->setValue(csv);
    if (deviceConnected) pCharacteristic->notify();
  } else Serial.printf("Modbus error: 0x%02X\n", result);
  sampled = true;
  ++sequence;
  time_t now = time(nullptr);
  sampleTs = now >= 1700000000 ? (uint32_t)now : 0;
}

bool publishJSON(const char* topic, JsonDocument& doc, bool retained = false) {
  if (measureJson(doc) >= 2048) return false;
  char buf[2048];
  size_t n = serializeJson(doc, buf, sizeof(buf));
  return mqtt.publish(topic, (const uint8_t*)buf, n, retained);
}

void publishStatus() {
  JsonDocument doc;
  doc["device_id"] = THING_NAME;
  doc["online"] = true;
  doc["ts"] = (uint32_t)time(nullptr);
  doc["rssi"] = WiFi.RSSI();
  publishJSON(TOPIC_BASE "/status", doc);
}

void publishSensors() {
  if (!sampled || sampleTs == 0) return;
  JsonDocument doc;
  doc["device_id"] = THING_NAME;
  doc["ts"] = sampleTs;
  doc["boot_id"] = bootId;
  doc["seq"] = sequence;
  doc["source"] = "real";
  doc["soil_ok"] = soilOK;
  doc["air_ok"] = isfinite(airTemperature) && isfinite(airHumidity);
  JsonObject soil = doc["soil"].to<JsonObject>();
  const char* names[] = {"moisture", "temperature", "ec", "ph", "n", "p", "k"};
  for (int i = 0; i < 7; ++i) {
    if (!soilOK) soil[names[i]] = nullptr;
    else if (i == 0 || i == 1 || i == 3) soil[names[i]] = raw[i] / 10.0;
    else soil[names[i]] = raw[i];
  }
  JsonObject air = doc["air"].to<JsonObject>();
  if (isfinite(airTemperature)) air["temperature"] = airTemperature;
  else air["temperature"] = nullptr;
  if (isfinite(airHumidity)) air["humidity"] = airHumidity;
  else air["humidity"] = nullptr;
  bool sent = publishJSON(TOPIC_BASE "/sensors", doc);
  Serial.printf("MQTT sensor publish: %s\n", sent ? "sent" : "failed");
}

void onMessage(char* topic, byte* payload, unsigned int length) {
  Serial.printf("MQTT received [%s]\n", topic);
  JsonDocument doc;
  if (deserializeJson(doc, payload, length)) return;
  if (String(doc["device_id"] | "") != THING_NAME) return;
  uint32_t now = (uint32_t)time(nullptr);
  uint32_t ts = doc["ts"] | 0U;
  uint32_t expires = doc["expires_ts"] | 0U;
  String level = doc["priority"] | "unknown";
  if (ts < 1700000000 || expires <= now || expires > now + 1200 || ts > now + 60 || ts < priorityTs) return;
  if (level != "low" && level != "medium" && level != "high" && level != "unknown") return;
  backendPriority = level;
  priorityExpires = expires;
  priorityTs = ts;
  // NEVER put the MQTT payload or AI text on the LCD.
}

void serviceNetwork() {
  unsigned long now = millis();
  if (WiFi.status() != WL_CONNECTED) {
    if (now - lastWiFi >= 15000) {
      lastWiFi = now;
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    }
    return;
  }
  if (time(nullptr) < 1700000000) return; // wait for NTP without blocking sensor reads
  if (!mqtt.connected() && now - lastMQTT >= 10000) {
    lastMQTT = now;
    bool ok = mqtt.connect(THING_NAME, TOPIC_BASE "/status", 1, false,
       "{\"device_id\":\"" THING_NAME "\",\"online\":false}");
    if (ok) {
      bool a = mqtt.subscribe(TOPIC_BASE "/care", 1);
      bool b = mqtt.subscribe(TOPIC_BASE "/alerts", 1);
      Serial.printf("MQTT connected, subscribe requests: %d %d\n", a, b);
      publishStatus();
      lastStatus = now;
    } else Serial.printf("MQTT connect failed: %d (free heap %u bytes)\n", mqtt.state(), ESP.getFreeHeap());
  }
  if (mqtt.connected()) {
    mqtt.loop();
    if (now - lastStatus >= 30000) { lastStatus = now; publishStatus(); }
    if (now - lastPublish >= 10000) { lastPublish = now; publishSensors(); }
  }
}

void lcdLine(int row, const char* text) {
  char line[17];
  snprintf(line, sizeof(line), "%-16.16s", text);
  lcd.setCursor(0, row);
  lcd.print(line);
}

void updateLCD() {
  if (!lcdReady) return;
  char a[32], b[32];
  unsigned int page = (millis() / 3000) % 6;
  const char* state = mqtt.connected() ? "ON" : "OFF";
  if (page == 0) {
    if (soilOK) {
      snprintf(a, sizeof(a), "Moist:%.1f%%", raw[0] / 10.0);
      snprintf(b, sizeof(b), "Soil:%.1fC", raw[1] / 10.0);
    } else { snprintf(a, sizeof(a), "Soil: no reading"); snprintf(b, sizeof(b), "Check probe"); }
  } else if (page == 1) {
    if (isfinite(airTemperature)) snprintf(a, sizeof(a), "Air:%.1fC", airTemperature);
    else snprintf(a, sizeof(a), "Air temp: --");
    if (isfinite(airHumidity)) snprintf(b, sizeof(b), "Humidity:%.1f%%", airHumidity);
    else snprintf(b, sizeof(b), "Humidity: --");
  } else if (page == 2) {
    if (soilOK) { snprintf(a, sizeof(a), "pH:%.1f", raw[3] / 10.0); snprintf(b, sizeof(b), "EC:%u uS/cm", raw[2]); }
    else { snprintf(a, sizeof(a), "pH: --"); snprintf(b, sizeof(b), "EC: --"); }
  } else if (page == 3) {
    if (soilOK) { snprintf(a, sizeof(a), "N:%u mg/kg", raw[4]); snprintf(b, sizeof(b), "P:%u mg/kg", raw[5]); }
    else { snprintf(a, sizeof(a), "N:--"); snprintf(b, sizeof(b), "P:--"); }
  } else if (page == 4) {
    if (soilOK) snprintf(a, sizeof(a), "K:%u mg/kg", raw[6]);
    else snprintf(a, sizeof(a), "K:--");
    snprintf(b, sizeof(b), "MQTT:%s", state);
  } else {
    snprintf(a, sizeof(a), "WiFi:%s", WiFi.status() == WL_CONNECTED ? "ON" : "OFF");
    snprintf(b, sizeof(b), "MQTT:%s", state);
  }
  // A status indicator on every sensor page; rows remain exactly 16 characters.
  if (page != 5) {
    char line[17];
    snprintf(line, sizeof(line), "%-12.12s M:%c", a, mqtt.connected() ? 'Y' : 'N');
    lcdLine(0, line);
  } else lcdLine(0, a);
  lcdLine(1, b);
}

void updateLEDs() {
  if (!ENABLE_LEDS) return;
  String level = "unknown";
  uint32_t now = (uint32_t)time(nullptr);
  if (mqtt.connected() && priorityExpires > now) level = backendPriority;
  // Unknown, expired or disconnected: all OFF (never imply a healthy reading).
  digitalWrite(LED_GREEN, level == "low" ? HIGH : LOW);
  digitalWrite(LED_YELLOW, level == "medium" ? HIGH : LOW);
  digitalWrite(LED_RED, level == "high" ? HIGH : LOW);
}

void setup() {
  Serial.begin(115200);
  pinMode(RS485_DIR, OUTPUT);
  digitalWrite(RS485_DIR, LOW);
  Serial2.begin(4800, SERIAL_8N1, RXD2, TXD2);
  node.begin(1, Serial2);
  node.preTransmission(preTransmission);
  node.postTransmission(postTransmission);
  dht.begin();
  if (ENABLE_LEDS) {
    pinMode(LED_GREEN, OUTPUT); pinMode(LED_YELLOW, OUTPUT); pinMode(LED_RED, OUTPUT);
    updateLEDs();
  }
  if (ENABLE_LCD) {
    Wire.begin(21, 22);
    Wire.beginTransmission(LCD_ADDRESS);
    lcdReady = Wire.endTransmission() == 0;
    if (lcdReady) { lcd.init(); lcd.backlight(); lcdLine(0, "GreenPulse"); lcdLine(1, "Sensors starting"); }
    else Serial.println("LCD not found: run i2c_scanner and edit LCD_ADDRESS");
  }
  BLEDevice::init("Soil Sensor BLE");
  BLEServer* pServer = BLEDevice::createServer();
  pServer->setCallbacks(new ServerCallbacks());
  BLEService* pService = pServer->createService(SERVICE_UUID);
  pCharacteristic = pService->createCharacteristic(CHARACTERISTIC_UUID,
      BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
  pCharacteristic->addDescriptor(new BLE2902());
  pService->start();
  BLEAdvertising* advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(SERVICE_UUID);
  advertising->setScanResponse(true);
  BLEDevice::startAdvertising();
  snprintf(bootId, sizeof(bootId), "%08lx", (unsigned long)esp_random());
  net.setCACert(AWS_CERT_CA);
  net.setCertificate(AWS_CERT_CRT);
  net.setPrivateKey(AWS_CERT_PRIVATE);
  net.setHandshakeTimeout(5);
  mqtt.setServer(AWS_IOT_ENDPOINT, 8883);
  mqtt.setCallback(onMessage);
  mqtt.setBufferSize(4096);
  mqtt.setKeepAlive(30);
  mqtt.setSocketTimeout(5);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  Serial.printf("Setup done. Free heap: %u bytes\n", ESP.getFreeHeap());
}

void loop() {
  if (millis() - lastSensor >= 3000) {
    readSensors();
    lastSensor = millis();
  }
  serviceNetwork();
  updateLEDs();
  if (millis() - lastLCD >= 500) { lastLCD = millis(); updateLCD(); }
  delay(5);
}
