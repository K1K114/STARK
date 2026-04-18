#include <TMCStepper.h>

#define STEP_PIN1    4
#define DIR_PIN1     5
#define EN_PIN1      6
#define STEP_PIN2    19
#define DIR_PIN2     20
#define EN_PIN2      21
#define R_SENSE     0.11f  // TMC2209 typical sense resistor

// Motor 1 UART pins (TX=17, RX=16)
#define TMC1_TX_PIN  17
#define TMC1_RX_PIN  16

// Motor 2 UART pins (TX=43, RX=44)
#define TMC2_TX_PIN  43
#define TMC2_RX_PIN  44

// One UART bus per driver.
TMC2209Stepper driver1(&Serial1, R_SENSE, 0b00);
TMC2209Stepper driver2(&Serial2, R_SENSE, 0b00);

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

void step_both(int steps, bool dir1, bool dir2, uint16_t step_delay_us) {
  digitalWrite(DIR_PIN1, dir1 ? HIGH : LOW);
  digitalWrite(DIR_PIN2, dir2 ? HIGH : LOW);

  for (int i = 0; i < steps; i++) {
    digitalWrite(STEP_PIN1, HIGH);
    digitalWrite(STEP_PIN2, HIGH);
    delayMicroseconds(step_delay_us);
    digitalWrite(STEP_PIN1, LOW);
    digitalWrite(STEP_PIN2, LOW);
    delayMicroseconds(step_delay_us);
  }
}

void setup() {
  Serial.begin(115200);
  Serial.println("TMC2209 Dual-Motor Test Starting...");

  // Start UART for each TMC2209 (Serial.begin uses RX, TX order)
  Serial1.begin(115200, SERIAL_8N1, TMC1_RX_PIN, TMC1_TX_PIN);
  Serial2.begin(115200, SERIAL_8N1, TMC2_RX_PIN, TMC2_TX_PIN);

  pinMode(STEP_PIN1, OUTPUT);
  pinMode(DIR_PIN1, OUTPUT);
  pinMode(EN_PIN1, OUTPUT);
  pinMode(STEP_PIN2, OUTPUT);
  pinMode(DIR_PIN2, OUTPUT);
  pinMode(EN_PIN2, OUTPUT);

  digitalWrite(EN_PIN1, LOW);  // Enable driver
  digitalWrite(EN_PIN2, LOW);  // Enable driver

  init_driver(driver1, "Driver1");
  init_driver(driver2, "Driver2");

  // Print some info
  Serial.print("Driver1 microsteps: ");
  Serial.println(driver1.microsteps());
  Serial.print("Driver1 current (mA): ");
  Serial.println(driver1.rms_current());
  Serial.print("Driver2 microsteps: ");
  Serial.println(driver2.microsteps());
  Serial.print("Driver2 current (mA): ");
  Serial.println(driver2.rms_current());
}

void loop() {
  Serial.println("Spinning both clockwise...");
  step_both(STEPS_PER_REV, true, true, 500);

  delay(1000);

  Serial.println("Spinning both counter-clockwise...");
  step_both(STEPS_PER_REV, false, false, 500);

  delay(1000);
}