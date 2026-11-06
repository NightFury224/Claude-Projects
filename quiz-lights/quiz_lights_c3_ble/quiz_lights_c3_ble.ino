// Quiz Lights, Bluetooth version, for the ESP32-C3 Super Mini. Study Watch on the laptop connects
// straight to this board (no Wi-Fi, no topic, no setup). One bulb (the board's blue LED) shows answers.
// Binary: long flash = 1, short flash = 0. Counting: one blink per unit. A=1, B=2 ... no answer = 0.
// Arduino IDE: board "ESP32C3 Dev Module", USB CDC On Boot: Enabled. No extra libraries needed.

#include <BLEDevice.h>
#include <BLEServer.h>
#include <Preferences.h>

#define BULB_PIN 8              // the Super Mini's blue LED. For a real bulb/LED use 4 and set BULB_ON HIGH
#define BULB_ON LOW             // the blue LED lights when the pin is LOW
#define BUTTON_PIN 9            // BOOT button: short press = switch counting / binary
#define BITS 3                  // 3 bits = 0..7 (A..G). Use 4 for more options
#define LONG_MS 1200            // binary 1
#define SHORT_MS 300            // binary 0
#define GAP_MS 500              // dark gap between flashes
#define BLINK_MS 400            // counting blink
#define BETWEEN_ANSWERS_MS 3000 // pause between answers when one screen has several questions

// Must match Study Watch.
#define SERVICE_UUID "7a3c0001-5f1e-4e8a-9b6d-2c4f1e0b7a10"
#define CHAR_UUID    "7a3c0002-5f1e-4e8a-9b6d-2c4f1e0b7a10"

Preferences prefs;
int mode;  // 1 = counting, 2 = binary
portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;
String pending;          // last message from the laptop, handled in loop()
volatile bool hasPending = false;
volatile bool linkChanged = false;
volatile bool linked = false;

void bulb(bool on) { digitalWrite(BULB_PIN, on ? BULB_ON : !BULB_ON); }
void flash(int ms) { bulb(true); delay(ms); bulb(false); }

void sendCount(int v) {
  for (int i = 0; i < v; i++) { flash(BLINK_MS); delay(BLINK_MS); }
}

void sendBinary(int v) {  // most significant bit first; a 0 is a short flash, never darkness
  for (int b = BITS - 1; b >= 0; b--) { flash((v >> b) & 1 ? LONG_MS : SHORT_MS); delay(GAP_MS); }
}

void show(int v) {
  Serial.printf("Showing %d (%s)\n", v, mode == 1 ? "counting" : "binary");
  if (mode == 1) sendCount(v); else sendBinary(v);
}

void setMode(int m) {
  mode = m;
  prefs.putInt("mode", m);
  Serial.println(m == 1 ? "Mode: counting" : "Mode: binary");
  delay(300);
  for (int i = 0; i < m; i++) { flash(150); delay(250); }  // 1 quick blink = counting, 2 = binary
}

class ServerEvents : public BLEServerCallbacks {
  void onConnect(BLEServer*) override { linked = true; linkChanged = true; }
  void onDisconnect(BLEServer*) override { linked = false; linkChanged = true; }
};

class WriteEvents : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* c) override {
    String m = String(c->getValue().c_str());
    portENTER_CRITICAL(&lock);
    pending = m;
    hasPending = true;
    portEXIT_CRITICAL(&lock);
  }
};

void handle(String m) {
  m.trim();
  m.toUpperCase();
  if (m.length() == 0) return;
  Serial.println("Got: " + m);
  if (m.startsWith("MODE")) {
    if (m.indexOf("COUNT") > 0) setMode(1);
    else if (m.indexOf("BINARY") > 0) setMode(2);
    return;  // zones needs an LED strip
  }
  if (m == "THINKING" || m == "ERROR" || m == "OFF") return;  // the bulb shows answers only
  if (m == "NONE") { show(0); return; }
  bool first = true;
  int start = 0;
  while (start <= (int)m.length()) {  // "B" or "B,-,D"
    int c = m.indexOf(',', start);
    if (c < 0) c = m.length();
    String tok = m.substring(start, c);
    tok.trim();
    start = c + 1;
    int v;
    if (tok == "-" || tok == "NONE") v = 0;
    else if (tok.length() == 1 && tok[0] >= 'A' && tok[0] <= 'Z') v = tok[0] - 'A' + 1;
    else continue;
    if (!first) delay(BETWEEN_ANSWERS_MS);
    first = false;
    show(v);
  }
}

void checkButton() {
  if (digitalRead(BUTTON_PIN) != LOW) return;
  unsigned long t = millis();
  while (digitalRead(BUTTON_PIN) == LOW) delay(10);
  if (millis() - t > 50) setMode(mode == 2 ? 1 : 2);
}

void setup() {
  Serial.begin(115200);
  pinMode(BULB_PIN, OUTPUT);
  bulb(false);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  prefs.begin("quiz", false);
  mode = prefs.getInt("mode", 2);
  if (mode != 1 && mode != 2) mode = 2;

  BLEDevice::init("QuizLights");
  BLEServer* server = BLEDevice::createServer();
  server->setCallbacks(new ServerEvents());
  BLEService* service = server->createService(SERVICE_UUID);
  BLECharacteristic* ch = service->createCharacteristic(
      CHAR_UUID, BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  ch->setCallbacks(new WriteEvents());
  service->start();
  BLEAdvertising* adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(SERVICE_UUID);
  adv->setScanResponse(true);
  BLEDevice::startAdvertising();
  Serial.println("Ready: waiting for Study Watch over Bluetooth (QuizLights)");
  Serial.println("Bluetooth address: " + String(BLEDevice::getAddress().toString().c_str()));
}

void loop() {
  checkButton();
  static unsigned long lastAddress = 0;  // repeat the address, so it's visible whenever Serial Monitor opens
  if (!linked && millis() - lastAddress > 5000) {
    lastAddress = millis();
    Serial.println("Bluetooth address: " + String(BLEDevice::getAddress().toString().c_str()));
  }
  if (linkChanged) {
    linkChanged = false;
    Serial.println(linked ? "Laptop connected" : "Laptop disconnected, advertising again");
    if (!linked) { delay(300); BLEDevice::startAdvertising(); }
  }
  if (hasPending) {
    portENTER_CRITICAL(&lock);
    String m = pending;
    hasPending = false;
    portEXIT_CRITICAL(&lock);
    handle(m);
  }
  delay(10);
}
