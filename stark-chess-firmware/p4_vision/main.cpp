/*
 * ESP32-P4 Vision Firmware — STARK Chess Board (play mode + local HTTP)
 *
 * - WiFi: WPA2-Enterprise (credentials from p4_vision/.env via load_env.py).
 * - Outbound HTTP to STARK server: POST /connect, GET /game_state, POST /make_move.
 * - WS2812: flash engine moves using custom file/rank LED index groups.
 * - Local WebServer (port 80): POST /set_reference, GET /poll_move, GET /infer, GET /frame
 */

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <cctype>
#include <cstring>
#include <WebServer.h>
#include <ArduinoJson.h>
#include <Adafruit_NeoPixel.h>
#include "esp_wpa2.h"
#include "esp_camera.h"

// Injected by PlatformIO pre:load_env.py (defaults if building without script)
#ifndef WIFI_SSID
#define WIFI_SSID "PAL3.0"
#endif
#ifndef WIFI_USERNAME
#define WIFI_USERNAME "user"
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "password"
#endif
#ifndef STARK_SERVER_HOST
#define STARK_SERVER_HOST "192.168.1.100"
#endif
#ifndef STARK_SERVER_PORT
#define STARK_SERVER_PORT 8000
#endif
#ifndef LED_DATA_PIN
#define LED_DATA_PIN 39
#endif
#ifndef NEOPIXEL_COUNT
#define NEOPIXEL_COUNT 48
#endif

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

#define MAE_THRESHOLD  5.0f
#define SETTLE_FRAMES  30

#define HTTP_TIMEOUT_MS 20000
#define WIFI_RETRY_INTERVAL_MS 5000
#define GAME_STATE_POLL_MS 4000
#define STARK_RECONNECT_COOLDOWN_MS 3000

// ─────────────────────────────────────────────────────────────
WebServer server(80);

static uint8_t* refFrame  = nullptr;
static size_t   frameSize = 0;

enum MotionState { WAITING, MOVING, SETTLING };
static MotionState motionState = WAITING;
static int stableCount = 0;

static bool  moveReady = false;
static char  moveUCI[8] = {0};

static void runYOLOAndDetermineMove(const uint8_t* gray);

#if NEOPIXEL_COUNT > 0
static Adafruit_NeoPixel strip(NEOPIXEL_COUNT, LED_DATA_PIN, NEO_GRB + NEO_KHZ800);
#endif

// ── Custom LED map: variable-length groups per file / rank ───
struct LedVarGroup {
    uint8_t n;
    uint8_t idx[4];
};

// a..h
static const LedVarGroup kFileGroups[8] = {
    {2, {2, 3, 0, 0}},
    {2, {5, 6, 0, 0}},
    {2, {7, 8, 0, 0}},
    {2, {9, 10, 0, 0}},
    {3, {11, 12, 13, 0}},
    {2, {14, 15, 0, 0}},
    {2, {16, 17, 0, 0}},
    {2, {18, 19, 0, 0}},
};

// rank 1..8 (index 0 = rank 1)
static const LedVarGroup kRankGroups[8] = {
    {3, {23, 24, 25, 0}},
    {2, {26, 27, 0, 0}},
    {2, {28, 29, 0, 0}},
    {2, {30, 31, 0, 0}},
    {3, {32, 33, 34, 0}},
    {2, {35, 36, 0, 0}},
    {2, {37, 38, 0, 0}},
    {2, {39, 40, 0, 0}},
};

static int fileIndexFromChar(char f) {
    f = static_cast<char>(tolower(static_cast<unsigned char>(f)));
    if (f < 'a' || f > 'h') return -1;
    return f - 'a';
}

static int rankIndexFromChar(char r) {
    if (r < '1' || r > '8') return -1;
    return r - '1';
}

static void appendGroupUnique(uint8_t* out, uint8_t* nOut, uint8_t maxOut, const LedVarGroup& g) {
    for (uint8_t i = 0; i < g.n; i++) {
        uint8_t v = g.idx[i];
        bool dup = false;
        for (uint8_t j = 0; j < *nOut; j++) {
            if (out[j] == v) { dup = true; break; }
        }
        if (dup) continue;
        if (*nOut < maxOut) out[(*nOut)++] = v;
    }
}

