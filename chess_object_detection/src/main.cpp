#include <Arduino.h>

#include <stdint.h>
#include <string.h>

#if __has_include("dl_detect_base.hpp") && __has_include("dl_detect_yolo11_postprocessor.hpp") && \
    __has_include("dl_image_jpeg.hpp") && __has_include("dl_image_preprocessor.hpp") && __has_include("dl_model_base.hpp")
#define HAS_ESPDL 1
#include "dl_detect_base.hpp"
#include "dl_detect_yolo11_postprocessor.hpp"
#include "dl_image_jpeg.hpp"
#include "dl_image_preprocessor.hpp"
#include "dl_model_base.hpp"
#else
#define HAS_ESPDL 0
#endif

namespace {
constexpr int kBaudRate = 921600;
constexpr uint32_t kMaxFrameBytes = 250000;
constexpr uint32_t kReadTimeoutMs = 2000;
constexpr int kStatusLedPin = 2;

uint8_t *g_jpegBuf = nullptr;
uint32_t gFrameCount = 0;
uint32_t gDropCount = 0;
uint32_t gLastLogMs = 0;

bool readExact(uint8_t *dst, size_t len, uint32_t timeoutMs) {
  const uint32_t start = millis();
  size_t offset = 0;
  while (offset < len) {
    const int n = Serial.readBytes(reinterpret_cast<char *>(dst + offset), len - offset);
    if (n > 0) {
      offset += static_cast<size_t>(n);
      continue;
    }
    if (millis() - start > timeoutMs) {
      return false;
    }
    delay(1);
  }
  return true;
}

bool readFrameLengthLE(uint32_t &outLen) {
  uint8_t hdr[4];
  if (!readExact(hdr, sizeof(hdr), kReadTimeoutMs)) {
    return false;
  }
  outLen = static_cast<uint32_t>(hdr[0]) |
           (static_cast<uint32_t>(hdr[1]) << 8) |
           (static_cast<uint32_t>(hdr[2]) << 16) |
           (static_cast<uint32_t>(hdr[3]) << 24);
  return true;
}

void flushInput() {
  while (Serial.available() > 0) {
    Serial.read();
  }
}

#if HAS_ESPDL
extern "C" {
extern const uint8_t _binary_chess_yolo_320_p4_int8_espdl_start[];
extern const uint8_t _binary_chess_yolo_320_p4_int8_espdl_end[];
}

const uint8_t *resolveEmbeddedModelPtr() {
  if (_binary_chess_yolo_320_p4_int8_espdl_end >
      _binary_chess_yolo_320_p4_int8_espdl_start) {
    return _binary_chess_yolo_320_p4_int8_espdl_start;
  }
  return nullptr;
}

class ChessDetectImpl : public dl::detect::DetectImpl {
 public:
  ChessDetectImpl(const uint8_t *modelPtr, float scoreThr, float nmsThr) {
    m_model = new dl::Model(
        reinterpret_cast<const char *>(modelPtr),
        fbs::MODEL_LOCATION_IN_FLASH_RODATA,
        0,
        dl::MEMORY_MANAGER_GREEDY,
        nullptr,
        true);
    m_model->minimize();

    m_image_preprocessor = new dl::image::ImagePreprocessor(m_model, {0, 0, 0}, {255, 255, 255});
    m_image_preprocessor->enable_letterbox({114, 114, 114});
    m_postprocessor = new dl::detect::yolo11PostProcessor(
        m_model,
        m_image_preprocessor,
        scoreThr,
        nmsThr,
        32,
        {{8, 8, 4, 4}, {16, 16, 8, 8}, {32, 32, 16, 16}});
  }
};

ChessDetectImpl *gDetector = nullptr;

const char *labelForClass(int cls) {
  static const char *kLabels[] = {
      "black_bishop", "black_king", "black_knight", "black_pawn", "black_queen", "black_rook",
      "white_bishop", "white_king", "white_knight", "white_pawn", "white_queen", "white_rook",
  };
  if (cls >= 0 && cls < static_cast<int>(sizeof(kLabels) / sizeof(kLabels[0]))) {
    return kLabels[cls];
  }
  return "unknown";
}

bool runDetection(const uint8_t *jpegData, size_t jpegLen) {
  dl::image::jpeg_img_t jpeg = {
      .data = const_cast<uint8_t *>(jpegData),
      .data_len = jpegLen,
  };
  auto img = dl::image::sw_decode_jpeg(jpeg, dl::image::DL_IMAGE_PIX_TYPE_RGB888);
  if (!img.data) {
    Serial.println("ERR:JPEG_DECODE");
    return false;
  }

  auto &results = gDetector->run(img);
  Serial.printf("DET frame=%lu count=%d\n", static_cast<unsigned long>(gFrameCount), static_cast<int>(results.size()));
  for (const auto &r : results) {
    Serial.printf(
        "BOX cls=%d label=%s conf=%.3f x1=%d y1=%d x2=%d y2=%d\n",
        r.category,
        labelForClass(r.category),
        r.score,
        r.box[0],
        r.box[1],
        r.box[2],
        r.box[3]);
  }

  heap_caps_free(img.data);
  return true;
}

#else
bool runDetection(const uint8_t *jpegData, size_t jpegLen) {
  (void)jpegData;
  (void)jpegLen;
  Serial.println("ERR:ESPDL_NOT_AVAILABLE");
  return false;
}
#endif

void printPeriodicStats() {
  const uint32_t now = millis();
  if (now - gLastLogMs < 2000) {
    return;
  }
  gLastLogMs = now;
  Serial.printf(
      "STAT frames=%lu drops=%lu heap_kb=%lu\n",
      static_cast<unsigned long>(gFrameCount),
      static_cast<unsigned long>(gDropCount),
      static_cast<unsigned long>(ESP.getFreeHeap() / 1024));
}

}  // namespace

