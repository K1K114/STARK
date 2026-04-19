#include <Arduino.h>
#include "TMC2209_Driver.h"
#include "DRV8825_Driver.h"

// Motor 1 (TMC2209)
#define STEP_PIN1    19
#define DIR_PIN1     20
#define EN_PIN1      21

// Motor 2 (DRV8825)
#define STEP_PIN2    4
#define DIR_PIN2     5
#define EN_PIN2      6
#define R_SENSE     0.11f  // TMC2209 typical sense resistor

// Motor 1 UART pins (TX=17, RX=16)
#define TMC1_TX_PIN  17
#define TMC1_RX_PIN  16

#define LEFT_PIN 1
#define RIGHT_PIN 2
#define UP_PIN 42
#define DOWN_PIN 41

#define UART_BAUDRATE 115200
#define STEPS_PER_REV 6400
#define DRIVER_CURRENT_MA 800
#define DRIVER_MICROSTEPS 32

// Base speed for TMC2209 motor. Increase DRV8825 ratio if it still lags.
#define STEP_HALF_PERIOD_US_M1 400
#define DRV8825_SPEED_RATIO 2.4f
#define STEP_HALF_PERIOD_US_M2 ((uint32_t)(STEP_HALF_PERIOD_US_M1 / DRV8825_SPEED_RATIO))

enum MotionMode {
  MOTION_NONE,
  MOTION_LEFT,
  MOTION_RIGHT,
  MOTION_UP,
  MOTION_DOWN
};

TMC2209Driver motor1;
DRV8825Driver motor2;
static MotionMode currentMotion = MOTION_NONE;
static bool stepLevel1 = false;
static bool stepLevel2 = false;
static uint32_t lastStepMicros1 = 0;
static uint32_t lastStepMicros2 = 0;

static MotionMode readMotionFromButtons() {
  if (digitalRead(LEFT_PIN) == LOW) return MOTION_LEFT;
  if (digitalRead(RIGHT_PIN) == LOW) return MOTION_RIGHT;
  if (digitalRead(UP_PIN) == LOW) return MOTION_UP;
  if (digitalRead(DOWN_PIN) == LOW) return MOTION_DOWN;
  return MOTION_NONE;
}

static void applyDirections(MotionMode mode) {
  switch (mode) {
    case MOTION_LEFT:
      // LEFT: M1 CW, M2 CW
      TMC2209_SetDirection(&motor1, true);
      DRV8825_SetDirection(&motor2, true);
      break;
    case MOTION_RIGHT:
      // RIGHT: M1 CCW, M2 CCW
      TMC2209_SetDirection(&motor1, false);
      DRV8825_SetDirection(&motor2, false);
      break;
    case MOTION_UP:
      // UP: M1 CW, M2 CCW
      TMC2209_SetDirection(&motor1, true);
      DRV8825_SetDirection(&motor2, false);
      break;
    case MOTION_DOWN:
      // DOWN: M1 CCW, M2 CW
      TMC2209_SetDirection(&motor1, false);
      DRV8825_SetDirection(&motor2, true);
      break;
    case MOTION_NONE:
    default:
      break;
  }
}

static void runSteppersWhileHeld() {
  MotionMode requested = readMotionFromButtons();

  if (requested != currentMotion) {
    currentMotion = requested;
    stepLevel1 = false;
    stepLevel2 = false;
    TMC2209_SetStepLevel(&motor1, false);
    DRV8825_SetStepLevel(&motor2, false);
    lastStepMicros1 = micros();
    lastStepMicros2 = lastStepMicros1;

    if (currentMotion != MOTION_NONE) {
      applyDirections(currentMotion);
    }
  }

  if (currentMotion == MOTION_NONE) {
    return;
  }

  uint32_t now = micros();

  if ((uint32_t)(now - lastStepMicros1) >= STEP_HALF_PERIOD_US_M1) {
    lastStepMicros1 = now;
    stepLevel1 = !stepLevel1;
    TMC2209_SetStepLevel(&motor1, stepLevel1);
  }

  if ((uint32_t)(now - lastStepMicros2) >= STEP_HALF_PERIOD_US_M2) {
    lastStepMicros2 = now;
    stepLevel2 = !stepLevel2;
    DRV8825_SetStepLevel(&motor2, stepLevel2);
  }
}

static void init_stepper_motors() {
  bool ok1 = TMC2209_Init(
    &motor1,
    &Serial1,
    TMC1_RX_PIN,
    TMC1_TX_PIN,
    0b00,
    STEP_PIN1,
    DIR_PIN1,
    EN_PIN1,
    false,
    true,
    STEPS_PER_REV,
    R_SENSE,
    DRIVER_CURRENT_MA,
    DRIVER_MICROSTEPS
  );

  bool ok2 = DRV8825_Init(
    &motor2,
    STEP_PIN2,
    DIR_PIN2,
    EN_PIN2,
    false,
    true
  );

  if (!ok1 || !ok2) {
    Serial.println("Stepper init failed");
    return;
  }

  bool begin1 = TMC2209_Begin(&motor1, UART_BAUDRATE);

  if (!begin1) {
    Serial.println("Stepper UART/TMC begin failed");
    return;
  }

  TMC2209_Enable(&motor1);
  DRV8825_Enable(&motor2);

  TMC2209_SetPulseWidthUs(&motor1, 2);
  DRV8825_SetPulseWidthUs(&motor2, 2);

  Serial.print("Motor1 test_connection: ");
  Serial.println(TMC2209_TestConnection(&motor1));
  Serial.println("Motor2 DRV8825 ready (no UART test)");
  Serial.println("Both steppers initialized");
}

void setup() { 
  pinMode(LEFT_PIN, INPUT_PULLUP);
  pinMode(RIGHT_PIN, INPUT_PULLUP);
  pinMode(UP_PIN, INPUT_PULLUP);
  pinMode(DOWN_PIN, INPUT_PULLUP);

  Serial.begin(115200);
  Serial.println("Gantry startup");

  init_stepper_motors();
}

void loop() { 
  runSteppersWhileHeld();
}

