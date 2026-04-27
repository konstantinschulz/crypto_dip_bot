import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import datetime
import hmac
import json
import os
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
from typing import Dict, Optional, Tuple, Any, List

import ccxt
import numpy as np
import pandas as pd
from dotenv import load_dotenv


# ============================================================
#  MEXC Dip Bot v20 — Triple-Strategy Edition (DIP + Momentum + MA-DIP)
#
#  Neu in v20:
#  ── DIP BTC-Kontext-Filter komplett deaktiviert (backtest_dip_btc_buckets.py) ──
#  btc_ctx=True Coins feuern jetzt in ALLEN BTC-Marktphasen (flat, steigend, fallend).
#  Backtest-Ergebnis (2J-Parquet, 48 btc_ctx=True Coins, Bucket-Analyse):
#    Jede BTC-Return-Zone ist profitabel (WR 95.4%–99.3%, alle mit positivem PnL)
#    Entgangenes PnL durch Filter: +101 USDT über 2 Jahre (blockierte profitable Zonen)
#    Freigegeben: ~8.479 Trades über 2 Jahre die bisher geblockt wurden
#    → kein Filter = +922.5 USDT (2J) vs. -1.5%: +910.8 USDT vs. -1.0%: +972.4 USDT
#  Archiv-Bestätigung: backtest_btc_filter_output.txt zeigte bereits:
#    jede Filterstufe reduziert PnL vs. kein Filter (konsistent über alle Versionen)
#  Basis: backtest_dip_btc_buckets.py / backtest_dip_btc_filter.py
#
#  Neu in v19:
#  ── DIP BTC-Kontext-Filter gelockert: -1.5% → -1.0% (backtest_dip_btc_filter.py) ──
#  Schwellenwert für btc_ctx=True Coins gesenkt von -1.5% auf -1.0% (BTC 60m-Return).
#  Backtest-Ergebnis (2J-Parquet, 113 DIP-Coins):
#    Baseline (-1.5%):  N=18.210  WR=94.06%  PnL=+910.8 USDT  Verluste=1.082
#    Neu     (-1.0%):   N=19.979  WR=94.27%  PnL=+972.4 USDT  Verluste=1.145
#    → +61.6 USDT PnL  |  +1.769 Trades/Woche  |  WR praktisch gleich
#  Basis: backtest_dip_btc_filter.py (Grid -5.0% bis kein Filter)
#
#  Neu in v18:
#  ── BTC 15min Makro-Filter für MADIP (backtest_madip_btc_filter.py) ──
#  MADIP-Entry wird übersprungen wenn BTC in den letzten 15 Minuten
#  mehr als 2.0% gefallen ist → breiter Marktabverkauf erkannt.
#
#  Backtest-Ergebnis (2J-Parquet, 81 MADIP-Coins):
#    Baseline:             N=4.328  WR=89.67%  PnL=+732.8 USDT  Verluste=447
#    BTC 15min < -2.0%:   N=3.639  WR=91.56%  PnL=+846.8 USDT  Verluste=307
#    → +1.89pp WR  |  +114 USDT PnL (+16%)  |  -31% weniger Verlustrades
#    → Filter greift bei ~4.456 von 19.948 Signalen (22%)
#  Basis: backtest_madip_btc_filter.py / backtest_madip_macro_score.py
#
#  Neu in v17:
#  ── Portfolio-Cooldown nach N konsekutiven Verlusten (backtest_cooldown.py) ──
#  Nach 3 Fehltrades am Stück (portfolio-global, alle Strategien) werden
#  neue Entries für 2 Stunden pausiert (Cooldown).
#
#  Backtest-Ergebnis (2J-Parquet, alle 3 Strategien):
#    Portfolio Baseline:  WR 95.08%  →  Nach Cooldown: WR 97.41%  (+2.33pp)
#    PnL-Verbesserung:    +3.000 USDT bei nur 698 übersprungenen Trades (5.5%)
#  Aufschlüsselung per Strategie (Streak>=3, CD=2h):
#    DIP:    WR 95.99% → 98.01%  (+2.02pp)  |  PnL +1.639 USDT
#    MOM:    WR 94.90% → 96.60%  (+1.70pp)  |  PnL +127 USDT
#    MA-DIP: WR 93.44% → 97.08%  (+3.65pp)  |  PnL +1.234 USDT
#  Robustheit (4J-Parquet inkl. Bärenmarkt 2022):
#    Portfolio Baseline: WR 92.62%  →  Nach Cooldown: WR 96.08%  (+3.46pp)
#    PnL-Verbesserung:   +5.030 USDT — Effekt verstärkt sich in schwachen Märkten
#  Basis: backtest_cooldown.py / backtest_cooldown_4y.py
#
#  Neu in v16:
#  ── Zeitfilter auf Basis 2J-Backtest-Verlustanalyse (analyze_loss_patterns.py) ──
#  Alle Verluste sind Time-Stops; Verluste kommen gehäuft in bestimmten
#  Stunden/Wochentagen. Filter-Wirkung (Jahr 2, v15-Coins):
#
#  DIP:    Stunde 21 UTC gesperrt
#          → WR: 92.63% → 95.47% (+2.84pp)  |  PnL: +675 → +1610 USDT
#
#  MOM:    Stunde 21 + 23 UTC gesperrt  +  Dienstag gesperrt
#          → WR: 92.03% → 96.02% (+3.99pp)  |  PnL: +672 → +641 USDT (-5%)
#
#  MA-DIP: Stunde 21 UTC gesperrt
#          → WR: 88.41% → 93.21% (+4.80pp)  |  PnL: +104 → +1053 USDT
#
#  Portfolio gesamt: WR 91.27% → 94.91%  |  PnL +1451 → +3304 USDT (+2.3x)
#  Basis: analyze_loss_patterns.py  /  backtest_xgb_losses.py  (2J-Parquet)
#
#  Neu in v15:
#  ++ Neue Coins aus Backtest-Ergebnissen ++++++++++++++++++++++++++++++++
#  Qualifizierungskriterien: win_rate >= 90%, trades >= 20, net_pnl > 0
#  Hinzugefuegt: 51 neue DIP-Coins, 58 neue MOM-Coins, 56 neue MA-DIP-Coins
#
#  Neu in v14:
#  ── MA-DIP Strategie (dritte parallele Strategie) ──────────────────
#  Einstieg: Preis fällt mehr als 4% unter den MA(30min)
#  Kein BTC-Filter — feuert unabhängig vom Marktregime (Seitwärtsmärkte!)
#  Kein Peak nötig — misst normale Intraday-Schwankungen
#  TP: 1.0% | Time-Stop: 240 Min | Max 3 Slots
#  Backtest 4J/25 Coins: WR=95.1%, PnL=+327 USDT, ~10.5 Trades/Woche
#  Kein Doppel-Einstieg: Coin bereits in DIP oder MOM → überspringen
#  Kapital-Split: DIP=55% / MOM=25% / MA-DIP=20%
#
#  Neu in v13:
#  ── MOM Loss-Cluster-Filter (backtest_loss_cluster.py) ──
#  Nach einem MOM-Time-Stop (Verlust): globale Pause für alle neuen MOM-Entries.
#
#  Begründung (4J-Backtest, backtest_loss_cluster.py):
#    60% aller Verluste haben Folgeverlust innerhalb 30 Min (Median-Abstand: 7 Min)
#    1. Trade nach Verlust: WR=69.72% (-19.6pp!)  2. Trade: 75.6% (-13.8pp)
#    → Verlust = Frühwarnsignal für kippendes Marktregime
#
#  Neue Portfolio-Stats (Simulation, backtest_loss_cluster.py, 30-Min-Pause):
#    MOM:  2867 Trades (vs. 5122), WR=93.83% (+4.47pp), PnL=+1478 USDT (+55%)
#    → 42% weniger Trades, aber 55% mehr PnL
#
#  Basis: dip_bot_v12 (60 DIP-Coins, 47 MOM-Coins, DIP=2 Slots, MOM=7 Slots)
#
#  Neu in v9:
#  ── Momentum: 4 Coins entfernt (backtest_prio1_prio2.py) ──
#  Entfernt: BTC/USDT, BNB/USDT, MINA/USDT, LDO/USDT
#  Begründung: Alle 4 haben negativen PnL im 4J-Backtest
#    BTC:  106 Trades, WR=75.47%, PnL=-4.41 USDT
#    BNB:   80 Trades, WR=76.25%, PnL=-6.66 USDT
#    MINA:  58 Trades, WR=77.59%, PnL=-7.00 USDT
#    LDO:  268 Trades, WR=88.06%, PnL=-8.67 USDT
#
#  Basis: dip_bot_v8 (60 DIP-Coins, 51 MOM-Coins, MOM-WR=89.43%)
#
#  Neu in v6:
#  ── Momentum-Strategie ───────────────────────────────────
#  Eingabe:  Kurs steigt X% über rollierendes N-Bar-Minimum
#  Exit:     TP = +1.0% oder Time-Stop (max_hold_m Minuten)
#  50 Coins  (Basis: momentum_results.csv + momentum_filter_test.py)
#  Ausgeschlossen: ORDI, RAY, MOVE, SHIB, IOTA (schlechteste Coins)
#  BTC-Filter:     BTC 60m-Return > +1.5% (Aufwärtstrend bestätigt)
#  Zeit-Filter:    Block-Stunden UTC {1,4,7,9,14,18,20} (schwache Stunden)
#                  → Backtest: WR=93.25%, PF=2.78, EV=+0.536%/Trade
#  Kein SL (SL verschlechtert die Strategie in allen Konfigurationen)
#
#  ── Kapital-Allokation ───────────────────────────────────
#  FREE_USDT:    90% → 95%  (balance_use_pct)
#  Aufteilung:   70% DIP-Strategie / 30% Momentum-Strategie
#  Env-Vars:     DIP_CAPITAL_SPLIT (default 0.70)
#                MOMENTUM_CAPITAL_SPLIT (default 0.30)
#                MAX_DIP_SLOTS (default 2)
#                MAX_MOMENTUM_SLOTS (default 7)
#
#  ── DIP-Strategie ────────────────────────────────────────
#  Vollständig unverändert aus v5.5 (56 Coins, alle Settings)
#
#  Hardened safety (wie v1-v5):
#  1) Uses ONLY (BALANCE_USE_PCT * free_usdt) minus MIN_FREE_RESERVE_USDT
#  2) Every BUY re-fetches live balance right before sending the order
#  3) BUY uses a "spend cap": min(requested_quote, currently_usable_slice)
#  4) Fee/slippage buffer + retry downscale
#  5) Market min-cost / min-amount checks + precision rounding
#  6) If buy succeeds, reads filled/average from order
#  7) If sell errors (InsufficientFunds), sells base-free fallback
#  8) Enforces "one buy per loop" optional throttle
# ============================================================


# ── Momentum-Konstanten ────────────────────────────────────────────────────────
MOMENTUM_TP_PCT        = 1.0          # Take-Profit: +1%
MOMENTUM_BTC_THRESHOLD = 1.5          # BTC 60m-Return muss > +1.5% sein
MOMENTUM_BAD_HOURS_UTC    = frozenset({1, 4, 7, 9, 14, 18, 20, 21, 23})  # +21,23 (v16: Verlustanalyse 2J-Backtest)
MOMENTUM_BAD_WEEKDAYS_UTC = frozenset({1, 3})                             # +1=Di (v16); 3=Do (WR=88%, neg. PnL)

# v16: Zeitfilter DIP + MA-DIP
DIP_BAD_HOURS_UTC   = frozenset({21})   # Stunde 21 UTC: Loss-Rate 38.7% (v16-Analyse)
MADIP_BAD_HOURS_UTC = frozenset({18, 19, 20, 21})  # v24: 6J-Stunden-Analyse: WR 76-81%, EV neg. bei 20+21h

# v17: Portfolio-Cooldown nach N konsekutiven Verlusten
COOLDOWN_STREAK_THRESH = 3    # Cooldown-Trigger: 3 Verluste am Stück (alle Strategien)
COOLDOWN_HOURS         = 2    # Cooldown-Dauer: 2 Stunden (Backtest-Optimum)
MOMENTUM_LOSS_PAUSE_MIN   = 30                                    # Pause nach Time-Stop [Min] (backtest_loss_cluster.py)
MOMENTUM_FEE_BUFFER    = 0.10         # Gebühren-Buffer für Momentum (~0.1% RT)

# ── MA-DIP-Konstanten ──────────────────────────────────────────────────────────
MADIP_TP_PCT     = 1.5   # Take-Profit: +1.5%  (v23: optimiert via 6J-Sweep, war 1.0%)
MADIP_MA_BARS    = 30    # MA über letzte 30 geschlossene 1m-Bars
MADIP_DROP_PCT   = 4.0   # Einstieg wenn Preis > 5% unter MA  (v23: war 4.0%)
MADIP_MAX_HOLD_M = 240   # Time-Stop: 240 Minuten

# v18: BTC 15min Makro-Filter für MADIP
# v23: deaktiviert — 6J-Sweep zeigt keinen signifikanten Vorteil (+0.1% EV, -50% Trades)
MADIP_BTC_LOOKBACK_MIN  = 15     # BTC Return-Fenster: letzte 15 Minuten
MADIP_BTC_FILTER_THRESH = -100.0 # -100 = effektiv deaktiviert  (v23: war -2.0%)

# v19: DIP BTC-Kontext-Filter Schwellenwert (gelockert von -1.5% auf -1.0%)
DIP_BTC_CTX_THRESH = -1.0       # Entry erlaubt wenn BTC 60m-Return < -1.0%

# ── Dashboard HTTP-Server ──────────────────────────────────────────────────────
DASHBOARD_JSON = "dashboard_state.json"
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
# Prefer common PaaS PORT env var, keep DASHBOARD_PORT for local/backward compatibility.
DASHBOARD_PORT = int(os.getenv("PORT") or os.getenv("DASHBOARD_PORT", "8050"))
DASHBOARD_HTML_FILE = os.path.basename(os.getenv("DASHBOARD_HTML_FILE", "dashboard_v4.html"))

# ── Single-Instance-Lock ───────────────────────────────────────────────────────
PID_FILE = "bot_v17.pid"


# -----------------------------
# Single-Instance-Lock
# -----------------------------

