#pragma once
// Enable only after checking LCD power and I2C voltage compatibility.
#define ENABLE_LCD 0
#define LCD_ADDRESS 0x27
// Three separate LEDs (each needs its own 330-ohm series resistor).
#define ENABLE_LEDS 0
#define LED_GREEN 25
#define LED_YELLOW 26
#define LED_RED 27
