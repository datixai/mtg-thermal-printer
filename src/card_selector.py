"""
card_selector.py
----------------
Manages card type filters and orchestrates card selection
from the local database, applying active filter settings.

Datix AI | Ahmed Ali | datixai.com
"""

import logging
import configparser
from pathlib import Path

logger = logging.getLogger(__name__)

# All configurable card type names
ALL_TYPES = [
    "artifact", "battle", "creature", "enchantment",
    "instant", "planeswalker", "sorcery"
]


class CardSelector:
    """
    Reads enabled card types from config.ini [FILTERS] section.
    Provides card selection interface to the main application loop.
    """

    def __init__(self, cfg: configparser.ConfigParser, database):
        self._cfg = cfg
        self._db  = database

    # ── Filter management ─────────────────────────────────────────────────────
    def get_enabled_types(self) -> list:
        """Return list of currently enabled card type strings (title-cased)."""
        enabled = []
        for t in ALL_TYPES:
            try:
                if self._cfg.getboolean("FILTERS", t, fallback=True):
                    enabled.append(t.title())
            except (configparser.NoSectionError, configparser.NoOptionError):
                enabled.append(t.title())
        return enabled

    def get_filter_state(self) -> dict:
        """Return dict of {type_name: bool} for all card types."""
        state = {}
        for t in ALL_TYPES:
            try:
                state[t] = self._cfg.getboolean("FILTERS", t, fallback=True)
            except Exception:
                state[t] = True
        return state

    def set_filter(self, card_type: str, enabled: bool):
        """
        Toggle a single card type filter and save to config.ini.
        card_type: lowercase string, e.g. "creature"
        """
        card_type = card_type.lower()
        if card_type not in ALL_TYPES:
            logger.warning(f"Unknown card type: {card_type}")
            return False

        if not self._cfg.has_section("FILTERS"):
            self._cfg.add_section("FILTERS")

        self._cfg.set("FILTERS", card_type, str(enabled).lower())
        self._save_config()
        logger.info(f"Filter '{card_type}' set to {enabled}")
        return True

    def set_all_filters(self, filters: dict):
        """Set multiple filters at once from a dict {type: bool}."""
        if not self._cfg.has_section("FILTERS"):
            self._cfg.add_section("FILTERS")
        for card_type, enabled in filters.items():
            if card_type.lower() in ALL_TYPES:
                self._cfg.set("FILTERS", card_type.lower(), str(enabled).lower())
        self._save_config()
        logger.info(f"Filters updated: {filters}")

    def _save_config(self):
        """Write current config back to disk."""
        config_path = Path(__file__).resolve().parent / "config.ini"
        try:
            with open(str(config_path), "w") as f:
                self._cfg.write(f)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    # ── Card selection ────────────────────────────────────────────────────────
    def select_card(self, cmc: int) -> dict | None:
        """
        Select a random card at the given CMC value using current filters.
        Returns card dict or None if no matching cards.
        """
        enabled = self.get_enabled_types()
        if not enabled:
            logger.warning("All card types disabled — no cards available")
            return None

        return self._db.get_random_card(cmc, enabled)

    def count_available(self, cmc: int) -> int:
        """How many cards are available at this CMC with current filters?"""
        enabled = self.get_enabled_types()
        return self._db.get_cards_at_cmc(cmc, enabled)

    # ── Config mode cycling (for encoder long-press interface) ─────────────────
    def get_type_at_index(self, index: int) -> str:
        """Get the card type name at a given index (for cycling in config mode)."""
        return ALL_TYPES[index % len(ALL_TYPES)]

    def toggle_type_at_index(self, index: int) -> bool:
        """Toggle the card type at given index. Returns new state."""
        t       = self.get_type_at_index(index)
        current = self._cfg.getboolean("FILTERS", t, fallback=True)
        self.set_filter(t, not current)
        return not current

    def get_type_state_at_index(self, index: int) -> tuple:
        """Returns (type_name, is_enabled) for display in config mode."""
        t       = self.get_type_at_index(index)
        enabled = self._cfg.getboolean("FILTERS", t, fallback=True)
        return t.upper(), enabled

    @staticmethod
    def type_count() -> int:
        return len(ALL_TYPES)
