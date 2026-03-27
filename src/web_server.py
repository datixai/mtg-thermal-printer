"""
web_server.py
-------------
Flask web server providing a browser-based dashboard for the MTG Printer.
Runs in a background thread alongside the main hardware loop.
Access from any device on the same Wi-Fi: http://[PI-IP]:5000

Endpoints:
  GET  /              — Main dashboard UI
  GET  /api/status    — JSON device status
  GET  /api/filters   — JSON filter state
  POST /api/filters   — Update card type filters
  POST /api/update    — Trigger Scryfall database update
  GET  /api/stats     — Database statistics
  GET  /api/history   — Recent print history
  POST /api/test_print— Trigger a test print (simulation)
  GET  /api/system    — System info (CPU temp, storage, etc.)

Datix AI | Ahmed Ali | datixai.com
"""

import logging
import os
import threading
from datetime import datetime

logger = logging.getLogger(__name__)
_print_history = []   # Global print history list


def run_web_server(cfg, state, database, card_selector, image_processor, printer):
    """
    Start the Flask development server in a daemon thread.
    Returns the thread object.
    """
    thread = threading.Thread(
        target=_server_main,
        args=(cfg, state, database, card_selector, image_processor, printer),
        daemon=True,
        name="WebServer"
    )
    thread.start()
    logger.info(f"Web server thread started on port {cfg.getint('WEB', 'port', fallback=5000)}")
    return thread


def _server_main(cfg, state, database, card_selector, image_processor, printer):
    try:
        from flask import Flask, jsonify, request, render_template, send_from_directory
        from flask import abort
    except ImportError:
        logger.error("Flask not installed — web server disabled. Run: pip install flask")
        return

    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "templates", "static"),
    )
    app.secret_key = cfg.get("WEB", "secret_key", fallback="datixai-change-me")
    app.config["JSONIFY_PRETTYPRINT_REGULAR"] = True

    # ── Main dashboard ────────────────────────────────────────────────────────
    @app.route("/")
    def index():
        return render_template("index.html")

    # ── Status ────────────────────────────────────────────────────────────────
    @app.route("/api/status")
    def api_status():
        data = state.to_dict()
        data["sim_display"]  = True  # Always report sim for web
        data["web_server"]   = "running"
        return jsonify(data)

    # ── Filters ───────────────────────────────────────────────────────────────
    @app.route("/api/filters", methods=["GET"])
    def api_filters_get():
        return jsonify({
            "filters": card_selector.get_filter_state(),
            "enabled_types": card_selector.get_enabled_types(),
        })

    @app.route("/api/filters", methods=["POST"])
    def api_filters_post():
        data = request.get_json(force=True, silent=True) or {}
        filters = data.get("filters", {})
        if not filters:
            return jsonify({"error": "No filters provided"}), 400
        card_selector.set_all_filters(filters)
        return jsonify({
            "success": True,
            "filters": card_selector.get_filter_state(),
            "message": "Filters saved successfully"
        })

    # ── Database update ───────────────────────────────────────────────────────
    @app.route("/api/update", methods=["POST"])
    def api_update():
        if state.get("update_running"):
            return jsonify({"error": "Update already in progress"}), 409

        state.update(update_running=True, update_progress="Starting...", update_percent=0)

        def run_update():
            try:
                database.update(progress_callback=lambda msg, pct: state.update(
                    update_progress=msg, update_percent=pct
                ))
            except Exception as e:
                logger.error(f"Update thread error: {e}")
                state.update(update_progress=f"Error: {e}", update_percent=0)
            finally:
                state.update(update_running=False)

        t = threading.Thread(target=run_update, daemon=True, name="DBUpdate")
        t.start()
        return jsonify({"success": True, "message": "Database update started"})

    @app.route("/api/update_progress")
    def api_update_progress():
        return jsonify({
            "running":  state.get("update_running"),
            "progress": state.get("update_progress"),
            "percent":  state.get("update_percent"),
        })

    # ── Database stats ────────────────────────────────────────────────────────
    @app.route("/api/stats")
    def api_stats():
        try:
            stats = database.get_stats()
        except Exception as e:
            stats = {"error": str(e)}
        return jsonify(stats)

    # ── Print history ─────────────────────────────────────────────────────────
    @app.route("/api/history")
    def api_history():
        return jsonify({"history": list(reversed(_print_history[-20:]))})

    # ── Test print ────────────────────────────────────────────────────────────
    @app.route("/api/test_print", methods=["POST"])
    def api_test_print():
        data  = request.get_json(force=True, silent=True) or {}
        cmc   = data.get("cmc", 3)
        card  = card_selector.select_card(int(cmc))
        if not card:
            return jsonify({"error": f"No cards found for CMC {cmc}"}), 404

        success = printer.print_card(card, image_processor)
        if success:
            _record_print(card, state)

        return jsonify({
            "success": success,
            "card": {
                "name":      card.get("name"),
                "type_line": card.get("type_line"),
                "mana_cost": card.get("mana_cost"),
                "cmc":       card.get("cmc"),
                "oracle_text": card.get("oracle_text", "")[:200],
            }
        })

    # ── CMC availability ──────────────────────────────────────────────────────
    @app.route("/api/cmc/<int:cmc>")
    def api_cmc(cmc):
        count = card_selector.count_available(cmc)
        return jsonify({"cmc": cmc, "available_cards": count})

    # ── System info ───────────────────────────────────────────────────────────
    @app.route("/api/system")
    def api_system():
        info = _get_system_info()
        return jsonify(info)

    # ── Config ────────────────────────────────────────────────────────────────
    @app.route("/api/config", methods=["GET"])
    def api_config_get():
        """Return safe subset of config for display."""
        return jsonify({
            "cmc_min":        cfg.getint("HARDWARE", "cmc_min",  fallback=0),
            "cmc_max":        cfg.getint("HARDWARE", "cmc_max",  fallback=16),
            "art_enabled":    cfg.getboolean("PRINTER", "card_art_enabled",   fallback=True),
            "qr_enabled":     cfg.getboolean("PRINTER", "qr_code_enabled",    fallback=True),
            "simulation_mode":cfg.getboolean("APP", "simulation_mode",        fallback=False),
            "serial_port":    cfg.get("HARDWARE", "serial_port",              fallback="/dev/serial0"),
            "oled_address":   cfg.get("HARDWARE", "i2c_address",              fallback="0x3C"),
        })

    @app.route("/api/config", methods=["POST"])
    def api_config_post():
        """Update safe config settings from web UI."""
        data = request.get_json(force=True, silent=True) or {}
        allowed = {
            "art_enabled":  ("PRINTER", "card_art_enabled"),
            "qr_enabled":   ("PRINTER", "qr_code_enabled"),
        }
        updated = {}
        for key, (section, option) in allowed.items():
            if key in data:
                val = str(data[key]).lower()
                if not cfg.has_section(section):
                    cfg.add_section(section)
                cfg.set(section, option, val)
                updated[key] = data[key]

        if updated:
            from card_selector import CardSelector
            CardSelector(cfg, None)._save_config()  # reuse save logic

        return jsonify({"success": True, "updated": updated})

    # ── Start Flask ───────────────────────────────────────────────────────────
    host  = cfg.get("WEB", "host",  fallback="0.0.0.0")
    port  = cfg.getint("WEB", "port", fallback=5000)
    debug = cfg.getboolean("WEB", "debug", fallback=False)

    logger.info(f"Web server starting at http://{host}:{port}")
    try:
        app.run(host=host, port=port, debug=debug, use_reloader=False, threaded=True)
    except Exception as e:
        logger.error(f"Web server failed: {e}")


