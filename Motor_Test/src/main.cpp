#include <TMCStepper.h>

#define STEP_PIN1    4
#define DIR_PIN1     5
#define EN_PIN1      6
#define R_SENSE     0.11f  // TMC2209 typical sense resistor

// Motor 1 UART pins (TX=17, RX=16)
#define TMC1_TX_PIN  17
#define TMC1_RX_PIN  16

// Single driver on Serial1.
TMC2209Stepper driver1(&Serial1, R_SENSE, 0b00);

constexpr int STEPS_PER_REV = 3200;  // 200 full steps * 16 microsteps

void init_driver(TMC2209Stepper &driver, const char *name) {
  driver.begin();
  driver.toff(5);                // Enable driver via UART
  driver.rms_current(800);       // Adjust for your motor
  driver.microsteps(16);         // 16 microstepping
  driver.pwm_autoscale(true);    // StealthChop
  driver.en_spreadCycle(false);  // StealthChop mode (quiet)

  uint8_t result = driver.test_connection();
  if (result == 0) {
    Serial.print(name);
    Serial.println(" connected OK!");
  } else {
    Serial.print(name);
    Serial.print(" connection FAILED! Error: ");
    Serial.println(result);
  }
}

void step_motor1(int steps, bool clockwise, uint16_t step_delay_us) {
  digitalWrite(DIR_PIN1, clockwise ? HIGH : LOW);

  for (int i = 0; i < steps; i++) {
    digitalWrite(STEP_PIN1, HIGH);
    delayMicroseconds(step_delay_us);
    digitalWrite(STEP_PIN1, LOW);
    delayMicroseconds(step_delay_us);
  }
}

void setup() {
  Serial.begin(115200);
  Serial.println("TMC2209 Single-Motor Test Starting...");

  // Start UART for TMC2209 (Serial.begin uses RX, TX order)
  Serial1.begin(115200, SERIAL_8N1, TMC1_RX_PIN, TMC1_TX_PIN);

  pinMode(STEP_PIN1, OUTPUT);
  pinMode(DIR_PIN1, OUTPUT);
  pinMode(EN_PIN1, OUTPUT);

  digitalWrite(EN_PIN1, LOW);  // Enable driver

  init_driver(driver1, "Driver1");

  // Print some info
  Serial.print("Driver1 microsteps: ");
  Serial.println(driver1.microsteps());
  Serial.print("Driver1 current (mA): ");
  Serial.println(driver1.rms_current());
}

void loop() {
  Serial.println("Spinning clockwise...");
  step_motor1(STEPS_PER_REV, true, 500);

  delay(1000);

  Serial.println("Spinning counter-clockwise...");
  step_motor1(STEPS_PER_REV, false, 500);

  delay(1000);
}