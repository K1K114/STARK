#include <WiFi.h>
#include "esp_wpa2.h" // Required for enterprise networks

#ifndef WIFI_SSID
#define WIFI_SSID "PAL3.0"
#endif

#ifndef WIFI_USERNAME
#define WIFI_USERNAME "jain925"
#endif

#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "YOUR_PASSWORD"
#endif

const char* ssid = WIFI_SSID;
const char* username = WIFI_USERNAME;
const char* password = WIFI_PASSWORD;

void setup() {
    Serial.begin(115200);
    delay(10);
    Serial.println(ssid); 
    Serial.println(username);
    Serial.println();
    Serial.print("Connecting to network: ");
    Serial.println(ssid);

    // 1. Disconnect from any previous Wi-Fi session
    WiFi.disconnect(true);

    // 2. Set Wi-Fi mode to Station
    WiFi.mode(WIFI_STA);

    // 3. Configure WPA2 Enterprise 
    // This uses the PEAP method (Username + Password)
    esp_wifi_sta_wpa2_ent_set_identity((uint8_t *)username, strlen(username));
    esp_wifi_sta_wpa2_ent_set_username((uint8_t *)username, strlen(username));
    esp_wifi_sta_wpa2_ent_set_password((uint8_t *)password, strlen(password));
    
    // Enable WPA2 Enterprise
    esp_wifi_sta_wpa2_ent_enable();

    // 4. Begin connection
    WiFi.begin(ssid);

    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }

    Serial.println("");
    Serial.println("WiFi connected!");
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());
}

void loop() {
    // Your code here
}