"""
web_server.py
-------------
Flask web server — serves the game dashboard and REST API.
Runs in a background thread alongside the main hardware loop.

Access from any device on the same Wi-Fi: http://[PI-IP]:5000

Datix AI | datixai.com
"""

import json
import logging
import os
import threading
import urllib.request
from datetime import datetime

logger = logging.getLogger(__name__)
_print_history = []


def run_web_server(cfg, state, database, card_selector, image_processor, printer):
    thread = threading.Thread(
        target=_server_main,
        args=(cfg, state, database, card_selector, image_processor, printer),
        daemon=True, name="WebServer"
    )
    thread.start()
    logger.info(f"Web server thread started on port {cfg.getint('WEB','port',fallback=5000)}")
    return thread


def _server_main(cfg, state, database, card_selector, image_processor, printer):
    try:
        from flask import Flask, jsonify, request, render_template
    except ImportError:
        logger.error("Flask not installed — web server disabled.")
        return

    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "templates", "static"),
    )
    app.secret_key = cfg.get("WEB", "secret_key", fallback="datixai-change-me")

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _img_url(card):
        uris = card.get("image_uris", {})
        if uris:
            return uris.get("normal") or uris.get("large") or uris.get("small","")
        faces = card.get("card_faces", [])
        if faces:
            fu = faces[0].get("image_uris", {})
            return fu.get("normal") or fu.get("large","")
        return ""

    def _api_card(card):
        return {
            "id":          card.get("id",""),
            "name":        card.get("name","Unknown"),
            "mana_cost":   card.get("mana_cost",""),
            "cmc":         card.get("cmc",0),
            "type_line":   card.get("type_line",""),
            "oracle_text": card.get("oracle_text",""),
            "power":       card.get("power"),
            "toughness":   card.get("toughness"),
            "loyalty":     card.get("loyalty"),
            "rarity":      card.get("rarity","common"),
            "set":         card.get("set",""),
            "image_url":   _img_url(card),
        }

    # ── Dashboard ─────────────────────────────────────────────────────────────
    @app.route("/")
    def index():
        return render_template("index.html")

    # ── Status ────────────────────────────────────────────────────────────────
    @app.route("/api/status")
    def api_status():
        d = state.to_dict()
        d["web_server"] = "running"
        return jsonify(d)

    # ── Card: random ─────────────────────────────────────────────────────────
    @app.route("/api/card/random")
    def api_card_random():
        try:
            cmc = int(request.args.get("cmc", 3))
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid CMC"}), 400

        if not database.is_loaded():
            return jsonify({"error": "Database not loaded. Run update first."}), 503

        card = card_selector.select_card(cmc)
        if not card:
            enabled = card_selector.get_enabled_types()
            return jsonify({
                "error": f"No cards at CMC {cmc} with types: {', '.join(enabled)}"
            }), 404

        return jsonify({"success": True, "card": _api_card(card)})

    # ── Card: print ───────────────────────────────────────────────────────────
    @app.route("/api/card/print", methods=["POST"])
    def api_card_print():
        data = request.get_json(force=True, silent=True) or {}
        card = data.get("card")
        if not card:
            return jsonify({"error": "No card data"}), 400
        try:
            success = printer.print_card(card, image_processor)
        except Exception as e:
            logger.error(f"Print error: {e}")
            success = False
        if success:
            _record_print(card, state)
        return jsonify({"success": success})

    # ── Legacy endpoint (Vercel dashboard compat) ─────────────────────────────
    @app.route("/api/test_print", methods=["POST"])
    def api_test_print():
        data = request.get_json(force=True, silent=True) or {}
        cmc  = data.get("cmc", 3)
        if not database.is_loaded():
            return jsonify({"error": "Database not loaded"}), 503
        card = card_selector.select_card(int(cmc))
        if not card:
            return jsonify({"error": f"No cards for CMC {cmc}"}), 404
        try:
            success = printer.print_card(card, image_processor)
        except Exception as e:
            logger.error(f"Print error: {e}")
            success = False
        if success:
            _record_print(card, state)
        return jsonify({"success": success, "card": _api_card(card)})

    # ── Token ─────────────────────────────────────────────────────────────────
    @app.route("/api/token")
    def api_token():
        try:
            ua  = cfg.get("SCRYFALL","header_user_agent",fallback="DatixAI-MTGPrinter/1.0")
            req = urllib.request.Request(
                "https://api.scryfall.com/cards/named?exact=Factory+of+Momir+Vig",
                headers={"User-Agent": ua, "Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                c = json.loads(r.read())
            return jsonify({
                "name":        c.get("name"),
                "image_url":   c.get("image_uris",{}).get("normal",""),
                "type_line":   c.get("type_line","Emblem"),
                "oracle_text": c.get("oracle_text",""),
            })
        except Exception as e:
            logger.warning(f"Token fetch failed: {e}")
            return jsonify({
                "name":        "Factory of Momir Vig",
                "image_url":   "",
                "type_line":   "Emblem",
                "oracle_text": (
                    "{X}, Discard a Card: Create a token that's a copy of a random "
                    "creature card with converted mana cost X. Activate this ability "
                    "only any time you could cast a sorcery and only once each turn."
                ),
            })

    # ── Filters ───────────────────────────────────────────────────────────────
    @app.route("/api/filters", methods=["GET"])
    def api_filters_get():
        return jsonify({
            "filters":       card_selector.get_filter_state(),
            "enabled_types": card_selector.get_enabled_types(),
        })

    @app.route("/api/filters", methods=["POST"])
    def api_filters_post():
        data = request.get_json(force=True, silent=True) or {}
        f    = data.get("filters",{})
        if not f:
            return jsonify({"error":"No filters"}), 400
        card_selector.set_all_filters(f)
        return jsonify({"success":True,"filters":card_selector.get_filter_state()})

    # ── Database update ───────────────────────────────────────────────────────
    @app.route("/api/update", methods=["POST"])
    def api_update():
        if state.get("update_running"):
            return jsonify({"error":"Already running"}), 409
        state.update(update_running=True, update_progress="Starting...", update_percent=0)
        def _run():
            try:
                database.update(
                    progress_callback=lambda msg,pct: state.update(
                        update_progress=msg, update_percent=pct))
            except Exception as e:
                logger.error(f"Update error: {e}")
                state.update(update_progress=f"Error: {e}", update_percent=0)
            finally:
                state.update(update_running=False)
        threading.Thread(target=_run, daemon=True, name="DBUpdate").start()
        return jsonify({"success":True,"message":"Update started"})

    @app.route("/api/update_progress")
    def api_update_progress():
        return jsonify({
            "running":  state.get("update_running"),
            "progress": state.get("update_progress"),
            "percent":  state.get("update_percent"),
        })

    # ── Stats / History / CMC / System ───────────────────────────────────────
    @app.route("/api/stats")
    def api_stats():
        try:    return jsonify(database.get_stats())
        except Exception as e: return jsonify({"error":str(e)})

    @app.route("/api/history")
    def api_history():
        return jsonify({"history": list(reversed(_print_history[-20:]))})

    @app.route("/api/cmc/<int:cmc>")
    def api_cmc(cmc):
        return jsonify({"cmc":cmc,"available_cards":card_selector.count_available(cmc)})

    @app.route("/api/system")
    def api_system():
        return jsonify(_get_system_info())

    @app.route("/api/config")
    def api_config():
        return jsonify({
            "cmc_min":         cfg.getint("HARDWARE","cmc_min",fallback=0),
            "cmc_max":         cfg.getint("HARDWARE","cmc_max",fallback=16),
            "art_enabled":     cfg.getboolean("PRINTER","card_art_enabled",fallback=True),
            "qr_enabled":      cfg.getboolean("PRINTER","qr_code_enabled",fallback=True),
            "simulation_mode": cfg.getboolean("APP","simulation_mode",fallback=False),
        })

    # ── Start ─────────────────────────────────────────────────────────────────
    host  = cfg.get("WEB","host",fallback="0.0.0.0")
    port  = cfg.getint("WEB","port",fallback=5000)
    debug = cfg.getboolean("WEB","debug",fallback=False)
    logger.info(f"Web server starting at http://{host}:{port}")
    try:
        app.run(host=host,port=port,debug=debug,use_reloader=False,threaded=True)
    except Exception as e:
        logger.error(f"Web server failed: {e}")


def _record_print(card, state):
    e = {
        "name":      card.get("name"),
        "type_line": card.get("type_line"),
        "mana_cost": card.get("mana_cost"),
        "cmc":       card.get("cmc"),
        "set":       card.get("set"),
        "rarity":    card.get("rarity"),
        "timestamp": datetime.now().isoformat(),
    }
    _print_history.append(e)
    if len(_print_history) > 100:
        _print_history.pop(0)
    state.update(last_card=e, print_count=state.get("print_count")+1)


def _get_system_info():
    import shutil, sys
    info = {"platform":sys.platform,"python":sys.version.split()[0]}
    try:
        t,u,f = shutil.disk_usage("/")
        info["storage"] = {"total_gb":round(t/1e9,1),"used_gb":round(u/1e9,1),"free_gb":round(f/1e9,1),"percent":round(u/t*100,1)}
    except Exception:
        info["storage"] = {}
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            info["cpu_temp_c"] = round(int(f.read().strip())/1000,1)
    except Exception:
        info["cpu_temp_c"] = None
    try:
        import psutil
        m = psutil.virtual_memory()
        info["memory"] = {"total_mb":round(m.total/1e6),"used_mb":round(m.used/1e6),"percent":m.percent}
    except Exception:
        info["memory"] = {}
    try:
        with open("/proc/uptime") as f:
            s = float(f.read().split()[0])
        info["uptime"] = f"{int(s//3600)}h {int((s%3600)//60)}m"
    except Exception:
        info["uptime"] = "N/A"
    return info
