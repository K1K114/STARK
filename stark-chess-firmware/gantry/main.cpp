#include <Arduino.h>
#include <AccelStepper.h>
#include "TMC2209_Driver.h"

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

// NC limit switches: CLOSED to GND in normal state, OPEN when triggered.
// With INPUT_PULLUP: normal = LOW, triggered = HIGH.
#define X_HOME_PIN 9
#define Y_HOME_PIN 10

#define UART_BAUDRATE 115200
#define STEPS_PER_REV 6400
#define DRIVER_CURRENT_MA 800
#define DRIVER_MICROSTEPS 32

// Jog tuning for manual control via buttons.
static float jogSpeedM1Steps = 600.0f;
static float ratioLeft = 2.40f;
static float ratioRight = 2.40f;
static float ratioUp = 2.40f;
static float ratioDown = 2.40f;

// Homing tuning.
static float homeFastSpeedM1Steps = 120.0f;
static float homeSlowSpeedM1Steps = 40.0f;
static const uint32_t HOME_BACKOFF_MS = 500;
static const uint32_t HOME_PHASE_TIMEOUT_MS = 30000;

enum MotionMode {
  MOTION_NONE,
  MOTION_LEFT,
  MOTION_RIGHT,
  MOTION_UP,
  MOTION_DOWN
};

enum HomingState {
  HOMING_IDLE,
  HOMING_X_CLEAR,
  HOMING_X_SEEK_FAST,
  HOMING_X_BACKOFF,
  HOMING_X_SEEK_SLOW,
  HOMING_Y_CLEAR,
  HOMING_Y_SEEK_FAST,
  HOMING_Y_BACKOFF,
  HOMING_Y_SEEK_SLOW,
  HOMING_DONE,
  HOMING_FAULT
};

TMC2209Driver motor1;
AccelStepper stepper1(AccelStepper::DRIVER, STEP_PIN1, DIR_PIN1);
AccelStepper stepper2(AccelStepper::DRIVER, STEP_PIN2, DIR_PIN2);
static MotionMode currentMotion = MOTION_NONE;
static bool homed = false;
static HomingState homingState = HOMING_IDLE;
static uint32_t homingPhaseStartMs = 0;
static uint32_t homingBackoffStartMs = 0;

static void applyMotionSpeeds(MotionMode mode);

// Configure which gantry direction moves each axis toward its home switch.
static const MotionMode X_HOME_TOWARD_SWITCH = MOTION_RIGHT;
static const MotionMode Y_HOME_TOWARD_SWITCH = MOTION_UP;

static float positive(float v) {
  return (v < 0.0f) ? -v : v;
}

static void printTuning() {
  Serial.println("---- Gantry Tuning ----");
  Serial.print("speed ");
  Serial.println(jogSpeedM1Steps, 3);
  Serial.print("ratio l ");
  Serial.println(ratioLeft, 4);
  Serial.print("ratio r ");
  Serial.println(ratioRight, 4);
  Serial.print("ratio u ");
  Serial.println(ratioUp, 4);
  Serial.print("ratio d ");
  Serial.println(ratioDown, 4);
  Serial.println("Commands:");
  Serial.println("  show");
  Serial.println("  speed <float>");
  Serial.println("  ratio <l|r|u|d> <float>");
  Serial.println("  home");
  Serial.println("  home stop");
  Serial.println("  home status");
  Serial.println("-----------------------");
}

static bool xHomeTriggered() {
  return digitalRead(X_HOME_PIN) == HIGH;
}

static bool yHomeTriggered() {
  return digitalRead(Y_HOME_PIN) == HIGH;
}

static MotionMode oppositeMotion(MotionMode mode) {
  switch (mode) {
    case MOTION_LEFT: return MOTION_RIGHT;
    case MOTION_RIGHT: return MOTION_LEFT;
    case MOTION_UP: return MOTION_DOWN;
    case MOTION_DOWN: return MOTION_UP;
    case MOTION_NONE:
    default:
      return MOTION_NONE;
  }
}

