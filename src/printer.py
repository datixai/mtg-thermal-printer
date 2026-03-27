"""
printer.py
----------
Thermal printer handler using python-escpos.
Formats and prints MTG card receipts including:
  - Card artwork (dithered monochrome)
  - Card name + mana cost
  - Type line
  - Oracle text (word-wrapped)
  - Power/toughness or loyalty
  - QR code linking to Scryfall

Wiring:
  Printer TX → GPIO15 (UART RX)  via logic level converter
  Printer RX ← GPIO14 (UART TX)  via logic level converter
  Printer GND → GND
  Printer VCC → 5-9V from PSU

Datix AI | Ahmed Ali | datixai.com
"""

import logging
import textwrap
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class ThermalPrinter:
    """
    Thread-safe wrapper around python-escpos for card receipt printing.
    Falls back to console simulation when hardware is unavailable.
    """

    def __init__(self, cfg):
        self._lock     = threading.Lock()
        self._printer  = None
        self._sim      = False
        self._cfg      = cfg

        self._serial_port   = cfg.get("HARDWARE", "serial_port",     fallback="/dev/serial0")
        self._baud_rate     = cfg.getint("HARDWARE", "serial_baud_rate", fallback=9600)
        self._dtr_enabled   = cfg.getboolean("HARDWARE", "printer_dtr_enabled", fallback=True)
        self._dtr_pin       = cfg.getint("HARDWARE", "gpio_printer_dtr", fallback=17)
        self._media_w_px    = cfg.getint("PRINTER",  "printer_media_width_px", fallback=384)
        self._paper_chars   = cfg.getint("PRINTER",  "paper_width_chars",      fallback=32)
        self._art_enabled   = cfg.getboolean("PRINTER", "card_art_enabled",    fallback=True)
        self._qr_enabled    = cfg.getboolean("PRINTER", "qr_code_enabled",     fallback=True)
        self._qr_size       = cfg.getint("PRINTER",  "qr_code_size",           fallback=3)
        self._profile       = cfg.get("PRINTER",     "printer_profile",        fallback="default")
        self._dtr_timeout   = cfg.getfloat("HARDWARE", "printer_dtr_timeout",  fallback=10.0)
        self._dtr_poll      = cfg.getfloat("HARDWARE", "dtr_poll_interval",    fallback=0.1)

        self._init_printer()

    # ── Initialisation ────────────────────────────────────────────────────────
    def _init_printer(self):
        """Connect to thermal printer; fall back to simulation."""
        try:
            from escpos.printer import Serial as EscSerial
            self._printer = EscSerial(
                devfile=self._serial_port,
                baudrate=self._baud_rate,
                bytesize=8,
                parity="N",
                stopbits=1,
                timeout=1.00,
                dsrdtr=self._dtr_enabled,
                profile=self._profile,
            )
            logger.info(f"Printer connected: {self._serial_port} @ {self._baud_rate} baud")
        except Exception as e:
            logger.warning(f"Printer not available ({e}) — using simulation mode")
            self._sim = True

    # ── Public print method ───────────────────────────────────────────────────
    def print_card(self, card: dict, image_processor=None) -> bool:
        """
        Print a complete MTG card receipt.
        Returns True on success, False on error.
        """
        with self._lock:
            if self._sim:
                return self._simulate_print(card)
            try:
                return self._do_print(card, image_processor)
            except Exception as e:
                logger.error(f"Print failed: {e}")
                self._reconnect()
                return False

    def print_status(self, message: str):
        """Print a short status message (for testing/diagnostics)."""
        with self._lock:
            if self._sim:
                print(f"[PRINTER] {message}")
                return
            try:
                p = self._printer
                p.set(align="center")
                p.text(f"\n{message}\n\n")
                p.cut()
            except Exception as e:
                logger.error(f"Status print failed: {e}")

    # ── Internal print logic ──────────────────────────────────────────────────
    def _do_print(self, card: dict, image_processor) -> bool:
        """Full ESC/POS card receipt output."""
        p = self._printer

        # ── Art ──────────────────────────────────────────────────────────────
        if self._art_enabled and image_processor:
            try:
                img = image_processor.get_card_image(card)
                p.image(img, impl="bitImageRaster")
                p.ln(1)
            except Exception as e:
                logger.warning(f"Art print failed (continuing without): {e}")

        # ── Header: name + mana cost ─────────────────────────────────────────
        name      = card.get("name", "Unknown Card")
        mana_cost = self._clean_mana(card.get("mana_cost", ""))
        p.set(align="left", bold=True, double_height=False, double_width=False)

        if mana_cost:
            # Right-align mana cost, left-align name
            gap = self._paper_chars - len(name) - len(mana_cost)
            if gap >= 1:
                header = name + (" " * gap) + mana_cost
            else:
                header = name[:self._paper_chars - len(mana_cost) - 1] + " " + mana_cost
        else:
            header = name

        p.text(header[:self._paper_chars] + "\n")

        # ── Type line ────────────────────────────────────────────────────────
        p.set(align="left", bold=False)
        type_line = card.get("type_line", "")
        p.text(self._wrap_line(type_line) + "\n")

        # ── Divider ──────────────────────────────────────────────────────────
        p.text("─" * self._paper_chars + "\n")

        # ── Oracle text ──────────────────────────────────────────────────────
        oracle = self._clean_oracle(card.get("oracle_text", ""))
        if oracle:
            for para in oracle.split("\n"):
                for line in textwrap.wrap(para.strip(), width=self._paper_chars):
                    p.text(line + "\n")
                p.ln(1)

        # ── Power/toughness or loyalty ────────────────────────────────────────
        power     = card.get("power")
        toughness = card.get("toughness")
        loyalty   = card.get("loyalty")
        if power and toughness:
            p.set(bold=True)
            p.text(f"P/T: {power}/{toughness}\n")
            p.set(bold=False)
        elif loyalty:
            p.set(bold=True)
            p.text(f"Loyalty: {loyalty}\n")
            p.set(bold=False)

        # ── Rarity + Set ──────────────────────────────────────────────────────
        rarity = card.get("rarity", "").capitalize()
        set_id = card.get("set", "").upper()
        if rarity or set_id:
            p.text(f"{rarity} · {set_id}\n")

        # ── QR code ──────────────────────────────────────────────────────────
        if self._qr_enabled:
            scryfall_id = card.get("id", "")
            if scryfall_id:
                qr_url = f"https://scryfall.com/card/{scryfall_id}"
                try:
                    p.ln(1)
                    p.set(align="center")
                    p.qr(qr_url, size=self._qr_size)
                    p.text("Scan for card details\n")
                    p.set(align="left")
                except Exception as e:
                    logger.warning(f"QR code generation failed: {e}")

        # ── Footer ────────────────────────────────────────────────────────────
        p.ln(1)
        p.set(align="center")
        p.text("Datix AI · MTG Printer\n")
        p.set(align="left")
        p.ln(2)
        p.cut()

        logger.info(f"Printed: {name}")
        return True

    # ── Console simulation ────────────────────────────────────────────────────
    def _simulate_print(self, card: dict) -> bool:
        """Print card info to console when hardware is unavailable."""
        w = self._paper_chars
        sep = "─" * w
        name      = card.get("name", "Unknown Card")
        mana_cost = self._clean_mana(card.get("mana_cost", ""))
        type_line = card.get("type_line", "")
        oracle    = self._clean_oracle(card.get("oracle_text", ""))
        power     = card.get("power")
        toughness = card.get("toughness")
        loyalty   = card.get("loyalty")

        print(f"\n{'='*w}")
        print(f"  {name:<{w-len(mana_cost)-4}}{mana_cost}")
        print(sep)
        print(f"  {type_line}")
        print(sep)
        if oracle:
            for line in textwrap.wrap(oracle, width=w-2):
                print(f"  {line}")
        if power and toughness:
            print(f"\n  P/T: {power}/{toughness}")
        elif loyalty:
            print(f"\n  Loyalty: {loyalty}")
        rarity = card.get("rarity", "").capitalize()
        set_id = card.get("set", "").upper()
        if rarity:
            print(f"  {rarity} · {set_id}")
        print(f"{'='*w}\n")
        logger.info(f"[SIM] Printed: {name}")
        return True

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _clean_mana(self, mana: str) -> str:
        """Remove {} brackets from mana cost strings."""
        if not mana:
            return ""
        # Replace {W} → W, {2/W} → 2/W, etc.
        import re
        result = re.sub(r"\{([^}]+)\}", lambda m: m.group(1), mana)
        return result.strip()

    def _clean_oracle(self, text: str) -> str:
        """Clean up oracle text for thermal printing."""
        if not text:
            return ""
        import re
        # Replace mana symbols
        text = re.sub(r"\{([^}]+)\}", lambda m: f"[{m.group(1)}]", text)
        return text

    def _wrap_line(self, text: str) -> str:
        """Wrap a single line to paper width."""
        if len(text) <= self._paper_chars:
            return text
        return text[:self._paper_chars - 3] + "..."

    def _reconnect(self):
        """Attempt to reconnect to printer after an error."""
        logger.info("Attempting printer reconnection...")
        try:
            self._init_printer()
        except Exception as e:
            logger.error(f"Reconnection failed: {e}")

    def is_simulation(self) -> bool:
        return self._sim
