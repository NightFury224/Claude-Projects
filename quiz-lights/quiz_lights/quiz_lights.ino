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
int signalMode = SIGNAL_MODE;  // can be switched with a short BOOT press or a "MODE …" message
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

// ------------------------------------------------------------------ one-bulb signalling (teaching modes)
// The whole strip acts as ONE bulb. Option A = 1, B = 2, C = 3 …; 0 means "no answer".

const int TOTAL_LEDS = NUM_ZONES * LEDS_PER_ZONE;

void bulb(uint32_t color) {
  for (int i = 0; i < TOTAL_LEDS; i++) strip.setPixelColor(i, color);
  strip.show();
}

// "Get ready": three quick blue flashes so everyone starts watching.
void attention() {
  for (int i = 0; i < 3; i++) {
    bulb(rgb(0, 60, 255));
    beep(988, 80);
    delay(150);
    bulb(rgb(0, 0, 0));
    delay(150);
  }
  delay(SLOT_MS / 2);
}

// Counting (unary): the bulb blinks N times. Simple to read, but slow for big numbers.
void sendCount(int value) {
  attention();
  for (int i = 0; i < value; i++) {
    bulb(rgb(255, 200, 120));
    beep(1319, 120);
    delay(SLOT_MS / 2);
    bulb(rgb(0, 0, 0));
    delay(SLOT_MS / 2);
  }
  bulb(rgb(255, 0, 0));  // red = end of message
  beep(440, 300);
  delay(SLOT_MS);
  bulb(rgb(0, 0, 0));
}

// Binary (like a real serial line): a START slot, then BITS time slots, most significant bit first.
// ON for the whole slot = 1, OFF = 0. A dim blue tick (and a click) marks the start of every slot,
// so a run of zeros can still be counted: that tick is the "clock". Then a red STOP slot.
// Afterwards the strip splits into BITS segments showing all the bits at once ("parallel").
void sendBinary(int value) {
  attention();
  bulb(rgb(0, 60, 255));  // START
  beep(988, 150);
  delay(SLOT_MS);
  for (int bit = BITS - 1; bit >= 0; bit--) {
    bool one = (value >> bit) & 1;
    bulb(rgb(0, 0, 40));  // clock tick
    beep(one ? 1568 : 330, 60);
    delay(120);
    bulb(one ? rgb(255, 200, 120) : rgb(0, 0, 0));
    delay(SLOT_MS - 120);
  }
  bulb(rgb(255, 0, 0));  // STOP
  beep(440, 300);
  delay(SLOT_MS);

  // Parallel recap: segment per bit, left = most significant. Bright = 1, faint = 0.
  strip.clear();
  int segment = TOTAL_LEDS / BITS;
  for (int bit = BITS - 1, s = 0; bit >= 0; bit--, s++) {
    bool one = (value >> bit) & 1;
    for (int i = s * segment; i < (s + 1) * segment - 1; i++)  // last LED of a segment stays dark: a gap
      strip.setPixelColor(i, one ? rgb(255, 200, 120) : rgb(10, 10, 25));
  }
  strip.show();
}

// Sends one answer as a number in the chosen signal mode.
void sendValue(int value) {
  if (signalMode == SIGNAL_COUNT) sendCount(value);
  else sendBinary(value);
}

// Reveals the next letter in [reveal]. "-" (a question with no option letter) means 0 = no answer.
void showNextLetter() {
  while (reveal.length() > 0) {
    char letter = reveal[0];
    reveal.remove(0, 1);
    int value = letter == '-' ? 0 : letter - 'A' + 1;

    if (signalMode != SIGNAL_ZONES) {
      if (signalMode == SIGNAL_BINARY && value >= (1 << BITS)) value = 0;  // doesn't fit in BITS
      sendValue(value);
      shownZone = 0;
      setMode(SHOWING);
      return;
    }

    if (letter == '-') continue;
    int zone = value - 1;
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
    if (signalMode == SIGNAL_ZONES) {
      setMode(NO_OPTION);
    } else {  // teaching modes: "no answer" is sent as the number 0
      reveal = "-";
      showNextLetter();
    }
  } else if (message == "ERROR") {
    setMode(FAILED);
  } else if (message.startsWith("MODE")) {
    if (message.indexOf("ZONE") > 0) setSignalMode(SIGNAL_ZONES);
    else if (message.indexOf("COUNT") > 0) setSignalMode(SIGNAL_COUNT);
    else if (message.indexOf("BIN") > 0) setSignalMode(SIGNAL_BINARY);
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

// Shows which mode is active: 1 flash = zones, 2 = counting, 3 = binary (purple).
void showSignalMode() {
  for (int i = 0; i <= signalMode; i++) {
    fillAll(rgb(150, 0, 255));
    strip.show();
    beep(1175, 100);
    delay(250);
    fillAll(rgb(0, 0, 0));
    strip.show();
    delay(250);
  }
}

void setSignalMode(int next) {
  signalMode = next;
  prefs.putInt("mode", signalMode);
  showSignalMode();
  setMode(IDLE);
}

// BOOT button: short press = next signal mode; hold 3 s = Wi-Fi/topic setup.
void checkSetupButton() {
  static unsigned long pressedAt = 0;
  if (digitalRead(SETUP_BUTTON_PIN) == LOW) {
    if (pressedAt == 0) pressedAt = millis();
    if (millis() - pressedAt > 3000) {
      pressedAt = 0;
      runSetupPortal(true);
    }
  } else {
    if (pressedAt != 0 && millis() - pressedAt > 50 && millis() - pressedAt < 1000)
      setSignalMode((signalMode + 1) % 3);
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
  signalMode = prefs.getInt("mode", SIGNAL_MODE);
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
