# Quiz Lights

A classroom game for Study Watch. Project a question, the kids stand on the zone they think is right (A, B, C, …), and you tap **Right Ctrl** on the laptop. The lights play a drum roll while the AI works, then the correct zone flashes green, and everyone on it cheers.

```
Right Ctrl → laptop (Study Watch) → AI → ntfy → ESP32 box → light zone A / B / C / D / E
```

- **No extra button:** Right Ctrl is the reveal. The drum roll starts the moment you tap it, and the answer lights up about 10 seconds later.
- **Any number of options:** the box lights whichever letter the AI answers. Set how many zones you've built (4 for A–D, 5 for A–E, up to 8). If the AI answers a letter you have no zone for, every zone blinks white.
- **Several questions on one screen:** they're revealed one after another, 6 seconds each.
- **Your phone still gets the normal Study Watch notification,** so you can see the answer too.

| Lights | Meaning |
|---|---|
| Soft white breathing | Ready |
| Orange light chasing across the zones, with ticks | Thinking (drum roll) |
| One zone flashing, then solid **green**; the others dim red | The answer |
| Purple pulse | Answered, but there's no option to light (an open question) |
| Orange blinking | The AI failed. Tap Right Ctrl again |
| Zone A slowly blinking red | No Wi-Fi or internet |
| All blue | Setup mode (see below) |

The AI is usually right, but not always. Since the reveal is instant, glance at your phone's notification if an answer looks surprising.

---

## Parts (about ₹1,600–2,500)
| Part | Notes |
|---|---|
| ESP32 dev board (ESP32-WROOM DevKit, 30 or 38 pin) | ~₹400 |
| WS2812B LED strip, 5 V, 60 LEDs/m | One piece per zone, e.g. 10 LEDs each. 1 m is enough for 5 zones (~₹400–600) |
| 5 V power supply, **4 A** or more | With a DC barrel jack adapter (~₹400) |
| 330 Ω resistor | On the LED data line |
| 1000 µF capacitor (6.3 V+) | Across the strip's 5 V and GND |
| Buzzer (optional) | Passive buzzer for tunes; an active one works too (~₹30) |
| Wires and connectors | 3-pin JST connectors make the zones easy to unplug |
| Mats or cards for A, B, C … | Put each zone's light at the front of its mat, under a translucent cover, so nobody steps on the LEDs |

## Wiring
```
5 V supply +  ──────────┬───────────────► Strip 5V          (and ESP32 VIN/5V)
5 V supply −  ──────────┼──┬────────────► Strip GND         (and ESP32 GND)
                    1000µF │
ESP32 GPIO 5  ──[330 Ω]────┴────────────► Strip DIN  (zone A's first LED)
ESP32 GPIO 18 ─────────────► Buzzer +    Buzzer − ──► GND
```
- **Chain the zones in order:** zone A's strip DOUT goes to zone B's DIN, and so on. Use 3 wires between zones (5V, GND, data); a metre or two of wire between zones is fine.
- **Power:** feed the strip from the supply, not through the ESP32. For more than about 60 LEDs, also feed 5 V and GND into the last zone.
- **Always connect the grounds** of the supply, the strip and the ESP32 together.

## Flash the firmware (once)
**Easiest, from the browser (Chrome or Edge on the laptop):**
1. Download **QuizLights-esp32.bin** from this repo's Releases → **"Quiz Lights (latest ESP32 firmware)"**.
2. Plug the ESP32 into the laptop with a USB data cable.
3. Open **https://espressif.github.io/esptool-js/**, click **Connect** and pick the ESP32's port. If it doesn't show up, install the CP210x or CH340 USB driver for your board.
4. Set **Flash Address** to `0x0`, choose the `.bin` file and click **Program**.

**To change zones or pins:** edit `quiz_lights/config.h` (number of zones, LEDs per zone, pins, brightness). Then upload with the **Arduino IDE**:
- ESP32 board package by Espressif
- the **Adafruit NeoPixel** and **WiFiManager** (by tzapu) libraries
- board **ESP32 Dev Module**

## Set it up (once)
1. Power the box. All zones turn **blue**: it's in setup mode.
2. On your phone, join the Wi-Fi network **QuizLights-Setup**. A setup page opens; if not, open `192.168.4.1`.
3. Choose the Wi-Fi the box will use and enter its password.
   - **School Wi-Fi with a login page won't work.** Use your **phone's hotspot** or a normal password-protected Wi-Fi instead.
4. In **ntfy topic**, paste your Study Watch topic: the `studywatch-…` value from Study Watch's Settings, the same one your phone subscribes to. The box adds `-lights` itself.
5. Save. The box joins the Wi-Fi, beeps, and starts **breathing white**.

To change the Wi-Fi or topic later, hold the ESP32's **BOOT** button for 3 seconds.

## Turn it on in Study Watch
On the laptop, right-click the tray icon:
1. Tick **Quiz lights**.
2. Click **Test quiz lights**. You should see a drum roll, then a random zone lights up.

Then project a question and tap **Right Ctrl**.

## Troubleshooting
- **Zone A blinks red:** the box has no internet. Check the Wi-Fi or hotspot, or hold BOOT to set it up again.
- **Drum roll never starts:** check **Quiz lights** is ticked in the tray, and that the box's topic matches Study Watch's exactly.
- **Wrong zone lights up, or colours look odd:** check `LEDS_PER_ZONE` and `NUM_ZONES` match your strips. Zones must be chained A → B → C in order.
- **LEDs flicker or the ESP32 restarts:** the power supply is too weak. Lower `BRIGHTNESS` in `config.h` or use a bigger supply.
