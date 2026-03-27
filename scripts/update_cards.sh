#!/bin/bash
# ============================================================
# MTG Printer — Card Database Update Script
# Datix AI | Ahmed Ali | datixai.com
# Run when new MTG sets are released (3-4x per year)
# Usage: bash scripts/update_cards.sh
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
echo "============================================================"
echo "  Datix AI — MTG Card Database Update"
echo "  $(date)"
echo "============================================================"
echo ""
echo "Downloading latest card data from Scryfall..."
echo "(This requires Wi-Fi and takes 5-15 minutes)"
echo ""
# Stop service during update to free memory
echo "Stopping printer service temporarily..."
sudo systemctl stop mtg-printer.service 2>/dev/null || true
# Run the update
python3 "$PROJECT_DIR/src/main.py" --update
EXIT_CODE=$?
# Restart service
echo ""
echo "Restarting printer service..."
sudo systemctl start mtg-printer.service 2>/dev/null || true
if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "✅ Update complete! Printer service restarted."
else
    echo ""
    echo "❌ Update failed. Check logs: sudo journalctl -u mtg-printer.service"
fi
echo "============================================================"
