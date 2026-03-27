"""
config_manager.py
-----------------
Centralized configuration loading and shared application state.
Detects simulation mode automatically when RPi hardware is unavailable (e.g. Windows dev).

Datix AI | Ahmed Ali | datixai.com
"""

import configparser
import os
import sys
import logging
import threading
from pathlib import Path
from logging.handlers import RotatingFileHandler

# ── Project root (one level above src/) ──────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH  = PROJECT_ROOT / "src" / "config.ini"

# ── Detect platform ───────────────────────────────────────────────────────────
IS_RASPBERRY_PI = False
try:
    with open("/proc/cpuinfo", "r") as f:
        if "Raspberry Pi" in f.read() or "BCM" in f.read():
            IS_RASPBERRY_PI = True
except Exception:
    pass

if sys.platform == "win32":
    IS_RASPBERRY_PI = False


def load_config() -> configparser.ConfigParser:
    """Load and return the config.ini ConfigParser object."""
    cfg = configparser.ConfigParser(interpolation=None)
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")
    cfg.read(str(CONFIG_PATH))
    return cfg


def save_config(cfg: configparser.ConfigParser) -> None:
    """Write changes back to config.ini (thread-safe via caller lock)."""
    with open(str(CONFIG_PATH), "w") as f:
        cfg.write(f)


def setup_logging(cfg: configparser.ConfigParser) -> logging.Logger:
    """Configure root logger with rotating file + console handlers."""
    log_level  = cfg.get("LOGGING", "log_level", fallback="INFO")
    log_format = cfg.get("LOGGING", "log_format",
                         fallback="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    date_fmt   = cfg.get("LOGGING", "log_date_format", fallback="%Y-%m-%d %H:%M:%S")
    log_file   = PROJECT_ROOT / cfg.get("LOGGING", "log_file", fallback="logs/mtg_printer.log")
    max_bytes  = cfg.getint("LOGGING", "max_log_bytes",  fallback=5_242_880)
    backup     = cfg.getint("LOGGING", "log_backup_count", fallback=3)

    log_file.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    fmt = logging.Formatter(log_format, datefmt=date_fmt)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # File handler (rotating)
    try:
        fh = RotatingFileHandler(str(log_file), maxBytes=max_bytes, backupCount=backup)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception as e:
        root.warning(f"Could not create log file handler: {e}")

    return root


# ── Shared application state (thread-safe) ────────────────────────────────────
class AppState:
    """
    Thread-safe shared state between the main hardware loop and the Flask web server.
    All reads/writes should go through this object.
    """
    def __init__(self):
        self._lock = threading.Lock()

        self.status         = "Booting..."   # Current OLED status string
        self.cmc            = 0              # Currently selected CMC (0-16)
        self.in_config_mode = False          # Is device in filter config mode?
        self.config_type_idx= 0             # Which filter type is being edited
        self.db_loaded      = False          # Is the card database loaded?
        self.db_card_count  = 0             # Total cards in DB
        self.db_last_updated= None           # ISO datetime string
        self.last_card      = None           # Dict of last printed card
        self.print_count    = 0             # Total prints since boot
        self.update_running = False          # Is a DB update in progress?
        self.update_progress= ""            # Update progress message
        self.update_percent = 0             # Update progress 0-100
        self.error_message  = None          # Last error (or None)
        self.simulation_mode= False          # Hardware simulation active

    # ── Generic get/set ──────────────────────────────────────────────────────
    def get(self, attr):
        with self._lock:
            return getattr(self, attr)

    def set(self, attr, value):
        with self._lock:
            setattr(self, attr, value)

    def update(self, **kwargs):
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def to_dict(self) -> dict:
        """Snapshot of state as plain dict for JSON serialisation."""
        with self._lock:
            return {
                "status":          self.status,
                "cmc":             self.cmc,
                "in_config_mode":  self.in_config_mode,
                "db_loaded":       self.db_loaded,
                "db_card_count":   self.db_card_count,
                "db_last_updated": self.db_last_updated,
                "last_card":       self.last_card,
                "print_count":     self.print_count,
                "update_running":  self.update_running,
                "update_progress": self.update_progress,
                "update_percent":  self.update_percent,
                "error_message":   self.error_message,
                "simulation_mode": self.simulation_mode,
                "platform":        "Raspberry Pi" if IS_RASPBERRY_PI else "Simulation",
            }


# Singleton instances
_cfg   = None
_state = None

def get_config() -> configparser.ConfigParser:
    global _cfg
    if _cfg is None:
        _cfg = load_config()
    return _cfg

def reload_config() -> configparser.ConfigParser:
    """Force reload of config from disk."""
    global _cfg
    _cfg = load_config()
    return _cfg

def get_state() -> AppState:
    global _state
    if _state is None:
        _state = AppState()
    return _state
