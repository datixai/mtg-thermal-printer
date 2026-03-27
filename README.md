# 🃏 MTG Thermal Printer

> **Raspberry Pi 5 thermal card printer for Magic: The Gathering — custom card type filters, offline 70k+ card database, Flask web dashboard, and one-command Vercel deployment.**

Built by **Ahmed Ali · Datix AI · [datixai.com](https://datixai.com)**

---

## What Is This?

A fully custom embedded device that sits on your game table and prints random Magic: The Gathering card receipts on demand. Spin a physical dial to pick a mana cost, press a button, and a 58mm thermal printer outputs the card's artwork, name, rules text, and a QR code — all within 3–5 seconds. Works completely offline. No phone, no laptop, no internet required during gameplay.

Extends the standard [Momir Basic](https://magic.wizards.com/en/formats/momir-basic) format with a configurable card type filter system — toggle Artifacts, Enchantments, Instants, Planeswalkers, Sorceries, Battles, and Creatures individually from the physical device or the web dashboard.

---

## Screenshots / Demo

```
┌──────────────────────────────────┐
│  OLED Display                    │
│  CMC                             │
│  ████ 5                          │
│  ─────────────────────────────   │
│  Printing...                     │
└──────────────────────────────────┘
     ↓ 3–5 seconds later
┌──────────────────────────────────┐   ← 58mm receipt
│  Shivan Dragon         {4}{R}{R} │
│  Creature — Dragon               │
│  ──────────────────────────────  │
│  Flying                          │
│  {R}: +1/+0 until end of turn.   │
│                           5/5    │
│  Rare · M10                      │
│  [QR code] → scryfall.com/...    │
└──────────────────────────────────┘
```

---

## Features

- **Random card selection** from a local database of 70,000+ MTG cards across all sets
- **Card type filter system** — toggle 7 types individually (Artifact, Battle, Creature, Enchantment, Instant, Planeswalker, Sorcery)
- **Offline operation** — full card database stored on MicroSD, no internet needed at the table
- **Card artwork** downloaded from Scryfall and dithered to 1-bit monochrome for thermal printing
- **QR code** on every receipt links to the card's Scryfall page
- **OLED display** shows current CMC and real-time status messages
- **Web dashboard** accessible from any device on your Wi-Fi (Flask on Pi + static Vercel site)
- **Auto-boot** via systemd — power on and it's ready in under 30 seconds
- **Wi-Fi card update** — one command downloads new sets when they release
- **Simulation mode** — full app runs on Windows/Mac with no hardware for development

---

## Hardware

| Component | Spec | Purpose |
|---|---|---|
| Raspberry Pi 5 | 4GB RAM | Main processor |
| 58mm Thermal Printer | Maikrt MC206H, ESC/POS serial | Card receipt output |
| SSD1306 OLED Display | 128×64, I2C | Status + CMC display |
| KY-040 Rotary Encoder | With push button | CMC selection + confirm |
| LM2596 Buck Converter | 12V → 5.1V | Pi power regulation |
| I2C Logic Level Converter | 4-channel 5V/3.3V | GPIO voltage bridging |
| 12V 60W Power Supply | SHNITPWR | Single-supply for whole unit |
| SPST Rocker Switch | 12V rated | Main power on/off |
| ABS Portable Enclosure | Compact case | Houses all electronics |
| 32GB MicroSD | Class 10 A1 | OS + card database |

---

## Wiring Reference

### OLED Display (SSD1306)
| Display | Pi Pin | GPIO |
|---------|--------|------|
| VCC | Pin 1 | 3.3V |
| GND | Pin 6 | GND |
| SDA | Pin 3 | GPIO2 |
| SCL | Pin 5 | GPIO3 |

### Rotary Encoder (KY-040)
| Encoder | Pi Pin | GPIO |
|---------|--------|------|
| VCC | Pin 1 | 3.3V |
| GND | Pin 9 | GND |
| CLK | Pin 33 | GPIO13 |
| DT | Pin 31 | GPIO6 |
| SW | Pin 29 | GPIO5 |

### Thermal Printer (via Logic Level Converter)
| Printer | → Converter → | Pi Pin | GPIO |
|---------|---------------|--------|------|
| TX | HV1 → LV1 | Pin 10 | GPIO15 (RX) |
| RX | HV2 ← LV2 | Pin 8 | GPIO14 (TX) |
| DTR | HV3 → LV3 | Pin 11 | GPIO17 |
| GND | — | Pin 14 | GND |
| VCC | — | 5–9V from PSU | — |

LV side of converter to Pi 3.3V. HV side to printer 5V.

---

## Project Structure

```
mtg-thermal-printer/
├── src/
│   ├── main.py              ← Entry point — run this
│   ├── config.ini           ← All 70+ settings (hardware pins, features)
│   ├── config_manager.py    ← Config loading + thread-safe shared state
│   ├── display.py           ← OLED SSD1306 controller (sim fallback)
│   ├── encoder.py           ← KY-040 Gray-code interrupt handler
│   ├── printer.py           ← ESC/POS thermal printer (sim fallback)
│   ├── image_processor.py   ← Art download + Floyd-Steinberg dithering
│   ├── database.py          ← Scryfall bulk download + CMC indexing
│   ├── card_selector.py     ← Filter logic + random card selection
│   ├── web_server.py        ← Flask API (10 endpoints)
│   └── templates/
│       └── index.html       ← Local web dashboard (Pi-hosted)
├── web/
│   ├── index.html           ← Remote dashboard (deploy to Vercel)
│   ├── vercel.json          ← Vercel config
│   ├── package.json         ← Minimal package for Vercel detection
│   └── README.md            ← Vercel deployment instructions
├── scripts/
│   ├── setup.sh             ← Full Pi setup in one command
│   ├── update_cards.sh      ← Update card database (new sets)
│   └── test_hardware.py     ← Individual component tests
├── services/
│   └── mtg-printer.service  ← systemd auto-boot service
├── data/
│   ├── cards/               ← Card database (auto-populated, gitignored)
│   └── art/                 ← Art cache (auto-populated, gitignored)
├── fonts/                   ← DejaVuSans fonts (see fonts/README.txt)
├── logs/                    ← Application logs (gitignored)
├── .gitignore
├── requirements.txt         ← Raspberry Pi dependencies
├── requirements_dev.txt     ← Windows / dev machine dependencies
└── README.md                ← This file
```

---

## Quick Start — Windows / VS Code (No Pi Required)

Test and develop without any hardware.

### 1. Clone the repo
```bash
git clone https://github.com/yourusername/mtg-thermal-printer.git
cd mtg-thermal-printer
```

### 2. Install dependencies
```bash
pip install -r requirements_dev.txt
```

### 3. Run in simulation mode
```bash
python src/main.py --sim
```

### 4. Open the web dashboard
```
http://localhost:5000
```

### 5. Keyboard controls (encoder simulation)
```
→  or  d     = CMC +1 (clockwise turn)
←  or  a     = CMC -1 (counter-clockwise)
Enter/Space  = Confirm selection (short press)
L            = Long press — enter/exit config mode
Q            = Quit
```

---

## Raspberry Pi Setup

### Prerequisites
- Raspberry Pi 5 with Raspberry Pi OS Lite (Bookworm 64-bit)
- SSH enabled (`sudo raspi-config` → Interface → SSH)
- Connected to Wi-Fi

### 1. Clone to Pi
```bash
git clone https://github.com/yourusername/mtg-thermal-printer.git
cd mtg-thermal-printer
```

Or copy via SCP from Windows:
```bash
scp -r mtg-thermal-printer pi@192.168.x.x:/home/pi/
```

### 2. Run setup (installs everything)
```bash
bash scripts/setup.sh
```

This installs all system packages, Python libraries, enables I2C and Serial interfaces, adds the user to hardware groups, copies fonts, and registers the systemd service.

### 3. Verify hardware connections
```bash
# Check OLED is detected on I2C
i2cdetect -y 1         # Should show 0x3c

# Check serial port for printer
ls /dev/serial*        # Should show /dev/serial0

# Run component tests
python3 scripts/test_hardware.py --all
```

### 4. Edit config if needed
```bash
nano src/config.ini
```

Key settings:
- `serial_port = /dev/serial0` — thermal printer port
- `i2c_address = 0x3C` — OLED address (confirm with i2cdetect)
- `gpio_encoder_clk/dt/sw` — must match your actual wiring

### 5. Download card database (first time only, ~100MB)
```bash
python3 src/main.py --update
```

Takes 5–15 minutes. Downloads all 70,000+ MTG cards from Scryfall.

### 6. Start the service
```bash
sudo systemctl start mtg-printer.service
sudo systemctl status mtg-printer.service
```

### 7. Open web dashboard from any device on same Wi-Fi
```
http://[YOUR-PI-IP]:5000
```

Find Pi's IP: `hostname -I`

---

## Service Management

```bash
# Start
sudo systemctl start mtg-printer.service

# Stop
sudo systemctl stop mtg-printer.service

# Restart (after code changes)
sudo systemctl restart mtg-printer.service

# Enable auto-start on boot
sudo systemctl enable mtg-printer.service

# Disable auto-start
sudo systemctl disable mtg-printer.service

# View live logs
sudo journalctl -u mtg-printer.service -f

# View logs in project folder
tail -f logs/mtg_printer.log
```

---

## Card Type Filters

Toggle which card types are included in the random selection pool.

### Via web dashboard
Open `http://[PI-IP]:5000` → Card Type Filters → toggle → Save

### Via physical device (long-press config mode)
1. Hold encoder button for 3 seconds → enters Config Mode
2. Turn dial to cycle through: Artifact → Battle → Creature → Enchantment → Instant → Planeswalker → Sorcery
3. Short press to toggle current type ON/OFF
4. Hold button 3 seconds again to exit and save

### Via config.ini directly
```ini
[FILTERS]
artifact     = true
battle       = true
creature     = true
enchantment  = true
instant      = true
planeswalker = true
sorcery      = true
```

Changes take effect after restarting the service.

---

## Update Card Database

New MTG sets release 3–4 times per year. Update the local database:

```bash
# Option A — script (stops/restarts service automatically)
bash scripts/update_cards.sh

# Option B — direct Python
python3 src/main.py --update

# Option C — web dashboard
http://[PI-IP]:5000 → Update Database → Download Latest Cards
```

---

## Vercel Web Dashboard

Deploy the remote dashboard so you can access it from any browser.

### 1. Push repo to GitHub

### 2. Deploy to Vercel
- Go to [vercel.com](https://vercel.com) → New Project
- Import your GitHub repo
- **Set Root Directory to `web`**
- Framework: **Other**
- Click **Deploy**

### 3. Open your Vercel URL
- First visit shows a setup screen — enter your Pi's IP address
- Pi and your browser must be on the same Wi-Fi network
- The dashboard saves the IP in your browser and connects directly

---

## API Reference

The Flask server on the Pi exposes these endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Device status, CMC, last card, print count |
| GET | `/api/filters` | Current filter state |
| POST | `/api/filters` | Update card type filters |
| POST | `/api/update` | Start Scryfall database download |
| GET | `/api/update_progress` | Update progress (percent + message) |
| GET | `/api/stats` | Database stats + CMC breakdown |
| GET | `/api/history` | Last 20 printed cards |
| POST | `/api/test_print` | Print a card at given CMC `{"cmc": 5}` |
| GET | `/api/cmc/<n>` | Card count available at CMC n |
| GET | `/api/system` | CPU temp, storage, memory, uptime |

---

## Troubleshooting

**OLED not showing:**
```bash
i2cdetect -y 1
# Expected: 3c at address 0x3C
# Fix: check SDA→GPIO2, SCL→GPIO3 wiring
# Check: sudo raspi-config → Interfaces → I2C → Enable
```

**Printer not responding:**
```bash
ls /dev/serial*
# Expected: /dev/serial0
# Fix: sudo raspi-config → Interfaces → Serial Port
#      Hardware = Yes, Console = No
```

**Encoder not registering turns:**
```bash
python3 scripts/test_hardware.py --encoder
# Check BCM GPIO numbers in config.ini match actual wiring
# Default: CLK=13, DT=6, SW=5
```

**Database won't load:**
```bash
ls -lh data/cards/
# Expected: all_cards.json.gz (15–30 MB)
# Fix: python3 src/main.py --update
```

**Web dashboard can't reach Pi:**
```bash
# Confirm Pi port 5000 is open
sudo ufw allow 5000/tcp

# Confirm Pi and your device are on same Wi-Fi
ping [PI-IP]

# Check service is running
sudo systemctl status mtg-printer.service
```

---

## Development Commands

```bash
# Run full simulation (no hardware)
python src/main.py --sim

# Update card database
python src/main.py --update

# Test OLED display
python scripts/test_hardware.py --display

# Test rotary encoder
python scripts/test_hardware.py --encoder

# Test thermal printer
python scripts/test_hardware.py --printer

# Scan I2C bus
python scripts/test_hardware.py --i2c

# Run all hardware tests
python scripts/test_hardware.py --all
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| OS | Raspberry Pi OS Lite (Bookworm 64-bit) — headless |
| Language | Python 3.11+ |
| Web framework | Flask 3.x |
| Printer | python-escpos (ESC/POS serial) |
| OLED display | luma.oled (SSD1306, I2C) |
| Image processing | Pillow — Floyd-Steinberg dithering |
| Card data | Scryfall API (bulk data download) |
| GPIO | RPi.GPIO (interrupt-based, no polling) |
| Service | systemd |
| Remote dashboard | Static HTML/CSS/JS → Vercel |

---

## Credits & Licence

- Card data courtesy of the [Scryfall API](https://scryfall.com/docs/api) — free for non-commercial use
- Base project reference: [MoritzHayden/momir-basic-printer](https://github.com/MoritzHayden/momir-basic-printer) (MIT)
- python-escpos (MIT) · luma.oled (MIT) · Flask (BSD)
- Built by **Ahmed Ali**, Founder & CEO, **Datix AI** — [datixai.com](https://datixai.com)

---

*Neither this project nor Datix AI are affiliated with Hasbro, Wizards of the Coast, or Magic: The Gathering.*