"""
image_processor.py
------------------
Downloads card artwork from Scryfall, applies Floyd-Steinberg dithering
to produce 1-bit monochrome bitmaps suitable for thermal printing.
Results are cached locally to avoid re-downloading.

Datix AI | Ahmed Ali | datixai.com
"""

import io
import logging
import hashlib
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class ImageProcessor:
    """
    Handles all card image operations:
    - Download from Scryfall art_crop URL
    - Resize to printer media width
    - Convert to greyscale
    - Apply Floyd-Steinberg dithering → 1-bit bitmap
    - Cache to local disk
    - Provide default placeholder image
    """

    def __init__(self, cfg):
        from PIL import Image, ImageDraw
        self._Image     = Image
        self._ImageDraw = ImageDraw

        self._art_path    = Path(__file__).resolve().parent.parent / cfg.get(
                                "FILESYSTEM", "art_path", fallback="data/art")
        self._default_art = Path(__file__).resolve().parent.parent / cfg.get(
                                "FILESYSTEM", "default_art_path", fallback="assets/default_art.png")
        self._media_w     = cfg.getint("PRINTER", "printer_media_width_px", fallback=384)
        self._request_delay = cfg.getfloat("SCRYFALL", "request_delay_seconds", fallback=0.1)
        self._max_retries   = cfg.getint("SCRYFALL", "max_retries", fallback=3)
        self._user_agent    = cfg.get("SCRYFALL", "header_user_agent",
                                      fallback="DatixAI-MTGPrinter/1.0")
        self._art_path.mkdir(parents=True, exist_ok=True)
        self._ensure_default_art()

    # ── Public interface ──────────────────────────────────────────────────────
    def get_card_image(self, card: dict):
        """
        Return a PIL Image (1-bit dithered, printer-ready) for the given card dict.
        Uses cache if available. Falls back to default art on any error.
        """
        art_url = self._extract_art_url(card)
        if not art_url:
            logger.warning(f"No art URL for card: {card.get('name','?')}")
            return self._load_default_art()

        cache_path = self._cache_path(art_url)
        if cache_path.exists():
            try:
                return self._Image.open(str(cache_path)).convert("1")
            except Exception:
                cache_path.unlink(missing_ok=True)

        # Download and process
        try:
            raw = self._download(art_url)
            img = self._process(raw)
            img.save(str(cache_path), format="PNG")
            logger.debug(f"Art cached: {card.get('name','?')} → {cache_path.name}")
            return img
        except Exception as e:
            logger.error(f"Art processing failed for {card.get('name','?')}: {e}")
            return self._load_default_art()

    def get_card_image_bytes(self, card: dict) -> bytes:
        """Return dithered image as bytes (PNG format) for sending to printer."""
        img = self.get_card_image(card)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf.getvalue()

    # ── Download ──────────────────────────────────────────────────────────────
    def _download(self, url: str) -> bytes:
        """Download image bytes with retry logic."""
        import urllib.request
        headers = {"User-Agent": self._user_agent}

        for attempt in range(1, self._max_retries + 1):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return resp.read()
            except Exception as e:
                logger.warning(f"Art download attempt {attempt}/{self._max_retries} failed: {e}")
                if attempt < self._max_retries:
                    time.sleep(self._request_delay * attempt)
        raise RuntimeError(f"Failed to download art after {self._max_retries} attempts: {url}")

    # ── Image processing pipeline ─────────────────────────────────────────────
    def _process(self, raw_bytes: bytes):
        """
        Full processing pipeline:
        raw JPEG → resize → greyscale → Floyd-Steinberg dither → 1-bit
        """
        img = self._Image.open(io.BytesIO(raw_bytes)).convert("RGB")

        # Resize to printer media width, preserve aspect ratio
        w, h  = img.size
        new_h = int(h * self._media_w / w)
        img   = img.resize((self._media_w, new_h), self._Image.LANCZOS)

        # Greyscale using ITU-R 601-2 luma
        img = img.convert("L")

        # Floyd-Steinberg dither to 1-bit
        img = img.convert("1", dither=self._Image.Dither.FLOYDSTEINBERG)

        return img

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _extract_art_url(self, card: dict) -> str:
        """Extract the best available art URL from card data."""
        uris = card.get("image_uris", {})
        if uris:
            return uris.get("art_crop") or uris.get("normal") or uris.get("small", "")
        # Handle double-faced cards
        faces = card.get("card_faces", [])
        if faces:
            for face in faces:
                face_uris = face.get("image_uris", {})
                url = face_uris.get("art_crop") or face_uris.get("normal")
                if url:
                    return url
        return ""

    def _cache_path(self, url: str) -> Path:
        """Generate a deterministic cache filename from the URL."""
        url_hash = hashlib.md5(url.encode()).hexdigest()[:16]
        return self._art_path / f"{url_hash}.png"

    def _load_default_art(self):
        """Load or create a default placeholder image."""
        if self._default_art.exists():
            try:
                return self._Image.open(str(self._default_art)).convert("1")
            except Exception:
                pass
        return self._make_placeholder()

    def _make_placeholder(self):
        """Generate a simple placeholder image with question mark."""
        img  = self._Image.new("L", (self._media_w, 150), color=128)
        draw = self._ImageDraw.Draw(img)
        draw.rectangle([(0,0),(self._media_w-1,149)], outline=0, width=2)
        draw.text((self._media_w//2 - 20, 50), "?", fill=0)
        draw.text((10, 120), "No artwork", fill=0)
        return img.convert("1", dither=self._Image.Dither.FLOYDSTEINBERG)

    def _ensure_default_art(self):
        """Make sure the default art file exists."""
        if not self._default_art.exists():
            self._default_art.parent.mkdir(parents=True, exist_ok=True)
            try:
                placeholder = self._make_placeholder()
                placeholder.save(str(self._default_art))
            except Exception as e:
                logger.warning(f"Could not create default art: {e}")

    def clear_cache(self):
        """Delete all cached art files."""
        count = 0
        for f in self._art_path.glob("*.png"):
            f.unlink(missing_ok=True)
            count += 1
        logger.info(f"Art cache cleared: {count} files removed")
        return count
