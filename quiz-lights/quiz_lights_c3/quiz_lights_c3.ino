// Quiz Lights for the ESP32-C3 Super Mini: one bulb (the board's blue LED) shows Study Watch answers.
// Binary: long flash = 1, short flash = 0. Counting: one blink per unit. A=1, B=2 ... no answer = 0.
// Arduino IDE: board "ESP32C3 Dev Module", USB CDC On Boot: Enabled. Library: WiFiManager (tzapu).

#include <WiFi.h>
#include <WiFiManager.h>
#include <Preferences.h>

#define BULB_PIN 8              // the Super Mini's blue LED. For a real bulb/LED use 4 and set BULB_ON HIGH
#define BULB_ON LOW             // the blue LED lights when the pin is LOW
#define BUTTON_PIN 9            // BOOT button: short press = switch mode, hold 3 s = Wi-Fi/topic setup
#define BITS 3                  // 3 bits = 0..7 (A..G). Use 4 for more options
#define LONG_MS 1200            // binary 1
#define SHORT_MS 300            // binary 0
#define GAP_MS 500              // dark gap between flashes
#define BLINK_MS 400            // counting blink
#define BETWEEN_ANSWERS_MS 3000 // pause between answers when one screen has several questions
const char* NTFY_HOST = "ntfy.sh";

Preferences prefs;
WiFiClient client;
String topic;
char topicBuf[64];
int mode;  // 1 = counting, 2 = binary

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

void runPortal(bool force) {
  WiFiManager wm;
  WiFiManagerParameter p("topic", "ntfy topic (studywatch-...)", topicBuf, 63);
  wm.addParameter(&p);
  wm.setConfigPortalTimeout(300);
  Serial.println(force ? "Setup: join Wi-Fi QuizLights-Setup" : "Connecting to Wi-Fi...");
  bool ok = force ? wm.startConfigPortal("QuizLights-Setup") : wm.autoConnect("QuizLights-Setup");
  String t = String(p.getValue());
  t.trim();
  if (t.length()) {
    topic = t;
    prefs.putString("topic", t);
    strncpy(topicBuf, t.c_str(), 63);
  }
  if (!ok) ESP.restart();
}

void checkButton() {
  if (digitalRead(BUTTON_PIN) != LOW) return;
  unsigned long t = millis();
  while (digitalRead(BUTTON_PIN) == LOW) {
    if (millis() - t > 3000) {
      bulb(true);
      client.stop();
      runPortal(true);
      bulb(false);
      return;
    }
    delay(10);
  }
  if (millis() - t > 50) setMode(mode == 2 ? 1 : 2);
}

bool connectStream() {
  if (topic.length() == 0) return false;
  if (!client.connect(NTFY_HOST, 80)) { Serial.println("Can't reach ntfy.sh"); return false; }
  client.printf("GET /%s-lights/raw HTTP/1.0\r\nHost: %s\r\nUser-Agent: QuizLights\r\n\r\n", topic.c_str(), NTFY_HOST);
  unsigned long t = millis();
  while (client.connected() && millis() - t < 10000) {  // skip the HTTP headers
    String line = client.readStringUntil('\n');
    line.trim();
    if (line.length() == 0) break;
  }
  Serial.println("Listening on " + topic + "-lights");
  return true;
}

void handle(String m) {
  m.trim();
  m.toUpperCase();
  if (m.length() == 0) return;  // keep-alive
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

void setup() {
  Serial.begin(115200);
  pinMode(BULB_PIN, OUTPUT);
  bulb(false);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  prefs.begin("quiz", false);
  topic = prefs.getString("topic", "");
  strncpy(topicBuf, topic.c_str(), 63);
  mode = prefs.getInt("mode", 2);
  if (mode != 1 && mode != 2) mode = 2;
  WiFi.mode(WIFI_STA);
  WiFi.setTxPower(WIFI_POWER_8_5dBm);  // Super Mini boards often fail to connect at full power
  runPortal(topic.length() == 0);
  WiFi.setAutoReconnect(true);
  Serial.println("Ready. Topic: " + topic);
}

void loop() {
  checkButton();
  if (WiFi.status() != WL_CONNECTED) { delay(500); return; }
  if (!client.connected()) {
    client.stop();
    if (!connectStream()) delay(3000);
    return;
  }
  while (client.available()) handle(client.readStringUntil('\n'));
  delay(10);
}
