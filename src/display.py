"""
display.py
----------
SSD1306 OLED display controller using luma.oled.
Falls back to console simulation on non-Pi systems.

Wiring:
  VCC → 3.3V (Pin 1)
  GND → GND  (Pin 6)
  SDA → GPIO2 / SDA1 (Pin 3)
  SCL → GPIO3 / SCL1 (Pin 5)

Datix AI | Ahmed Ali | datixai.com
"""

import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class OLEDDisplay:
    """
    Wrapper around luma.oled SSD1306 128x64 display.
    Provides thread-safe rendering of CMC value and status messages.
    Gracefully degrades to console output on non-Pi systems.
    """

    def __init__(self, cfg):
        self._lock   = threading.Lock()
        self._device = None
        self._sim    = False
        self._font_cmc    = None
        self._font_status = None
        self._width  = cfg.getint("HARDWARE", "oled_width",  fallback=128)
        self._height = cfg.getint("HARDWARE", "oled_height", fallback=64)
        self._i2c_addr = cfg.get("HARDWARE", "i2c_address",  fallback="0x3C")
        self._i2c_port = cfg.getint("HARDWARE", "i2c_port",  fallback=1)
        self._size_cmc  = cfg.getint("HARDWARE", "display_font_size_cmc",    fallback=38)
        self._size_stat = cfg.getint("HARDWARE", "display_font_size_status", fallback=11)
        self._status_y  = cfg.getint("HARDWARE", "display_status_y_offset",  fallback=48)
        self._pad_x     = cfg.getint("HARDWARE", "display_padding_x",        fallback=4)
        self._prefix    = cfg.get("HARDWARE",    "display_cmc_prefix",       fallback="CMC")
        self._gap       = cfg.getint("HARDWARE", "display_cmc_value_gap",    fallback=6)
        font_cmc_rel    = cfg.get("HARDWARE", "display_font_cmc_path",    fallback="fonts/DejaVuSans-Bold.ttf")
        font_stat_rel   = cfg.get("HARDWARE", "display_font_status_path", fallback="fonts/DejaVuSans.ttf")
        self._font_cmc_path  = str(PROJECT_ROOT / font_cmc_rel)
        self._font_stat_path = str(PROJECT_ROOT / font_stat_rel)

        self._init_display()
        self._load_fonts()

    def _init_display(self):
        """Attempt to initialise luma.oled, fall back to simulation."""
        try:
            from luma.core.interface.serial import i2c
            from luma.oled.device import ssd1306
            addr = int(self._i2c_addr, 16) if isinstance(self._i2c_addr, str) else self._i2c_addr
            serial = i2c(port=self._i2c_port, address=addr)
            self._device = ssd1306(serial, width=self._width, height=self._height)
            logger.info(f"OLED initialised at I2C {self._i2c_addr} port {self._i2c_port}")
        except Exception as e:
            logger.warning(f"OLED hardware not available ({e}) — using simulation mode")
            self._sim = True

    def _load_fonts(self):
        """Load TTF fonts; fall back to PIL default if not found."""
        try:
            from PIL import ImageFont
            if Path(self._font_cmc_path).exists():
                self._font_cmc = ImageFont.truetype(self._font_cmc_path, self._size_cmc)
            else:
                self._font_cmc = ImageFont.load_default()
                logger.warning(f"Font not found: {self._font_cmc_path} — using default")
            if Path(self._font_stat_path).exists():
                self._font_status = ImageFont.truetype(self._font_stat_path, self._size_stat)
            else:
                self._font_status = ImageFont.load_default()
        except Exception as e:
            logger.warning(f"Font loading failed: {e}")
            self._font_cmc = self._font_status = None

    def show(self, cmc: int, status: str):
        """
        Render the OLED display with CMC value (large) and status (small).
        Thread-safe — can be called from any thread.
        """
        with self._lock:
            if self._sim:
                print(f"[OLED] {self._prefix} {cmc:>2}  |  {status}", flush=True)
                return
            try:
                self._render(cmc, status)
            except Exception as e:
                logger.error(f"OLED render error: {e}")

    def _render(self, cmc: int, status: str):
        """Internal render — must be called with lock held."""
        from luma.core.render import canvas
        from PIL import ImageDraw

        with canvas(self._device) as draw:
            # Clear background (black)
            draw.rectangle([(0, 0), (self._width - 1, self._height - 1)], fill="black")

            # Draw CMC prefix label (small, top left)
            prefix_x = self._pad_x
            prefix_y = 4
            if self._font_status:
                draw.text((prefix_x, prefix_y), self._prefix, font=self._font_status, fill="white")

            # Draw CMC number (large, centre)
            cmc_str = str(cmc)
            if self._font_cmc:
                try:
                    bbox = draw.textbbox((0, 0), cmc_str, font=self._font_cmc)
                    text_w = bbox[2] - bbox[0]
                except AttributeError:
                    text_w = self._size_cmc * len(cmc_str) * 0.6
                cmc_x = (self._width - text_w) // 2
                cmc_y = 2
                draw.text((cmc_x, cmc_y), cmc_str, font=self._font_cmc, fill="white")

            # Divider line
            draw.line([(0, self._status_y - 4), (self._width, self._status_y - 4)],
                      fill="white", width=1)

            # Status text (small, bottom)
            if self._font_status:
                # Truncate if too long
                max_chars = self._width // 6
                status_trunc = status[:max_chars]
                draw.text((self._pad_x, self._status_y), status_trunc,
                          font=self._font_status, fill="white")

    def show_message(self, line1: str, line2: str = ""):
        """Show two lines of text (used for config mode and error screens)."""
        with self._lock:
            if self._sim:
                print(f"[OLED] {line1}  {line2}", flush=True)
                return
            try:
                from luma.core.render import canvas
                with canvas(self._device) as draw:
                    draw.rectangle([(0,0),(self._width-1,self._height-1)], fill="black")
                    if self._font_status:
                        draw.text((self._pad_x, 10), line1, font=self._font_status, fill="white")
                        if line2:
                            draw.text((self._pad_x, 32), line2, font=self._font_status, fill="white")
            except Exception as e:
                logger.error(f"OLED show_message error: {e}")

    def clear(self):
        """Blank the display."""
        with self._lock:
            if self._sim:
                print("[OLED] <cleared>", flush=True)
                return
            try:
                from luma.core.render import canvas
                with canvas(self._device) as draw:
                    draw.rectangle([(0,0),(self._width-1,self._height-1)], fill="black")
            except Exception as e:
                logger.error(f"OLED clear error: {e}")

    def is_simulation(self) -> bool:
        return self._sim