def _acquire_pid_lock() -> None:
    """Verhindert doppelten Start. Schreibt PID-File und prüft ob bereits eine Instanz läuft."""
    import atexit

    def _pid_is_running(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    cur_pid = os.getpid()

    # Atomic create avoids race conditions when two instances start nearly at once.
    for _ in range(3):
        if os.path.exists(PID_FILE):
            try:
                with open(PID_FILE, "r", encoding="utf-8") as f:
                    old_pid = int((f.read() or "").strip())
                if old_pid != cur_pid and _pid_is_running(old_pid):
                    print(
                        f"[ERROR] Bot läuft bereits (PID {old_pid}). "
                        f"Erst stoppen, dann neu starten. Abbruch."
                    )
                    sys.exit(1)
                os.remove(PID_FILE)
            except (ValueError, OSError):
                # Veraltetes/kaputtes PID-File ignorieren und neu versuchen.
                try:
                    os.remove(PID_FILE)
                except OSError:
                    pass

        try:
            fd = os.open(PID_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(str(cur_pid))
            break
        except FileExistsError:
            continue
    else:
        print("[ERROR] PID-Lock konnte nicht erstellt werden. Abbruch.")
        sys.exit(1)

    def _cleanup():
        try:
            with open(PID_FILE, "r", encoding="utf-8") as f:
                owner_pid = int((f.read() or "").strip())
            if owner_pid == cur_pid:
                os.remove(PID_FILE)
        except (OSError, ValueError):
            pass
    atexit.register(_cleanup)


# -----------------------------
# Dashboard HTTP Server
# -----------------------------

def start_dashboard_server(
    directory: str,
    host: str = DASHBOARD_HOST,
    port: int = DASHBOARD_PORT,
) -> Optional[int]:
    """Startet einen gehaerteten Dashboard-Server im Hintergrund (Daemon-Thread)."""
    host = str(host or "127.0.0.1").strip()
    dashboard_root = os.path.abspath(directory)
    json_abs = os.path.abspath(os.path.join(dashboard_root, DASHBOARD_JSON))
    html_name = DASHBOARD_HTML_FILE or "dashboard_v4.html"
    html_abs = os.path.abspath(os.path.join(dashboard_root, html_name))
    dashboard_token = (os.getenv("DASHBOARD_TOKEN") or "").strip()
    allow_public_no_auth = (os.getenv("DASHBOARD_ALLOW_PUBLIC_NO_AUTH", "false").strip().lower()
                            in ("1", "true", "yes", "y", "on"))

    is_public_bind = host not in ("127.0.0.1", "localhost", "::1")
    if is_public_bind and (not dashboard_token) and (not allow_public_no_auth):
        print(
            "[DASH] Oeffentliche Bind-Adresse ohne Auth blockiert. "
            "Setze DASHBOARD_TOKEN oder (unsicher) DASHBOARD_ALLOW_PUBLIC_NO_AUTH=true."
        )
        return None

    class _Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=dashboard_root, **kwargs)

        def version_string(self):
            return ""

        def list_directory(self, path):
            self.send_error(403, "Directory listing disabled")
            return None

        def end_headers(self):
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'none'")
            super().end_headers()

        def _auth_ok(self) -> bool:
            if not dashboard_token:
                return True

            auth_header = self.headers.get("Authorization", "")
            candidate = ""
            if auth_header.lower().startswith("bearer "):
                candidate = auth_header[7:].strip()
            if not candidate:
                candidate = self.headers.get("X-Dashboard-Token", "").strip()

            return bool(candidate) and hmac.compare_digest(candidate, dashboard_token)

        def _reject_auth(self):
            self.send_response(401)
            self.send_header("WWW-Authenticate", "Bearer realm=dashboard")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(b"Unauthorized")

        def _serve_file(self, abs_path: str, content_type: str):
            if not abs_path.startswith(dashboard_root + os.sep):
                self.send_error(403, "Forbidden")
                return
            if not os.path.isfile(abs_path):
                self.send_error(404, "Not Found")
                return

            try:
                with open(abs_path, "rb") as f:
                    payload = f.read()
            except OSError:
                self.send_error(500, "Read error")
                return

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        def _serve_index(self):
            # Fallback index if dashboard HTML is not present.
            body = (
                "<html><body><h3>MEXC Dip Bot Dashboard</h3>"
                f"<p>Open <a href='/{html_name}'>/{html_name}</a> if available.</p>"
                f"<p>State JSON: <a href='/{DASHBOARD_JSON}'>/{DASHBOARD_JSON}</a></p>"
                "</body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _handle_dashboard_request(self):
            if not self._auth_ok():
                self._reject_auth()
                return

            path = urlparse(self.path).path

            if path == "/":
                if os.path.isfile(html_abs):
                    self._serve_file(html_abs, "text/html; charset=utf-8")
                else:
                    self._serve_index()
                return

            if path == f"/{html_name}":
                self._serve_file(html_abs, "text/html; charset=utf-8")
                return

            if path == f"/{DASHBOARD_JSON}":
                self._serve_file(json_abs, "application/json; charset=utf-8")
                return

            self.send_error(404, "Not Found")

        def do_GET(self):
            self._handle_dashboard_request()

        def do_HEAD(self):
            self._handle_dashboard_request()

        def do_POST(self):
            self.send_error(405, "Method Not Allowed")

        def do_PUT(self):
            self.send_error(405, "Method Not Allowed")

        def do_DELETE(self):
            self.send_error(405, "Method Not Allowed")

        def log_message(self, fmt, *args):  # Access-Logs unterdrücken
            pass

    configured_port = int(port)
    bind_attempts = [configured_port] if configured_port == 0 else [configured_port, 0]
    last_error: Optional[Exception] = None

    for bind_port in bind_attempts:
        try:
            server = ThreadingHTTPServer((host, bind_port), _Handler)
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()

            actual_port = int(server.server_port)
            display_host = "127.0.0.1" if host == "0.0.0.0" else host
            if configured_port != 0 and actual_port != configured_port:
                print(
                    f"[DASH] Port {configured_port} belegt, "
                    f"nutze dynamischen Port {actual_port}."
                )
            auth_hint = " (Auth: token required)" if dashboard_token else ""
            print(f"[DASH] Dashboard: http://{display_host}:{actual_port}/{auth_hint}")
            return actual_port
        except OSError as e:
            last_error = e

    print(f"[DASH] HTTP-Server konnte nicht gestartet werden (Host={host}, Port={configured_port}): {last_error}")
    return None


# -----------------------------
# Data Models
# -----------------------------

@dataclass
class StrategyParams:
    drop_trigger_pct: float
    tp_pct: float
    max_hold_h: int
    filter_name: str
    threshold: float
    sl_pct: Optional[float] = None

    # Drop speed filter controls
    use_drop_speed_filter: bool = False
    min_drop_speed_pct_per_min: float = 0.007

    # Profit lock
    use_profit_lock: bool = False
    profit_arm_pct: float = 0.70
    profit_lock_pct: float = 0.50

    # Rolling peak (statt Session-Peak)
    use_rolling_peak: bool = False
    rolling_peak_lookback_bars: int = 240

    # BTC-Kontext-Filter (v4, Schwelle v19: -1.0%)
    # True  → Einstieg nur wenn BTC 60m-Return < DIP_BTC_CTX_THRESH (-1.0%)
    # False → kein BTC-Filter (für BTC selbst + niedrig-korrelierte Coins)
    use_btc_context_filter: bool = False


@dataclass
class BotSizingConfig:
    use_dynamic_sizing: bool = False
    candidate_ratio_min: float = 0.70
    candidate_require_filter_ok: bool = True
    candidate_require_speed_ok: bool = True

    max_pos_pct_of_equity: float = 0.35
    max_pos_pct_of_free: float = 0.60

    min_usdt_per_trade: float = 10.0


@dataclass
class DashboardConfig:
    compact: bool = True
    use_colors: bool = True
    max_col_width: int = 14


@dataclass
class Position:
    # DIP position
    entry_price: float
    entry_ts: float
    amount_base: float
    symbol: str
    max_price: float

    # peak context at entry
    peak_price_at_entry: float
    peak_ts_at_entry: float

    # drop-speed context at entry
    since_peak_s_at_entry: float
    drop_speed_pct_per_min_at_entry: float

    # TP at entry
    tp_pct_at_entry: float

    # profit lock context at entry
    use_profit_lock_at_entry: int
    profit_arm_pct_at_entry: float
    profit_lock_pct_at_entry: float
    profit_lock_armed: bool


@dataclass
class MomentumParams:
    """Parameter für eine Momentum-Position."""
    lookback_m:       int       # Rollierendes Minimum über N Bars
    trigger_pct:      float     # Mindeststieg über rollendes Minimum [%]
    max_hold_m:       int       # Maximale Haltedauer [Minuten] (Time-Stop)
    tp_pct:           float     = MOMENTUM_TP_PCT  # Take-Profit-Ziel [%]
    extra_bad_hours:  frozenset = field(default_factory=frozenset)  # Coin-spezifische Extra-Blockhstunden UTC


@dataclass
class MomentumPosition:
    """Offene Momentum-Position."""
    entry_price: float
    entry_ts:    float
    amount_base: float
    symbol:      str
    tp_abs:      float  # Absoluter TP-Kurs: entry_price * (1 + tp_pct/100)
    max_hold_ts: float  # Unix-Timestamp des Time-Stops
    lookback_m:  int
    trigger_pct: float
    max_hold_m:  int
    # Entry-Kontext (für Trade-Log)
    max_price:           float = 0.0
    btc_ret60_at_entry:  float = float("nan")
    rise_pct_at_entry:   float = float("nan")
    rolling_min_at_entry: float = float("nan")


@dataclass
class MaDipParams:
    """Parameter für die MA-DIP Strategie."""
    ma_bars:    int   = MADIP_MA_BARS
    drop_pct:   float = MADIP_DROP_PCT
    tp_pct:     float = MADIP_TP_PCT
    max_hold_m: int   = MADIP_MAX_HOLD_M


@dataclass
class MaDipPosition:
    """Offene MA-DIP Position."""
    entry_price:       float
    entry_ts:          float
    amount_base:       float
    symbol:            str
    tp_abs:            float
    max_hold_ts:       float
    ma_at_entry:       float
    drop_pct_at_entry: float
    max_price:         float = 0.0


# -----------------------------
# Feature calc (DIP)
# -----------------------------

W15 = 15
W60 = 60
FLOW_SPAN = 60
VOL_WIN = 60


def compute_features_from_closes(closes: np.ndarray) -> Dict[str, float]:
    if len(closes) < 100:
        return {"valid": False}
    s = pd.Series(closes.astype(float))
    r1 = np.log(s / s.shift(1))
    v15 = np.log(s / s.shift(W15))
    v60 = np.log(s / s.shift(W60))
    decel = v15 - v60
    vol60 = r1.rolling(VOL_WIN).std()
    speed_z = v60 / vol60
    neg = r1.clip(upper=0.0)
    neg_flow60 = neg.ewm(span=FLOW_SPAN, adjust=False).mean()
    ma10 = s.rolling(10).mean()
    close_gt_ma10 = (s > ma10).astype(int)

    return {
        "valid": True,
        "r1": float(r1.iloc[-1]) if pd.notna(r1.iloc[-1]) else np.nan,
        "v15": float(v15.iloc[-1]) if pd.notna(v15.iloc[-1]) else np.nan,
        "v60": float(v60.iloc[-1]) if pd.notna(v60.iloc[-1]) else np.nan,
        "decel": float(decel.iloc[-1]) if pd.notna(decel.iloc[-1]) else np.nan,
        "vol60": float(vol60.iloc[-1]) if pd.notna(vol60.iloc[-1]) else np.nan,
        "speed_z": float(speed_z.iloc[-1]) if pd.notna(speed_z.iloc[-1]) else np.nan,
        "neg_flow60": float(neg_flow60.iloc[-1]) if pd.notna(neg_flow60.iloc[-1]) else np.nan,
        "ma10": float(ma10.iloc[-1]) if pd.notna(ma10.iloc[-1]) else np.nan,
        "close_gt_ma10": int(close_gt_ma10.iloc[-1]) if pd.notna(close_gt_ma10.iloc[-1]) else 0,
        "close": float(s.iloc[-1]),
    }


def filter_passes(filter_name: str, threshold: float, feats: Dict[str, float]) -> bool:
    if not feats.get("valid", False):
        return False
    if filter_name == "none":
        return True
    if filter_name == "baseline":
        return True
    if filter_name == "close_gt_ma10":
        return feats["close_gt_ma10"] == 1

    val_map = {
        "decel_gt": feats["decel"],
        "speed_z_gt": feats["speed_z"],
        "neg_flow60_gt": feats["neg_flow60"],
        "v60_gt": feats["v60"],
        "v60_gt_": feats["v60"],
    }
    v = val_map.get(filter_name)
    if v is None or np.isnan(v):
        return False
    return v > float(threshold)


# -----------------------------
# Strategies (DIP) — unverändert aus v5.5
# -----------------------------
#
# COIN_CONFIGS: alle Settings pro Coin auf einen Blick.
#
# Schlüssel:
#   d   = drop_trigger_pct      — Rückgang vom Peak [%]
#   tp  = take_profit_pct       — TP-Ziel [%]
#   h   = max_hold_h            — Maximale Haltedauer [h] (Time-Stop)
#   f   = filter_name           — Technischer Filter
#   th  = threshold             — Filter-Schwellenwert
#   spd = min_drop_speed        — Mindest-Drop-Speed [%/min]
#   rp  = use_rolling_peak      — True: 4h-Rolling-Peak / False: Session-Peak
#   rb  = rolling_peak_bars     — Fenstergröße Rolling-Peak [Bars, 1m]
#   sl  = sl_pct                — Stop-Loss [%] oder None
#   btc_ctx = use_btc_context_filter (v4)
#             True  → Einstieg nur wenn BTC 60m-Return < DIP_BTC_CTX_THRESH (-1.0%, v19)
#             False → kein BTC-Filter (BTC selbst + niedrig-korrelierte Coins)
#
# Profit-Lock wird global für alle Coins gesetzt:
#   use_profit_lock=True, profit_lock_pct=tp, profit_arm_pct=max(tp, 0.70)
#
COIN_CONFIGS: Dict[str, dict] = {
    # ══ LARGE-CAP / ROLLING 4h PEAK ══════════════════════════════════════════════
    # sym            d [v2→v3]    tp    h    f                   th       spd      rp     rb   sl      btc_ctx
    'BTC/USDT':  dict(d=4.5,  tp=1.5, h=72, f='baseline',      th=0.0,    spd=0.337, rp=True,  rb=240, sl=None, btc_ctx=False),
    'ETH/USDT':  dict(d=5.5,  tp=0.5, h=96, f='decel_gt',      th=0.005,  spd=1.503, rp=True,  rb=240, sl=None, btc_ctx=True),
    'BNB/USDT':  dict(d=4.0,  tp=2.0, h=72, f='baseline',      th=0.0,    spd=3.109, rp=True,  rb=240, sl=None, btc_ctx=True),
    'XRP/USDT':  dict(d=4.0,  tp=1.0, h=72, f='neg_flow60_gt', th=-0.006, spd=0.499, rp=True,  rb=240, sl=None, btc_ctx=True),
    'SOL/USDT':  dict(d=5.0,  tp=0.5, h=72, f='decel_gt',      th=0.005,  spd=0.647, rp=True,  rb=240, sl=None, btc_ctx=True),
    'DOGE/USDT': dict(d=6.0,  tp=0.5, h=48, f='decel_gt',      th=0.015,  spd=1.810, rp=True,  rb=240, sl=None, btc_ctx=True),
    'ADA/USDT':  dict(d=8.0,  tp=1.0, h=36, f='decel_gt',      th=0.02,   spd=3.250, rp=True,  rb=240, sl=None, btc_ctx=True),
    'TRX/USDT':  dict(d=5.0,  tp=2.0, h=120, f='baseline',      th=0.0,    spd=0.257, rp=True,  rb=240, sl=None, btc_ctx=True),
    'AVAX/USDT': dict(d=6.5,  tp=0.5, h=72, f='decel_gt',      th=0.02,   spd=0.724, rp=True,  rb=240, sl=None, btc_ctx=True),
    'LTC/USDT':  dict(d=5.5,  tp=0.5, h=72, f='v60_gt',        th=-0.03,  spd=4.043, rp=True,  rb=240, sl=None, btc_ctx=True),
    # ── Neu in v8 (Top-50 Market Cap, 4J-Backtest 100% WR) ───────────────────────
    'XLM/USDT':  dict(d=7.0,  tp=0.7, h=48,  f='baseline',      th=0.0,    spd=0.015, rp=True,  rb=240, sl=None, btc_ctx=True),
    'SUI/USDT':  dict(d=12.0, tp=1.4, h=18,  f='baseline',      th=0.0,    spd=0.015, rp=True,  rb=240, sl=None, btc_ctx=False),
    'BCH/USDT':  dict(d=10.0, tp=2.0, h=48, f='baseline',      th=0.0,    spd=0.015, rp=True,  rb=240, sl=None, btc_ctx=False),
    'ICP/USDT':  dict(d=12.0, tp=1.0, h=6,  f='close_gt_ma10', th=1.0,    spd=0.015, rp=True,  rb=240, sl=None, btc_ctx=False),

    # ══ STANDARD / SESSION-PEAK COINS ════════════════════════════════════════════
    'RAY/USDT':   dict(d=6.0,  tp=1.5, h=36, f='neg_flow60_gt', th=-0.004, spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'WIF/USDT':   dict(d=10.5, tp=0.5, h=18, f='close_gt_ma10', th=1,      spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'PEPE/USDT':  dict(d=6.0,  tp=1.5, h=72, f='decel_gt',      th=0.015,  spd=0.015, rp=False, rb=0, sl=None, btc_ctx=False),
    'PENDLE/USDT':dict(d=7.0,  tp=0.5, h=24, f='speed_z_gt',    th=-2.5,   spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'INJ/USDT':   dict(d=9.0,  tp=0.5, h=36, f='v60_gt',        th=-0.02,  spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'RENDER/USDT':dict(d=6.5,  tp=0.5, h=6, f='close_gt_ma10', th=1,      spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'TAO/USDT':   dict(d=6.0,  tp=0.5, h=6, f='close_gt_ma10', th=1,      spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'ALGO/USDT':  dict(d=5.5,  tp=1.5, h=24, f='decel_gt',      th=0.02,   spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'BONK/USDT':  dict(d=8.5,  tp=0.5, h=48, f='decel_gt',      th=0.02,   spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'ATOM/USDT':  dict(d=9.5,  tp=0.5, h=6, f='speed_z_gt',    th=-3,     spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'JASMY/USDT': dict(d=6.5,  tp=0.5, h=36, f='decel_gt',      th=0.01,   spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'AAVE/USDT':  dict(d=7.5,  tp=1.5, h=48, f='decel_gt',      th=0.015,  spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'IOTA/USDT':  dict(d=8.0,  tp=0.5, h=12, f='speed_z_gt',    th=-3,     spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'NEAR/USDT':  dict(d=7.0,  tp=0.5, h=6, f='speed_z_gt',    th=-1,     spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'DOT/USDT':   dict(d=8.5,  tp=1.8, h=12, f='speed_z_gt',    th=-2.5,   spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'GALA/USDT':  dict(d=10.5, tp=0.5, h=6, f='baseline',      th=0.0,    spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'SHIB/USDT':  dict(d=4.5,  tp=0.5, h=12, f='decel_gt',      th=0,      spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'ONDO/USDT':  dict(d=6.0,  tp=0.5, h=12, f='decel_gt',      th=0.005,  spd=0.015, rp=False, rb=0, sl=None, btc_ctx=False),
    'MANA/USDT':  dict(d=9.0,  tp=0.5, h=24, f='speed_z_gt',    th=-3,     spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'HBAR/USDT':  dict(d=7.5,  tp=0.9, h=12, f='speed_z_gt',    th=-2,     spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'MOVE/USDT':  dict(d=7.5,  tp=0.5, h=72, f='baseline',      th=0.0,    spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'STRK/USDT':  dict(d=5.0,  tp=0.5, h=6, f='decel_gt',      th=0.02,   spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'ENA/USDT':   dict(d=7.0,  tp=0.5, h=6, f='baseline',      th=0.0,    spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'LDO/USDT':   dict(d=8.5,  tp=0.5, h=36, f='decel_gt',      th=0.005,  spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'IMX/USDT':   dict(d=9.0,  tp=0.5, h=24, f='baseline',      th=0.0,    spd=0.015, rp=False, rb=0, sl=None, btc_ctx=False),
    'FLOKI/USDT': dict(d=6.5,  tp=0.5, h=6, f='decel_gt',      th=0.005,  spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'UNI/USDT':   dict(d=9.0,  tp=1.9, h=24, f='neg_flow60_gt', th=-0.006, spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'VET/USDT':   dict(d=7.0,  tp=0.5, h=96, f='speed_z_gt',    th=-2.5,   spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'WLD/USDT':   dict(d=9.0,  tp=0.5, h=6, f='neg_flow60_gt', th=-0.006, spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'CRV/USDT':   dict(d=8.0,  tp=0.6, h=18, f='neg_flow60_gt', th=-0.004, spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'MINA/USDT':  dict(d=6.0,  tp=1.5, h=48, f='neg_flow60_gt', th=-0.004, spd=0.015, rp=False, rb=0, sl=None, btc_ctx=False),
    'FET/USDT':   dict(d=7.0,  tp=0.5, h=18, f='neg_flow60_gt', th=-0.006, spd=0.015, rp=False, rb=0, sl=None, btc_ctx=False),
    'GRT/USDT':   dict(d=6.5,  tp=1.5, h=96, f='speed_z_gt',    th=-1.5,   spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'SAND/USDT':  dict(d=8.5,  tp=0.5, h=12, f='speed_z_gt',    th=-2,     spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'ORDI/USDT':  dict(d=7.5,  tp=0.5, h=6, f='speed_z_gt',    th=-3,     spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'LINK/USDT':  dict(d=8.0,  tp=1.5, h=48, f='decel_gt',      th=-0.01,  spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'STX/USDT':   dict(d=8.0,  tp=1.5, h=120, f='decel_gt',      th=0.015,  spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'AXS/USDT':   dict(d=7.5,  tp=1.5, h=120, f='v60_gt',        th=-0.04,  spd=0.015, rp=False, rb=0, sl=None, btc_ctx=False),
    'OP/USDT':    dict(d=8.5,  tp=0.5, h=6, f='baseline',      th=0.0,    spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'TIA/USDT':   dict(d=8.5,  tp=0.5, h=18, f='speed_z_gt',    th=-3,     spd=0.015, rp=False, rb=0, sl=None, btc_ctx=False),
    'JUP/USDT':   dict(d=6.0,  tp=0.5, h=6, f='speed_z_gt',    th=-1,     spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'ARB/USDT':   dict(d=8.5,  tp=2.0, h=6, f='decel_gt',      th=-0.01,  spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    'RUNE/USDT':  dict(d=15.0, tp=0.5, h=24, f='v60_gt',        th=-0.04,  spd=0.015, rp=False, rb=0, sl=None, btc_ctx=True),
    # ++ Neu in v15 (backtest_results_DIP.csv: WR>=90%, trades>=20, PnL>0) ++++++++++++++
    'APT/USDT':     dict(d=12,   tp=1.0, h=48, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'QNT/USDT':     dict(d=8,    tp=2.0, h=72, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'SEI/USDT':     dict(d=12,   tp=1.5, h=36, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'XTZ/USDT':     dict(d=12,   tp=1.0, h=72, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'FLOW/USDT':    dict(d=10,   tp=0.7, h=72, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    # 'EOS/USDT':     dict(d=15,   tp=1.9, h=48, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'NEO/USDT':     dict(d=12,   tp=1.1, h=48, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'AR/USDT':      dict(d=12,   tp=0.5, h=24, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    # 'THETA/USDT':   dict(d=10,   tp=1.0, h=96, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    # 'FTM/USDT':     dict(d=15,   tp=2.0, h=96, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'KAVA/USDT':    dict(d=15,   tp=2.0, h=120, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'CHZ/USDT':     dict(d=12,   tp=2.0, h=72, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'SNX/USDT':     dict(d=15,   tp=1.2, h=96, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'ROSE/USDT':    dict(d=9,    tp=1.9, h=72, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'DASH/USDT':    dict(d=15,   tp=2.0, h=24, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'ZEC/USDT':     dict(d=15,   tp=2.0, h=72, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'KSM/USDT':     dict(d=15,   tp=2.0, h=120, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'DYDX/USDT':    dict(d=12,   tp=0.5, h=72, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'LRC/USDT':     dict(d=15,   tp=1.9, h=120, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    '1INCH/USDT':   dict(d=15,   tp=1.6, h=48, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'BAT/USDT':     dict(d=12,   tp=1.8, h=96, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'QTUM/USDT':    dict(d=15,   tp=2.0, h=120, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    # 'ICX/USDT':     dict(d=12,   tp=0.9, h=48, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'IOTX/USDT':    dict(d=12,   tp=2.0, h=48, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'WOO/USDT':     dict(d=15,   tp=2.0, h=96, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    # 'GLM/USDT':     dict(d=15,   tp=1.9, h=72, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'ANKR/USDT':    dict(d=12,   tp=1.0, h=96, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'ARKM/USDT':    dict(d=15,   tp=1.2, h=72, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'SKL/USDT':     dict(d=10,   tp=1.0, h=48, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    # 'FLUX/USDT':    dict(d=9,    tp=1.3, h=120, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'CELO/USDT':    dict(d=12,   tp=0.5, h=96, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    # 'AUDIO/USDT':   dict(d=15,   tp=2.0, h=72, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'ZEN/USDT':     dict(d=15,   tp=2.0, h=36, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    # 'DENT/USDT':    dict(d=12,   tp=1.0, h=72, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'NMR/USDT':     dict(d=15,   tp=1.4, h=72, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'OGN/USDT':     dict(d=10,   tp=1.0, h=96, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
    'POL/USDT':     dict(d=8,    tp=1.9, h=96, f='baseline',      th=0.0,    spd=0.0, rp=False, rb=0, sl=None, btc_ctx=False),
}


def get_strategies() -> Dict[str, StrategyParams]:
    strategies = {}
    for sym, c in COIN_CONFIGS.items():
        p = StrategyParams(
            drop_trigger_pct=c['d'],
            tp_pct=c['tp'],
            max_hold_h=c['h'],
            filter_name=c['f'],
            threshold=c['th'],
            sl_pct=c.get('sl'),
            use_drop_speed_filter=True,
            min_drop_speed_pct_per_min=c['spd'],
            use_rolling_peak=c.get('rp', False),
            rolling_peak_lookback_bars=c.get('rb', 240),
            use_btc_context_filter=c.get('btc_ctx', True),
        )
        strategies[sym] = p
    # Profit-Lock global für alle Coins
    for p in strategies.values():
        p.use_profit_lock = True
        p.profit_lock_pct = float(p.tp_pct)
        p.profit_arm_pct = float(max(p.tp_pct, 0.70))
    return strategies


# -----------------------------
# Strategies (MOMENTUM) — neu in v6
# -----------------------------
#
# Basis: momentum_results.csv + Analyse in momentum_btc_regime.py /
#        momentum_filter_test.py (24 Monate)
#
# Ausgeschlossene Coins (schlechteste WR + negativer EV):
#   ORDI, RAY, MOVE, SHIB, IOTA
#
# Parameter-Schlüssel:
#   lb   = lookback_m   — Rollierendes Minimum über lb Bars [1m]
#   trig = trigger_pct  — Mindeststieg über rollendes Minimum [%]
#   mh   = max_hold_m   — Maximale Haltedauer [min] (Time-Stop)
#
MOMENTUM_COIN_CONFIGS: Dict[str, dict] = {
    # sym             lb    trig    mh      extra_bh (v10: coin-spezifische Extra-Blockhstunden UTC)
    'TAO/USDT':    dict(lb=60,  trig=10.0, mh=60),
    'RENDER/USDT': dict(lb=60,  trig=10.0, mh=60),
    'AXS/USDT':    dict(lb=120, trig=8.0,  mh=480, extra_bh={16}),
    'ALGO/USDT':   dict(lb=240, trig=10.0, mh=480),
    'LINK/USDT':   dict(lb=60,  trig=6.0,  mh=480),
    'DOGE/USDT':   dict(lb=120, trig=10.0, mh=480),
    'IMX/USDT':    dict(lb=60,  trig=8.0,  mh=480, extra_bh={13, 15}),
    # 'MINA/USDT': entfernt in v9 (4J-Backtest: WR=77.59%, PnL=-7.00 USDT)
    'TIA/USDT':    dict(lb=60,  trig=10.0, mh=120),
    'VET/USDT':    dict(lb=120, trig=10.0, mh=240),
    'PENDLE/USDT': dict(lb=60,  trig=10.0, mh=120),
    'ADA/USDT':    dict(lb=120, trig=10.0, mh=480),
    'AAVE/USDT':   dict(lb=120, trig=10.0, mh=480, extra_bh={22}),
    'JUP/USDT':    dict(lb=60,  trig=10.0, mh=480),
    'GRT/USDT':    dict(lb=60,  trig=6.0,  mh=480, extra_bh={0, 13, 16}),
    'JASMY/USDT':  dict(lb=60,  trig=10.0, mh=240, extra_bh={0}),
    'GALA/USDT':   dict(lb=60,  trig=8.0,  mh=480, extra_bh={0}),
    'BONK/USDT':   dict(lb=60,  trig=8.0,  mh=480),
    'HBAR/USDT':   dict(lb=60,  trig=10.0, mh=120, extra_bh={16}),
    'STX/USDT':    dict(lb=60,  trig=8.0,  mh=480),
    'ETH/USDT':    dict(lb=60,  trig=6.0,  mh=480),
    'WLD/USDT':    dict(lb=60,  trig=10.0, mh=480),
    'AVAX/USDT':   dict(lb=60,  trig=6.0,  mh=480, extra_bh={0, 13, 17}),
    'FLOKI/USDT':  dict(lb=120, trig=10.0, mh=480, extra_bh={15}),
    'ONDO/USDT':   dict(lb=60,  trig=6.0,  mh=120),
    'DOT/USDT':    dict(lb=120, trig=8.0,  mh=480, extra_bh={15, 16}),
    'PEPE/USDT':   dict(lb=60,  trig=8.0,  mh=480, extra_bh={16, 21}),
    'SOL/USDT':    dict(lb=60,  trig=6.0,  mh=480, extra_bh={13, 15, 16, 17, 19}),
    'INJ/USDT':    dict(lb=120, trig=10.0, mh=240),
    'XRP/USDT':    dict(lb=240, trig=8.0,  mh=480, extra_bh={5, 16, 19}),
    'LTC/USDT':    dict(lb=480, trig=10.0, mh=480, extra_bh={13}),
    'FET/USDT':    dict(lb=120, trig=8.0,  mh=480, extra_bh={6, 15, 16, 17}),
    'RUNE/USDT':   dict(lb=120, trig=8.0,  mh=480, extra_bh={0}),
    'MANA/USDT':   dict(lb=60,  trig=6.0,  mh=480, extra_bh={15}),
    'ARB/USDT':    dict(lb=240, trig=10.0, mh=480, extra_bh={16}),
    'OP/USDT':     dict(lb=60,  trig=6.0,  mh=480, extra_bh={16, 21}),
    'NEAR/USDT':   dict(lb=60,  trig=8.0,  mh=480),
    'SAND/USDT':   dict(lb=60,  trig=8.0,  mh=120, extra_bh={15}),
    'ATOM/USDT':   dict(lb=60,  trig=5.0,  mh=480, extra_bh={13, 15, 16}),
    # 'BNB/USDT':  entfernt in v9 (4J-Backtest: WR=76.25%, PnL=-6.66 USDT)
    'ENA/USDT':    dict(lb=60,  trig=10.0, mh=480),
    'TRX/USDT':    dict(lb=240, trig=4.0,  mh=480, extra_bh={13, 15, 21}),
    'STRK/USDT':   dict(lb=60,  trig=8.0,  mh=240),
    'CRV/USDT':    dict(lb=60,  trig=5.0,  mh=480, extra_bh={0, 3, 15, 16, 17, 19}),
    # 'LDO/USDT':  entfernt in v9 (4J-Backtest: WR=88.06%, PnL=-8.67 USDT)
    'WIF/USDT':    dict(lb=60,  trig=6.0,  mh=480),
    # 'BTC/USDT':  entfernt in v9 (4J-Backtest: WR=75.47%, PnL=-4.41 USDT)
    'UNI/USDT':    dict(lb=60,  trig=6.0,  mh=480, extra_bh={16}),
    # ── Neu in v8 ────────────────────────────────────────────────────────────────
    'SUI/USDT':    dict(lb=120, trig=10.0, mh=480),
    # ++ Neu in v15 (backtest_results_MOM.csv: WR>=90%, trades>=20, PnL>0) ++++++++++++++
    'BNB/USDT':     dict(lb=240,  trig=6,    mh=480),
    'XLM/USDT':     dict(lb=120,  trig=8,    mh=480),
    'APT/USDT':     dict(lb=60,   trig=5,    mh=480),
    'ICP/USDT':     dict(lb=240,  trig=10,   mh=480),
    'RAY/USDT':     dict(lb=240,  trig=10,   mh=480),
    'MOVE/USDT':    dict(lb=60,   trig=8,    mh=480),
    'LDO/USDT':     dict(lb=60,   trig=8,    mh=480),
    'QNT/USDT':     dict(lb=60,   trig=7,    mh=480),
    'SEI/USDT':     dict(lb=120,  trig=10,   mh=480),
    'XTZ/USDT':     dict(lb=60,   trig=6,    mh=480),
    'IOTA/USDT':    dict(lb=60,   trig=6,    mh=480),
    'FLOW/USDT':    dict(lb=240,  trig=10,   mh=480),
    # 'EOS/USDT':     dict(lb=120,  trig=7,    mh=480),
    'NEO/USDT':     dict(lb=120,  trig=8,    mh=480),
    'MINA/USDT':    dict(lb=60,   trig=7,    mh=480),
    'ORDI/USDT':    dict(lb=120,  trig=10,   mh=480),
    # 'THETA/USDT':   dict(lb=240,  trig=10,   mh=480),
    'KAVA/USDT':    dict(lb=240,  trig=10,   mh=480),
    'CHZ/USDT':     dict(lb=60,   trig=7,    mh=480),
    'SNX/USDT':     dict(lb=60,   trig=7,    mh=480),
    'ROSE/USDT':    dict(lb=60,   trig=7,    mh=480),
    'DASH/USDT':    dict(lb=60,   trig=6,    mh=480),
    'ZEC/USDT':     dict(lb=120,  trig=10,   mh=480),
    'KSM/USDT':     dict(lb=60,   trig=7,    mh=480),
    'DYDX/USDT':    dict(lb=60,   trig=7,    mh=480),
    'LRC/USDT':     dict(lb=60,   trig=7,    mh=480),
    'BAT/USDT':     dict(lb=240,  trig=10,   mh=480),
    'QTUM/USDT':    dict(lb=120,  trig=8,    mh=480),
    'WAVES/USDT':   dict(lb=60,   trig=4,    mh=480),
    # 'ICX/USDT':     dict(lb=60,   trig=5,    mh=480),
    'IOTX/USDT':    dict(lb=60,   trig=7,    mh=480),
    # 'OCEAN/USDT':   dict(lb=60,   trig=5,    mh=480),
    'WOO/USDT':     dict(lb=60,   trig=7,    mh=480),
    # 'GLM/USDT':     dict(lb=120,  trig=8,    mh=480),
    'RVN/USDT':     dict(lb=120,  trig=8,    mh=480),
    'ANKR/USDT':    dict(lb=60,   trig=6,    mh=480),
    'ARKM/USDT':    dict(lb=60,   trig=8,    mh=480),
    'SKL/USDT':     dict(lb=60,   trig=7,    mh=480),
    # 'FLUX/USDT':    dict(lb=60,   trig=6,    mh=480),
    'CELO/USDT':    dict(lb=60,   trig=7,    mh=480),
    'ZEN/USDT':     dict(lb=120,  trig=10,   mh=480),
    # 'DENT/USDT':    dict(lb=60,   trig=8,    mh=480),
    # 'BAND/USDT':    dict(lb=120,  trig=8,    mh=480),
    'NMR/USDT':     dict(lb=60,   trig=7,    mh=480),
    'OGN/USDT':     dict(lb=240,  trig=10,   mh=480),
    'POL/USDT':     dict(lb=60,   trig=5,    mh=480),
}


def get_momentum_configs() -> Dict[str, MomentumParams]:
    """Erstellt MomentumParams-Objekte aus MOMENTUM_COIN_CONFIGS."""
    configs = {}
    for sym, c in MOMENTUM_COIN_CONFIGS.items():
        configs[sym] = MomentumParams(
            lookback_m=int(c['lb']),
            trigger_pct=float(c['trig']),
            max_hold_m=int(c['mh']),
            tp_pct=MOMENTUM_TP_PCT,
            extra_bad_hours=frozenset(c.get('extra_bh', set())),
        )
    return configs


# -----------------------------
# Strategies (MA-DIP) — neu in v14
# -----------------------------
#
# Signal: Preis < MA(30min) × (1 - 5%)
# TP: +1.5% | Time-Stop: 240 Min | Kein BTC-Filter
# v23: optimiert via backtest_madip_optimizer.py (6J-Sweep, 74 Coins, 64 Kombos)
#      drop 4%→5%, TP 1%→1.5%, BTC-Filter deaktiviert
#      Ergebnis: WR 90.92%, EV +1.12%/Trade, 8.856 Trades über 74 Coins / 6 Jahre
#      Entfernt: BTC/USDT (0 Trades bei 5%-Drop), STRK/USDT (neg. EV)
#
MADIP_COINS: List[str] = [
    'ETH/USDT',  'BNB/USDT',  'XRP/USDT',  'SOL/USDT',
    'DOGE/USDT', 'ADA/USDT',  'TRX/USDT',  'AVAX/USDT', 'LTC/USDT',
    'LINK/USDT', 'DOT/USDT',  'UNI/USDT',  'ATOM/USDT', 'GRT/USDT',
    'CRV/USDT',  'MANA/USDT', 'ONDO/USDT', 'OP/USDT',   'NEAR/USDT',
    'ARB/USDT',  'SUI/USDT',  'BCH/USDT',  'XLM/USDT',  'ICP/USDT',
    'HBAR/USDT',
    'SHIB/USDT',
    'AAVE/USDT',
    'APT/USDT',
    'TAO/USDT',
    'VET/USDT',
    'RENDER/USDT',
    'FET/USDT',
    'ENA/USDT',
    'TIA/USDT',
    'JUP/USDT',
    'IMX/USDT',
    'STX/USDT',
    'MOVE/USDT',
    'INJ/USDT',
    'SEI/USDT',
    'SAND/USDT',
    'GALA/USDT',
    'XTZ/USDT',
    'IOTA/USDT',
    'FLOW/USDT',
    'AXS/USDT',
    'RUNE/USDT',
    'PEPE/USDT',
    'BONK/USDT',
    'WIF/USDT',
    'FLOKI/USDT',
    'NEO/USDT',
    'JASMY/USDT',
    'MINA/USDT',
    'AR/USDT',
    # 'THETA/USDT',
    # 'FTM/USDT',
    'CHZ/USDT',
    'SNX/USDT',
    'ROSE/USDT',
    'DASH/USDT',
    'ZEC/USDT',
    'KSM/USDT',
    '1INCH/USDT',
    'BAT/USDT',
    'WOO/USDT',
    'RVN/USDT',
    'ANKR/USDT',
    'ARKM/USDT',
    # 'AUDIO/USDT',
    # 'DENT/USDT',
    'NMR/USDT',
]


def get_madip_configs() -> Dict[str, MaDipParams]:
    """Erstellt MaDipParams für alle MA-DIP Coins (einheitliche Parameter)."""
    return {sym: MaDipParams() for sym in MADIP_COINS}


# -----------------------------
# Utils / ANSI
# -----------------------------

def now_ts() -> float:
    return time.time()


def _env_true(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


ANSI = {
    "reset": "\033[0m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "cyan": "\033[36m",
}


def colorize(s: str, color: str, enabled: bool) -> str:
    if not enabled:
        return s
    return f"{ANSI.get(color, '')}{s}{ANSI['reset']}"


def icon_bool(ok: bool, enabled: bool) -> str:
    if not enabled:
        return "yes" if ok else "no"
    return colorize("✓", "green", True) if ok else colorize("✗", "red", True)


def compute_drop_speed_pct_per_min(drop_frac: float, since_peak_s: float) -> float:
    if since_peak_s is None or since_peak_s <= 0:
        return float("nan")
    since_peak_min = since_peak_s / 60.0
    if since_peak_min <= 0:
        return float("nan")
    return (drop_frac * 100.0) / since_peak_min


def speed_bucket(speed: float) -> str:
    if speed is None or not np.isfinite(speed):
        return "-"
    if speed < 0.003:
        return "slow"
    if speed < 0.007:
        return "slow2"
    if speed < 0.015:
        return "mid"
    if speed < 0.03:
        return "fast"
    return "flush"


def icon_speed_bin(bin_name: str, enabled: bool) -> str:
    if not enabled:
        return bin_name
    if bin_name.startswith("slow"):
        return colorize("●", "red", True) + " " + colorize(bin_name, "red", True)
    if bin_name == "mid":
        return colorize("●", "yellow", True) + " " + colorize(bin_name, "yellow", True)
    if bin_name == "fast":
        return colorize("●", "green", True) + " " + colorize(bin_name, "green", True)
    if bin_name == "flush":
        return colorize("●", "cyan", True) + " " + colorize(bin_name, "cyan", True)
    return bin_name


# -----------------------------
# Bot
# -----------------------------

class MexcDipBot:
    def __init__(
        self,
        exchange: ccxt.Exchange,
        strategies: Dict[str, StrategyParams],
        usdt_per_trade: float,
        dry_run: bool,
        sizing_cfg: BotSizingConfig,
        dash_cfg: DashboardConfig,
        momentum_configs: Optional[Dict[str, MomentumParams]] = None,
        madip_configs: Optional[Dict[str, MaDipParams]] = None,
    ):
        self.ex = exchange
        self.strategies = strategies
        self.momentum_configs: Dict[str, MomentumParams] = momentum_configs or {}
        self.madip_configs: Dict[str, MaDipParams] = madip_configs or {}
        self.usdt_per_trade = float(usdt_per_trade)
        self.max_slots = int(os.getenv("MAX_DIP_SLOTS", "2"))
        self.max_momentum_slots = int(os.getenv("MAX_MOMENTUM_SLOTS", "7"))
        self.max_madip_slots = int(os.getenv("MAX_MADIP_SLOTS", "3"))
        self.dry_run = dry_run
        self.sizing_cfg = sizing_cfg
        self.dash_cfg = dash_cfg

        # ── Kapital-Aufteilung ───────────────────────────────────
        self.dip_capital_split      = float(os.getenv("DIP_CAPITAL_SPLIT",      "0.55"))
        self.momentum_capital_split = float(os.getenv("MOMENTUM_CAPITAL_SPLIT", "0.25"))
        self.madip_capital_split    = float(os.getenv("MADIP_CAPITAL_SPLIT",    "0.20"))

        # ── Safety knobs ─────────────────────────────────────────
        # v6: balance_use_pct default 0.95 (war 0.90 in v5)
        self.balance_use_pct = float(os.getenv("BALANCE_USE_PCT", "0.95"))
        self.min_free_reserve_usdt = float(os.getenv("MIN_FREE_RESERVE_USDT", "5"))
        self.fee_buffer_pct = float(os.getenv("FEE_BUFFER_PCT", "0.25"))
        self.buy_retry_attempts = int(os.getenv("BUY_RETRY_ATTEMPTS", "3"))
        self.buy_retry_scale = float(os.getenv("BUY_RETRY_SCALE", "0.95"))
        self.use_spread_check_global = _env_true("USE_SPREAD_CHECK", True)
        self.max_spread_pct_global = float(os.getenv("MAX_SPREAD_PCT", "0.25"))

        # hard cap per single order vs current free
        self.max_spend_pct_of_free_per_order = float(os.getenv("MAX_SPEND_PCT_FREE_PER_ORDER", "0.60"))

        # throttle to max one BUY per loop (DIP + Momentum gemeinsam)
        self.max_one_buy_per_loop = _env_true("MAX_ONE_BUY_PER_LOOP", True)

        # limit sell config (TP exits only)
        self.limit_sell_timeout_s = int(os.getenv("LIMIT_SELL_TIMEOUT_S", "30"))
        self.limit_sell_poll_s = float(os.getenv("LIMIT_SELL_POLL_S", "5"))

        # Momentum OHLCV-Limit: max lookback ist 480m → min 485 Bars nötig
        self.momentum_ohlcv_limit = int(os.getenv("MOMENTUM_OHLCV_LIMIT", "500"))

        # ── DIP State ────────────────────────────────────────────
        self.peaks: Dict[str, float] = {}
        self.peak_ts: Dict[str, float] = {}
        self.positions: Dict[str, Position] = {}

        # ── Entry Lock (verhindert Doppel-Einstieg bei Race Conditions) ──
        self._position_lock   = threading.Lock()
        self._entering: set   = set()   # Symbole die gerade einen Buy ausführen

        # ── Momentum State ───────────────────────────────────────
        self.momentum_positions: Dict[str, MomentumPosition] = {}
        self.mom_loss_pause_until: float = 0.0   # Unix-TS bis wann neue MOM-Entries pausiert sind

        # ── MA-DIP State ─────────────────────────────────────────
        self.madip_positions: Dict[str, MaDipPosition] = {}

        # ── v17: Portfolio-Cooldown ───────────────────────────────
        self.consecutive_losses: int = 0      # laufender Verlust-Streak (portfolio-global)
        self.cooldown_until:     float = 0.0  # Unix-TS bis wann keine neuen Entries

        # ── Logging ──────────────────────────────────────────────
        self.trade_log_file          = "trades_new.csv"
        self.momentum_trade_log_file = "trades_momentum.csv"
        self.madip_trade_log_file    = "trades_madip.csv"
        self.next_trade_nr = 0
        self._init_logging()

        # ── Session-PnL Tracking ─────────────────────────────────
        self.session_start_ts      = now_ts()
        self.session_start_equity  = 0.0   # wird beim ersten Balance-Fetch gesetzt
        self.session_pnl_usdt      = 0.0   # realisierte PnL dieser Session
        self.session_trades        = 0
        self.session_wins          = 0
        self.pnl_history: List[Dict] = []  # [{t, v}] für Chart
        # Per-Strategie Session-Zähler (reset bei Neustart)
        self.session_dip_trades    = 0
        self.session_dip_wins      = 0
        self.session_dip_pnl       = 0.0
        self.session_mom_trades    = 0
        self.session_mom_wins      = 0
        self.session_mom_pnl       = 0.0
        self.session_madip_trades  = 0
        self.session_madip_wins    = 0
        self.session_madip_pnl     = 0.0

    # ---------- logging ----------
    def _init_logging(self):
        # DIP-Log
        if os.path.exists(self.trade_log_file):
            try:
                df = pd.read_csv(self.trade_log_file)
                if not df.empty and 'trade_nr' in df.columns:
                    self.next_trade_nr = int(df['trade_nr'].max()) + 1
            except Exception as e:
                print(f"Error loading existing DIP log: {e}. Starting from trade_nr=0.")
        # Momentum-Log (falls vorhanden, höchste trade_nr berücksichtigen)
        if os.path.exists(self.momentum_trade_log_file):
            try:
                df = pd.read_csv(self.momentum_trade_log_file)
                if not df.empty and 'trade_nr' in df.columns:
                    max_nr = int(df['trade_nr'].max()) + 1
                    self.next_trade_nr = max(self.next_trade_nr, max_nr)
            except Exception as e:
                print(f"Error loading existing Momentum log: {e}.")
        # MA-DIP-Log
        if os.path.exists(self.madip_trade_log_file):
            try:
                df = pd.read_csv(self.madip_trade_log_file)
                if not df.empty and 'trade_nr' in df.columns:
                    max_nr = int(df['trade_nr'].max()) + 1
                    self.next_trade_nr = max(self.next_trade_nr, max_nr)
            except Exception as e:
                print(f"Error loading existing MA-DIP log: {e}.")

    def _log_trade_common(self, row: Dict[str, Any], log_file: str):
        df = pd.DataFrame([row])
        header = not os.path.exists(log_file)
        df.to_csv(log_file, mode='a', header=header, index=False)

    # ---------- data fetch ----------
    def fetch_closes(self, symbol: str, timeframe: str, limit: int) -> Tuple[np.ndarray, float]:
        ohlcv = self.ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        closes = np.array([c[4] for c in ohlcv], dtype=float)
        last = float(closes[-1])
        return closes, last

    def _fetch_usdt_equity_and_free(self) -> Tuple[float, float]:
        bal = self.ex.fetch_balance()
        usdt = bal.get("USDT", {}) if isinstance(bal, dict) else {}
        free = float(usdt.get("free") or 0.0)
        total = usdt.get("total")
        used = usdt.get("used")
        equity = float(total) if total is not None else free + float(used or 0.0)
        return equity, free

    def _fetch_base_free(self, symbol: str) -> float:
        base = symbol.split("/")[0]
        try:
            bal = self.ex.fetch_balance()
            b = bal.get(base, {}) if isinstance(bal, dict) else {}
            return float(b.get("free") or 0.0)
        except Exception:
            return 0.0

    # ---------- market microstructure ----------
    def _spread_pct(self, symbol: str) -> Tuple[Optional[float], str]:
        try:
            ob = self.ex.fetch_order_book(symbol, limit=5)
            bids = ob.get("bids") or []
            asks = ob.get("asks") or []
            if not bids or not asks:
                return None, "no_book"
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            if best_bid <= 0 or best_ask <= 0 or best_ask <= best_bid:
                return None, "bad_book"
            mid = (best_bid + best_ask) / 2.0
            sp = (best_ask - best_bid) / mid * 100.0
            return float(sp), "ok"
        except Exception as e:
            return None, f"err:{type(e).__name__}"

    def _spread_ok(self, symbol: str, max_spread_pct: float) -> bool:
        sp, why = self._spread_pct(symbol)
        if sp is None:
            print(f"[SKIP] {symbol}: spread check failed ({why})")
            return False
        if sp > float(max_spread_pct):
            print(f"[SKIP] {symbol}: spread {sp:.3f}% > {max_spread_pct:.3f}%")
            return False
        return True

    # ---------- peak (DIP) ----------
    def _update_peak_if_new_high(self, symbol: str, last: float):
        if symbol not in self.peaks:
            self.peaks[symbol] = last
            self.peak_ts[symbol] = now_ts()
            return
        if last > self.peaks[symbol]:
            self.peaks[symbol] = last
            self.peak_ts[symbol] = now_ts()

    def _reset_peak_to_price_now(self, symbol: str, price: float):
        self.peaks[symbol] = price
        self.peak_ts[symbol] = now_ts()

    # ---------- formatting ----------
    def _fmt_duration(self, seconds: float) -> str:
        if seconds is None or seconds < 0:
            return "-"
        if seconds < 3600:
            return f"{seconds/60:.0f}m"
        if seconds < 86400:
            return f"{seconds/3600:.1f}h"
        return f"{seconds/86400:.1f}d"

    def _fmt(self, x, digits=4):
        if x is None:
            return "-"
        try:
            f = float(x)
            if np.isnan(f):
                return "-"
            if abs(f) >= 1000:
                return f"{f:,.0f}"
            if abs(f) >= 1:
                return f"{f:.{digits}f}"
            return f"{f:.{max(digits, 6)}f}"
        except Exception:
            return str(x)

    def _render_table(self, headers, rows, max_col_width=14):
        cols = len(headers)
        widths = [len(str(h)) for h in headers]
        for r in rows:
            for i in range(cols):
                widths[i] = max(widths[i], len(str(r[i])))
        widths = [min(w, max_col_width) for w in widths]

        def clip(s, w):
            s = str(s)
            return (s[: w - 1] + "…") if len(s) > w else s

        def fmt_row(r):
            return " | ".join(clip(r[i], widths[i]).ljust(widths[i]) for i in range(cols))

        out = [fmt_row(headers), "-+-".join("-" * w for w in widths)]
        for r in rows:
            out.append(fmt_row(r))
        return "\n".join(out)

    # ---------- rounding ----------
    def _round_amount(self, symbol: str, amount: float) -> float:
        try:
            return float(self.ex.amount_to_precision(symbol, float(amount)))
        except Exception:
            return float(amount)

    def _round_price(self, symbol: str, price: float) -> float:
        try:
            return float(self.ex.price_to_precision(symbol, float(price)))
        except Exception:
            return float(price)

    # ---------- capital safety ----------
    def _compute_usable_free_usdt(self, free_usdt: float) -> Tuple[float, float]:
        """
        Returns (usable_free, reserve).
        reserve is ALWAYS kept: max(pct reserve, MIN_FREE_RESERVE_USDT).
        """
        pct = float(self.balance_use_pct)
        pct = 0.95 if (not np.isfinite(pct) or pct <= 0 or pct > 1) else pct

        usable_by_pct = float(free_usdt) * pct
        usable = max(0.0, usable_by_pct - float(self.min_free_reserve_usdt))
        reserve = max(float(self.min_free_reserve_usdt), float(free_usdt) - usable)
        reserve = max(0.0, reserve)
        return float(usable), float(reserve)

    def _prepare_market_buy_amount(self, symbol: str, buy_quote_usdt: float, last_price: float) -> Tuple[Optional[float], str]:
        if not np.isfinite(buy_quote_usdt) or buy_quote_usdt <= 0:
            return None, "bad_quote"
        if not np.isfinite(last_price) or last_price <= 0:
            return None, "bad_price"

        buf = float(self.fee_buffer_pct) / 100.0
        buf = max(0.0, min(buf, 0.03))
        spend = float(buy_quote_usdt) * (1.0 - buf)

        try:
            m = self.ex.market(symbol)
        except Exception:
            m = {}

        limits = (m or {}).get("limits", {}) or {}
        min_amt = ((limits.get("amount") or {}).get("min"))
        min_cost = ((limits.get("cost") or {}).get("min"))

        if min_cost is not None and np.isfinite(float(min_cost)) and float(min_cost) > 0:
            if spend < float(min_cost):
                return None, f"below_min_cost({spend:.2f}<{float(min_cost):.2f})"

        amount_base = spend / float(last_price)
        amount_base = self._round_amount(symbol, amount_base)

        if not np.isfinite(amount_base) or amount_base <= 0:
            return None, "amount_zero_after_precision"

        if min_amt is not None and np.isfinite(float(min_amt)) and float(min_amt) > 0:
            if amount_base < float(min_amt):
                return None, f"below_min_amount({amount_base}<{float(min_amt)})"

        if min_cost is not None and np.isfinite(float(min_cost)) and float(min_cost) > 0:
            cost_after = float(amount_base) * float(last_price)
            if cost_after < float(min_cost):
                return None, f"below_min_cost_after_round({cost_after:.2f}<{float(min_cost):.2f})"

        return float(amount_base), "ok"

    def _cap_quote_by_live_free(self, requested_quote: float) -> Tuple[float, float, float]:
        """
        Returns (capped_quote, equity_usdt, free_usdt) using LIVE balance refresh.
        In DRY, returns requested.
        """
        if self.dry_run:
            return float(requested_quote), max(250.0, self.usdt_per_trade * 10.0), max(250.0, self.usdt_per_trade * 10.0)

        equity, free = self._fetch_usdt_equity_and_free()
        usable, _ = self._compute_usable_free_usdt(free)

        hard_cap = float(free) * float(self.max_spend_pct_of_free_per_order)
        hard_cap = max(0.0, hard_cap)

        capped = min(float(requested_quote), float(usable), float(hard_cap))
        capped = max(0.0, capped)
        return float(capped), float(equity), float(free)

    def _extract_fill(self, order: dict, fallback_price: float, fallback_amt: float) -> Tuple[float, float]:
        """
        Tries to extract (avg_price, filled_amount_base). Falls back gracefully.
        """
        avg = order.get("average")
        filled = order.get("filled")
        cost = order.get("cost")

        avg_px = float(avg) if avg is not None and np.isfinite(float(avg)) and float(avg) > 0 else float(fallback_price)

        filled_amt = None
        if filled is not None and np.isfinite(float(filled)) and float(filled) > 0:
            filled_amt = float(filled)
        elif cost is not None and np.isfinite(float(cost)) and float(cost) > 0 and avg_px > 0:
            filled_amt = float(cost) / float(avg_px)

        if filled_amt is None:
            filled_amt = float(fallback_amt)

        return float(avg_px), float(filled_amt)

    def _safe_market_buy(self, symbol: str, requested_quote: float, last_price: float, tag: str) -> Tuple[Optional[float], Optional[float], str]:
        """
        Returns (filled_amount_base, avg_price, status)
        """
        attempts = max(1, int(self.buy_retry_attempts))
        scale = float(self.buy_retry_scale)
        scale = max(0.80, min(scale, 0.995))

        q = float(requested_quote)

        for i in range(attempts):
            q_cap, eq, free = self._cap_quote_by_live_free(q)
            if q_cap <= 0:
                return None, None, "no_usable_free"

            amount_base, why = self._prepare_market_buy_amount(symbol, q_cap, last_price)
            if amount_base is None:
                return None, None, why

            if self.use_spread_check_global:
                if not self._spread_ok(symbol, self.max_spread_pct_global):
                    return None, None, "spread_skip"

            if self.dry_run:
                print(f"[DRY] BUY {tag} {symbol}: quote={q_cap:.2f} last~{last_price:.6f} amt={amount_base}")
                return float(amount_base), float(last_price), "dry_ok"

            try:
                order = self.ex.create_market_buy_order(symbol, amount_base)
                avg_px, filled_amt = self._extract_fill(order, fallback_price=last_price, fallback_amt=amount_base)
                print(f"[LIVE] BUY {tag} {symbol} ok: avg={avg_px:.6f} filled={filled_amt} (req_amt={amount_base})")
                return float(filled_amt), float(avg_px), "ok"
            except ccxt.InsufficientFunds as e:
                print(f"[WARN] BUY {tag} {symbol}: InsufficientFunds (try {i+1}/{attempts}) {e}")
            except ccxt.InvalidOrder as e:
                print(f"[WARN] BUY {tag} {symbol}: InvalidOrder (try {i+1}/{attempts}) {e}")
            except ccxt.BaseError as e:
                print(f"[WARN] BUY {tag} {symbol}: CCXT error (try {i+1}/{attempts}) {e}")

            q = q_cap * scale

        return None, None, "buy_failed"

    def _safe_sell(self, symbol: str, amount_base: float, tag: str, reason: str, try_limit_first: bool = False) -> bool:
        """
        Sells amount_base of symbol.
        If try_limit_first=True: places limit sell at best bid, waits up to
        limit_sell_timeout_s for fill, then cancels and falls back to market.
        Otherwise goes straight to market.
        """
        amt = self._round_amount(symbol, float(amount_base))
        if not np.isfinite(amt) or amt <= 0:
            print(f"[SKIP] SELL {tag} {symbol}: bad amount {amount_base}")
            return False

        if self.dry_run:
            mode = "LIMIT→MKT" if try_limit_first else "MKT"
            print(f"[DRY] SELL {tag} {symbol} ({reason}) [{mode}]: amt={amt}")
            return True

        if try_limit_first:
            # Fetch best bid
            best_bid = None
            try:
                ob = self.ex.fetch_order_book(symbol, limit=5)
                bids = ob.get("bids") or []
                if bids:
                    best_bid = float(bids[0][0])
            except Exception as e:
                print(f"[WARN] SELL {tag} {symbol}: order book fetch failed ({e}), going market")

            if best_bid is not None and best_bid > 0:
                limit_px = self._round_price(symbol, best_bid)
                order_id = None
                try:
                    order = self.ex.create_limit_sell_order(symbol, amt, limit_px)
                    order_id = order.get("id")
                    print(f"[LIVE] LIMIT SELL {tag} {symbol} ({reason}): amt={amt} bid={limit_px} id={order_id}")
                except Exception as e:
                    print(f"[WARN] LIMIT SELL {tag} {symbol}: place failed ({e}), going market")

                if order_id is not None:
                    deadline = time.time() + float(self.limit_sell_timeout_s)
                    filled_amt = 0.0
                    while time.time() < deadline:
                        time.sleep(float(self.limit_sell_poll_s))
                        try:
                            o = self.ex.fetch_order(order_id, symbol)
                            status = o.get("status", "")
                            filled_amt = float(o.get("filled") or 0.0)
                            if status == "closed":
                                print(f"[LIVE] LIMIT SELL {tag} {symbol} ({reason}) filled: {filled_amt}")
                                return True
                            if status in ("canceled", "expired", "rejected"):
                                print(f"[WARN] LIMIT SELL {tag} {symbol}: status={status}, going market")
                                break
                        except Exception as e:
                            print(f"[WARN] fetch_order {order_id} failed: {e}")
                            break

                    # Timeout or bad status — cancel order
                    try:
                        self.ex.cancel_order(order_id, symbol)
                        print(f"[LIVE] LIMIT SELL {tag} {symbol}: canceled (timeout), switching to market")
                    except Exception:
                        pass

                    # Handle partial fill: sell only the remaining amount
                    remaining = self._round_amount(symbol, amt - filled_amt)
                    if remaining <= 0:
                        return True
                    amt = remaining

        # Market sell (direct or fallback after limit)
        try:
            order = self.ex.create_market_sell_order(symbol, amt)
            print(f"[LIVE] MARKET SELL {tag} {symbol} ({reason}) ok: {order}")
            return True
        except ccxt.InsufficientFunds as e:
            base_free = self._fetch_base_free(symbol)
            base_free = self._round_amount(symbol, base_free)
            if base_free > 0:
                try:
                    order = self.ex.create_market_sell_order(symbol, base_free)
                    print(f"[LIVE] MARKET SELL {tag} {symbol} ({reason}) fallback base_free={base_free}: {order}")
                    return True
                except Exception as e2:
                    print(f"[ERR] SELL {tag} {symbol} fallback failed: {e2}")
            print(f"[ERR] SELL {tag} {symbol}: InsufficientFunds {e}")
            return False
        except ccxt.BaseError as e:
            print(f"[ERR] SELL {tag} {symbol}: CCXT error {e}")
            return False

    # ---------- DIP sizing ----------
    def _compute_buy_quote_dip(self, equity_usdt: float, free_usdt: float, active_candidates: int) -> float:
        if self.dry_run:
            free_usdt = max(free_usdt, float(self.usdt_per_trade))

        if not self.sizing_cfg.use_dynamic_sizing:
            free_slots = max(self.max_slots - len(self.positions), 1)
            return float(free_usdt) / float(free_slots)

        denom = max(int(active_candidates), 1)
        raw = float(free_usdt) / float(denom)

        cap_equity = float(equity_usdt) * float(self.sizing_cfg.max_pos_pct_of_equity) if equity_usdt > 0 else raw
        cap_free = float(free_usdt) * float(self.sizing_cfg.max_pos_pct_of_free) if free_usdt > 0 else raw
        capped = min(raw, cap_equity, cap_free)

        min_trade = min(float(self.usdt_per_trade), float(free_usdt))
        return max(capped, min_trade)

    # ---------- Momentum sizing ----------
    def _compute_buy_quote_momentum(self, usable_momentum: float) -> float:
        """Gleichmäßige Aufteilung des Momentum-Budgets auf freie Slots."""
        if self.dry_run:
            usable_momentum = max(usable_momentum, float(self.usdt_per_trade))
        free_slots = max(self.max_momentum_slots - len(self.momentum_positions), 1)
        return float(usable_momentum) / float(free_slots)

    # ---------- MADIP BTC filter (v18) ----------
    def _btc_madip_filter_ok(self, btc_ret_15m: float) -> bool:
        """BTC 15min-Return darf nicht < MADIP_BTC_FILTER_THRESH sein.
        Kein BTC-Daten verfügbar → Entry erlaubt (fail-open)."""
        if not np.isfinite(btc_ret_15m):
            return True
        return btc_ret_15m >= MADIP_BTC_FILTER_THRESH

    # ---------- Momentum filter checks ----------
    def _btc_momentum_ok(self, btc_ret_60m: float) -> bool:
        """BTC 60m-Return muss > +MOMENTUM_BTC_THRESHOLD% sein."""
        return bool(np.isfinite(btc_ret_60m) and btc_ret_60m > MOMENTUM_BTC_THRESHOLD)

    def _time_filter_momentum_ok(self, extra_bad_hours: frozenset = frozenset()) -> bool:
        """Blockiert Einträge an schlechten UTC-Wochentagen und -Stunden (global + coin-spezifisch)."""
        now_utc = datetime.datetime.now(datetime.UTC)
        if now_utc.weekday() in MOMENTUM_BAD_WEEKDAYS_UTC:
            return False
        utc_hour = now_utc.hour
        return utc_hour not in MOMENTUM_BAD_HOURS_UTC and utc_hour not in extra_bad_hours

    def _time_filter_dip_ok(self) -> bool:
        """v16: DIP-Entries in Stunde 21 UTC gesperrt (Loss-Rate 38.7% in Backtest)."""
        return datetime.datetime.now(datetime.UTC).hour not in DIP_BAD_HOURS_UTC

    def _time_filter_madip_ok(self) -> bool:
        """v16: MA-DIP-Entries in Stunde 21 UTC gesperrt (Loss-Rate 37.0% in Backtest)."""
        return datetime.datetime.now(datetime.UTC).hour not in MADIP_BAD_HOURS_UTC

    def _register_trade_result(self, is_win: bool) -> None:
        """v17: Verlust-Streak tracken und Cooldown auslösen wenn Streak >= COOLDOWN_STREAK_THRESH."""
        if is_win:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            if self.consecutive_losses >= COOLDOWN_STREAK_THRESH:
                self.cooldown_until = now_ts() + COOLDOWN_HOURS * 3600
                print(
                    f"[COOLDOWN] {self.consecutive_losses} Verluste am Stück → "
                    f"Neue Entries für {COOLDOWN_HOURS}h pausiert bis "
                    f"{time.strftime('%H:%M UTC', time.gmtime(self.cooldown_until))}"
                )
                self.consecutive_losses = 0  # Reset nach Trigger

    def _cooldown_ok(self) -> bool:
        """v17: True wenn kein Cooldown aktiv ist."""
        return now_ts() >= self.cooldown_until

    # ---------- DIP enter/exit ----------
    def _log_trade_dip(self, symbol: str, pos: Position, last_price: float, reason: str, params: StrategyParams, exec_mode: str):
        now = now_ts()
        profit_pct_exit = (last_price / pos.entry_price - 1.0) * 100.0 if pos.entry_price > 0 else float("nan")
        max_profit_pct = (pos.max_price / pos.entry_price - 1.0) * 100.0 if pos.entry_price > 0 else float("nan")

        row = {
            "trade_nr": self.next_trade_nr,
            "strategy": "DIP",
            "symbol": symbol,
            "buy_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(pos.entry_ts)),
            "sell_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "buy_price": pos.entry_price,
            "sell_price": last_price,
            "amount_base": pos.amount_base,
            "invested_usdt": float(pos.amount_base) * float(pos.entry_price),
            "pnl_pct": profit_pct_exit,
            "pnl_usdt": pos.amount_base * (last_price - pos.entry_price),
            "hold_hours": (now - pos.entry_ts) / 3600,
            "exit_reason": reason,
            "exec_mode": exec_mode,

            "drop_trigger_pct": params.drop_trigger_pct,
            "tp_pct": params.tp_pct,
            "max_hold_h": params.max_hold_h,
            "filter_name": params.filter_name,
            "threshold": params.threshold,
            "sl_pct": params.sl_pct if params.sl_pct is not None else "",

            "since_peak_s_at_entry": pos.since_peak_s_at_entry,
            "drop_speed_pct_per_min_at_entry": pos.drop_speed_pct_per_min_at_entry,
            "profit_lock_armed_at_exit": int(bool(pos.profit_lock_armed)),
            "max_profit_pct_during_trade": max_profit_pct,

            "peak_price_at_entry": pos.peak_price_at_entry,
            "drop_pct_at_entry": round((pos.peak_price_at_entry - pos.entry_price) / pos.peak_price_at_entry * 100.0, 4) if pos.peak_price_at_entry > 0 else float("nan"),
            "use_rolling_peak": int(params.use_rolling_peak),
            "use_btc_context_filter": int(params.use_btc_context_filter),
            "min_drop_speed_cfg": params.min_drop_speed_pct_per_min,
            "use_profit_lock_at_entry": pos.use_profit_lock_at_entry,
            "profit_arm_pct_at_entry": pos.profit_arm_pct_at_entry,
            "profit_lock_pct_at_entry": pos.profit_lock_pct_at_entry,
        }
        self._log_trade_common(row, self.trade_log_file)
        self.session_pnl_usdt   += float(row["pnl_usdt"])
        self.session_trades     += 1
        self.session_dip_trades += 1
        self.session_dip_pnl    += float(row["pnl_usdt"])
        if float(row["pnl_usdt"]) > 0:
            self.session_wins     += 1
            self.session_dip_wins += 1
        self._register_trade_result(float(row["pnl_usdt"]) > 0)  # v17: Cooldown-Tracker
        self.pnl_history.append({"t": int(now_ts()), "v": round(self.session_pnl_usdt, 6)})
        if len(self.pnl_history) > 500:
            self.pnl_history = self.pnl_history[-500:]
        print(f"Logged DIP trade #{self.next_trade_nr} for {symbol} to {self.trade_log_file}")
        self.next_trade_nr += 1

    def _enter_position_dip(self, symbol: str, params: StrategyParams, last_price: float,
                            feats: Dict[str, float], since_peak_s: float, drop_speed: float,
                            buy_quote: float, peak_price_override: Optional[float] = None) -> bool:
        with self._position_lock:
            if symbol in self.positions or symbol in self._entering:
                return False
            self._entering.add(symbol)

        try:
            filled_amt, avg_px, status = self._safe_market_buy(symbol, buy_quote, last_price, tag="DIP")
            if filled_amt is None or avg_px is None:
                print(f"[SKIP] BUY DIP {symbol}: {status}")
                return False
        finally:
            with self._position_lock:
                self._entering.discard(symbol)

        peak_price_at_entry = float(
            peak_price_override if peak_price_override is not None
            else self.peaks.get(symbol, last_price)
        )
        peak_ts_at_entry = float(self.peak_ts.get(symbol, now_ts()))
        entry_time = now_ts()

        self.positions[symbol] = Position(
            entry_price=float(avg_px),
            entry_ts=float(entry_time),
            amount_base=float(filled_amt),
            symbol=symbol,
            max_price=float(avg_px),

            peak_price_at_entry=peak_price_at_entry,
            peak_ts_at_entry=peak_ts_at_entry,

            since_peak_s_at_entry=float(since_peak_s),
            drop_speed_pct_per_min_at_entry=float(drop_speed),

            tp_pct_at_entry=float(params.tp_pct),

            use_profit_lock_at_entry=int(bool(params.use_profit_lock)),
            profit_arm_pct_at_entry=float(params.profit_arm_pct),
            profit_lock_pct_at_entry=float(params.profit_lock_pct),
            profit_lock_armed=False,
        )

        self._reset_peak_to_price_now(symbol, float(avg_px))

        print(
            f"[INFO] DIP ENTER {symbol} | quote~{buy_quote:.2f} avg={avg_px:.6f} filled={filled_amt} "
            f"| spd={drop_speed:.5f}%/m {speed_bucket(drop_speed)} | tp={params.tp_pct:.2f}%"
        )
        return True

    def _maybe_exit_dip(self, symbol: str, params: StrategyParams, last_price: float):
        pos = self.positions.get(symbol)
        if not pos:
            return

        profit_pct_now = (float(last_price) / float(pos.entry_price) - 1.0) * 100.0 if pos.entry_price > 0 else float("nan")
        max_profit_pct = (float(pos.max_price) / float(pos.entry_price) - 1.0) * 100.0 if pos.entry_price > 0 else float("nan")

        if last_price > pos.max_price:
            pos.max_price = last_price
            max_profit_pct = (float(pos.max_price) / float(pos.entry_price) - 1.0) * 100.0 if pos.entry_price > 0 else float("nan")

        # arm lock
        if pos.use_profit_lock_at_entry and (not pos.profit_lock_armed):
            if np.isfinite(max_profit_pct) and max_profit_pct >= float(pos.profit_arm_pct_at_entry):
                pos.profit_lock_armed = True

        tp = float(pos.tp_pct_at_entry) / 100.0
        max_hold_seconds = params.max_hold_h * 3600

        hit_tp = float(last_price) >= float(pos.entry_price) * (1.0 + tp)
        hit_ts = (now_ts() - pos.entry_ts) >= max_hold_seconds

        hit_sl = False
        if params.sl_pct is not None:
            sl = params.sl_pct / 100.0
            hit_sl = float(last_price) <= float(pos.entry_price) * (1.0 - sl)

        hit_lock = False
        if pos.use_profit_lock_at_entry and pos.profit_lock_armed:
            floor_pct = float(pos.profit_lock_pct_at_entry)
            if np.isfinite(profit_pct_now) and profit_pct_now <= floor_pct:
                hit_lock = True

        if not (hit_tp or hit_ts or hit_sl or hit_lock):
            return

        if hit_sl:
            reason = "SL"
        elif hit_lock:
            reason = "LOCK"
        elif hit_tp:
            reason = "TP"
        else:
            reason = "TS"

        ok = self._safe_sell(symbol, pos.amount_base, tag="DIP", reason=reason, try_limit_first=(reason == "TP"))
        exec_mode = "MARKET" if ok else "FAILED"

        self._log_trade_dip(symbol, pos, float(last_price), reason, params, exec_mode=exec_mode)
        del self.positions[symbol]
        self._reset_peak_to_price_now(symbol, float(last_price))

    # ---------- Momentum enter/exit ----------
    def _log_trade_momentum(self, symbol: str, pos: MomentumPosition,
                            last_price: float, reason: str, exec_mode: str):
        n = now_ts()
        profit_pct = (last_price / pos.entry_price - 1.0) * 100.0 if pos.entry_price > 0 else float("nan")

        row = {
            "trade_nr":      self.next_trade_nr,
            "strategy":      "MOM",
            "symbol":        symbol,
            "buy_time":      time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(pos.entry_ts)),
            "sell_time":     time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(n)),
            "buy_price":     pos.entry_price,
            "sell_price":    last_price,
            "amount_base":   pos.amount_base,
            "invested_usdt": float(pos.amount_base) * float(pos.entry_price),
            "pnl_pct":       profit_pct,
            "pnl_usdt":      pos.amount_base * (last_price - pos.entry_price),
            "hold_hours":    (n - pos.entry_ts) / 3600,
            "exit_reason":   reason,
            "exec_mode":     exec_mode,
            "lookback_m":    pos.lookback_m,
            "trigger_pct":   pos.trigger_pct,
            "max_hold_m":    pos.max_hold_m,
            "tp_pct":        MOMENTUM_TP_PCT,

            "rise_pct_at_entry":    round(float(pos.rise_pct_at_entry), 4),
            "rolling_min_at_entry": pos.rolling_min_at_entry,
            "btc_ret60_at_entry":   round(float(pos.btc_ret60_at_entry), 4) if np.isfinite(pos.btc_ret60_at_entry) else float("nan"),
            "max_profit_pct_during_trade": round((pos.max_price / pos.entry_price - 1.0) * 100.0, 4) if pos.entry_price > 0 else float("nan"),
            "utc_hour_at_entry":    time.gmtime(pos.entry_ts).tm_hour,
        }
        self._log_trade_common(row, self.momentum_trade_log_file)
        self.session_pnl_usdt   += float(row["pnl_usdt"])
        self.session_trades     += 1
        self.session_mom_trades += 1
        self.session_mom_pnl    += float(row["pnl_usdt"])
        if float(row["pnl_usdt"]) > 0:
            self.session_wins     += 1
            self.session_mom_wins += 1
        self._register_trade_result(float(row["pnl_usdt"]) > 0)  # v17: Cooldown-Tracker
        self.pnl_history.append({"t": int(now_ts()), "v": round(self.session_pnl_usdt, 6)})
        if len(self.pnl_history) > 500:
            self.pnl_history = self.pnl_history[-500:]
        print(f"Logged MOM trade #{self.next_trade_nr} for {symbol} to {self.momentum_trade_log_file}")
        self.next_trade_nr += 1

    def _enter_position_momentum(self, symbol: str, params: MomentumParams,
                                 last_price: float, buy_quote: float,
                                 btc_ret60: float = float("nan"),
                                 rise_pct: float = float("nan"),
                                 roll_min: float = float("nan")) -> bool:
        with self._position_lock:
            if symbol in self.momentum_positions or symbol in self._entering:
                return False
            self._entering.add(symbol)

        try:
            filled_amt, avg_px, status = self._safe_market_buy(symbol, buy_quote, last_price, tag="MOM")
            if filled_amt is None or avg_px is None:
                print(f"[SKIP] BUY MOM {symbol}: {status}")
                return False
        finally:
            with self._position_lock:
                self._entering.discard(symbol)

        entry_time = now_ts()
        tp_abs = float(avg_px) * (1.0 + params.tp_pct / 100.0)
        max_hold_ts = entry_time + params.max_hold_m * 60.0

        self.momentum_positions[symbol] = MomentumPosition(
            entry_price=float(avg_px),
            entry_ts=float(entry_time),
            amount_base=float(filled_amt),
            symbol=symbol,
            tp_abs=tp_abs,
            max_hold_ts=max_hold_ts,
            lookback_m=params.lookback_m,
            trigger_pct=params.trigger_pct,
            max_hold_m=params.max_hold_m,
            max_price=float(avg_px),
            btc_ret60_at_entry=float(btc_ret60),
            rise_pct_at_entry=float(rise_pct),
            rolling_min_at_entry=float(roll_min),
        )

        print(
            f"[INFO] MOM ENTER {symbol} | quote~{buy_quote:.2f} avg={avg_px:.6f} filled={filled_amt} "
            f"| lb={params.lookback_m}m trig={params.trigger_pct:.1f}% tp={params.tp_pct:.1f}% "
            f"| max_hold={params.max_hold_m}m"
        )
        return True

    def _maybe_exit_momentum(self, symbol: str, last_price: float):
        pos = self.momentum_positions.get(symbol)
        if not pos:
            return

        # max_price für Trade-Log aktualisieren
        if float(last_price) > pos.max_price:
            pos.max_price = float(last_price)

        hit_tp = float(last_price) >= pos.tp_abs
        hit_ts = now_ts() >= pos.max_hold_ts

        if not (hit_tp or hit_ts):
            return

        reason = "TP" if hit_tp else "TS"
        ok = self._safe_sell(symbol, pos.amount_base, tag="MOM", reason=reason,
                             try_limit_first=(reason == "TP"))
        exec_mode = "MARKET" if ok else "FAILED"

        self._log_trade_momentum(symbol, pos, float(last_price), reason, exec_mode)
        del self.momentum_positions[symbol]

        # v13: Time-Stop → globale MOM-Pause aktivieren
        if reason == "TS":
            self.mom_loss_pause_until = now_ts() + MOMENTUM_LOSS_PAUSE_MIN * 60
            print(f"[MOM-PAUSE] Time-Stop auf {symbol} → "
                  f"neue MOM-Entries pausiert für {MOMENTUM_LOSS_PAUSE_MIN} Min.")

    # ---------- MA-DIP sizing ----------
    def _compute_buy_quote_madip(self, usable_madip: float) -> float:
        """Gleichmäßige Aufteilung des MA-DIP-Budgets auf freie Slots."""
        if self.dry_run:
            usable_madip = max(usable_madip, float(self.usdt_per_trade))
        free_slots = max(self.max_madip_slots - len(self.madip_positions), 1)
        return float(usable_madip) / float(free_slots)

    # ---------- MA-DIP enter/exit ----------
    def _log_trade_madip(self, symbol: str, pos: MaDipPosition,
                         last_price: float, reason: str, exec_mode: str):
        n = now_ts()
        profit_pct = (last_price / pos.entry_price - 1.0) * 100.0 if pos.entry_price > 0 else float("nan")
        row = {
            "trade_nr":        self.next_trade_nr,
            "strategy":        "MADIP",
            "symbol":          symbol,
            "buy_time":        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(pos.entry_ts)),
            "sell_time":       time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(n)),
            "buy_price":       pos.entry_price,
            "sell_price":      last_price,
            "amount_base":     pos.amount_base,
            "invested_usdt":   float(pos.amount_base) * float(pos.entry_price),
            "pnl_pct":         profit_pct,
            "pnl_usdt":        pos.amount_base * (last_price - pos.entry_price),
            "hold_hours":      (n - pos.entry_ts) / 3600,
            "exit_reason":     reason,
            "exec_mode":       exec_mode,
            "ma_bars":         MADIP_MA_BARS,
            "drop_pct_cfg":    MADIP_DROP_PCT,
            "tp_pct":          MADIP_TP_PCT,
            "max_hold_m":      MADIP_MAX_HOLD_M,
            "ma_at_entry":     pos.ma_at_entry,
            "drop_pct_at_entry": pos.drop_pct_at_entry,
            "max_profit_pct":  round((pos.max_price / pos.entry_price - 1.0) * 100.0, 4) if pos.entry_price > 0 else float("nan"),
            "utc_hour_at_entry": time.gmtime(pos.entry_ts).tm_hour,
        }
        self._log_trade_common(row, self.madip_trade_log_file)
        self.session_pnl_usdt     += float(row["pnl_usdt"])
        self.session_trades       += 1
        self.session_madip_trades += 1
        self.session_madip_pnl    += float(row["pnl_usdt"])
        if float(row["pnl_usdt"]) > 0:
            self.session_wins       += 1
            self.session_madip_wins += 1
        self._register_trade_result(float(row["pnl_usdt"]) > 0)  # v17: Cooldown-Tracker
        self.pnl_history.append({"t": int(now_ts()), "v": round(self.session_pnl_usdt, 6)})
        if len(self.pnl_history) > 500:
            self.pnl_history = self.pnl_history[-500:]
        print(f"Logged MADIP trade #{self.next_trade_nr} for {symbol} to {self.madip_trade_log_file}")
        self.next_trade_nr += 1

    def _enter_position_madip(self, symbol: str, params: MaDipParams,
                               last_price: float, buy_quote: float,
                               ma_val: float, drop_pct: float) -> bool:
        with self._position_lock:
            if symbol in self.madip_positions or symbol in self._entering:
                return False
            self._entering.add(symbol)

        try:
            filled_amt, avg_px, status = self._safe_market_buy(symbol, buy_quote, last_price, tag="MADIP")
            if filled_amt is None or avg_px is None:
                print(f"[SKIP] BUY MADIP {symbol}: {status}")
                return False
        finally:
            with self._position_lock:
                self._entering.discard(symbol)
        entry_time  = now_ts()
        tp_abs      = float(avg_px) * (1.0 + params.tp_pct / 100.0)
        max_hold_ts = entry_time + params.max_hold_m * 60.0
        self.madip_positions[symbol] = MaDipPosition(
            entry_price=float(avg_px),
            entry_ts=float(entry_time),
            amount_base=float(filled_amt),
            symbol=symbol,
            tp_abs=tp_abs,
            max_hold_ts=max_hold_ts,
            ma_at_entry=float(ma_val),
            drop_pct_at_entry=float(drop_pct),
            max_price=float(avg_px),
        )
        print(
            f"[INFO] MADIP ENTER {symbol} | quote~{buy_quote:.2f} avg={avg_px:.6f} filled={filled_amt} "
            f"| ma={ma_val:.6f} drop={drop_pct:.2f}% tp={params.tp_pct:.1f}% max_hold={params.max_hold_m}m"
        )
        return True

    def _maybe_exit_madip(self, symbol: str, last_price: float):
        pos = self.madip_positions.get(symbol)
        if not pos:
            return
        if float(last_price) > pos.max_price:
            pos.max_price = float(last_price)
        hit_tp = float(last_price) >= pos.tp_abs
        hit_ts = now_ts() >= pos.max_hold_ts
        if not (hit_tp or hit_ts):
            return
        reason = "TP" if hit_tp else "TS"
        ok = self._safe_sell(symbol, pos.amount_base, tag="MADIP", reason=reason,
                             try_limit_first=(reason == "TP"))
        exec_mode = "MARKET" if ok else "FAILED"
        self._log_trade_madip(symbol, pos, float(last_price), reason, exec_mode)
        del self.madip_positions[symbol]

    # ---------- dashboard ----------
    def _print_dashboard(self, snapshot_rows, open_pos_rows, momentum_pos_rows,
                         madip_pos_rows,
                         mom_snapshot_rows,
                         equity_usdt, free_usdt, usable_free, reserve_usdt,
                         active_candidates: int, btc_ret_60m: float,
                         btc_mom_ok: bool, time_ok: bool,
                         btc_ret_15m: float = float("nan")):
        print("\033[2J\033[H", end="")
        print("=== MEXC Dip Bot v20 — DIP + Momentum + MA-DIP ===")

        btc_str = f"{btc_ret_60m:+.2f}%" if np.isfinite(btc_ret_60m) else "n/a"
        dip_btc_flag  = ""  # v20: btc_ctx-Filter deaktiviert
        mom_btc_flag  = " [MOM✓]"  if btc_mom_ok else ""
        time_flag     = " [TIME✓]" if time_ok else " [TIME✗]"
        btc15_str     = f"{btc_ret_15m:+.2f}%" if np.isfinite(btc_ret_15m) else "n/a"
        madip_btc_flag = " [MADIP✗ BTC-BLOCK]" if (np.isfinite(btc_ret_15m) and btc_ret_15m < MADIP_BTC_FILTER_THRESH) else ""
        pause_remain  = max(0.0, self.mom_loss_pause_until - now_ts())
        pause_flag    = f" [PAUSE {pause_remain/60:.0f}m]" if pause_remain > 0 else ""
        utc_h = datetime.datetime.now(datetime.UTC).hour

        # Session-PnL berechnen
        session_age_h = (now_ts() - self.session_start_ts) / 3600.0
        session_pnl_pct = (
            (self.session_pnl_usdt / self.session_start_equity * 100.0)
            if self.session_start_equity > 0 else 0.0
        )
        wr_str = (
            f"{self.session_wins}/{self.session_trades} "
            f"({self.session_wins/self.session_trades*100:.0f}%)"
            if self.session_trades > 0 else "0/0"
        )
        pnl_sign = "+" if self.session_pnl_usdt >= 0 else ""

        print(
            f"DIP: {len(self.positions)}/{self.max_slots} | "
            f"MOM: {len(self.momentum_positions)}/{self.max_momentum_slots} | "
            f"MADIP: {len(self.madip_positions)}/{self.max_madip_slots} | "
            f"BTC60m: {btc_str}{dip_btc_flag}{mom_btc_flag} | "
            f"BTC15m: {btc15_str}{madip_btc_flag} | "
            f"UTC:{utc_h:02d}h{time_flag}{pause_flag} | "
            f"DIP-cands: {active_candidates} | "
            f"Equity: {equity_usdt:,.2f} | Free: {free_usdt:,.2f} | "
            f"Usable: {usable_free:,.2f} | "
            f"DIP-cap: {usable_free*self.dip_capital_split:,.2f} "
            f"MOM-cap: {usable_free*self.momentum_capital_split:,.2f} "
            f"MADIP-cap: {usable_free*self.madip_capital_split:,.2f} | "
            f"{time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        print(
            f"Session ({session_age_h:.1f}h) | "
            f"PnL: {pnl_sign}{self.session_pnl_usdt:.4f} USDT  "
            f"({pnl_sign}{session_pnl_pct:.3f}%) | "
            f"Trades: {wr_str} W/L"
        )
        print()

        print("DIP: Top 10 closest-to-entry (not in position):")
        if snapshot_rows:
            headers = ["#", "sym", "last", "peak", "age", "dr%", "tr%", "rt", "spd", "bin", "S", "f", "thr", "F", "tp", "L", "pk", "B"]
            print(self._render_table(headers=headers, rows=snapshot_rows, max_col_width=self.dash_cfg.max_col_width))
        else:
            print("(no data)")
        print()

        print("DIP: Open positions:")
        if open_pos_rows:
            headers = ["sym", "entry", "last", "max", "pnl%", "ageh", "tp", "A", "floor", "pNow", "pMax", "spd", "x"]
            print(self._render_table(headers=headers, rows=open_pos_rows, max_col_width=self.dash_cfg.max_col_width))
        else:
            print("(none)")
        print()

        print("MOM: Open positions:")
        if momentum_pos_rows:
            headers = ["sym", "entry", "last", "tp_abs", "pnl%", "ageh", "mh_rem"]
            print(self._render_table(headers=headers, rows=momentum_pos_rows, max_col_width=self.dash_cfg.max_col_width))
        else:
            print("(none)")
        print()

        print("MA-DIP: Open positions:")
        if madip_pos_rows:
            headers = ["sym", "entry", "last", "tp_abs", "pnl%", "ageh", "mh_rem", "ma", "drop%"]
            print(self._render_table(headers=headers, rows=madip_pos_rows, max_col_width=self.dash_cfg.max_col_width))
        else:
            print("(none)")
        print()

        print("MOM: Top 10 closest-to-entry (not in position):")
        if mom_snapshot_rows:
            headers = ["#", "sym", "last", "roll_min", "rise%", "trig%", "dist%", "lb", "mh", "BTC", "TIME"]
            print(self._render_table(headers=headers, rows=mom_snapshot_rows, max_col_width=self.dash_cfg.max_col_width))
        else:
            print("(no data)")
        print()

    # ---------- dashboard json ----------
    def _write_dashboard_json(self, equity_usdt, free_usdt, usable_free, reserve_usdt,
                              btc_ret_60m, btc_mom_ok, time_ok, active_candidates,
                              candidates_sorted, scan, mom_scan_sorted, last_prices,
                              madip_scan=None, btc_ret_15m: float = float("nan")):
        now = now_ts()
        utc_h = datetime.datetime.now(datetime.UTC).hour
        session_age_h = (now - self.session_start_ts) / 3600.0
        session_pnl_pct = (self.session_pnl_usdt / self.session_start_equity * 100.0
                           if self.session_start_equity > 0 else 0.0)

        # DIP Kandidaten Top-10
        dip_cands = []
        count = 0
        for _, __, symbol in candidates_sorted:
            if count >= 10:
                break
            if symbol in self.positions:
                continue
            m = scan.get(symbol)
            if not m:
                continue
            params = self.strategies[symbol]
            dip_cands.append({
                "sym":         symbol.replace("/USDT", ""),
                "last":        round(float(m["last"]), 8),
                "peak":        round(float(m["peak"]), 8),
                "drop_pct":    round(float(m["drop_frac"]) * 100, 4),
                "trigger_pct": round(float(m["trigger"]) * 100, 4),
                "ratio":       round(float(m["ratio"]), 4),
                "filter_ok":   bool(m["filter_ok"]),
                "spd_ok":      bool(m["spd_ok"]),
                "btc_ok":      bool(m["btc_ctx_ok"]),
                "filter_name": params.filter_name,
                "tp_pct":      float(params.tp_pct),
            })
            count += 1

        # MOM Kandidaten Top-10
        mom_cands = []
        for symbol, mdata in mom_scan_sorted[:10]:
            mom_cands.append({
                "sym":         symbol.replace("/USDT", ""),
                "last":        round(float(mdata["last"]), 8),
                "roll_min":    round(float(mdata["roll_min"]), 8),
                "rise_pct":    round(mdata["rise"] * 100, 4),
                "trigger_pct": round(mdata["trig"] * 100, 4),
                "dist_pct":    round(mdata["dist_to_trig"] * 100, 4),
                "triggered":   bool(mdata["triggered"]),
                "lb":          int(mdata["lb"]),
                "mh":          int(mdata["mh"]),
            })

        # MA-DIP Kandidaten Top-10
        madip_cands = []
        if madip_scan:
            madip_sorted_cands = sorted(
                madip_scan.items(), key=lambda kv: -kv[1]["drop_pct"]
            )[:10]
            for symbol, mdata in madip_sorted_cands:
                madip_cands.append({
                    "sym":        symbol.replace("/USDT", ""),
                    "last":       round(float(mdata["last"]), 8),
                    "ma":         round(float(mdata["ma"]), 8),
                    "threshold":  round(float(mdata["threshold"]), 8),
                    "drop_pct":   round(float(mdata["drop_pct"]), 4),
                    "triggered":  bool(mdata["triggered"]),
                    "btc_ok":     bool(mdata.get("btc_ok", True)),
                })

        # Offene DIP-Positionen
        dip_pos = []
        for symbol, pos in self.positions.items():
            last = float(last_prices.get(symbol, pos.entry_price))
            pnl_pct = (last / pos.entry_price - 1.0) * 100.0 if pos.entry_price else 0.0
            age_h   = (now - pos.entry_ts) / 3600.0
            params  = self.strategies[symbol]
            tp_prog = min(max(pnl_pct / pos.tp_pct_at_entry * 100, 0), 100) if pos.tp_pct_at_entry else 0
            dip_pos.append({
                "sym":        symbol.replace("/USDT", ""),
                "entry":      round(float(pos.entry_price), 8),
                "last":       round(last, 8),
                "pnl_pct":    round(pnl_pct, 4),
                "age_h":      round(age_h, 3),
                "tp_pct":     float(pos.tp_pct_at_entry),
                "tp_progress": round(tp_prog, 1),
                "max_hold_h": params.max_hold_h,
            })

        # Offene MOM-Positionen
        mom_pos = []
        for symbol, mpos in self.momentum_positions.items():
            last      = float(last_prices.get(symbol, mpos.entry_price))
            pnl_pct   = (last / mpos.entry_price - 1.0) * 100.0 if mpos.entry_price else 0.0
            age_h     = (now - mpos.entry_ts) / 3600.0
            mh_rem_m  = max((mpos.max_hold_ts - now) / 60.0, 0.0)
            mh_total  = float(mpos.max_hold_m)
            mh_prog   = max(0, 100 - mh_rem_m / mh_total * 100) if mh_total > 0 else 0
            mom_pos.append({
                "sym":        symbol.replace("/USDT", ""),
                "entry":      round(float(mpos.entry_price), 8),
                "last":       round(last, 8),
                "tp_abs":     round(float(mpos.tp_abs), 8),
                "pnl_pct":    round(pnl_pct, 4),
                "age_h":      round(age_h, 3),
                "mh_rem_m":   round(mh_rem_m, 1),
                "mh_total_m": int(mh_total),
                "mh_progress": round(mh_prog, 1),
            })

        # Offene MA-DIP Positionen
        madip_pos_j = []
        for symbol, mpos in self.madip_positions.items():
            last      = float(last_prices.get(symbol, mpos.entry_price))
            pnl_pct   = (last / mpos.entry_price - 1.0) * 100.0 if mpos.entry_price else 0.0
            age_h     = (now - mpos.entry_ts) / 3600.0
            mh_rem_m  = max((mpos.max_hold_ts - now) / 60.0, 0.0)
            mh_total  = float(MADIP_MAX_HOLD_M)
            mh_prog   = max(0, 100 - mh_rem_m / mh_total * 100) if mh_total > 0 else 0
            madip_pos_j.append({
                "sym":         symbol.replace("/USDT", ""),
                "entry":       round(float(mpos.entry_price), 8),
                "last":        round(last, 8),
                "tp_abs":      round(float(mpos.tp_abs), 8),
                "pnl_pct":     round(pnl_pct, 4),
                "age_h":       round(age_h, 3),
                "mh_rem_m":    round(mh_rem_m, 1),
                "mh_total_m":  int(mh_total),
                "mh_progress": round(mh_prog, 1),
            })

        # Letzte 10 Trades aus allen CSV-Logs
        recent: List[Dict] = []
        for fpath, strat in [(self.trade_log_file, "DIP"), (self.momentum_trade_log_file, "MOM"), (self.madip_trade_log_file, "MADIP")]:
            if os.path.exists(fpath):
                try:
                    df = pd.read_csv(fpath)
                    if not df.empty:
                        for _, r in df.tail(5).iterrows():
                            recent.append({
                                "nr":       int(r["trade_nr"]),
                                "strategy": strat,
                                "sym":      str(r["symbol"]).replace("/USDT", ""),
                                "pnl_pct":  round(float(r["pnl_pct"]), 4),
                                "pnl_usdt": round(float(r["pnl_usdt"]), 4),
                                "hold_min": round(float(r["hold_hours"]) * 60, 1),
                                "exit":     str(r["exit_reason"]),
                                "time":     str(r["sell_time"]),
                            })
                except Exception:
                    pass
        recent.sort(key=lambda x: x["nr"], reverse=True)
        recent = recent[:10]

        data = {
            "ts":          time.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "ts_epoch":    int(now),
            "bot_version": "v24",
            "dry_run":     self.dry_run,
            "session": {
                "age_h":        round(session_age_h, 2),
                "pnl_usdt":     round(self.session_pnl_usdt, 6),
                "pnl_pct":      round(session_pnl_pct, 4),
                "trades":       self.session_trades,
                "wins":         self.session_wins,
                "wr_pct":       round(self.session_wins / self.session_trades * 100, 1)
                                if self.session_trades > 0 else 0.0,
                "start_equity": round(self.session_start_equity, 2),
            },
            "balance": {
                "equity_usdt":      round(float(equity_usdt), 2),
                "free_usdt":        round(float(free_usdt), 2),
                "usable_free":      round(float(usable_free), 2),
                "usable_dip":       round(float(usable_free) * float(self.dip_capital_split), 2),
                "usable_momentum":  round(float(usable_free) * float(self.momentum_capital_split), 2),
                "usable_madip":     round(float(usable_free) * float(self.madip_capital_split), 2),
                "reserve_usdt":     round(float(reserve_usdt), 2),
            },
            "btc": {
                "ret_60m":   round(float(btc_ret_60m), 4) if np.isfinite(btc_ret_60m) else None,
                "ret_15m":   round(float(btc_ret_15m), 4) if np.isfinite(btc_ret_15m) else None,
                "mom_ok":    bool(btc_mom_ok),
                "dip_ok":    True,  # v20: btc_ctx-Filter deaktiviert
                "madip_ok":  bool(not np.isfinite(btc_ret_15m) or btc_ret_15m >= MADIP_BTC_FILTER_THRESH),
            },
            "filters": {
                "time_ok":  bool(time_ok),
                "utc_hour": utc_h,
            },
            "cooldown": {
                "active":             now_ts() < self.cooldown_until,
                "remain_min":         round(max(0.0, self.cooldown_until - now_ts()) / 60.0, 1),
                "until_utc":          time.strftime("%H:%M UTC", time.gmtime(self.cooldown_until))
                                      if now_ts() < self.cooldown_until else None,
                "consecutive_losses": self.consecutive_losses,
                "streak_thresh":      COOLDOWN_STREAK_THRESH,
                "cooldown_hours":     COOLDOWN_HOURS,
            },
            "dip": {
                "slots":             len(self.positions),
                "max_slots":         self.max_slots,
                "active_candidates": active_candidates,
                "candidates":        dip_cands,
                "positions":         dip_pos,
                "session_trades":    self.session_dip_trades,
                "session_wins":      self.session_dip_wins,
                "session_pnl":       round(self.session_dip_pnl, 6),
            },
            "momentum": {
                "slots":          len(self.momentum_positions),
                "max_slots":      self.max_momentum_slots,
                "candidates":     mom_cands,
                "positions":      mom_pos,
                "session_trades": self.session_mom_trades,
                "session_wins":   self.session_mom_wins,
                "session_pnl":    round(self.session_mom_pnl, 6),
            },
            "madip": {
                "slots":          len(self.madip_positions),
                "max_slots":      self.max_madip_slots,
                "candidates":     madip_cands,
                "positions":      madip_pos_j,
                "btc_filter_ok":  bool(not np.isfinite(btc_ret_15m) or btc_ret_15m >= MADIP_BTC_FILTER_THRESH),
                "btc_ret_15m":    round(float(btc_ret_15m), 4) if np.isfinite(btc_ret_15m) else None,
                "session_trades": self.session_madip_trades,
                "session_wins":   self.session_madip_wins,
                "session_pnl":    round(self.session_madip_pnl, 6),
            },
            "recent_trades": recent,
            "pnl_history":   self.pnl_history,
        }

        try:
            with open(DASHBOARD_JSON, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            print(f"[DASH] JSON write error: {e}")

    # ---------- main loop ----------
    def run_forever(self, timeframe: str, ohlcv_limit: int, poll_seconds: int):
        print(
            f"Running Dip Bot v24 | DRY_RUN={self.dry_run} | "
            f"BAL_USE_PCT={self.balance_use_pct} | "
            f"DIP_SPLIT={self.dip_capital_split} MOM_SPLIT={self.momentum_capital_split} MADIP_SPLIT={self.madip_capital_split} | "
            f"MAX_DIP_SLOTS={self.max_slots} MAX_MOM_SLOTS={self.max_momentum_slots} MAX_MADIP_SLOTS={self.max_madip_slots} | "
            f"DIP_COINS={len(self.strategies)} MOM_COINS={len(self.momentum_configs)} MADIP_COINS={len(self.madip_configs)} | "
            f"MIN_RES={self.min_free_reserve_usdt} FEE_BUF={self.fee_buffer_pct}% "
            f"BUY_RETRY={self.buy_retry_attempts}x scale={self.buy_retry_scale} "
            f"MAX_ONE_BUY_PER_LOOP={self.max_one_buy_per_loop}"
        )

        while True:
            now = now_ts()
            did_buy_this_loop = False

            # ─────────────────────────────────────────
            # 1. Balance
            # ─────────────────────────────────────────
            if not self.dry_run:
                try:
                    equity_usdt, free_usdt = self._fetch_usdt_equity_and_free()
                except Exception as e:
                    print(f"[BAL] error: {e}")
                    equity_usdt, free_usdt = 0.0, 0.0
            else:
                equity_usdt = max(float(self.usdt_per_trade) * 10.0, 250.0)
                free_usdt = equity_usdt

            # Ersten Equity-Wert als Session-Startpunkt merken
            if self.session_start_equity == 0.0 and equity_usdt > 0.0:
                self.session_start_equity = equity_usdt

            usable_free, reserve_usdt = self._compute_usable_free_usdt(float(free_usdt))
            usable_dip       = usable_free * float(self.dip_capital_split)
            usable_momentum  = usable_free * float(self.momentum_capital_split)
            usable_madip     = usable_free * float(self.madip_capital_split)

            # ─────────────────────────────────────────
            # 2. BTC Returns (60m für DIP/MOM-Filter; 15m für MADIP-Filter v18)
            # ─────────────────────────────────────────
            btc_ret_60m: float = float('nan')
            btc_ret_15m: float = float('nan')
            try:
                _btc_c, _ = self.fetch_closes(
                    'BTC/USDT', timeframe=timeframe,
                    limit=max(ohlcv_limit, 65)
                )
                if len(_btc_c) >= 61:
                    btc_ret_60m = (float(_btc_c[-1]) / float(_btc_c[-61]) - 1.0) * 100.0
                if len(_btc_c) >= MADIP_BTC_LOOKBACK_MIN + 1:
                    btc_ret_15m = (float(_btc_c[-1]) / float(_btc_c[-(MADIP_BTC_LOOKBACK_MIN + 1)]) - 1.0) * 100.0
            except Exception as _e:
                print(f"[BTC] Fehler beim Abrufen: {_e}")

            # ─────────────────────────────────────────
            # 3. DIP scan
            # ─────────────────────────────────────────
            scan: Dict[str, Dict[str, Any]] = {}
            last_prices: Dict[str, float] = {}

            for symbol, params in self.strategies.items():
                try:
                    closes, last = self.fetch_closes(symbol, timeframe=timeframe, limit=ohlcv_limit)
                    last_prices[symbol] = last
                    feats = compute_features_from_closes(closes)

                    if params.use_rolling_peak and len(closes) >= params.rolling_peak_lookback_bars:
                        if symbol in self.positions:
                            pos = self.positions[symbol]
                            if last > pos.max_price:
                                pos.max_price = last
                        window = closes[-params.rolling_peak_lookback_bars:]
                        peak_idx = int(np.argmax(window))
                        peak = float(window[peak_idx])
                        since_peak_s = (len(window) - 1 - peak_idx) * 60.0
                    else:
                        if symbol not in self.positions:
                            self._update_peak_if_new_high(symbol, last)
                        else:
                            pos = self.positions[symbol]
                            if last > pos.max_price:
                                pos.max_price = last
                        peak = self.peaks.get(symbol, last)
                        peak_time = self.peak_ts.get(symbol, now)
                        since_peak_s = max(now - peak_time, 0.0)

                    drop_frac = (peak - last) / peak if peak and peak > 0 else 0.0
                    trigger = params.drop_trigger_pct / 100.0 if params.drop_trigger_pct else 0.0
                    ratio = (drop_frac / trigger) if trigger > 0 else 0.0
                    dist = max(trigger - drop_frac, 0.0) if trigger > 0 else float("inf")

                    drop_spd = compute_drop_speed_pct_per_min(drop_frac, max(since_peak_s, 1e-9))
                    spd_bin = speed_bucket(drop_spd)
                    spd_ok = True
                    if params.use_drop_speed_filter:
                        spd_ok = bool(np.isfinite(drop_spd) and (drop_spd >= float(params.min_drop_speed_pct_per_min)))

                    filter_ok = filter_passes(params.filter_name, params.threshold, feats) if feats.get("valid", False) else False

                    # BTC-Kontext-Filter (DIP: BTC muss gefallen sein)
                    btc_ctx_ok = True  # v20: btc_ctx-Filter deaktiviert (alle Zonen profitabel)

                    scan[symbol] = {
                        "last": last,
                        "feats": feats,
                        "peak": peak,
                        "since_peak_s": since_peak_s,
                        "drop_frac": drop_frac,
                        "trigger": trigger,
                        "ratio": ratio,
                        "dist": dist,
                        "drop_spd": drop_spd,
                        "spd_bin": spd_bin,
                        "spd_ok": spd_ok,
                        "filter_ok": filter_ok,
                        "btc_ctx_ok": btc_ctx_ok,
                    }

                except ccxt.BaseError as e:
                    print(f"[{symbol}] CCXT error: {e}")
                except Exception as e:
                    print(f"[{symbol}] Error: {e}")

            # ─────────────────────────────────────────
            # 4. DIP exits
            # ─────────────────────────────────────────
            for symbol, pos in list(self.positions.items()):
                last = float(last_prices.get(symbol, pos.entry_price))
                params = self.strategies.get(symbol)
                if params:
                    self._maybe_exit_dip(symbol, params, last)

            # ─────────────────────────────────────────
            # 5. DIP active candidates count
            # ─────────────────────────────────────────
            active_candidates = 0
            for symbol, params in self.strategies.items():
                if symbol in self.positions or symbol in self.madip_positions:
                    continue
                m = scan.get(symbol)
                if not m:
                    continue
                if float(m["ratio"]) < float(self.sizing_cfg.candidate_ratio_min):
                    continue
                if self.sizing_cfg.candidate_require_filter_ok and not bool(m["filter_ok"]):
                    continue
                if self.sizing_cfg.candidate_require_speed_ok and params.use_drop_speed_filter and not bool(m["spd_ok"]):
                    continue
                active_candidates += 1

            # ─────────────────────────────────────────
            # 6. DIP entries (sorted by proximity to trigger)
            # ─────────────────────────────────────────
            candidates_sorted: List[Tuple[float, float, str]] = []
            for symbol, m in scan.items():
                if symbol in self.positions or symbol in self.madip_positions:
                    continue
                candidates_sorted.append((float(m["dist"]), -float(m["ratio"]), symbol))
            candidates_sorted.sort(key=lambda x: (x[0], x[1], x[2]))

            free_work_dip = float(usable_dip)

            for _, __, symbol in candidates_sorted:
                if len(self.positions) >= self.max_slots:
                    break
                if self.max_one_buy_per_loop and did_buy_this_loop:
                    break

                params = self.strategies[symbol]
                m = scan.get(symbol)
                if not m:
                    continue
                if float(m["drop_frac"]) < float(m["trigger"]):
                    continue
                if params.use_drop_speed_filter and not bool(m["spd_ok"]):
                    continue
                if not bool(m["filter_ok"]):
                    continue
                if not bool(m["btc_ctx_ok"]):
                    continue
                if not self._time_filter_dip_ok():   # v16: Stunde 21 UTC gesperrt
                    continue
                if not self._cooldown_ok():          # v17: Portfolio-Cooldown
                    continue

                buy_quote = self._compute_buy_quote_dip(equity_usdt, free_work_dip, active_candidates)
                buy_quote = min(float(buy_quote), float(free_work_dip))
                if buy_quote < float(self.sizing_cfg.min_usdt_per_trade):
                    continue

                ok = self._enter_position_dip(
                    symbol=symbol,
                    params=params,
                    last_price=float(m["last"]),
                    feats=m["feats"],
                    since_peak_s=float(m["since_peak_s"]),
                    drop_speed=float(m["drop_spd"]),
                    buy_quote=float(buy_quote),
                    peak_price_override=float(m["peak"]),
                )
                if ok:
                    did_buy_this_loop = True
                    free_work_dip = max(float(free_work_dip) - float(buy_quote), 0.0)
                    active_candidates = max(int(active_candidates) - 1, 1)

            # ─────────────────────────────────────────
            # 7. Momentum exits
            # ─────────────────────────────────────────
            for symbol in list(self.momentum_positions.keys()):
                # Verwende letzte bekannte Preis aus DIP-Scan, sonst neu holen
                last = float(last_prices.get(symbol, 0.0))
                if last <= 0:
                    try:
                        _, last = self.fetch_closes(symbol, timeframe=timeframe, limit=5)
                        last_prices[symbol] = last
                    except Exception as e:
                        print(f"[MOM-EXIT] {symbol}: Fehler beim Preis-Abruf: {e}")
                        continue
                self._maybe_exit_momentum(symbol, last)

            # ─────────────────────────────────────────
            # 7b. MA-DIP exits
            # ─────────────────────────────────────────
            for symbol in list(self.madip_positions.keys()):
                last = float(last_prices.get(symbol, 0.0))
                if last <= 0:
                    try:
                        _, last = self.fetch_closes(symbol, timeframe=timeframe, limit=5)
                        last_prices[symbol] = last
                    except Exception as e:
                        print(f"[MADIP-EXIT] {symbol}: Fehler beim Preis-Abruf: {e}")
                        continue
                self._maybe_exit_madip(symbol, last)

            # ─────────────────────────────────────────
            # 8. Momentum scan (immer alle Coins) + entries
            # ─────────────────────────────────────────
            btc_ok_for_mom  = self._btc_momentum_ok(btc_ret_60m)
            time_ok_for_mom = self._time_filter_momentum_ok()

            # Immer scannen — für Dashboard Top-10
            mom_scan: Dict[str, Dict[str, Any]] = {}

            for symbol, mcfg in self.momentum_configs.items():
                if symbol in self.momentum_positions or symbol in self.madip_positions:
                    continue
                try:
                    closes, last = self.fetch_closes(
                        symbol, timeframe=timeframe,
                        limit=self.momentum_ohlcv_limit
                    )
                    last_prices[symbol] = last
                except Exception as e:
                    print(f"[MOM-SCAN] {symbol}: Fehler: {e}")
                    continue

                lb = mcfg.lookback_m
                if len(closes) < lb + 2:
                    continue

                roll_min = float(np.min(closes[-lb - 1: -1]))
                if not np.isfinite(roll_min) or roll_min <= 0:
                    continue

                current_close = float(closes[-1])
                rise = (current_close / roll_min) - 1.0
                trig = mcfg.trigger_pct / 100.0
                dist_to_trig = trig - rise   # negativ = bereits getriggert

                mom_scan[symbol] = {
                    "last":         current_close,
                    "roll_min":     roll_min,
                    "rise":         rise,
                    "trig":         trig,
                    "dist_to_trig": dist_to_trig,
                    "lb":           lb,
                    "mh":           mcfg.max_hold_m,
                    "triggered":    rise >= trig,
                }

            # Entries nur wenn Filter ok (inkl. Loss-Pause v13)
            mom_loss_paused = now_ts() < self.mom_loss_pause_until
            if btc_ok_for_mom and time_ok_for_mom and not mom_loss_paused and self._cooldown_ok():
                free_work_momentum = float(usable_momentum)

                # Sortiert nach Nähe zum Trigger (bereits getriggerte zuerst)
                mom_sorted = sorted(
                    mom_scan.items(),
                    key=lambda kv: kv[1]["dist_to_trig"]
                )

                for symbol, mdata in mom_sorted:
                    if len(self.momentum_positions) >= self.max_momentum_slots:
                        break
                    if self.max_one_buy_per_loop and did_buy_this_loop:
                        break
                    if not mdata["triggered"]:
                        continue
                    # v10: per-coin extra bad hours filter
                    mcfg = self.momentum_configs[symbol]
                    if mcfg.extra_bad_hours and not self._time_filter_momentum_ok(mcfg.extra_bad_hours):
                        continue

                    buy_quote = self._compute_buy_quote_momentum(free_work_momentum)
                    buy_quote = min(float(buy_quote), float(free_work_momentum))
                    if buy_quote < float(self.sizing_cfg.min_usdt_per_trade):
                        continue

                    ok = self._enter_position_momentum(
                        symbol=symbol,
                        params=self.momentum_configs[symbol],
                        last_price=mdata["last"],
                        buy_quote=float(buy_quote),
                        btc_ret60=btc_ret_60m,
                        rise_pct=mdata["rise"] * 100.0,
                        roll_min=mdata["roll_min"],
                    )
                    if ok:
                        did_buy_this_loop = True
                        free_work_momentum = max(float(free_work_momentum) - float(buy_quote), 0.0)

            # ─────────────────────────────────────────
            # 8b. MA-DIP scan + entries
            # ─────────────────────────────────────────
            madip_scan: Dict[str, Dict[str, Any]] = {}

            for symbol, mcfg in self.madip_configs.items():
                if symbol in self.madip_positions:
                    continue
                try:
                    closes_md, current_close = self.fetch_closes(
                        symbol, timeframe=timeframe, limit=mcfg.ma_bars + 5
                    )
                    last_prices[symbol] = current_close
                except Exception as e:
                    print(f"[MADIP-SCAN] {symbol}: Fehler: {e}")
                    continue

                if len(closes_md) < mcfg.ma_bars + 1:
                    continue

                # MA über letzte ma_bars geschlossene Bars (exkl. aktuelle Bar)
                ma_val = float(np.mean(closes_md[-mcfg.ma_bars - 1: -1]))
                if not np.isfinite(ma_val) or ma_val <= 0:
                    continue

                threshold   = ma_val * (1.0 - mcfg.drop_pct / 100.0)
                drop_actual = (ma_val - current_close) / ma_val * 100.0
                triggered   = current_close < threshold

                madip_scan[symbol] = {
                    "last":      current_close,
                    "ma":        ma_val,
                    "threshold": threshold,
                    "drop_pct":  drop_actual,
                    "triggered": triggered,
                    "btc_ok":    self._btc_madip_filter_ok(btc_ret_15m),
                }

            # Entries: sortiert nach stärkstem Drop unter MA
            if len(self.madip_positions) < self.max_madip_slots:
                free_work_madip = float(usable_madip)
                madip_sorted = sorted(
                    madip_scan.items(),
                    key=lambda kv: -kv[1]["drop_pct"]
                )
                for symbol, mdata in madip_sorted:
                    if len(self.madip_positions) >= self.max_madip_slots:
                        break
                    if self.max_one_buy_per_loop and did_buy_this_loop:
                        break
                    if not mdata["triggered"]:
                        continue
                    # Kein Doppel-Einstieg: Coin bereits in DIP oder MOM
                    if symbol in self.positions or symbol in self.momentum_positions:
                        continue
                    if not self._time_filter_madip_ok():             # v16: Stunde 21 UTC gesperrt
                        continue
                    if not self._cooldown_ok():                      # v17: Portfolio-Cooldown
                        continue
                    if not self._btc_madip_filter_ok(btc_ret_15m):  # v18: BTC 15min Makro-Filter
                        continue
                    buy_quote = self._compute_buy_quote_madip(free_work_madip)
                    buy_quote = min(float(buy_quote), float(free_work_madip))
                    if buy_quote < float(self.sizing_cfg.min_usdt_per_trade):
                        continue
                    ok = self._enter_position_madip(
                        symbol=symbol,
                        params=self.madip_configs[symbol],
                        last_price=mdata["last"],
                        buy_quote=float(buy_quote),
                        ma_val=mdata["ma"],
                        drop_pct=mdata["drop_pct"],
                    )
                    if ok:
                        did_buy_this_loop = True
                        free_work_madip = max(float(free_work_madip) - float(buy_quote), 0.0)

            # ─────────────────────────────────────────
            # 9. Dashboard
            # ─────────────────────────────────────────
            snapshot_rows = []
            open_pos_rows = []
            momentum_pos_rows = []
            madip_pos_rows = []
            mom_snapshot_rows = []

            count = 0
            for _, __, symbol in candidates_sorted[:10]:
                if symbol in self.positions:
                    continue
                m = scan.get(symbol)
                if not m:
                    continue
                params = self.strategies[symbol]

                spd_ok_i    = icon_bool(bool(m["spd_ok"]), self.dash_cfg.use_colors)
                filter_ok_i = icon_bool(bool(m["filter_ok"]), self.dash_cfg.use_colors)
                spd_bin_i   = icon_speed_bin(str(m["spd_bin"]), self.dash_cfg.use_colors)
                lock_i      = icon_bool(bool(params.use_profit_lock), self.dash_cfg.use_colors)

                snapshot_rows.append([
                    str(count + 1),
                    symbol.replace("/USDT", ""),
                    self._fmt(m["last"], digits=6),
                    self._fmt(m["peak"], digits=6),
                    self._fmt_duration(m["since_peak_s"]),
                    f"{float(m['drop_frac']) * 100:4.2f}",
                    f"{float(m['trigger']) * 100:4.2f}",
                    f"{float(m['ratio']):4.2f}",
                    f"{float(m['drop_spd']):0.5f}" if np.isfinite(float(m["drop_spd"])) else "-",
                    spd_bin_i,
                    spd_ok_i,
                    params.filter_name.replace("_gt", ""),
                    self._fmt(params.threshold, digits=6),
                    filter_ok_i,
                    f"{float(params.tp_pct):0.2f}",
                    lock_i,
                    "4h" if params.use_rolling_peak else "ses",
                    icon_bool(bool(m["btc_ctx_ok"]), self.dash_cfg.use_colors) if params.use_btc_context_filter else "-",
                ])
                count += 1

            for symbol, pos in list(self.positions.items()):
                last = float(last_prices.get(symbol, pos.entry_price))
                pnl = (last / pos.entry_price - 1.0) * 100.0 if pos.entry_price else 0.0
                age_h = (now_ts() - pos.entry_ts) / 3600.0
                params = self.strategies[symbol]

                tp = float(pos.tp_pct_at_entry) / 100.0
                profit_now = (last / pos.entry_price - 1.0) * 100.0 if pos.entry_price else float("nan")
                profit_max = (pos.max_price / pos.entry_price - 1.0) * 100.0 if pos.entry_price else float("nan")

                exit_hint = []
                if last >= pos.entry_price * (1.0 + tp):
                    exit_hint.append("TP")
                if (now_ts() - pos.entry_ts) >= params.max_hold_h * 3600:
                    exit_hint.append("T")
                if params.sl_pct is not None:
                    sl = params.sl_pct / 100.0
                    if last <= pos.entry_price * (1.0 - sl):
                        exit_hint.append("SL")
                if pos.use_profit_lock_at_entry and pos.profit_lock_armed:
                    if np.isfinite(profit_now) and profit_now <= float(pos.profit_lock_pct_at_entry):
                        exit_hint.append("LOCK")

                spd_i   = icon_speed_bin(speed_bucket(pos.drop_speed_pct_per_min_at_entry), self.dash_cfg.use_colors)
                armed_i = icon_bool(bool(pos.profit_lock_armed), self.dash_cfg.use_colors)

                open_pos_rows.append([
                    symbol.replace("/USDT", ""),
                    self._fmt(pos.entry_price),
                    self._fmt(last),
                    self._fmt(pos.max_price),
                    f"{pnl:5.2f}",
                    f"{age_h:4.1f}",
                    f"{pos.tp_pct_at_entry:0.2f}",
                    armed_i,
                    f"{pos.profit_lock_pct_at_entry:0.2f}",
                    f"{profit_now:0.2f}",
                    f"{profit_max:0.2f}",
                    spd_i,
                    ",".join(exit_hint) if exit_hint else "",
                ])

            for symbol, mpos in list(self.momentum_positions.items()):
                last = float(last_prices.get(symbol, mpos.entry_price))
                pnl = (last / mpos.entry_price - 1.0) * 100.0 if mpos.entry_price else 0.0
                age_h = (now_ts() - mpos.entry_ts) / 3600.0
                mh_rem_m = max((mpos.max_hold_ts - now_ts()) / 60.0, 0.0)

                momentum_pos_rows.append([
                    symbol.replace("/USDT", ""),
                    self._fmt(mpos.entry_price),
                    self._fmt(last),
                    self._fmt(mpos.tp_abs),
                    f"{pnl:5.2f}",
                    f"{age_h:4.1f}",
                    f"{mh_rem_m:.0f}m",
                ])

            for symbol, mpos in list(self.madip_positions.items()):
                last = float(last_prices.get(symbol, mpos.entry_price))
                pnl = (last / mpos.entry_price - 1.0) * 100.0 if mpos.entry_price else 0.0
                age_h = (now_ts() - mpos.entry_ts) / 3600.0
                mh_rem_m = max((mpos.max_hold_ts - now_ts()) / 60.0, 0.0)
                madip_pos_rows.append([
                    symbol.replace("/USDT", ""),
                    self._fmt(mpos.entry_price),
                    self._fmt(last),
                    self._fmt(mpos.tp_abs),
                    f"{pnl:5.2f}",
                    f"{age_h:4.1f}",
                    f"{mh_rem_m:.0f}m",
                    self._fmt(mpos.ma_at_entry),
                    f"{mpos.drop_pct_at_entry:.2f}",
                ])

            # MOM Top-10 closest-to-entry
            mom_sorted_dash = sorted(
                mom_scan.items(),
                key=lambda kv: kv[1]["dist_to_trig"]
            )
            mom_rank = 0
            for symbol, mdata in mom_sorted_dash:
                if mom_rank >= 10:
                    break
                btc_i  = icon_bool(btc_ok_for_mom,  self.dash_cfg.use_colors)
                time_i = icon_bool(time_ok_for_mom, self.dash_cfg.use_colors)
                dist_pct = mdata["dist_to_trig"] * 100.0
                rise_pct = mdata["rise"] * 100.0
                trig_pct = mdata["trig"] * 100.0
                # dist negativ = bereits getriggert → markieren
                dist_str = f"{dist_pct:+.2f}" if dist_pct >= 0 else f"\033[92m{dist_pct:+.2f}\033[0m" if self.dash_cfg.use_colors else f">{dist_pct:+.2f}"
                mom_snapshot_rows.append([
                    str(mom_rank + 1),
                    symbol.replace("/USDT", ""),
                    self._fmt(mdata["last"], digits=6),
                    self._fmt(mdata["roll_min"], digits=6),
                    f"{rise_pct:.2f}",
                    f"{trig_pct:.2f}",
                    dist_str,
                    str(mdata["lb"]),
                    str(mdata["mh"]),
                    btc_i,
                    time_i,
                ])
                mom_rank += 1

            self._print_dashboard(
                snapshot_rows=snapshot_rows,
                open_pos_rows=open_pos_rows,
                momentum_pos_rows=momentum_pos_rows,
                madip_pos_rows=madip_pos_rows,
                mom_snapshot_rows=mom_snapshot_rows,
                equity_usdt=equity_usdt,
                free_usdt=free_usdt,
                usable_free=usable_free,
                reserve_usdt=reserve_usdt,
                active_candidates=active_candidates,
                btc_ret_60m=btc_ret_60m,
                btc_mom_ok=btc_ok_for_mom,
                time_ok=time_ok_for_mom,
                btc_ret_15m=btc_ret_15m,
            )

            self._write_dashboard_json(
                equity_usdt=equity_usdt,
                free_usdt=free_usdt,
                usable_free=usable_free,
                reserve_usdt=reserve_usdt,
                btc_ret_60m=btc_ret_60m,
                btc_mom_ok=btc_ok_for_mom,
                time_ok=time_ok_for_mom,
                active_candidates=active_candidates,
                candidates_sorted=candidates_sorted,
                scan=scan,
                mom_scan_sorted=mom_sorted_dash,
                last_prices=last_prices,
                madip_scan=madip_scan,
                btc_ret_15m=btc_ret_15m,
            )

            time.sleep(poll_seconds)


# -----------------------------
# Exchange builder
# -----------------------------

def build_exchange_from_env() -> ccxt.Exchange:
    api_key = os.getenv("MEXC_API_KEY")
    api_secret = os.getenv("MEXC_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError("Missing MEXC_API_KEY / MEXC_API_SECRET in .env")

    # Load markets without auth first (newer ccxt/MEXC fetch_currencies requires valid keys).
    # Then inject credentials so authenticated calls (orders, balance) work normally.
    ex = ccxt.mexc({"enableRateLimit": True})
    ex.load_markets()
    ex.apiKey = api_key
    ex.secret = api_secret
    return ex


# -----------------------------
# Main
# -----------------------------

def main():
    _acquire_pid_lock()
    load_dotenv()

    dry_run       = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes", "y")
    usdt_per_trade = float(os.getenv("USDT_PER_TRADE", "25"))
    timeframe     = os.getenv("TIMEFRAME", "1m")
    # v6: default 500 um Momentum-Lookback von bis zu 480m abzudecken
    ohlcv_limit   = int(os.getenv("OHLCV_LIMIT", "500"))
    poll_seconds  = int(os.getenv("POLL_SECONDS", "20"))

    use_colors = not _env_true("NO_COLOR", False)
    compact    = _env_true("DASH_COMPACT", True)

    sizing_cfg = BotSizingConfig(
        use_dynamic_sizing=_env_true("USE_DYNAMIC_SIZING", False),
        candidate_ratio_min=float(os.getenv("CANDIDATE_RATIO_MIN", "0.70")),
        candidate_require_filter_ok=_env_true("CANDIDATE_REQUIRE_FILTER_OK", True),
        candidate_require_speed_ok=_env_true("CANDIDATE_REQUIRE_SPEED_OK", True),
        max_pos_pct_of_equity=float(os.getenv("MAX_POS_PCT_EQUITY", "0.35")),
        max_pos_pct_of_free=float(os.getenv("MAX_POS_PCT_FREE", "0.60")),
        min_usdt_per_trade=usdt_per_trade,
    )

    dash_cfg = DashboardConfig(
        compact=compact,
        use_colors=use_colors,
        max_col_width=int(os.getenv("DASH_MAX_COL_WIDTH", "14")),
    )

    strategies        = get_strategies()
    momentum_configs  = get_momentum_configs()
    madip_configs     = get_madip_configs()

    if _env_true("USE_DROP_SPEED_FILTER_GLOBAL", True):
        spd_min = float(os.getenv("DROP_SPEED_MIN", "0.007"))
        for p in strategies.values():
            p.use_drop_speed_filter = True
            p.min_drop_speed_pct_per_min = spd_min

    # Dashboard HTTP-Server starten (Hintergrund-Thread)
    start_dashboard_server(
        directory=os.path.dirname(os.path.abspath(__file__)),
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
    )

    ex = build_exchange_from_env()
    bot = MexcDipBot(
        ex,
        strategies,
        usdt_per_trade=usdt_per_trade,
        dry_run=dry_run,
        sizing_cfg=sizing_cfg,
        dash_cfg=dash_cfg,
        momentum_configs=momentum_configs,
        madip_configs=madip_configs,
    )
    bot.run_forever(timeframe=timeframe, ohlcv_limit=ohlcv_limit, poll_seconds=poll_seconds)


if __name__ == "__main__":
    main()