static void fillSquareIndices(const char sq[3], uint8_t* out, uint8_t* nOut, uint8_t maxOut) {
    *nOut = 0;
    if (!sq || strlen(sq) < 2) return;
    int fi = fileIndexFromChar(sq[0]);
    int ri = rankIndexFromChar(sq[1]);
    if (fi < 0 || ri < 0) return;
    appendGroupUnique(out, nOut, maxOut, kFileGroups[fi]);
    appendGroupUnique(out, nOut, maxOut, kRankGroups[ri]);
}

static bool parseUciSquares(const char* uci, char fromSq[3], char toSq[3]) {
    if (!uci) return false;
    size_t len = strlen(uci);
    if (len < 4) return false;
    fromSq[0] = uci[0];
    fromSq[1] = uci[1];
    fromSq[2] = '\0';
    toSq[0] = uci[2];
    toSq[1] = uci[3];
    toSq[2] = '\0';
    return true;
}

enum LedPhase {
    LEDP_IDLE = 0,
    LEDP_FROM,
    LEDP_GAP1,
    LEDP_TO,
    LEDP_GAP2,
};

struct LedFlashState {
    LedPhase phase;
    uint32_t phaseStartMs;
    uint8_t  repeatCount;
    uint8_t  indicesFrom[16];
    uint8_t  nFrom;
    uint8_t  indicesTo[16];
    uint8_t  nTo;
};

static LedFlashState gLedFlash = {};

static void stripClear() {
#if NEOPIXEL_COUNT > 0
    strip.clear();
    strip.show();
#endif
}

static void stripApplyGroup(const uint8_t* idx, uint8_t n, uint8_t r, uint8_t g, uint8_t b) {
#if NEOPIXEL_COUNT > 0
    strip.clear();
    for (uint8_t i = 0; i < n; i++) {
        int p = idx[i];
        if (p >= 0 && p < NEOPIXEL_COUNT) {
            strip.setPixelColor(static_cast<uint16_t>(p), strip.Color(r, g, b));
        }
    }
    strip.setBrightness(120);
    strip.show();
#else
    (void)idx;
    (void)n;
    (void)r;
    (void)g;
    (void)b;
#endif
}

static void ledFlashStart(const char* uci) {
    char fromSq[3], toSq[3];
    if (!parseUciSquares(uci, fromSq, toSq)) {
        Serial.printf("[LED] bad UCI for flash: %s\n", uci ? uci : "(null)");
        return;
    }
    fillSquareIndices(fromSq, gLedFlash.indicesFrom, &gLedFlash.nFrom, sizeof(gLedFlash.indicesFrom));
    fillSquareIndices(toSq, gLedFlash.indicesTo, &gLedFlash.nTo, sizeof(gLedFlash.indicesTo));
    gLedFlash.phase = LEDP_FROM;
    gLedFlash.phaseStartMs = millis();
    gLedFlash.repeatCount = 0;
    Serial.printf("[LED] flash engine move %s (from=%zu to=%zu pixels)\n",
                  uci, (size_t)gLedFlash.nFrom, (size_t)gLedFlash.nTo);
}

