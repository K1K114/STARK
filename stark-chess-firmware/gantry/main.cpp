#include <Arduino.h>
#include "Stepper_Driver.h"

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

#define LEFT_PIN 1
#define RIGHT_PIN 2
#define UP_PIN 42
#define DOWN_PIN 41

#define UART_BAUDRATE 115200
#define STEPS_PER_REV 3200
#define DRIVER_CURRENT_MA 800
#define DRIVER_MICROSTEPS 16
#define STEP_HALF_PERIOD_US 450

enum MotionMode {
  MOTION_NONE,
  MOTION_LEFT,
  MOTION_RIGHT,
  MOTION_UP,
  MOTION_DOWN
};

StepperDriver motor1;
StepperDriver motor2;
static MotionMode currentMotion = MOTION_NONE;
static bool stepLevel = false;
static uint32_t lastStepMicros = 0;

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
      Stepper_SetDirection(&motor1, true);
      Stepper_SetDirection(&motor2, true);
      break;
    case MOTION_RIGHT:
      // RIGHT: M1 CCW, M2 CCW
      Stepper_SetDirection(&motor1, false);
      Stepper_SetDirection(&motor2, false);
      break;
    case MOTION_UP:
      // UP: M1 CW, M2 CCW
      Stepper_SetDirection(&motor1, true);
      Stepper_SetDirection(&motor2, false);
      break;
    case MOTION_DOWN:
      // DOWN: M1 CCW, M2 CW
      Stepper_SetDirection(&motor1, false);
      Stepper_SetDirection(&motor2, true);
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
    stepLevel = false;
    digitalWrite(motor1.step_pin, LOW);
    digitalWrite(motor2.step_pin, LOW);
    lastStepMicros = micros();

    if (currentMotion != MOTION_NONE) {
      applyDirections(currentMotion);
    }
  }

  if (currentMotion == MOTION_NONE) {
    return;
  }

  uint32_t now = micros();
  if ((uint32_t)(now - lastStepMicros) >= STEP_HALF_PERIOD_US) {
    lastStepMicros = now;
    stepLevel = !stepLevel;
    digitalWrite(motor1.step_pin, stepLevel ? HIGH : LOW);
    digitalWrite(motor2.step_pin, stepLevel ? HIGH : LOW);
  }
}

static void init_stepper_motors() {
  bool ok1 = Stepper_Init(
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

  bool ok2 = Stepper_Init(
    &motor2,
    &Serial2,
    TMC2_RX_PIN,
    TMC2_TX_PIN,
    0b00,
    STEP_PIN2,
    DIR_PIN2,
    EN_PIN2,
    false,
    true,
    STEPS_PER_REV,
    R_SENSE,
    DRIVER_CURRENT_MA,
    DRIVER_MICROSTEPS
  );

  if (!ok1 || !ok2) {
    Serial.println("Stepper init failed");
    return;
  }

  bool begin1 = Stepper_Begin(&motor1, UART_BAUDRATE);
  bool begin2 = Stepper_Begin(&motor2, UART_BAUDRATE);

  if (!begin1 || !begin2) {
    Serial.println("Stepper UART/TMC begin failed");
    return;
  }

  Stepper_Enable(&motor1);
  Stepper_Enable(&motor2);

  Serial.print("Motor1 test_connection: ");
  Serial.println(Stepper_TestConnection(&motor1));
  Serial.print("Motor2 test_connection: ");
  Serial.println(Stepper_TestConnection(&motor2));
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