# ── Helpers ───────────────────────────────────────────────────────────────────
def _record_print(card: dict, state):
    """Add a card to print history and update state."""
    entry = {
        "name":       card.get("name"),
        "type_line":  card.get("type_line"),
        "mana_cost":  card.get("mana_cost"),
        "cmc":        card.get("cmc"),
        "set":        card.get("set"),
        "rarity":     card.get("rarity"),
        "timestamp":  datetime.now().isoformat(),
    }
    _print_history.append(entry)
    if len(_print_history) > 100:
        _print_history.pop(0)
    state.update(last_card=entry, print_count=state.get("print_count") + 1)


def _get_system_info() -> dict:
    """Collect system information (works on Pi and Windows)."""
    import shutil, sys

    info = {
        "platform":    sys.platform,
        "python":      sys.version.split()[0],
    }

    # Storage
    try:
        total, used, free = shutil.disk_usage("/")
        info["storage"] = {
            "total_gb": round(total / 1e9, 1),
            "used_gb":  round(used  / 1e9, 1),
            "free_gb":  round(free  / 1e9, 1),
            "percent":  round(used  / total * 100, 1),
        }
    except Exception:
        info["storage"] = {}

    # CPU temperature (Pi only)
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            temp_c = int(f.read().strip()) / 1000
        info["cpu_temp_c"] = round(temp_c, 1)
    except Exception:
        info["cpu_temp_c"] = None

    # Memory
    try:
        import psutil
        mem = psutil.virtual_memory()
        info["memory"] = {
            "total_mb": round(mem.total / 1e6, 0),
            "used_mb":  round(mem.used  / 1e6, 0),
            "percent":  mem.percent,
        }
    except Exception:
        info["memory"] = {}

    # Uptime
    try:
        with open("/proc/uptime") as f:
            uptime_s = float(f.read().split()[0])
        hours   = int(uptime_s // 3600)
        minutes = int((uptime_s % 3600) // 60)
        info["uptime"] = f"{hours}h {minutes}m"
    except Exception:
        info["uptime"] = "N/A"

    return info
