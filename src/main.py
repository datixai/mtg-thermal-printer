"""
main.py
-------
Main application entry point for the MTG Thermal Printer.
Orchestrates: encoder input → card selection → image processing → printing → display.
Runs the Flask web server in a background thread.

Usage:
  python src/main.py              # Normal run
  python src/main.py --sim        # Force simulation mode
  python src/main.py --update     # Update card database then exit

Datix AI | Ahmed Ali | datixai.com
"""

import sys
import signal
import logging
import threading
import time
import argparse
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# ── Local imports ─────────────────────────────────────────────────────────────
from config_manager import get_config, get_state, setup_logging, IS_RASPBERRY_PI
from display        import OLEDDisplay
from encoder        import RotaryEncoder, EncoderEvent
from printer        import ThermalPrinter
from image_processor import ImageProcessor
from database       import CardDatabase
from card_selector  import CardSelector
from web_server     import run_web_server, _record_print


# ── Main application class ────────────────────────────────────────────────────
class MTGPrinter:
    """
    Top-level application controller.
    Manages hardware lifecycle and the main event loop.
    """

    def __init__(self, args):
        self._args    = args
        self._running = False
        self._state   = get_state()
        self._cfg     = get_config()

        # Override simulation mode from CLI flag
        if args.sim:
            self._cfg.set("APP", "simulation_mode", "true")

        # Set up logging
        setup_logging(self._cfg)
        self._log = logging.getLogger("MTGPrinter")
        self._log.info("=" * 60)
        self._log.info("  Datix AI — MTG Thermal Printer  |  Starting up")
        self._log.info("=" * 60)
        self._log.info(f"Platform: {'Raspberry Pi' if IS_RASPBERRY_PI else 'Non-Pi (simulation mode)'}")

        sim_mode = self._cfg.getboolean("APP", "simulation_mode", fallback=False)
        self._state.update(simulation_mode=sim_mode)

        # Initialise components
        self._display   = None
        self._encoder   = None
        self._printer   = None
        self._img_proc  = None
        self._database  = None
        self._selector  = None
        self._web_thread= None

        # Config mode state
        self._in_config = False
        self._cfg_type_idx = 0

        # Prevent rapid re-entry
        self._processing = threading.Event()

        # Graceful shutdown
        signal.signal(signal.SIGINT,  self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    # ── Startup ───────────────────────────────────────────────────────────────
    def start(self):
        """Initialise all subsystems and start the main loop."""
        try:
            self._init_hardware()
            self._init_database()
            self._start_web_server()
            self._main_loop()
        except Exception as e:
            self._log.critical(f"Fatal startup error: {e}", exc_info=True)
            self._shutdown()
            sys.exit(1)

    def _init_hardware(self):
        self._log.info("Initialising hardware...")
        cfg = self._cfg

        # Display
        self._display = OLEDDisplay(cfg)
        self._display.show(0, cfg.get("APP", "booting_status", fallback="Booting..."))
        self._state.set("status", "Booting...")

        # Image processor
        self._img_proc = ImageProcessor(cfg)

        # Printer
        self._printer = ThermalPrinter(cfg)

        # Encoder (starts listening for input immediately)
        self._encoder = RotaryEncoder(cfg, self._on_encoder_event)

        self._log.info(f"Hardware ready — Display sim:{self._display.is_simulation()}, "
                       f"Printer sim:{self._printer.is_simulation()}, "
                       f"Encoder sim:{self._encoder.is_simulation()}")

    def _init_database(self):
        self._log.info("Loading card database...")
        self._database = CardDatabase(self._cfg, self._state)
        self._selector = CardSelector(self._cfg, self._database)

        cmc = self._cfg.getint("HARDWARE", "cmc_min", fallback=0)
        self._state.set("cmc", cmc)

        if not self._database.exists_on_disk():
            msg = self._cfg.get("APP", "no_db_status", fallback="No DB! Run update")
            self._display.show(cmc, msg)
            self._state.set("status", msg)
            self._log.warning("No card database found. Use web UI or --update flag to download.")
        else:
            self._display.show(cmc, self._cfg.get("APP", "refreshing_status", fallback="Loading..."))
            self._database.load()
            if self._database.is_loaded():
                ready_msg = self._cfg.get("APP", "ready_status", fallback="Ready")
                self._display.show(cmc, ready_msg)
                self._state.set("status", ready_msg)
            else:
                self._display.show(cmc, "Load Error!")
                self._state.set("status", "Load Error!")

    def _start_web_server(self):
        self._log.info("Starting web server...")
        self._web_thread = run_web_server(
            self._cfg,
            self._state,
            self._database,
            self._selector,
            self._img_proc,
            self._printer
        )
        port = self._cfg.getint("WEB", "port", fallback=5000)
        self._log.info(f"Web UI available at http://localhost:{port}")
        self._log.info(f"On Pi, access from your phone at http://[PI-IP]:{port}")

    # ── Main event loop ───────────────────────────────────────────────────────
    def _main_loop(self):
        """Keep the application alive while encoder events are handled in callbacks."""
        self._running = True
        self._log.info("Main loop running — waiting for encoder input")

        while self._running:
            try:
                time.sleep(0.1)
                # Watchdog: check if print job has been stuck
                # (In production, add a timeout monitor here)
            except KeyboardInterrupt:
                break

        self._shutdown()

    # ── Encoder event handler ─────────────────────────────────────────────────
    def _on_encoder_event(self, event: EncoderEvent):
        """
        Callback from encoder interrupt thread.
        Handles all user input for CMC selection and printing.
        """
        cmc = self._state.get("cmc")
        cmc_min = self._cfg.getint("HARDWARE", "cmc_min", fallback=0)
        cmc_max = self._cfg.getint("HARDWARE", "cmc_max", fallback=16)

        # ── Config mode events ────────────────────────────────────────────────
        if self._in_config:
            if event == EncoderEvent.TURN_CW:
                self._cfg_type_idx = (self._cfg_type_idx + 1) % CardSelector.type_count()
                self._show_config_screen()
            elif event == EncoderEvent.TURN_CCW:
                self._cfg_type_idx = (self._cfg_type_idx - 1) % CardSelector.type_count()
                self._show_config_screen()
            elif event == EncoderEvent.SHORT_PRESS:
                new_state = self._selector.toggle_type_at_index(self._cfg_type_idx)
                self._show_config_screen()
                self._log.info(f"Config: {self._selector.get_type_at_index(self._cfg_type_idx)} = {new_state}")
            elif event == EncoderEvent.LONG_PRESS:
                self._exit_config_mode()
            return

        # ── Normal mode events ────────────────────────────────────────────────
        if event == EncoderEvent.TURN_CW:
            new_cmc = min(cmc + 1, cmc_max)
            self._state.set("cmc", new_cmc)
            self._update_display(new_cmc)

        elif event == EncoderEvent.TURN_CCW:
            new_cmc = max(cmc - 1, cmc_min)
            self._state.set("cmc", new_cmc)
            self._update_display(new_cmc)

        elif event == EncoderEvent.SHORT_PRESS:
            if not self._processing.is_set():
                self._processing.set()
                t = threading.Thread(target=self._do_print_job, daemon=True)
                t.start()

        elif event == EncoderEvent.LONG_PRESS:
            self._enter_config_mode()

    # ── Print job ─────────────────────────────────────────────────────────────
    def _do_print_job(self):
        """Execute a full print job (runs in background thread)."""
        cmc = self._state.get("cmc")
        try:
            if not self._database.is_loaded():
                no_db = self._cfg.get("APP", "no_db_status", fallback="No DB!")
                self._display.show(cmc, no_db)
                self._state.set("status", no_db)
                time.sleep(2)
                self._update_display(cmc)
                return

            # Fetching
            fetch_msg = self._cfg.get("APP", "fetching_status", fallback="Fetching...")
            self._display.show(cmc, fetch_msg)
            self._state.set("status", fetch_msg)

            card = self._selector.select_card(cmc)

            if not card:
                no_cmc = self._cfg.get("APP", "no_cmc_status_template",
                                       fallback="No cards: CMC {cmc}")
                msg = no_cmc.format(cmc=cmc)
                self._display.show(cmc, msg)
                self._state.set("status", msg)
                time.sleep(2)
                self._update_display(cmc)
                return

            # Printing
            print_msg = self._cfg.get("APP", "printing_status", fallback="Printing...")
            self._display.show(cmc, print_msg)
            self._state.set("status", print_msg)

            success = self._printer.print_card(card, self._img_proc)

            if success:
                _record_print(card, self._state)
                done_msg = self._cfg.get("APP", "done_status", fallback="Done!")
                self._display.show(cmc, done_msg)
                self._state.set("status", done_msg)
                done_secs = self._cfg.getfloat("APP", "done_status_seconds", fallback=2.5)
                time.sleep(done_secs)
            else:
                err_msg = self._cfg.get("APP", "error_status", fallback="Error!")
                self._display.show(cmc, err_msg)
                self._state.set("status", err_msg)
                time.sleep(2)

        except Exception as e:
            self._log.error(f"Print job error: {e}", exc_info=True)
            self._display.show(cmc, "Error!")
            self._state.set("status", "Error!")
            time.sleep(2)
        finally:
            self._update_display(cmc)
            self._processing.clear()

    # ── Config mode ───────────────────────────────────────────────────────────
    def _enter_config_mode(self):
        self._in_config     = True
        self._cfg_type_idx  = 0
        self._state.set("in_config_mode", True)
        self._show_config_screen()
        self._log.info("Entered config mode")

    def _exit_config_mode(self):
        self._in_config = False
        self._state.set("in_config_mode", False)
        cmc = self._state.get("cmc")
        self._log.info("Exited config mode")
        self._update_display(cmc)

    def _show_config_screen(self):
        type_name, enabled = self._selector.get_type_state_at_index(self._cfg_type_idx)
        state_str = "ON" if enabled else "OFF"
        idx_str   = f"{self._cfg_type_idx + 1}/{CardSelector.type_count()}"
        self._display.show_message(f"CFG {idx_str}", f"{type_name}: {state_str}")
        self._state.set("status", f"CFG: {type_name}={state_str}")

    # ── Display update ────────────────────────────────────────────────────────
    def _update_display(self, cmc: int):
        status = self._state.get("status")
        # If we're back to idle, show ready status
        if status not in ["Booting...", "Loading...", "No DB! Run update"]:
            status = self._cfg.get("APP", "ready_status", fallback="Ready")
            self._state.set("status", status)
        self._display.show(cmc, status)

    # ── Shutdown ──────────────────────────────────────────────────────────────
    def _signal_handler(self, sig, frame):
        self._log.info(f"Signal {sig} received — shutting down")
        self._running = False

    def _shutdown(self):
        self._log.info("Shutting down...")
        self._running = False
        if self._encoder:
            self._encoder.stop()
        if self._display:
            try:
                self._display.show_message("Shutting down", "Goodbye!")
                time.sleep(1)
                self._display.clear()
            except Exception:
                pass
        # GPIO cleanup
        try:
            import RPi.GPIO as GPIO
            GPIO.cleanup()
        except Exception:
            pass
        self._log.info("Shutdown complete")


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Datix AI — MTG Thermal Printer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/main.py              Start normally
  python src/main.py --sim        Force simulation (no hardware required)
  python src/main.py --update     Download/update card database then exit
  python src/main.py --web-only   Start web server only (no hardware loop)
        """
    )
    parser.add_argument("--sim",      action="store_true", help="Force simulation mode")
    parser.add_argument("--update",   action="store_true", help="Update card database and exit")
    parser.add_argument("--web-only", action="store_true", help="Start web server only")
    args = parser.parse_args()

    if args.update:
        # Standalone database update
        cfg = get_config()
        setup_logging(cfg)
        state = get_state()
        db = CardDatabase(cfg, state)
        print("\n=== Datix AI — MTG Card Database Update ===\n")
        success = db.update(progress_callback=lambda msg, pct:
                            print(f"[{pct:3d}%] {msg}"))
        sys.exit(0 if success else 1)

    app = MTGPrinter(args)
    app.start()


if __name__ == "__main__":
    main()
