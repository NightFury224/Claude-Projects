/*
  Quiz Lights: one light zone per answer option (A, B, C, ...). When the teacher taps Right Ctrl,
  Study Watch sends "thinking" (drum roll), then the answer letter(s) and this box lights the right zone.

  Messages arrive on the ntfy topic "<your studywatch topic>-lights":
    thinking   drum roll until the answer arrives
    B          reveal zone B
    B,-,D      several questions on screen: reveal B, then (skip), then D, one after another
    none       the answer has no option letter (open question)
    error      the AI failed; tap Right Ctrl again
    off        back to idle

  First start: the box opens a Wi-Fi network "QuizLights-Setup". Join it from a phone, pick the
  classroom Wi-Fi (or your phone's hotspot) and paste the ntfy topic. Hold the BOOT button for
  3 seconds at any time to redo the setup.
*/
#include <Adafruit_NeoPixel.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiManager.h>

#include "config.h"

Adafruit_NeoPixel strip(NUM_ZONES * LEDS_PER_ZONE, LED_PIN, NEO_GRB + NEO_KHZ800);
Preferences prefs;
WiFiClient client;

String topic;
unsigned long lastData = 0;      // last byte from ntfy, including keepalives
unsigned long thinkingSince = 0; // 0 = not thinking

enum Mode { IDLE, THINKING, SHOWING, NO_OPTION, FAILED, OFFLINE };
Mode mode = OFFLINE;
String reveal;            // letters still to reveal, e.g. "B-D"
int shownZone = -1;       // zone lit by the last reveal
unsigned long modeSince = 0;

// ------------------------------------------------------------------ lights

uint32_t rgb(uint8_t r, uint8_t g, uint8_t b) { return strip.Color(r, g, b); }

void fillZone(int zone, uint32_t color) {
  for (int i = 0; i < LEDS_PER_ZONE; i++) strip.setPixelColor(zone * LEDS_PER_ZONE + i, color);
}

void fillAll(uint32_t color) {
  for (int z = 0; z < NUM_ZONES; z++) fillZone(z, color);
}

uint32_t scale(uint8_t r, uint8_t g, uint8_t b, float level) {
  return rgb(r * level, g * level, b * level);
}

float breathe(unsigned long periodMs) {
  return 0.15 + 0.85 * (0.5 - 0.5 * cos(2 * PI * (millis() % periodMs) / (float)periodMs));
}

void beep(int frequency, int ms) {
  if (BUZZER_PIN >= 0) tone(BUZZER_PIN, frequency, ms);
}

void setMode(Mode next) {
  mode = next;
  modeSince = millis();
}

// Celebrates zone [zone]: flashes green, then stays green while the other zones glow dim red.
void celebrate(int zone) {
  for (int i = 0; i < 6; i++) {
    fillAll(scale(255, 0, 0, 0.05));
    fillZone(zone, i % 2 ? rgb(0, 0, 0) : rgb(0, 255, 60));
    strip.show();
    beep(i % 2 ? 1319 : 1568, 120);
    delay(160);
  }
  fillAll(scale(255, 0, 0, 0.08));
  fillZone(zone, rgb(0, 255, 60));
  strip.show();
  beep(2093, 400);
}

// Called repeatedly from loop(): draws the current mode's animation.
void animate() {
  unsigned long t = millis() - modeSince;
  switch (mode) {
    case IDLE:  // gentle white breathing: ready
      fillAll(scale(255, 255, 255, 0.25 * breathe(4000)));
      break;

    case THINKING: {  // drum roll: a light chases across the zones, getting faster
      int step = (t / max(60, 260 - (int)(t / 60))) % NUM_ZONES;
      fillAll(rgb(0, 0, 0));
      fillZone(step, rgb(255, 160, 0));
      static int lastStep = -1;
      if (step != lastStep) beep(220 + step * 40, 25);
      lastStep = step;
      if (millis() - thinkingSince > THINKING_TIMEOUT_MS) setMode(FAILED);
      break;
    }

    case SHOWING:  // hold the current reveal, then move on to the next letter (several questions)
      if (reveal.length() > 0 && t > REVEAL_HOLD_MS) showNextLetter();
      return;  // the reveal itself drew the lights

    case NO_OPTION:  // purple pulse: answered, but there is no option to light
      fillAll(scale(150, 0, 255, breathe(1500)));
      if (t > 8000) setMode(IDLE);
      break;

    case FAILED:  // orange blink: tap Right Ctrl again
      fillAll((t / 400) % 2 ? rgb(0, 0, 0) : rgb(255, 80, 0));
      if (t > 6000) setMode(IDLE);
      break;

    case OFFLINE:  // slow red blink on the first zone only: no connection
      fillAll(rgb(0, 0, 0));
      fillZone(0, (millis() / 800) % 2 ? rgb(0, 0, 0) : rgb(120, 0, 0));
      break;
  }
  strip.show();
}