void setup() {
  Serial.begin(kBaudRate);
  pinMode(kStatusLedPin, OUTPUT);
  digitalWrite(kStatusLedPin, LOW);
  delay(1200);

  g_jpegBuf = static_cast<uint8_t *>(heap_caps_malloc(kMaxFrameBytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (!g_jpegBuf) {
    g_jpegBuf = static_cast<uint8_t *>(malloc(kMaxFrameBytes));
  }

  Serial.println("========================================");
  Serial.println("ESP32-P4 Serial Chess Detection");
  Serial.println("Protocol: [len32 LE] + [JPEG bytes]");
#if HAS_ESPDL
  Serial.println("ESP-DL: enabled");
  const uint8_t *modelPtr = resolveEmbeddedModelPtr();
  if (!modelPtr) {
    Serial.println("ERR:MODEL_SYMBOL_MISSING");
  } else {
    gDetector = new ChessDetectImpl(modelPtr, 0.25f, 0.70f);
  }
#else
  Serial.println("ESP-DL: disabled (component headers not found)");
#endif

  if (!g_jpegBuf) {
    Serial.println("FATAL: no frame buffer");
    while (true) {
      delay(1000);
    }
  }
  Serial.println("READY");
}

void loop() {
  if (Serial.available() < 4) {
    printPeriodicStats();
    delay(1);
    return;
  }

  uint32_t frameLen = 0;
  if (!readFrameLengthLE(frameLen)) {
    gDropCount++;
    flushInput();
    return;
  }

  if (frameLen == 0 || frameLen > kMaxFrameBytes) {
    Serial.printf("ERR:BAD_LEN %lu\n", static_cast<unsigned long>(frameLen));
    gDropCount++;
    flushInput();
    return;
  }

  if (!readExact(g_jpegBuf, frameLen, kReadTimeoutMs)) {
    Serial.println("ERR:FRAME_TIMEOUT");
    gDropCount++;
    flushInput();
    return;
  }

  digitalWrite(kStatusLedPin, HIGH);
  gFrameCount++;
  runDetection(g_jpegBuf, frameLen);
  digitalWrite(kStatusLedPin, LOW);
  printPeriodicStats();
}