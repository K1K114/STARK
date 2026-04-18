/**
 * StarkHacks 2026 — Gantry Controller Firmware
 * Target: ESP32 (Arduino framework via PlatformIO)
 *
 * Serial protocol (115200 baud, newline-terminated):
 *   Host → ESP32:
 *     MOVE <from> <to>   e.g. "MOVE e2 e4"
 *     CAPTURE <square>   e.g. "CAPTURE d5"  (remove piece to side pocket)
 *     RETURN <square>    e.g. "RETURN e4"   (illegal move — put piece back)
 *     HOME               return to rest position
 *
 *   ESP32 → Host:
 *     MOVING             command acknowledged, gantry started
 *     DONE               move complete, electromagnet released
 *     ERROR <msg>        something went wrong
 *
 * Build with PlatformIO:
 *   cd stark-chess-firmware
 *   pio run --target upload
 */

#include <Arduino.h>

// --- Pin assignments (adjust for your wiring) ---
#define MAGNET_PIN    26    // electromagnet relay/MOSFET gate
#define STEPPER_X_STEP  18
#define STEPPER_X_DIR   19
#define STEPPER_Y_STEP  21
#define STEPPER_Y_DIR   22
#define ENDSTOP_X       34
#define ENDSTOP_Y       35

// --- Board geometry ---
// Distance in stepper steps between adjacent squares.
// Calibrate by measuring your actual board and gear ratio.
#define STEPS_PER_SQUARE  200

// --- State ---
String inputBuffer = "";

// --- Forward declarations ---
void homeGantry();
void moveToSquare(int col, int row);
void setMagnet(bool on);
bool parseSquare(const String& sq, int& col, int& row);
void handleCommand(const String& cmd);

// ---------------------------------------------------------------

void setup() {
  Serial.begin(115200);

  pinMode(MAGNET_PIN, OUTPUT);
  pinMode(STEPPER_X_STEP, OUTPUT);
  pinMode(STEPPER_X_DIR, OUTPUT);
  pinMode(STEPPER_Y_STEP, OUTPUT);
  pinMode(STEPPER_Y_DIR, OUTPUT);
  pinMode(ENDSTOP_X, INPUT_PULLUP);
  pinMode(ENDSTOP_Y, INPUT_PULLUP);

  setMagnet(false);
  homeGantry();

  Serial.println("READY");
}

void loop() {
  // Read serial one character at a time into buffer
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      inputBuffer.trim();
      if (inputBuffer.length() > 0) {
        handleCommand(inputBuffer);
      }
      inputBuffer = "";
    } else {
      inputBuffer += c;
    }
  }
}

// ---------------------------------------------------------------
// Command dispatcher
// ---------------------------------------------------------------

void handleCommand(const String& cmd) {
  Serial.println("MOVING");

  if (cmd == "HOME") {
    homeGantry();
    Serial.println("DONE");
    return;
  }

  if (cmd.startsWith("MOVE ")) {
    // "MOVE e2 e4"
    String parts = cmd.substring(5);
    int space = parts.indexOf(' ');
    if (space < 0) { Serial.println("ERROR bad MOVE syntax"); return; }
    String fromSq = parts.substring(0, space);
    String toSq   = parts.substring(space + 1);

    int fc, fr, tc, tr;
    if (!parseSquare(fromSq, fc, fr) || !parseSquare(toSq, tc, tr)) {
      Serial.println("ERROR bad square");
      return;
    }

    moveToSquare(fc, fr);
    setMagnet(true);
    delay(200);            // let magnet grab the piece
    moveToSquare(tc, tr);
    setMagnet(false);
    delay(200);            // let piece settle before releasing
    Serial.println("DONE");
    return;
  }

  if (cmd.startsWith("CAPTURE ")) {
    // Move captured piece to off-board pocket at (-1, -1)
    String sq = cmd.substring(8);
    int col, row;
    if (!parseSquare(sq, col, row)) { Serial.println("ERROR bad square"); return; }
    moveToSquare(col, row);
    setMagnet(true);
    delay(200);
    // Move to pocket — adjust coordinates for your board layout
    moveToSquare(-1, -1);
    setMagnet(false);
    delay(200);
    Serial.println("DONE");
    return;
  }

  if (cmd.startsWith("RETURN ")) {
    // Same as CAPTURE but moves piece back from where it is now —
    // the host is responsible for calling MOVE first then RETURN if needed.
    // For now just report done; implement as needed.
    Serial.println("DONE");
    return;
  }

  Serial.println("ERROR unknown command");
}

// ---------------------------------------------------------------
// Motion primitives
// ---------------------------------------------------------------

void homeGantry() {
  // Drive X then Y toward endstops
  // TODO: implement endstop-based homing for your stepper driver
  // Placeholder: just delay to simulate homing time
  delay(500);
}

void moveToSquare(int col, int row) {
  // TODO: implement actual stepper motion.
  // col: 0 = a-file, 7 = h-file; row: 0 = rank 1, 7 = rank 8
  // For now this is a stub — replace with your CoreXY / Cartesian kinematics.
  long targetX = col * STEPS_PER_SQUARE;
  long targetY = row * STEPS_PER_SQUARE;

  // Drive steppers to (targetX, targetY)
  // ... your motion code here ...
  delay(300);  // placeholder delay
}

void setMagnet(bool on) {
  digitalWrite(MAGNET_PIN, on ? HIGH : LOW);
}

// ---------------------------------------------------------------
// Square parsing: "e4" → col=4, row=3
// ---------------------------------------------------------------

bool parseSquare(const String& sq, int& col, int& row) {
  if (sq.length() < 2) return false;
  char file = sq[0];  // 'a'–'h'
  char rank = sq[1];  // '1'–'8'
  if (file < 'a' || file > 'h') return false;
  if (rank < '1' || rank > '8') return false;
  col = file - 'a';   // 0–7
  row = rank - '1';   // 0–7
  return true;
}
