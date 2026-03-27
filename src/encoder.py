"""
encoder.py
----------
KY-040 Rotary Encoder handler using GPIO interrupt-based detection.
Supports: turn CW/CCW, short press, long press (config mode trigger).
Falls back to keyboard simulation on non-Pi systems.

Wiring (BCM GPIO):
  CLK  → GPIO13 (Pin 33)
  DT   → GPIO6  (Pin 31)
  SW   → GPIO5  (Pin 29)
  VCC  → 3.3V   (Pin 1)
  GND  → GND    (Pin 6)

Datix AI | Ahmed Ali | datixai.com
"""

import logging
import threading
import time
from enum import Enum, auto

logger = logging.getLogger(__name__)


class EncoderEvent(Enum):
    TURN_CW      = auto()   # Clockwise turn  → CMC +1
    TURN_CCW     = auto()   # Counter-clockwise → CMC -1
    SHORT_PRESS  = auto()   # Quick press → Confirm / select
    LONG_PRESS   = auto()   # Hold 3s → Enter/exit config mode
    NONE         = auto()


class RotaryEncoder:
    """
    Interrupt-driven KY-040 rotary encoder reader.
    Calls the provided callback(EncoderEvent) on any input.
    Uses a Gray-code state machine for reliable direction detection.
    """

    # Gray code transition table: maps (last_state, new_state) → direction
    _GRAY = {
        (0b00, 0b01): +1,
        (0b01, 0b11): +1,
        (0b11, 0b10): +1,
        (0b10, 0b00): +1,
        (0b00, 0b10): -1,
        (0b10, 0b11): -1,
        (0b11, 0b01): -1,
        (0b01, 0b00): -1,
    }

    def __init__(self, cfg, callback):
        """
        :param cfg:      ConfigParser instance
        :param callback: callable(EncoderEvent) — called on each event
        """
        self._callback  = callback
        self._sim       = False
        self._running   = False
        self._thread    = None

        # Pin config
        self._clk = cfg.getint("HARDWARE", "gpio_encoder_clk", fallback=13)
        self._dt  = cfg.getint("HARDWARE", "gpio_encoder_dt",  fallback=6)
        self._sw  = cfg.getint("HARDWARE", "gpio_encoder_sw",  fallback=5)
        self._hold_time = cfg.getfloat("HARDWARE", "hold_time", fallback=3.0)

        # State
        self._last_encoded   = 0
        self._press_time     = 0.0
        self._press_active   = False
        self._encoder_lock   = threading.Lock()

        self._init_gpio()

    # ── Initialisation ────────────────────────────────────────────────────────
    def _init_gpio(self):
        try:
            import RPi.GPIO as GPIO
            self._GPIO = GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

            GPIO.setup(self._clk, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(self._dt,  GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(self._sw,  GPIO.IN, pull_up_down=GPIO.PUD_UP)

            # Read initial state
            clk = GPIO.input(self._clk)
            dt  = GPIO.input(self._dt)
            self._last_encoded = (clk << 1) | dt

            # Interrupt detection
            GPIO.add_event_detect(self._clk, GPIO.BOTH,
                                  callback=self._encoder_callback,
                                  bouncetime=2)
            GPIO.add_event_detect(self._dt,  GPIO.BOTH,
                                  callback=self._encoder_callback,
                                  bouncetime=2)
            GPIO.add_event_detect(self._sw,  GPIO.BOTH,
                                  callback=self._button_callback,
                                  bouncetime=50)

            logger.info(f"Encoder GPIO initialised — CLK:{self._clk} DT:{self._dt} SW:{self._sw}")

        except (ImportError, RuntimeError, AttributeError) as e:
            logger.warning(f"GPIO not available ({e}) — encoder in keyboard simulation mode")
            self._sim = True
            self._GPIO = None
            self._start_keyboard_sim()

    # ── Interrupt callbacks (RPi) ─────────────────────────────────────────────
    def _encoder_callback(self, channel):
        """Called on CLK or DT edge — determines rotation direction."""
        try:
            clk = self._GPIO.input(self._clk)
            dt  = self._GPIO.input(self._dt)
            encoded = (clk << 1) | dt

            with self._encoder_lock:
                direction = self._GRAY.get((self._last_encoded, encoded), 0)
                self._last_encoded = encoded

            if direction == +1:
                self._callback(EncoderEvent.TURN_CW)
            elif direction == -1:
                self._callback(EncoderEvent.TURN_CCW)

        except Exception as e:
            logger.debug(f"Encoder callback error: {e}")

    def _button_callback(self, channel):
        """Called on SW pin edge — distinguishes short vs long press."""
        try:
            state = self._GPIO.input(self._sw)
            now   = time.time()

            if state == 0:  # Button pressed (active low with pull-up)
                self._press_time   = now
                self._press_active = True
            else:           # Button released
                if self._press_active:
                    duration = now - self._press_time
                    self._press_active = False
                    if duration >= self._hold_time:
                        self._callback(EncoderEvent.LONG_PRESS)
                    else:
                        self._callback(EncoderEvent.SHORT_PRESS)

        except Exception as e:
            logger.debug(f"Button callback error: {e}")

    # ── Keyboard simulation (Windows/dev) ────────────────────────────────────
    def _start_keyboard_sim(self):
        """
        On non-Pi systems, read keyboard input for testing.
        w/a = CW/CCW turn  |  Enter = short press  |  L = long press
        """
        self._running = True
        self._thread  = threading.Thread(target=self._keyboard_loop, daemon=True)
        self._thread.start()
        logger.info("Encoder keyboard simulation active — keys: [a/d] or arrows, Enter=select, L=long press")

    def _keyboard_loop(self):
        """Non-blocking keyboard input loop for simulation."""
        import sys
        print("\n[ENCODER SIM] Controls:", flush=True)
        print("  → or d = CMC +1 (CW turn)")
        print("  ← or a = CMC -1 (CCW turn)")
        print("  Enter  = Confirm (short press)")
        print("  l      = Long press (config mode)")
        print("  q      = Quit\n", flush=True)

        # Try to use getch for immediate response
        try:
            import msvcrt  # Windows
            def getch():
                ch = msvcrt.getwch()
                return ch if isinstance(ch, str) else ch.decode("utf-8", errors="ignore")
        except ImportError:
            try:
                import tty, termios  # Unix
                fd = sys.stdin.fileno()
                old = termios.tcgetattr(fd)
                def getch():
                    tty.setraw(fd)
                    try:
                        return sys.stdin.read(1)
                    finally:
                        termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except Exception:
                # Fallback — line-based input
                def getch():
                    return input("> ").strip()[:1] if self._running else "q"

        while self._running:
            try:
                ch = getch()
                if ch in ("d", "\x1b[C"):      # Right arrow or 'd'
                    self._callback(EncoderEvent.TURN_CW)
                elif ch in ("a", "\x1b[D"):    # Left arrow or 'a'
                    self._callback(EncoderEvent.TURN_CCW)
                elif ch in ("\r", "\n", " "): # Enter or Space
                    self._callback(EncoderEvent.SHORT_PRESS)
                elif ch in ("l", "L"):
                    self._callback(EncoderEvent.LONG_PRESS)
                elif ch in ("q", "Q"):
                    self._running = False
                    break
            except (EOFError, KeyboardInterrupt):
                break

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    def stop(self):
        """Clean up GPIO and threads."""
        self._running = False
        if self._GPIO and not self._sim:
            try:
                self._GPIO.remove_event_detect(self._clk)
                self._GPIO.remove_event_detect(self._dt)
                self._GPIO.remove_event_detect(self._sw)
            except Exception:
                pass
        logger.info("Encoder stopped")

    def is_simulation(self) -> bool:
        return self._sim