static void ledFlashTick() {
    if (gLedFlash.phase == LEDP_IDLE) return;

    const uint32_t FROM_MS = 550;
    const uint32_t TO_MS = 550;
    const uint32_t GAP_MS = 120;
    const uint8_t MAX_CYCLES = 4;

    uint32_t now = millis();
    uint32_t dt = now - gLedFlash.phaseStartMs;

    switch (gLedFlash.phase) {
        case LEDP_FROM:
            stripApplyGroup(gLedFlash.indicesFrom, gLedFlash.nFrom, 80, 80, 255);
            if (dt >= FROM_MS) {
                stripClear();
                gLedFlash.phase = LEDP_GAP1;
                gLedFlash.phaseStartMs = now;
            }
            break;
        case LEDP_GAP1:
            if (dt >= GAP_MS) {
                gLedFlash.phase = LEDP_TO;
                gLedFlash.phaseStartMs = now;
            }
            break;
        case LEDP_TO:
            stripApplyGroup(gLedFlash.indicesTo, gLedFlash.nTo, 0, 220, 60);
            if (dt >= TO_MS) {
                stripClear();
                gLedFlash.phase = LEDP_GAP2;
                gLedFlash.phaseStartMs = now;
            }
            break;
        case LEDP_GAP2:
            if (dt >= GAP_MS) {
                gLedFlash.repeatCount++;
                if (gLedFlash.repeatCount >= MAX_CYCLES) {
                    gLedFlash.phase = LEDP_IDLE;
                    stripClear();
                } else {
                    gLedFlash.phase = LEDP_FROM;
                    gLedFlash.phaseStartMs = now;
                }
            }
            break;
        default:
            gLedFlash.phase = LEDP_IDLE;
            stripClear();
            break;
    }
}

// ── STARK HTTP client ─────────────────────────────────────────
static bool     gStarkSessionOk = false;
static bool     gLastHumanTurn = true;
static uint32_t gLastGameStatePollMs = 0;
static uint32_t gLastWifiReconnectMs = 0;
static uint32_t gLastStarkReconnectMs = 0;

static String starkBaseUrl() {
    return String("http://") + STARK_SERVER_HOST + ":" + String(STARK_SERVER_PORT);
}

static int httpPostJson(const char* path, const char* jsonBody, String& responseOut) {
    HTTPClient http;
    String url = starkBaseUrl() + path;
    http.setTimeout(HTTP_TIMEOUT_MS);
    if (!http.begin(url)) {
        Serial.printf("[HTTP] begin failed: %s\n", url.c_str());
        return -1;
    }
    http.addHeader("Content-Type", "application/json");
    int code = http.POST(jsonBody);
    responseOut = http.getString();
    http.end();
    return code;
}

static int httpGetPath(const char* path, String& responseOut) {
    HTTPClient http;
    String url = starkBaseUrl() + path;
    http.setTimeout(HTTP_TIMEOUT_MS);
    if (!http.begin(url)) return -1;
    int code = http.GET();
    responseOut = http.getString();
    http.end();
    return code;
}

/** Optional: GET /hardware/move_hint (no /connect required on server). */
static int starkGetMoveHint(String& responseOut) {
    return httpGetPath("/hardware/move_hint", responseOut);
}

static bool starkPostConnect() {
    String body;
    int code = httpPostJson("/connect", "{\"mode\":\"playing\",\"human_color\":\"white\"}", body);
    Serial.printf("[STARK] POST /connect -> %d %s\n", code, body.substring(0, 120).c_str());
    if (code != 200) return false;

    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, body);
    if (err) {
        Serial.printf("[STARK] connect JSON err: %s\n", err.c_str());
        return false;
    }
    const char* mode = doc["mode"];
    if (!mode || strcmp(mode, "playing") != 0) {
        Serial.println("[STARK] connect: unexpected mode");
        return false;
    }
    gStarkSessionOk = true;
    return true;
}

static bool starkRefreshGameState() {
    String body;
    int code = httpGetPath("/game_state", body);
    if (code == 503) {
        gStarkSessionOk = false;
        return false;
    }
    if (code != 200) {
        Serial.printf("[STARK] GET /game_state -> %d\n", code);
        return false;
    }
    JsonDocument doc;
    if (deserializeJson(doc, body)) return false;
    gLastHumanTurn = doc["is_human_turn"] | true;
    const char* gs = doc["game_status"];
    if (gs && strlen(gs) > 0) {
        Serial.printf("[STARK] game_status=%s\n", gs);
    }
    return true;
}