// Reveals the next letter in [reveal]; "-" (a question with no option letter) is skipped.
void showNextLetter() {
  while (reveal.length() > 0) {
    char letter = reveal[0];
    reveal.remove(0, 1);
    int zone = letter - 'A';
    if (letter == '-') continue;
    if (zone < 0 || zone >= NUM_ZONES) {
      // The answer is an option this box has no zone for (e.g. "F" with 5 zones): blink everything.
      for (int i = 0; i < 4; i++) {
        fillAll(i % 2 ? rgb(0, 0, 0) : rgb(255, 255, 255));
        strip.show();
        delay(250);
      }
      continue;
    }
    shownZone = zone;
    celebrate(zone);
    setMode(SHOWING);
    return;
  }
  if (shownZone < 0) setMode(NO_OPTION);
}

void handleMessage(String message) {
  message.trim();
  message.toUpperCase();
  Serial.println("Message: " + message);
  if (message == "THINKING") {
    thinkingSince = millis();
    shownZone = -1;
    setMode(THINKING);
  } else if (message == "NONE") {
    setMode(NO_OPTION);
  } else if (message == "ERROR") {
    setMode(FAILED);
  } else if (message == "OFF") {
    setMode(IDLE);
  } else {
    reveal = "";
    for (char c : message) {
      if ((c >= 'A' && c <= 'Z') || c == '-') reveal += c;
    }
    if (reveal.length() == 0) return;
    beep(880, 150);  // end of the drum roll
    delay(250);
    shownZone = -1;
    showNextLetter();
  }
}

// ------------------------------------------------------------------ Wi-Fi and setup portal

void runSetupPortal(bool force) {
  fillAll(rgb(0, 0, 120));
  strip.show();
  WiFiManager wm;
  WiFiManagerParameter topicField("topic", "ntfy topic (studywatch-…)", topic.c_str(), 80);
  wm.addParameter(&topicField);
  wm.setConfigPortalTimeout(300);
  bool connected = force ? wm.startConfigPortal("QuizLights-Setup") : wm.autoConnect("QuizLights-Setup");
  String entered = String(topicField.getValue());
  entered.trim();
  if (entered.length() > 0 && entered != topic) {
    topic = entered;
    prefs.putString("topic", topic);
  }
  if (!connected) ESP.restart();
}

void checkSetupButton() {
  static unsigned long pressedAt = 0;
  if (digitalRead(SETUP_BUTTON_PIN) == LOW) {
    if (pressedAt == 0) pressedAt = millis();
    if (millis() - pressedAt > 3000) {
      pressedAt = 0;
      runSetupPortal(true);
    }
  } else {
    pressedAt = 0;
  }
}

// ------------------------------------------------------------------ ntfy

String lightsTopic() {
  return topic.endsWith("-lights") ? topic : topic + "-lights";
}

// Opens the ntfy stream. HTTP/1.0 so the reply isn't chunked: one message per line.
bool connectStream() {
  client.stop();
  if (!client.connect(NTFY_HOST, NTFY_PORT)) return false;
  client.print("GET /" + lightsTopic() + "/raw HTTP/1.0\r\nHost: " + NTFY_HOST +
               "\r\nUser-Agent: QuizLights\r\n\r\n");
  unsigned long start = millis();
  String status = "";
  while (millis() - start < 10000) {  // skip the headers
    if (!client.available()) {
      delay(10);
      continue;
    }
    String line = client.readStringUntil('\n');
    if (status.length() == 0) status = line;
    if (line == "\r" || line.length() == 0) break;
  }
  Serial.println("ntfy: " + status);
  lastData = millis();
  return status.indexOf(" 200") > 0;
}

void readStream() {
  while (client.available()) {
    String line = client.readStringUntil('\n');
    lastData = millis();
    line.trim();
    if (line.length() > 0) handleMessage(line);  // empty lines are keepalives
  }
}

// ------------------------------------------------------------------ main

void setup() {
  Serial.begin(115200);
  pinMode(SETUP_BUTTON_PIN, INPUT_PULLUP);
  strip.begin();
  strip.setBrightness(BRIGHTNESS);
  strip.show();

  prefs.begin("quizlights", false);
  topic = prefs.getString("topic", "");
  runSetupPortal(topic.length() == 0);  // first start: always ask for the topic
  WiFi.setSleep(false);                 // faster reaction; the box runs from mains power
  setMode(OFFLINE);
}

void loop() {
  checkSetupButton();
  bool online = WiFi.status() == WL_CONNECTED && client.connected() && millis() - lastData < 100000;
  if (!online) {
    if (mode != OFFLINE && mode != THINKING) setMode(OFFLINE);
    static unsigned long lastTry = 0;
    if (millis() - lastTry > 3000) {
      lastTry = millis();
      if (WiFi.status() != WL_CONNECTED) WiFi.reconnect();
      else if (connectStream() && mode == OFFLINE) {
        setMode(IDLE);
        beep(1047, 80);
      }
    }
  } else {
    readStream();
  }
  animate();
  delay(15);
}
