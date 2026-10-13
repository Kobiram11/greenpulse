#include <Wire.h>
void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);
  delay(1000);
  Serial.println("I2C scan: SDA=21 SCL=22");
  for (uint8_t address = 1; address < 127; ++address) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) Serial.printf("Found: 0x%02X\n", address);
  }
}
void loop() {}
