/*
 * ESP32-P4 Vision Firmware — STARK Chess Board
 *
 * Connects to WiFi and exposes 4 HTTP endpoints:
 *   POST /set_reference  →  "OK"
 *   GET  /poll_move      →  "NONE" or "MOVE:e2e4"
 *   GET  /infer          →  "e1:white_king,e4:white_pawn,..."
 *   GET  /frame          →  raw JPEG bytes
 *
 * Internally runs pixel-diff move detection + YOLO via ESP-DL.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include "esp_wpa2.h"
#include "esp_camera.h"

// ── WiFi (PAL3.0 WPA2-Enterprise) ────────────────────────────
#define WIFI_SSID     "PAL3.0"
#define WIFI_USER     "your_purdue_username"
#define WIFI_PASS     "your_purdue_password"

// ── Camera pin config (adjust for your P4 board) ─────────────
#define CAM_PIN_PWDN  -1
#define CAM_PIN_RESET -1
#define CAM_PIN_XCLK  10
#define CAM_PIN_SIOD  40
#define CAM_PIN_SIOC  39
#define CAM_PIN_D7    48
#define CAM_PIN_D6    11
#define CAM_PIN_D5    12
#define CAM_PIN_D4    14
#define CAM_PIN_D3    16
#define CAM_PIN_D2    18
#define CAM_PIN_D1    17
#define CAM_PIN_D0    15
#define CAM_PIN_VSYNC 38
#define CAM_PIN_HREF  47
#define CAM_PIN_PCLK  13

// ── Pixel-diff tuning ─────────────────────────────────────────
#define MAE_THRESHOLD  5.0f   // mean-abs-error above this = motion
#define SETTLE_FRAMES  30     // consecutive stable frames before inferring

// ── TODO: include your ESP-DL model header ───────────────────
// #include "chess_yolo.hpp"

// ─────────────────────────────────────────────────────────────
WebServer server(80);

static uint8_t* refFrame  = nullptr;  // grayscale reference
static size_t   frameSize = 0;

// Motion-detection state machine
enum MotionState { WAITING, MOVING, SETTLING };
static MotionState motionState = WAITING;
static int stableCount = 0;

static bool  moveReady = false;
static char  moveUCI[8] = {0};  // e.g. "e2e4"

// ── Pixel diff core (~20 lines) ───────────────────────────────
static float computeMAE(const uint8_t* a, const uint8_t* b, size_t n) {
    uint32_t sum = 0;
    for (size_t i = 0; i < n; i++) sum += abs((int)a[i] - (int)b[i]);
    return (float)sum / n;
}

static void updateMotionState(const uint8_t* gray, size_t n) {
    if (!refFrame) return;
    bool moving = computeMAE(gray, refFrame, n) > MAE_THRESHOLD;

    switch (motionState) {
        case WAITING:
            if (moving) { motionState = MOVING; stableCount = 0; }
            break;
        case MOVING:
            if (!moving) { motionState = SETTLING; stableCount = 1; }
            break;
        case SETTLING:
            if (moving) { motionState = MOVING; stableCount = 0; }
            else if (++stableCount >= SETTLE_FRAMES) {
                motionState = WAITING;
                runYOLOAndDetermineMove(gray);  // hand off to inference
            }
            break;
    }
}

// ── YOLO inference ────────────────────────────────────────────
// Replace the body with your ESP-DL API calls.
// Input: 320×320 grayscale (or RGB if your model expects it).
// Outputs: fills moveUCI[] and sets moveReady = true.
static void runYOLOAndDetermineMove(const uint8_t* gray) {
    // TODO (teammate):
    //   1. Convert gray → RGB or resize to model input shape
    //   2. dl::Model model("chess_yolo_320_p4_int8.espdl");
    //   3. auto detections = model.run(gray, 320, 320);
    //   4. Compare detections against refFrame detections to find
    //      which square became empty (from-square) and which gained
    //      a piece (to-square), write "e2e4" into moveUCI[].
    //   5. Set moveReady = true.

    // Stub: hard-code a move so HTTP plumbing can be tested end-to-end
    strncpy(moveUCI, "e2e4", sizeof(moveUCI));
    moveReady = true;
}

// ── HTTP handlers ─────────────────────────────────────────────
void handleSetReference() {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) { server.send(500, "text/plain", "CAMERA_ERROR"); return; }

    if (!refFrame || frameSize != fb->len) {
        free(refFrame);
        refFrame = (uint8_t*)malloc(fb->len);
        frameSize = fb->len;
    }
    memcpy(refFrame, fb->buf, fb->len);
    esp_camera_fb_return(fb);

    moveReady = false;
    moveUCI[0] = '\0';
    motionState = WAITING;
    stableCount = 0;

    server.send(200, "text/plain", "OK");
}

void handlePollMove() {
    // Run one frame of pixel diff (non-blocking)
    camera_fb_t* fb = esp_camera_fb_get();
    if (fb) {
        updateMotionState(fb->buf, fb->len);
        esp_camera_fb_return(fb);
    }

    if (moveReady) {
        char resp[16];
        snprintf(resp, sizeof(resp), "MOVE:%s", moveUCI);
        server.send(200, "text/plain", resp);
    } else {
        server.send(200, "text/plain", "NONE");
    }
}

void handleInfer() {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) { server.send(500, "text/plain", "CAMERA_ERROR"); return; }

    // TODO (teammate): run full-board YOLO snapshot here and
    // build a comma-separated string like:
    //   "e1:white_king,d1:white_queen,..."
    String result = "e1:white_king,d1:white_queen";  // stub

    esp_camera_fb_return(fb);
    server.send(200, "text/plain", result);
}

void handleFrame() {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) { server.send(500, "text/plain", "CAMERA_ERROR"); return; }
    server.send_P(200, "image/jpeg", (const char*)fb->buf, fb->len);
    esp_camera_fb_return(fb);
}

// ── Camera init ───────────────────────────────────────────────
static bool initCamera() {
    camera_config_t cfg = {};
    cfg.ledc_channel = LEDC_CHANNEL_0;
    cfg.ledc_timer   = LEDC_TIMER_0;
    cfg.pin_d0 = CAM_PIN_D0; cfg.pin_d1 = CAM_PIN_D1;
    cfg.pin_d2 = CAM_PIN_D2; cfg.pin_d3 = CAM_PIN_D3;
    cfg.pin_d4 = CAM_PIN_D4; cfg.pin_d5 = CAM_PIN_D5;
    cfg.pin_d6 = CAM_PIN_D6; cfg.pin_d7 = CAM_PIN_D7;
    cfg.pin_xclk  = CAM_PIN_XCLK;
    cfg.pin_pclk  = CAM_PIN_PCLK;
    cfg.pin_vsync = CAM_PIN_VSYNC;
    cfg.pin_href  = CAM_PIN_HREF;
    cfg.pin_sscb_sda = CAM_PIN_SIOD;
    cfg.pin_sscb_scl = CAM_PIN_SIOC;
    cfg.pin_pwdn  = CAM_PIN_PWDN;
    cfg.pin_reset = CAM_PIN_RESET;
    cfg.xclk_freq_hz = 20000000;
    cfg.pixel_format = PIXFORMAT_GRAYSCALE;  // grey for pixel diff
    cfg.frame_size   = FRAMESIZE_320X320;
    cfg.fb_count     = 2;
    return esp_camera_init(&cfg) == ESP_OK;
}

// ── WiFi (WPA2-Enterprise) ────────────────────────────────────
static void connectWiFi() {
    WiFi.disconnect(true);
    WiFi.mode(WIFI_STA);
    esp_wifi_sta_wpa2_ent_set_identity((uint8_t*)WIFI_USER, strlen(WIFI_USER));
    esp_wifi_sta_wpa2_ent_set_username((uint8_t*)WIFI_USER, strlen(WIFI_USER));
    esp_wifi_sta_wpa2_ent_set_password((uint8_t*)WIFI_PASS, strlen(WIFI_PASS));
    esp_wifi_sta_wpa2_ent_enable();
    WiFi.begin(WIFI_SSID);
    while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
    Serial.printf("\nConnected — IP: %s\n", WiFi.localIP().toString().c_str());
}

// ─────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);

    if (!initCamera()) { Serial.println("Camera init FAILED"); while (1); }
    Serial.println("Camera OK");

    connectWiFi();

    server.on("/set_reference", HTTP_POST, handleSetReference);
    server.on("/poll_move",     HTTP_GET,  handlePollMove);
    server.on("/infer",         HTTP_GET,  handleInfer);
    server.on("/frame",         HTTP_GET,  handleFrame);
    server.begin();
    Serial.println("HTTP server running");
}

void loop() {
    server.handleClient();
}
