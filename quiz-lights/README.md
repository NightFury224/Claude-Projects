# Quiz Lights

A classroom game and a lesson in how light carries information, for Study Watch. Project a question, the kids stand on the zone they think is right (A, B, C, …), and you tap **Right Ctrl** on the laptop. The lights play a drum roll while the AI works, then the correct zone flashes green, and everyone on it cheers.

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

## Teaching modes: one bulb carrying information
Switch modes from the laptop (tray → **Quiz lights mode**) or with a **short press of the box's BOOT button**. The box flashes purple 1, 2 or 3 times to show the mode. The mode is remembered when the box is switched off.

In the two teaching modes the **whole strip acts as one bulb**, and it shows **only the answer**: no drum roll, no start or stop signals. It stays dark while the AI works, then flashes the answer once. You do the explaining. Options become numbers: **0 = no answer, A = 1, B = 2, C = 3 …**

**Counting:** the bulb blinks white once per unit. B = 2 blinks, E = 5 blinks, and no answer = no blinks.

**Binary:** one flash per bit, most significant bit first, with a short dark gap between flashes.
- **1 = bright white**, **0 = dim blue.**
- A 0 is still a light that's **on**, so it can never be confused with the bulb being off. Dark only ever means "between bits" or "finished".

| Answer | Number | Binary | What the bulb shows | Counting blinks |
|---|---|---|---|---|
| no answer | 0 | 000 | 🔵 🔵 🔵 | none |
| A | 1 | 001 | 🔵 🔵 ⚪ | 1 |
| B | 2 | 010 | 🔵 ⚪ 🔵 | 2 |
| C | 3 | 011 | 🔵 ⚪ ⚪ | 3 |
| D | 4 | 100 | ⚪ 🔵 🔵 | 4 |
| E | 5 | 101 | ⚪ 🔵 ⚪ | 5 |
| F | 6 | 110 | ⚪ ⚪ 🔵 | 6 |
| G | 7 | 111 | ⚪ ⚪ ⚪ | 7 |

**Talking points for the class:**
- **Why binary wins:** 3 flashes always carry any of 8 values, while counting needs up to 7 blinks. 10 flashes carry 1,024 values; counting to 1,000 would take 1,000 blinks. Each extra flash **doubles** what you can send.
- **Why 0 must look different from "off":** if 0 were just darkness, nobody could tell 0-0-1 from 1, or a 0 from "the message has ended". Real systems solve this the same way, by giving 0 its own signal or by agreeing on exact timing.
- **Activity:** each kid writes down the flashes as they appear (white = 1, blue = 0), converts to a number and then to a letter, and stands on that option.

Settings in `config.h`:
- `BITS`: 3 gives 0–7; use 4 if your quiz has more than 7 options.
- `SLOT_MS` / `GAP_MS`: how long each flash and each dark gap lasts. Start slow, and speed up once the class gets good at it, to show how speed and readability trade off.
- `ONE_COLOR` / `ZERO_COLOR`: the colours for 1 and 0.
- `SIGNAL_MODE`: the mode used on first start.

## One plain bulb (the default build)
`config.h` ships with `SINGLE_BULB 1`: one ordinary on/off bulb or LED on **GPIO 4**. A plain bulb has no colours, so binary uses **flash length** instead, like Morse code:

- **1 = long flash** (1.2 s), **0 = short flash** (0.3 s), with a dark gap between flashes.
- A 0 is still a flash that's **on**, so it's never confused with "off". Dark only means "between bits" or "finished".
- Example: B = 2 = 010 → short, **long**, short.

| Answer | Binary | What the bulb shows |
|---|---|---|
| no answer | 000 | · · · |
| A | 001 | · · ▬ |
| B | 010 | · ▬ · |
| C | 011 | · ▬ ▬ |
| D | 100 | ▬ · · |
| E | 101 | ▬ · ▬ |

Counting works the same as above (B = 2 blinks). Zones mode needs a strip, so with one bulb the BOOT button switches only between **counting** and **binary**.

**The bulb only ever shows answers.** Status goes to the ESP32's small built-in LED: slow blink = no internet, solid = AI working, fast blink = failed. On a mode change it blinks 1× for counting, 2× for binary.

**Wiring the bulb:**
- **A single LED:** GPIO 4 → 220 Ω resistor → LED long leg; short leg → GND.
- **A brighter bulb (5–12 V LED bulb or lamp):** use a logic-level MOSFET module (e.g. IRLZ44N) or a transistor module driven from GPIO 4, powered by the bulb's own supply, grounds connected.
- **A mains (230 V) bulb:** only through a ready-made **relay module** in a closed box, wired by someone qualified. Many relay modules switch on when the pin is LOW: if yours is reversed, set `BULB_ACTIVE_HIGH false`. A relay clicks on every flash, which kids can also hear. An LED or 12 V bulb is safer and flashes more crisply.

**Testing on a Seeed XIAO ESP32S3:** flash **QuizLights-xiao-esp32s3.bin** instead. The board's small **orange LED** is the bulb, so you can test with no wiring at all. The board has no second LED, so status (thinking, no Wi-Fi) isn't shown during the test. For a real bulb, rebuild with `BULB_PIN 1` (pin D0). To flash: hold **B** (BOOT), plug in USB, then release it.

Settings: `LONG_MS` / `SHORT_MS` / `GAP_MS` set the flash lengths. To use an LED strip instead, set `SINGLE_BULB 0`.

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