static void setMotionWithBaseSpeed(MotionMode mode, float baseSpeedM1) {
  float savedSpeed = jogSpeedM1Steps;
  jogSpeedM1Steps = baseSpeedM1;
  currentMotion = mode;
  applyMotionSpeeds(currentMotion);
  jogSpeedM1Steps = savedSpeed;
}

static bool isCurrentPhaseTimedOut() {
  return (millis() - homingPhaseStartMs) > HOME_PHASE_TIMEOUT_MS;
}

static void enterHomingFault(const __FlashStringHelper *message) {
  setMotionWithBaseSpeed(MOTION_NONE, homeFastSpeedM1Steps);
  homingState = HOMING_FAULT;
  Serial.print("Homing fault: ");
  Serial.println(message);
}

static void startHoming() {
  homed = false;
  homingState = HOMING_X_CLEAR;
  homingPhaseStartMs = millis();
  setMotionWithBaseSpeed(oppositeMotion(X_HOME_TOWARD_SWITCH), homeFastSpeedM1Steps);
  Serial.println("Homing started");
}

static void stopHoming() {
  setMotionWithBaseSpeed(MOTION_NONE, homeFastSpeedM1Steps);
  homingState = HOMING_IDLE;
  Serial.println("Homing stopped");
}

static bool isAxisSwitchTriggered(MotionMode axisTowardSwitch) {
  if (axisTowardSwitch == X_HOME_TOWARD_SWITCH) {
    return xHomeTriggered();
  }
  return yHomeTriggered();
}

static void runCurrentMotionStep() {
  if (currentMotion == MOTION_NONE) {
    return;
  }
  stepper1.runSpeed();
  stepper2.runSpeed();
}

static void runHomingStateMachine() {
  if (homingState == HOMING_IDLE || homingState == HOMING_DONE || homingState == HOMING_FAULT) {
    return;
  }

  runCurrentMotionStep();

  if (isCurrentPhaseTimedOut()) {
    enterHomingFault(F("phase timeout"));
    return;
  }

  switch (homingState) {
    case HOMING_X_CLEAR:
      if (!xHomeTriggered()) {
        homingState = HOMING_X_SEEK_FAST;
        homingPhaseStartMs = millis();
        setMotionWithBaseSpeed(X_HOME_TOWARD_SWITCH, homeFastSpeedM1Steps);
        Serial.println("Homing X fast seek");
      }
      break;

    case HOMING_X_SEEK_FAST:
      if (xHomeTriggered()) {
        homingState = HOMING_X_BACKOFF;
        homingPhaseStartMs = millis();
        homingBackoffStartMs = millis();
        setMotionWithBaseSpeed(oppositeMotion(X_HOME_TOWARD_SWITCH), homeFastSpeedM1Steps);
        Serial.println("Homing X backoff");
      }
      break;

    case HOMING_X_BACKOFF:
      if ((millis() - homingBackoffStartMs) >= HOME_BACKOFF_MS) {
        homingState = HOMING_X_SEEK_SLOW;
        homingPhaseStartMs = millis();
        setMotionWithBaseSpeed(X_HOME_TOWARD_SWITCH, homeSlowSpeedM1Steps);
        Serial.println("Homing X slow seek");
      }
      break;

    case HOMING_X_SEEK_SLOW:
      if (xHomeTriggered()) {
        setMotionWithBaseSpeed(MOTION_NONE, homeFastSpeedM1Steps);
        homingState = HOMING_Y_CLEAR;
        homingPhaseStartMs = millis();
        setMotionWithBaseSpeed(oppositeMotion(Y_HOME_TOWARD_SWITCH), homeFastSpeedM1Steps);
        Serial.println("Homing Y clear");
      }
      break;

    case HOMING_Y_CLEAR:
      if (!yHomeTriggered()) {
        homingState = HOMING_Y_SEEK_FAST;
        homingPhaseStartMs = millis();
        setMotionWithBaseSpeed(Y_HOME_TOWARD_SWITCH, homeFastSpeedM1Steps);
        Serial.println("Homing Y fast seek");
      }
      break;

    case HOMING_Y_SEEK_FAST:
      if (yHomeTriggered()) {
        homingState = HOMING_Y_BACKOFF;
        homingPhaseStartMs = millis();
        homingBackoffStartMs = millis();
        setMotionWithBaseSpeed(oppositeMotion(Y_HOME_TOWARD_SWITCH), homeFastSpeedM1Steps);
        Serial.println("Homing Y backoff");
      }
      break;

    case HOMING_Y_BACKOFF:
      if ((millis() - homingBackoffStartMs) >= HOME_BACKOFF_MS) {
        homingState = HOMING_Y_SEEK_SLOW;
        homingPhaseStartMs = millis();
        setMotionWithBaseSpeed(Y_HOME_TOWARD_SWITCH, homeSlowSpeedM1Steps);
        Serial.println("Homing Y slow seek");
      }
      break;

    case HOMING_Y_SEEK_SLOW:
      if (yHomeTriggered()) {
        setMotionWithBaseSpeed(MOTION_NONE, homeFastSpeedM1Steps);
        stepper1.setCurrentPosition(0);
        stepper2.setCurrentPosition(0);
        homed = true;
        homingState = HOMING_DONE;
        Serial.println("Homing complete. Position set to (0,0)");
      }
      break;

    case HOMING_DONE:
    case HOMING_FAULT:
    case HOMING_IDLE:
    default:
      break;
  }
}