static int starkPostMakeMove(const char* uci, String& responseOut) {
    char payload[48];
    snprintf(payload, sizeof(payload), "{\"uci\":\"%s\"}", uci);
    int code = httpPostJson("/make_move", payload, responseOut);
    Serial.printf("[STARK] POST /make_move %s -> %d\n", uci, code);
    if (code == 503) gStarkSessionOk = false;
    return code;
}

static void starkTryRecoverSession() {
    uint32_t now = millis();
    if (now - gLastStarkReconnectMs < STARK_RECONNECT_COOLDOWN_MS) return;
    gLastStarkReconnectMs = now;
    Serial.println("[STARK] attempting session recovery (POST /connect)...");
    starkPostConnect();
}

static void processSerialInject() {
    static char lineBuf[24];
    static uint8_t pos = 0;
    while (Serial.available()) {
        char c = static_cast<char>(Serial.read());
        if (c == '\r') continue;
        if (c == '\n') {
            lineBuf[pos] = '\0';
            pos = 0;
            if (strncmp(lineBuf, "uci ", 4) == 0) {
                const char* m = lineBuf + 4;
                if (strlen(m) >= 4 && strlen(m) <= 5) {
                    strncpy(moveUCI, m, sizeof(moveUCI) - 1);
                    moveUCI[sizeof(moveUCI) - 1] = '\0';
                    moveReady = true;
                    Serial.printf("[TEST] injected move %s\n", moveUCI);
                }
            }
            return;
        }
        if (pos < sizeof(lineBuf) - 1) lineBuf[pos++] = c;
    }
}

static void trySubmitHumanMove() {
    if (!gStarkSessionOk || !moveReady) return;
    if (!gLastHumanTurn) return;
    if (gLedFlash.phase != LEDP_IDLE) return;

    String resp;
    int code = starkPostMakeMove(moveUCI, resp);
    if (code != 200) {
        if (code == 400) {
            Serial.println("[STARK] illegal move — clearing local move");
            moveReady = false;
            moveUCI[0] = '\0';
        }
        if (code == 503 || code < 0) starkTryRecoverSession();
        return;
    }

    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, resp);
    if (err) {
        Serial.printf("[STARK] make_move JSON: %s\n", err.c_str());
        return;
    }

    moveReady = false;
    moveUCI[0] = '\0';

    if (!doc["engine_reply"].isNull()) {
        const char* engUci = doc["engine_reply"]["uci"];
        if (engUci && strlen(engUci) >= 4) {
            ledFlashStart(engUci);
        }
    } else {
        Serial.println("[STARK] no engine_reply (game over or engine skipped)");
    }

    starkRefreshGameState();
}

// ── Pixel diff ────────────────────────────────────────────────
static float computeMAE(const uint8_t* a, const uint8_t* b, size_t n) {
    uint32_t sum = 0;
    for (size_t i = 0; i < n; i++) sum += static_cast<uint32_t>(abs(static_cast<int>(a[i]) - static_cast<int>(b[i])));
    return static_cast<float>(sum) / static_cast<float>(n);
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
                runYOLOAndDetermineMove(gray);
            }
            break;
    }
}

#ifndef STARK_VISION_STUB
#define STARK_VISION_STUB 0
#endif

static void runYOLOAndDetermineMove(const uint8_t* gray) {
    (void)gray;
    // TODO: ESP-DL YOLO → real UCI from board diff.
#if STARK_VISION_STUB
    strncpy(moveUCI, "e2e4", sizeof(moveUCI) - 1);
    moveUCI[sizeof(moveUCI) - 1] = '\0';
    moveReady = true;
#endif
}

// ── HTTP handlers ─────────────────────────────────────────────
void handleSetReference() {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) { server.send(500, "text/plain", "CAMERA_ERROR"); return; }

    if (!refFrame || frameSize != fb->len) {
        free(refFrame);
        refFrame = static_cast<uint8_t*>(malloc(fb->len));
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

    String result = "e1:white_king,d1:white_queen";

    esp_camera_fb_return(fb);
    server.send(200, "text/plain", result);
}

