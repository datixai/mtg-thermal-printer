#!/bin/bash
# ============================================================
# MTG Printer — Raspberry Pi Setup Script
# Datix AI | Ahmed Ali | datixai.com
# Run as the pi user: bash scripts/setup.sh
# ============================================================

set -e  # Exit on error
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
echo "============================================================"
echo "  Datix AI — MTG Thermal Printer Setup"
echo "  Project: $PROJECT_DIR"
echo "============================================================"
echo ""

# ── 1. System update & dependencies ──────────────────────────────────────────
echo "[1/7] Updating system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3-pip python3-dev python3-venv \
    libjpeg-dev zlib1g-dev libfreetype6-dev \
    liblcms2-dev libopenjp2-7 libtiff5 \
    i2c-tools \
    fonts-dejavu-core \
    git \
    2>/dev/null
echo "      ✓ System packages installed"

# ── 2. Enable interfaces ──────────────────────────────────────────────────────
echo "[2/7] Enabling I2C and Serial..."
# Enable I2C
sudo raspi-config nonint do_i2c 0 2>/dev/null || echo "      ! raspi-config not available (OK in dev)"
# Enable Serial (disable console, keep hardware)
sudo raspi-config nonint do_serial_hw 0 2>/dev/null || echo "      ! Serial config skipped (OK in dev)"
sudo raspi-config nonint do_serial_cons 1 2>/dev/null || true
echo "      ✓ Interfaces configured"

# ── 3. User groups ────────────────────────────────────────────────────────────
echo "[3/7] Adding user to hardware groups..."
sudo usermod -aG gpio,i2c,spi,dialout pi 2>/dev/null || true
echo "      ✓ Groups configured"

# ── 4. Python dependencies ────────────────────────────────────────────────────
echo "[4/7] Installing Python dependencies..."
pip3 install --break-system-packages -q -r "$PROJECT_DIR/requirements.txt"
# Install RPi.GPIO separately
pip3 install --break-system-packages -q RPi.GPIO 2>/dev/null || echo "      ! RPi.GPIO install failed (OK if not on Pi)"
echo "      ✓ Python packages installed"

# ── 5. Fonts ──────────────────────────────────────────────────────────────────
echo "[5/7] Setting up fonts..."
FONT_DIR="$PROJECT_DIR/fonts"
mkdir -p "$FONT_DIR"
# Copy DejaVu fonts from system
for FONT in "DejaVuSans.ttf" "DejaVuSans-Bold.ttf"; do
    FOUND=$(find /usr/share/fonts -name "$FONT" 2>/dev/null | head -1)
    if [ -n "$FOUND" ]; then
        cp "$FOUND" "$FONT_DIR/"
        echo "      ✓ Copied: $FONT"
    else
        echo "      ! Font not found: $FONT (display will use fallback)"
    fi
done

# ── 6. Directories ────────────────────────────────────────────────────────────
echo "[6/7] Creating data directories..."
mkdir -p "$PROJECT_DIR/data/cards"
mkdir -p "$PROJECT_DIR/data/art"
mkdir -p "$PROJECT_DIR/logs"
chmod 755 "$PROJECT_DIR/data/cards" "$PROJECT_DIR/data/art" "$PROJECT_DIR/logs"
echo "      ✓ Directories ready"

# ── 7. systemd service ────────────────────────────────────────────────────────
echo "[7/7] Installing systemd service..."
# Update path in service file to actual project location
SERVICE_SRC="$PROJECT_DIR/services/mtg-printer.service"
SERVICE_DST="/etc/systemd/system/mtg-printer.service"

# Replace placeholder paths with actual project path
sed "s|/home/pi/mtg-printer|$PROJECT_DIR|g" "$SERVICE_SRC" | \
    sudo tee "$SERVICE_DST" > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable mtg-printer.service
echo "      ✓ Service installed and enabled"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  ✅ Setup complete!"
echo ""
echo "  NEXT STEPS:"
echo ""
echo "  1. Download card database (first time only):"
echo "     python3 $PROJECT_DIR/src/main.py --update"
echo ""
echo "  2. Start the printer service:"
echo "     sudo systemctl start mtg-printer.service"
echo ""
echo "  3. Check it's running:"
echo "     sudo systemctl status mtg-printer.service"
echo ""
echo "  4. Open the web dashboard:"
echo "     http://$(hostname -I | awk '{print $1}'):5000"
echo ""
echo "  5. View live logs:"
echo "     sudo journalctl -u mtg-printer.service -f"
echo "============================================================"