static void printHomeStatus() {
  Serial.print("home x=");
  Serial.print(xHomeTriggered() ? "TRIG" : "OPEN");
  Serial.print(" y=");
  Serial.print(yHomeTriggered() ? "TRIG" : "OPEN");
  Serial.print(" state=");
  Serial.print((int)homingState);
  Serial.print(" homed=");
  Serial.println(homed ? "yes" : "no");
}

static MotionMode readMotionFromButtons() {
  if (digitalRead(LEFT_PIN) == LOW) return MOTION_LEFT;
  if (digitalRead(RIGHT_PIN) == LOW) return MOTION_RIGHT;
  if (digitalRead(UP_PIN) == LOW) return MOTION_UP;
  if (digitalRead(DOWN_PIN) == LOW) return MOTION_DOWN;
  return MOTION_NONE;
}

static void applyMotionSpeeds(MotionMode mode) {
  float m1Speed = 0.0f;
  float m2Speed = 0.0f;

  switch (mode) {
    case MOTION_LEFT:
      // LEFT: M1 CW, M2 CW
      m1Speed = jogSpeedM1Steps;
      m2Speed = jogSpeedM1Steps * ratioLeft;
      break;
    case MOTION_RIGHT:
      // RIGHT: M1 CCW, M2 CCW
      m1Speed = -jogSpeedM1Steps;
      m2Speed = -jogSpeedM1Steps * ratioRight;
      break;
    case MOTION_UP:
      // UP: M1 CW, M2 CCW
      m1Speed = jogSpeedM1Steps;
      m2Speed = -jogSpeedM1Steps * ratioUp;
      break;
    case MOTION_DOWN:
      // DOWN: M1 CCW, M2 CW
      m1Speed = -jogSpeedM1Steps;
      m2Speed = jogSpeedM1Steps * ratioDown;
      break;
    case MOTION_NONE:
    default:
      m1Speed = 0.0f;
      m2Speed = 0.0f;
      break;
  }

  stepper1.setMaxSpeed(positive(jogSpeedM1Steps));
  // Keep headroom above active ratio values for live tuning updates.
  stepper2.setMaxSpeed(positive(jogSpeedM1Steps) * 4.0f);
  stepper1.setSpeed(m1Speed);
  stepper2.setSpeed(m2Speed);
}

