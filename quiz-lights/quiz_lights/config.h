// Quiz Lights hardware settings. Change these to match your build, then upload again.
#pragma once

// What you're lighting:
//   SINGLE_BULB 1  one plain bulb or LED, switched on/off from BULB_PIN (no colours). Binary then uses
//                  flash LENGTH: long = 1, short = 0. Zones mode isn't available.
//   SINGLE_BULB 0  a WS2812B LED strip on LED_PIN (colours, zones).
#define SINGLE_BULB 1
#if defined(ARDUINO_XIAO_ESP32S3)
// Seeed XIAO ESP32S3: its orange user LED (GPIO 21, on when LOW) is the bulb, so you can test with
// no wiring. It has no second LED, so status isn't shown. For a real bulb, use pin D0 (GPIO 1).
#define BULB_PIN 21
#define BULB_ACTIVE_HIGH false
#define STATUS_LED_PIN -1
#else
#define BULB_PIN 4           // single bulb: through a resistor (LED) or a transistor/MOSFET/relay module
#define BULB_ACTIVE_HIGH true  // false for relay modules that switch on when the pin is LOW
#define STATUS_LED_PIN 2     // the board's built-in LED shows status, so the bulb only shows answers; -1 for none
#endif
#define LONG_MS 1200         // single bulb, binary: a 1 is a long flash
#define SHORT_MS 300         // single bulb, binary: a 0 is a short flash

// How the answer is shown:
//   SIGNAL_ZONES   one light zone per option; the right zone lights up (kids stand on zones)
//   SIGNAL_COUNT   the whole strip is one bulb that blinks N times: A = 1 blink, B = 2 … (0 = no answer)
//   SIGNAL_BINARY  the whole strip is one bulb showing N in binary: one flash per bit, white = 1, blue = 0
#define SIGNAL_ZONES 0
#define SIGNAL_COUNT 1
#define SIGNAL_BINARY 2
#define SIGNAL_MODE SIGNAL_BINARY

#define BITS 3               // binary: bits per answer. 3 bits = 0–7 (no answer, A–G); 4 bits = 0–15
#define SLOT_MS 1000         // binary and counting: how long each flash stays on
#define GAP_MS 500           // dark gap between flashes
#define ONE_COLOR rgb(255, 255, 255)  // binary 1, and every blink when counting: bright white
#define ZERO_COLOR rgb(0, 0, 90)      // binary 0: dim blue, so a 0 is still a visible light

#define NUM_ZONES 5          // zones mode: answer options (4 = A–D, 5 = A–E, up to 8). Other modes: any split
#define LEDS_PER_ZONE 10     // LEDs in each zone's strip piece (zones are chained A, B, C, …)
#define LED_PIN 5            // WS2812B data pin (through a 330 Ω resistor)
#define BRIGHTNESS 180       // 0–255. Keep total current within your power supply (see README)

#define BUZZER_PIN 18        // active or passive buzzer; -1 if you have none
#define SETUP_BUTTON_PIN 0   // BOOT button: hold 3 s to change Wi-Fi or topic

#define REVEAL_HOLD_MS 6000        // several questions on one screen: pause between answers
#define THINKING_TIMEOUT_MS 60000  // stop the drum roll if no answer comes

#define NTFY_HOST "ntfy.sh"  // same server as Study Watch's "ntfy_server"
#define NTFY_PORT 80
