/*
 * ESP32-P4 Simple Color Detector
 * 
 * Receives data from PC over USB serial
 * Checks if any byte is non-zero (not black)
 * Flashes LED if color detected
 * 
 * HARDWARE:
 * - LED on GPIO2 (built-in) or change LED_PIN below
 */

// ============================================================
// CONFIGURATION
// ============================================================
#include <Arduino.h>


const int LED_PIN = 2;        // Built-in LED pin (change if needed)
const int BAUD_RATE = 921600; // Fast serial speed

void processIncomingData();
void triggerColorDetection();
void updateLED();
void printStats();

// Detection settings
bool colorDetected = false;
unsigned long lastFlashTime = 0;
const unsigned long FLASH_DURATION_MS = 200; // How long LED stays on
const unsigned long FLASH_INTERVAL_MS = 500; // Minimum time between flashes

// Statistics
unsigned long totalBytesReceived = 0;
int framesProcessed = 0;

void setup() {
    // Initialize Serial (USB-C port)
    Serial.begin(BAUD_RATE);
    
    // Give time for serial monitor to connect
    delay(1500);
    
    // Setup LED
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);
    
    // Print startup message
    Serial.println("========================================");
    Serial.println("  ESP32-P4 COLOR DETECTOR READY");
    Serial.println("========================================");
    Serial.print("   Baud Rate: ");
    Serial.println(String(BAUD_RATE));
    Serial.print("   LED Pin: ");
    Serial.println(String(LED_PIN));
    Serial.println("");
    Serial.println("Waiting for image data from PC...");
    Serial.println("(Send raw bytes - any non-zero = color detected)");
    Serial.println("");
}

void loop() {
    // Check if data is available
    if (Serial.available() > 0) {
        processIncomingData();
    }
    
    // Handle LED flashing state machine
    updateLED();
    
    // Small delay to prevent overwhelming CPU
    delay(1);
}

// ============================================================
// DATA PROCESSING
// ============================================================
void processIncomingData() {
    bool foundColorInThisBatch = false;
    int bytesInBatch = 0;
    
    // Process all available bytes in buffer
    while (Serial.available() > 0) {
        byte b = Serial.read();  // Read one byte
        
        totalBytesReceived++;
        bytesInBatch++;
        
        // Check if this byte represents a non-black pixel
        // Assuming: 0x00 = black, anything else = some color
        // If you send RGB pixels, adjust logic below
        if (b != 0x00) {
            foundColorInThisBatch = true;
            
            // Optional: Print first few non-black values for debugging
            if (totalBytesReceived < 100) {
                Serial.print("Found color byte: 0x");
                Serial.println(String(b, HEX));
            }
        }
        
        // Don't block too long - yield periodically
        if (bytesInBatch % 1024 == 0) {
            // Allow other tasks to run briefly
            delayMicroseconds(10);
        }
    }
    
    // Update detection state
    if (foundColorInThisBatch) {
        triggerColorDetection();
        
        framesProcessed++;
        
        // Print stats every 100 frames
        if (framesProcessed % 100 == 0) {
            printStats();
        }
    }
}

// ============================================================
// DETECTION & LED CONTROL
// ============================================================
void triggerColorDetection() {
    colorDetected = true;
    lastFlashTime = millis();
    
    // Immediately turn on LED
    digitalWrite(LED_PIN, HIGH);
    
    // Optional: Debug message (uncomment if needed)
    // println("⚡ COLOR DETECTED!");
}

void updateLED() {
    // Turn off LED after flash duration
    if (colorDetected && (millis() - lastFlashTime > FLASH_DURATION_MS)) {
        digitalWrite(LED_PIN, LOW);
        colorDetected = false;
    }
}

void printStats() {
    Serial.print("[STATS] Frames processed: ");
    Serial.print(String(framesProcessed));
    Serial.print(" | Total bytes: ");
    Serial.print(String(totalBytesReceived));
    Serial.print(" | Free RAM: ");
    Serial.print(String(ESP.getFreeHeap() / 1024));
    Serial.println(" KB");
}