static void handleSerialTuning() {
  if (!Serial.available()) {
    return;
  }

  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) {
    return;
  }

  if (line.equalsIgnoreCase("show")) {
    printTuning();
    return;
  }

  if (line.equalsIgnoreCase("home")) {
    startHoming();
    return;
  }

  if (line.equalsIgnoreCase("home stop")) {
    stopHoming();
    return;
  }

  if (line.equalsIgnoreCase("home status")) {
    printHomeStatus();
    return;
  }

  if (line.startsWith("speed ")) {
    float value = line.substring(6).toFloat();
    if (value <= 0.0f) {
      Serial.println("ERR speed must be > 0");
      return;
    }
    jogSpeedM1Steps = value;
    applyMotionSpeeds(currentMotion);
    Serial.print("OK speed ");
    Serial.println(jogSpeedM1Steps, 3);
    return;
  }

  if (line.startsWith("ratio ")) {
    int spaceIndex = line.indexOf(' ', 6);
    if (spaceIndex < 0) {
      Serial.println("ERR usage: ratio <l|r|u|d> <float>");
      return;
    }

    String dir = line.substring(6, spaceIndex);
    String valueStr = line.substring(spaceIndex + 1);
    dir.trim();
    valueStr.trim();

    float ratioValue = valueStr.toFloat();
    if (ratioValue <= 0.0f) {
      Serial.println("ERR ratio must be > 0");
      return;
    }

    if (dir.equalsIgnoreCase("l")) {
      ratioLeft = ratioValue;
    } else if (dir.equalsIgnoreCase("r")) {
      ratioRight = ratioValue;
    } else if (dir.equalsIgnoreCase("u")) {
      ratioUp = ratioValue;
    } else if (dir.equalsIgnoreCase("d")) {
      ratioDown = ratioValue;
    } else {
      Serial.println("ERR dir must be l/r/u/d");
      return;
    }

    applyMotionSpeeds(currentMotion);
    Serial.print("OK ratio ");
    Serial.print(dir);
    Serial.print(' ');
    Serial.println(ratioValue, 4);
    return;
  }

  Serial.println("ERR unknown cmd. Use: show | speed <v> | ratio <l|r|u|d> <v>");
}

static void runSteppersWhileHeld() {
  if (homingState != HOMING_IDLE && homingState != HOMING_DONE && homingState != HOMING_FAULT) {
    return;
  }

  MotionMode requested = readMotionFromButtons();

  if (requested != currentMotion) {
    currentMotion = requested;
    applyMotionSpeeds(currentMotion);
  }

  if (currentMotion == MOTION_NONE) {
    return;
  }

  stepper1.runSpeed();
  stepper2.runSpeed();
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

  if (!ok1) {
    Serial.println("Stepper init failed");
    return;
  }

  bool begin1 = TMC2209_Begin(&motor1, UART_BAUDRATE);

  if (!begin1) {
    Serial.println("Stepper UART/TMC begin failed");
    return;
  }

  TMC2209_Enable(&motor1);
  pinMode(EN_PIN2, OUTPUT);
  digitalWrite(EN_PIN2, LOW);  // DRV8825 EN is active LOW

  TMC2209_SetPulseWidthUs(&motor1, 2);

  stepper1.setEnablePin(EN_PIN1);
  stepper1.setPinsInverted(false, false, true);
  stepper1.setMinPulseWidth(2);
  stepper1.setMaxSpeed(positive(jogSpeedM1Steps));
  stepper1.enableOutputs();

  stepper2.setEnablePin(EN_PIN2);
  stepper2.setPinsInverted(false, false, true);
  stepper2.setMinPulseWidth(2);
  stepper2.setMaxSpeed(positive(jogSpeedM1Steps) * 4.0f);
  stepper2.enableOutputs();

  applyMotionSpeeds(MOTION_NONE);

  Serial.print("Motor1 test_connection: ");
  Serial.println(TMC2209_TestConnection(&motor1));
  Serial.println("Motor2 DRV8825 ready (AccelStepper step/dir)");
  Serial.println("Both steppers initialized with AccelStepper control");
  printTuning();
  printHomeStatus();
}

void setup() { 
  pinMode(LEFT_PIN, INPUT_PULLUP);
  pinMode(RIGHT_PIN, INPUT_PULLUP);
  pinMode(UP_PIN, INPUT_PULLUP);
  pinMode(DOWN_PIN, INPUT_PULLUP);
  pinMode(X_HOME_PIN, INPUT_PULLUP);
  pinMode(Y_HOME_PIN, INPUT_PULLUP);

  Serial.begin(115200);
  Serial.setTimeout(25);
  Serial.println("Gantry startup");

  init_stepper_motors();
}

void loop() { 
  handleSerialTuning();
  runHomingStateMachine();
  runSteppersWhileHeld();
}

