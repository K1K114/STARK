#include <Arduino.h>
#include <Adafruit_NeoPixel.h>

// WS2812E signal input pin (DIN) wired to ESP32-S3 GPIO 39.
static constexpr uint8_t LED_PIN = 39;
// Change this if your strip has more LEDs.
static constexpr uint16_t NUM_PIXELS = 1;
static constexpr uint8_t BRIGHTNESS = 64;

Adafruit_NeoPixel pixels(NUM_PIXELS, LED_PIN, NEO_GRB + NEO_KHZ800);

void showColor(uint8_t r, uint8_t g, uint8_t b, uint16_t holdMs) {
  pixels.fill(pixels.Color(r, g, b));
  pixels.show();
  delay(holdMs);
}

void setup() {
  pixels.begin();
  pixels.setBrightness(BRIGHTNESS);
  pixels.clear();
  pixels.show();
}

void loop() {
  showColor(255, 0, 0, 500);   // Red
  showColor(0, 255, 0, 500);   // Green
  showColor(0, 0, 255, 500);   // Blue
  showColor(255, 255, 255, 500); // White
  showColor(0, 0, 0, 500);     // Off
}