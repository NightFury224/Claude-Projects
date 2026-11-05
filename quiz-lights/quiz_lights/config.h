// Quiz Lights hardware settings. Change these to match your build, then upload again.
#pragma once

// How the answer is shown:
//   SIGNAL_ZONES   one light zone per option; the right zone lights up (kids stand on zones)
//   SIGNAL_COUNT   the whole strip is one bulb that blinks N times: A = 1 blink, B = 2 … (0 = no answer)
//   SIGNAL_BINARY  the whole strip is one bulb sending N in binary, one bit per time slot
#define SIGNAL_ZONES 0
#define SIGNAL_COUNT 1
#define SIGNAL_BINARY 2
#define SIGNAL_MODE SIGNAL_BINARY

#define BITS 3               // binary: bits per answer. 3 bits = 0–7 (no answer, A–G); 4 bits = 0–15
#define SLOT_MS 1000         // binary and counting: length of one time slot. Shorter = faster but harder to read

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
