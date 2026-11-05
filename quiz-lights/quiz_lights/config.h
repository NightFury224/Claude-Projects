// Quiz Lights hardware settings. Change these to match your build, then upload again.
#pragma once

#define NUM_ZONES 5          // answer options: 4 = A–D, 5 = A–E, up to 8 = A–H
#define LEDS_PER_ZONE 10     // LEDs in each zone's strip piece (zones are chained A, B, C, …)
#define LED_PIN 5            // WS2812B data pin (through a 330 Ω resistor)
#define BRIGHTNESS 180       // 0–255. Keep total current within your power supply (see README)

#define BUZZER_PIN 18        // active or passive buzzer; -1 if you have none
#define SETUP_BUTTON_PIN 0   // BOOT button: hold 3 s to change Wi-Fi or topic

#define REVEAL_HOLD_MS 6000        // several questions on one screen: time each answer stays lit
#define THINKING_TIMEOUT_MS 60000  // stop the drum roll if no answer comes

#define NTFY_HOST "ntfy.sh"  // same server as Study Watch's "ntfy_server"
#define NTFY_PORT 80