void handleFrame() {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) { server.send(500, "text/plain", "CAMERA_ERROR"); return; }
    server.send_P(200, "image/jpeg", reinterpret_cast<const char*>(fb->buf), fb->len);
    esp_camera_fb_return(fb);
}

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
    cfg.pixel_format = PIXFORMAT_GRAYSCALE;
    cfg.frame_size   = FRAMESIZE_320X320;
    cfg.fb_count     = 2;
    return esp_camera_init(&cfg) == ESP_OK;
}

static void connectWiFi() {
    WiFi.disconnect(true);
    WiFi.mode(WIFI_STA);
    esp_wifi_sta_wpa2_ent_set_identity(reinterpret_cast<uint8_t*>(const_cast<char*>(WIFI_USERNAME)), strlen(WIFI_USERNAME));
    esp_wifi_sta_wpa2_ent_set_username(reinterpret_cast<uint8_t*>(const_cast<char*>(WIFI_USERNAME)), strlen(WIFI_USERNAME));
    esp_wifi_sta_wpa2_ent_set_password(reinterpret_cast<uint8_t*>(const_cast<char*>(WIFI_PASSWORD)), strlen(WIFI_PASSWORD));
    esp_wifi_sta_wpa2_ent_enable();
    WiFi.begin(WIFI_SSID);

    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        delay(300);
        Serial.print(".");
        if (millis() - start > 60000) {
            Serial.println("\n[WiFi] timeout, will retry in loop");
            return;
        }
    }
    Serial.printf("\n[WiFi] IP: %s\n", WiFi.localIP().toString().c_str());
}

static void wifiEnsureConnected() {
    if (WiFi.status() == WL_CONNECTED) return;
    uint32_t now = millis();
    if (now - gLastWifiReconnectMs < WIFI_RETRY_INTERVAL_MS) return;
    gLastWifiReconnectMs = now;
    Serial.println("[WiFi] disconnected — reconnecting");
    connectWiFi();
}

void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println("\n=== STARK P4 vision (play mode) ===");

    if (!initCamera()) { Serial.println("Camera init FAILED"); while (1) delay(1000); }
    Serial.println("Camera OK");

    connectWiFi();

#if NEOPIXEL_COUNT > 0
    strip.begin();
    strip.setBrightness(80);
    strip.clear();
    strip.show();
    Serial.printf("NeoPixel strip: %d LEDs on pin %d\n", NEOPIXEL_COUNT, LED_DATA_PIN);
#endif

    if (WiFi.status() == WL_CONNECTED) {
        String hintProbe;
        int hintCode = starkGetMoveHint(hintProbe);
        Serial.printf("[STARK] GET /hardware/move_hint -> %d (len=%u)\n", hintCode,
                      static_cast<unsigned>(hintProbe.length()));

        if (!starkPostConnect()) {
            Serial.println("[STARK] initial /connect failed — will retry when submitting moves");
        } else {
            starkRefreshGameState();
        }
    }

    server.on("/set_reference", HTTP_POST, handleSetReference);
    server.on("/poll_move",     HTTP_GET,  handlePollMove);
    server.on("/infer",         HTTP_GET,  handleInfer);
    server.on("/frame",         HTTP_GET,  handleFrame);
    server.begin();
    Serial.println("HTTP server on :80");
    Serial.println("Serial test: type  uci e2e4  + Enter to inject a move");
}

void loop() {
    wifiEnsureConnected();
    server.handleClient();
    processSerialInject();
    ledFlashTick();

    uint32_t now = millis();
    if (gStarkSessionOk && (now - gLastGameStatePollMs > GAME_STATE_POLL_MS)) {
        gLastGameStatePollMs = now;
        if (WiFi.status() == WL_CONNECTED) {
            if (!starkRefreshGameState()) {
                starkTryRecoverSession();
                if (gStarkSessionOk) starkRefreshGameState();
            }
        }
    }

    if (!gStarkSessionOk && WiFi.status() == WL_CONNECTED) {
        starkTryRecoverSession();
        if (gStarkSessionOk) starkRefreshGameState();
    }

    trySubmitHumanMove();
}
