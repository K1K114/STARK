#include <Arduino.h>
#include <AccelStepper.h>

#define STEP_PIN1 4
#define DIR_PIN1 5
#define EN_PIN1 6

constexpr int FULL_STEPS_PER_REV = 200;
constexpr int MICROSTEPS = 32;  // DRV8825 MS pins set for 1/32 mode
constexpr int STEPS_PER_REV = FULL_STEPS_PER_REV * MICROSTEPS;
constexpr float TARGET_RPM = 60.0f;
constexpr float MAX_SPEED_STEPS_S = (STEPS_PER_REV * TARGET_RPM) / 60.0f;
constexpr float ACCEL_STEPS_S2 = 12000.0f;
constexpr unsigned long DWELL_MS = 1000;

AccelStepper motor1(AccelStepper::DRIVER, STEP_PIN1, DIR_PIN1);

long targetPosition = STEPS_PER_REV;
unsigned long dwellStart = 0;
bool dwellActive = false;

void setup() {
  Serial.begin(115200);
  Serial.println("DRV8825 + AccelStepper Single-Motor Test Starting...");

  pinMode(EN_PIN1, OUTPUT);
  digitalWrite(EN_PIN1, LOW);  // DRV8825 enable is active LOW

  motor1.setEnablePin(EN_PIN1);
  motor1.setPinsInverted(false, false, true);
  motor1.setMinPulseWidth(2);  // DRV8825 step high pulse >= 1.9us
  motor1.enableOutputs();
  motor1.setMaxSpeed(MAX_SPEED_STEPS_S);
  motor1.setAcceleration(ACCEL_STEPS_S2);
  motor1.setCurrentPosition(0);
  motor1.moveTo(targetPosition);

  Serial.print("Max speed (steps/s): ");
  Serial.println(MAX_SPEED_STEPS_S);
  Serial.print("Target speed (RPM): ");
  Serial.println(TARGET_RPM);
  Serial.print("Acceleration (steps/s^2): ");
  Serial.println(ACCEL_STEPS_S2);
  Serial.print("Move distance (steps): ");
  Serial.println(STEPS_PER_REV);
}

void loop() {
  motor1.run();

  if (motor1.distanceToGo() != 0) {
    return;
  }

  if (!dwellActive) {
    dwellActive = true;
    dwellStart = millis();
    if (targetPosition > 0) {
      Serial.println("Reached CW target");
    } else {
      Serial.println("Reached CCW target");
    }
    return;
  }

  if (millis() - dwellStart >= DWELL_MS) {
    targetPosition = -targetPosition;
    if (targetPosition > 0) {
      Serial.println("Moving clockwise...");
    } else {
      Serial.println("Moving counter-clockwise...");
    }
    motor1.moveTo(targetPosition);
    dwellActive = false;
  }
}