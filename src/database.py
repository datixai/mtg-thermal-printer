"""
database.py
-----------
Manages the local MTG card database.
Downloads from Scryfall bulk data API, filters to relevant cards,
indexes by CMC and type for fast lookup, stores as compressed JSON.

Datix AI | Ahmed Ali | datixai.com
"""

import json
import gzip
import logging
import time
import threading
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Card types we care about (from config filters)
FILTERABLE_TYPES = [
    "Artifact", "Battle", "Creature", "Enchantment",
    "Instant", "Planeswalker", "Sorcery",
    "Conspiracy", "Dungeon", "Land", "Scheme", "Vanguard", "Kindred"
]

# Fields to keep from Scryfall (reduces database size)
KEEP_FIELDS = [
    "id", "name", "mana_cost", "cmc", "type_line",
    "oracle_text", "power", "toughness", "loyalty",
    "colors", "color_identity", "set", "rarity",
    "image_uris", "card_faces", "layout"
]


class CardDatabase:
    """
    Local MTG card database manager.

    Storage layout:
      data/cards/
        all_cards.json.gz     — compressed full card list (filtered fields)
        index.json            — metadata: last updated, card counts, etc.

    In-memory index:
      _by_cmc: dict[int, list[dict]]  — cards grouped by CMC
    """

    def __init__(self, cfg, state=None):
        self._cfg   = cfg
        self._state = state
        self._lock  = threading.Lock()

        project_root = Path(__file__).resolve().parent.parent
        self._cards_path = project_root / cfg.get("FILESYSTEM", "cards_path",
                                                    fallback="data/cards")
        self._cards_path.mkdir(parents=True, exist_ok=True)

        self._db_file    = self._cards_path / "all_cards.json.gz"
        self._index_file = self._cards_path / "index.json"

        self._base_url      = cfg.get("SCRYFALL", "base_url",
                                      fallback="https://api.scryfall.com")
        self._bulk_endpoint = cfg.get("SCRYFALL", "bulk_data_endpoint",
                                      fallback="/bulk-data")
        self._user_agent    = cfg.get("SCRYFALL", "header_user_agent",
                                      fallback="DatixAI-MTGPrinter/1.0")
        self._delay         = cfg.getfloat("SCRYFALL", "request_delay_seconds",
                                           fallback=0.1)
        self._excluded_sets = [s.strip() for s in
                               cfg.get("SCRYFALL", "excluded_sets", fallback="").split(",")
                               if s.strip()]
        self._excluded_layouts = [l.strip() for l in
                                   cfg.get("SCRYFALL", "excluded_layouts",
                                           fallback="token,emblem").split(",")
                                   if l.strip()]

        # In-memory index: {cmc_int: [card_dict, ...]}
        self._by_cmc: dict = {}
        self._metadata: dict = {}

    # ── Loading ───────────────────────────────────────────────────────────────
    def load(self) -> bool:
        """
        Load cards from local database into memory.
        Returns True on success, False if database doesn't exist.
        """
        if not self._db_file.exists():
            logger.warning("Card database not found — run update to download")
            return False

        try:
            logger.info("Loading card database into memory...")
            t0 = time.time()

            with gzip.open(str(self._db_file), "rt", encoding="utf-8") as f:
                cards = json.load(f)

            # Load metadata
            if self._index_file.exists():
                with open(str(self._index_file), "r") as f:
                    self._metadata = json.load(f)

            # Build CMC index
            by_cmc = {}
            for card in cards:
                cmc = int(card.get("cmc", 0))
                if cmc not in by_cmc:
                    by_cmc[cmc] = []
                by_cmc[cmc].append(card)

            with self._lock:
                self._by_cmc = by_cmc

            total = sum(len(v) for v in by_cmc.values())
            elapsed = time.time() - t0
            logger.info(f"Database loaded: {total:,} cards across {len(by_cmc)} CMC values "
                        f"in {elapsed:.2f}s")

            if self._state:
                self._state.update(
                    db_loaded=True,
                    db_card_count=total,
                    db_last_updated=self._metadata.get("last_updated")
                )
            return True

        except Exception as e:
            logger.error(f"Failed to load database: {e}")
            return False

    # ── Card selection ────────────────────────────────────────────────────────
    def get_random_card(self, cmc: int, enabled_types: list) -> dict | None:
        """
        Return a random card matching the given CMC and enabled type filters.
        Returns None if no matching cards are found.
        """
        import random
        with self._lock:
            candidates = self._by_cmc.get(cmc, [])

        if not candidates:
            logger.info(f"No cards found for CMC {cmc}")
            return None

        # Filter by enabled types
        filtered = [
            c for c in candidates
            if self._card_matches_types(c, enabled_types)
        ]

        if not filtered:
            logger.info(f"No cards found for CMC {cmc} with types: {enabled_types}")
            return None

        chosen = random.choice(filtered)
        logger.info(f"Selected: {chosen.get('name','?')} "
                    f"(CMC {cmc}, {chosen.get('type_line','?')[:40]})")
        return chosen

    def _card_matches_types(self, card: dict, enabled_types: list) -> bool:
        """Check if card's type_line contains any enabled type."""
        type_line = card.get("type_line", "")
        return any(t in type_line for t in enabled_types)

    def get_cards_at_cmc(self, cmc: int, enabled_types: list) -> int:
        """Return count of available cards at a given CMC with current filters."""
        with self._lock:
            candidates = self._by_cmc.get(cmc, [])
        return sum(1 for c in candidates if self._card_matches_types(c, enabled_types))

    def get_stats(self) -> dict:
        """Return database statistics."""
        with self._lock:
            total = sum(len(v) for v in self._by_cmc.values())
            by_cmc_counts = {k: len(v) for k, v in sorted(self._by_cmc.items())}
        return {
            "total_cards":  total,
            "cmc_breakdown": by_cmc_counts,
            "last_updated": self._metadata.get("last_updated"),
            "scryfall_date": self._metadata.get("scryfall_bulk_date"),
        }

    # ── Database update / download ────────────────────────────────────────────
    def update(self, progress_callback=None) -> bool:
        """
        Download latest card data from Scryfall, process, and save locally.
        progress_callback(message: str, percent: int) called periodically.
        Returns True on success.
        """
        def progress(msg, pct=0):
            logger.info(f"[UPDATE] {msg} ({pct}%)")
            if progress_callback:
                progress_callback(msg, pct)
            if self._state:
                self._state.update(update_progress=msg, update_percent=pct)

        try:
            progress("Finding bulk data URL...", 2)
            bulk_url = self._get_bulk_data_url("default_cards")
            if not bulk_url:
                raise RuntimeError("Could not find bulk data URL from Scryfall")

            progress("Downloading card data from Scryfall...", 5)
            progress("(This may take several minutes — ~100MB download)", 5)
            raw_data = self._download_bulk(bulk_url, progress)

            progress("Parsing card data...", 60)
            all_cards = json.loads(raw_data)

            progress(f"Processing {len(all_cards):,} cards...", 65)
            filtered = self._filter_cards(all_cards)
            trimmed  = [self._trim_card(c) for c in filtered]

            progress(f"Saving {len(trimmed):,} cards to database...", 85)
            self._save_database(trimmed)

            progress("Loading into memory...", 92)
            self.load()

            now = datetime.now(timezone.utc).isoformat()
            self._metadata["last_updated"] = now
            with open(str(self._index_file), "w") as f:
                json.dump(self._metadata, f, indent=2)

            progress(f"Complete! {len(trimmed):,} cards ready.", 100)
            return True

        except Exception as e:
            logger.error(f"Database update failed: {e}")
            if progress_callback:
                progress_callback(f"ERROR: {e}", 0)
            if self._state:
                self._state.update(update_progress=f"Error: {str(e)[:80]}", update_percent=0)
            return False

    def _get_bulk_data_url(self, bulk_type: str = "default_cards") -> str:
        """Fetch the download URL for the specified bulk data type from Scryfall."""
        url = self._base_url + self._bulk_endpoint
        headers = {"User-Agent": self._user_agent, "Accept": "application/json"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        for item in data.get("data", []):
            if item.get("type") == bulk_type:
                dl_url = item.get("download_uri", "")
                self._metadata["scryfall_bulk_date"] = item.get("updated_at", "")
                logger.info(f"Bulk data URL: {dl_url[:80]}... "
                            f"({item.get('size', 0) // 1_048_576:.0f} MB)")
                return dl_url
        return ""

    def _download_bulk(self, url: str, progress) -> bytes:
        """Download bulk data with progress reporting."""
        headers = {
            "User-Agent":      self._user_agent,
            "Accept-Encoding": "gzip",
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=300) as resp:
            total   = int(resp.headers.get("Content-Length", 0))
            chunks  = []
            downloaded = 0
            chunk_size = 65536  # 64KB chunks

            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                chunks.append(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = int((downloaded / total) * 50) + 5  # 5–55%
                    mb  = downloaded / 1_048_576
                    progress(f"Downloading... {mb:.1f} MB", pct)

        raw = b"".join(chunks)
        # Handle gzip
        try:
            return gzip.decompress(raw)
        except Exception:
            return raw

    def _filter_cards(self, cards: list) -> list:
        """Remove unwanted sets, layouts, and card types."""
        excluded_sets    = set(self._excluded_sets)
        excluded_layouts = set(self._excluded_layouts)

        filtered = []
        for card in cards:
            if card.get("set_type", "") in excluded_sets:
                continue
            if card.get("layout", "") in excluded_layouts:
                continue
            if card.get("lang", "en") != "en":
                continue
            # Must have at least one of our target types in type_line
            type_line = card.get("type_line", "")
            if any(t in type_line for t in FILTERABLE_TYPES[:7]):  # Artifact–Sorcery
                filtered.append(card)

        logger.info(f"Filtered {len(cards):,} → {len(filtered):,} playable cards")
        return filtered

    def _trim_card(self, card: dict) -> dict:
        """Keep only the fields we need to reduce database size."""
        trimmed = {k: card[k] for k in KEEP_FIELDS if k in card}
        # Ensure numeric CMC
        trimmed["cmc"] = int(trimmed.get("cmc", 0))
        return trimmed

    def _save_database(self, cards: list):
        """Save processed cards as compressed JSON."""
        tmp_path = self._db_file.with_suffix(".tmp.gz")
        with gzip.open(str(tmp_path), "wt", encoding="utf-8", compresslevel=6) as f:
            json.dump(cards, f)
        tmp_path.replace(self._db_file)
        size_mb = self._db_file.stat().st_size / 1_048_576
        logger.info(f"Database saved: {size_mb:.1f} MB compressed")

    # ── Status ────────────────────────────────────────────────────────────────
    def is_loaded(self) -> bool:
        with self._lock:
            return bool(self._by_cmc)

    def exists_on_disk(self) -> bool:
        return self._db_file.exists()
