"""Dashboard HTTP server — 봇 실시간 진행 상황 모니터.

stdlib 전용 (외부 의존성 X). JSON API + 정적 HTML.

Endpoints:
  GET /                  → static/index.html
  GET /api/status        → 프로세스·DB·세션 요약
  GET /api/profiles      → 상대별 프로필 (VPIP/PFR/AF/class)
  GET /api/responses     → 상대 × phase Dirichlet posterior
  GET /api/logs?n=200    → 최신 로그 tail
  GET /api/events?n=100  → 최근 게임 이벤트 (waiting_room/hand_start/action_request/...)

실행:
  uv run python -m holdem.dashboard.server --port 8765
  scripts/bot-dashboard.sh
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import sqlite3
import subprocess
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..estimate.class_typer import hard_assign, soft_assign
from ..persist import db as persist_db
from ..state.player_profile import PlayerProfile

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# --- 경로 해석 ---

def _root() -> Path:
    return Path(__file__).resolve().parents[3]

def _pid_file() -> Path:
    return _root() / "data/bot.pid"

def _log_dir() -> Path:
    return _root() / "data/logs/cli"

def _db_path() -> Path:
    return _root() / "data/profiles.db"

def _latest_log() -> Path | None:
    ldir = _log_dir()
    if not ldir.exists():
        return None
    logs = sorted(ldir.glob("session_*.log"))
    return logs[-1] if logs else None


# --- API 핸들러 ---

def api_status() -> dict[str, Any]:
    """프로세스 + DB + 최신 로그 경로 요약."""
    out: dict[str, Any] = {
        "pid": None,
        "running": False,
        "uptime": None,
        "db_path": str(_db_path()),
        "log_path": None,
        "db_profiles": 0,
        "db_responses": 0,
    }
    pid_file = _pid_file()
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            out["pid"] = pid
            out["running"] = _pid_alive(pid)
            if out["running"]:
                try:
                    etime = subprocess.check_output(
                        ["ps", "-p", str(pid), "-o", "etime="], text=True
                    ).strip()
                    out["uptime"] = etime
                except Exception:
                    pass
        except Exception:
            pass

    latest = _latest_log()
    if latest:
        out["log_path"] = str(latest)

    # 로그 tail 에서 현 room/hand 추출 + 최근 30초 결정 수.
    out["current_room"] = None
    out["current_hand"] = None
    out["recent_decisions"] = 0
    out["last_event_ts"] = None
    if latest:
        try:
            with latest.open("r", errors="replace") as f:
                tail_lines = f.readlines()[-200:]
            import re
            from datetime import datetime, timedelta
            pat = re.compile(r"room=(\d+) hand=(\d+).*→ (\w+)")
            now_ts = None
            decisions = []
            for ln in tail_lines:
                m = pat.search(ln)
                if not m:
                    continue
                ts_m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+", ln)
                if ts_m:
                    try:
                        ts = datetime.strptime(ts_m.group(1), "%Y-%m-%d %H:%M:%S")
                        decisions.append((ts, m.group(1), m.group(2), m.group(3)))
                        now_ts = ts
                    except ValueError:
                        pass
            if decisions:
                last = decisions[-1]
                out["current_room"] = last[1]
                out["current_hand"] = last[2]
                out["last_event_ts"] = last[0].isoformat()
                # 30초 내 결정 수
                cutoff = now_ts - timedelta(seconds=30)
                out["recent_decisions"] = sum(1 for ts, *_ in decisions if ts >= cutoff)
        except Exception:
            pass

    dbp = _db_path()
    if dbp.exists():
        try:
            conn = sqlite3.connect(str(dbp))
            out["db_profiles"] = conn.execute(
                "SELECT COUNT(*) FROM opponent_profile"
            ).fetchone()[0]
            out["db_responses"] = conn.execute(
                "SELECT COUNT(*) FROM opponent_response"
            ).fetchone()[0]
            conn.close()
        except Exception as e:
            out["db_error"] = str(e)
    return out


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def api_profiles() -> list[dict[str, Any]]:
    """상대별 프로필 + VPIP/PFR/AF + class softmax."""
    dbp = _db_path()
    if not dbp.exists():
        return []
    store = persist_db.load_store(persist_db.connect(dbp))
    rows: list[dict[str, Any]] = []
    for name, prof in store.profiles.items():
        rows.append(_profile_row(name, prof))
    rows.sort(key=lambda r: -r["hands_seen"])
    return rows


def _profile_row(name: str, prof: PlayerProfile) -> dict[str, Any]:
    vpip = prof.vpip()
    pfr = prof.pfr()
    af = prof.af()
    try:
        soft = soft_assign(prof)
        hard = hard_assign(prof)
    except Exception:
        soft = {"NIT": 0.25, "TAG": 0.25, "LAG": 0.25, "Fish": 0.25}
        hard = "unknown"
    return {
        "name": name,
        "hands_seen": prof.hands_seen,
        "vpip": round(vpip, 4),
        "pfr": round(pfr, 4),
        "af": round(af, 3),
        "n_aggressive": prof.aggression.aggressive,
        "n_passive": prof.aggression.passive,
        "class_hard": hard,
        "class_soft": {k: round(v, 3) for k, v in soft.items()},
    }


def api_responses() -> list[dict[str, Any]]:
    """상대 × phase Dirichlet posterior (alpha)."""
    dbp = _db_path()
    if not dbp.exists():
        return []
    conn = sqlite3.connect(str(dbp))
    cur = conn.execute(
        "SELECT name, phase, alpha_fold, alpha_call, alpha_raise, updated_at "
        "FROM opponent_response ORDER BY name, phase"
    )
    rows = []
    for name, phase, af, ac, ar, updated in cur.fetchall():
        total = float(af) + float(ac) + float(ar)
        rows.append({
            "name": name,
            "phase": phase,
            "alpha_fold": round(float(af), 2),
            "alpha_call": round(float(ac), 2),
            "alpha_raise": round(float(ar), 2),
            "p_fold": round(float(af) / total, 3) if total > 0 else 0.333,
            "p_call": round(float(ac) / total, 3) if total > 0 else 0.333,
            "p_raise": round(float(ar) / total, 3) if total > 0 else 0.333,
            "n_obs": round(total - 3.0, 2),  # baseline (1,1,1) 제외
            "updated_at": updated,
        })
    conn.close()
    return rows


def api_logs(n: int = 200) -> dict[str, Any]:
    """최신 세션 로그의 뒤 n 줄."""
    latest = _latest_log()
    if not latest:
        return {"path": None, "lines": []}
    try:
        with latest.open("r", errors="replace") as f:
            lines = f.readlines()
        tail = lines[-n:] if len(lines) > n else lines
        return {"path": str(latest), "lines": [ln.rstrip() for ln in tail]}
    except Exception as e:
        return {"path": str(latest), "error": str(e), "lines": []}


_EVENT_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+)\s+(?P<lvl>\w+)\s+(?P<logger>[\w\.]+): (?P<msg>.*)"
)

_INTEREST_KEYS = (
    "waiting_room", "joined_room", "hand_start", "hand_result",
    "action_request", "action_performed", "phase_change",
    "auth_ok", "server_shutdown", "session ended",
    "reconnect", "deploy",
    # holdem.cli 의 결정 로그: "room=X hand=Y phase=Z → action"
    "room=", "→ fold", "→ call", "→ raise", "→ allin", "→ check",
)


def api_recent_decisions(n: int = 30) -> dict[str, Any]:
    """각 room JSONL 을 뒤에서 읽어 최근 n 개의 (action_request → action) 쌍을 추출.

    각 엔트리:
      ts, room_id, hand_number, phase, hole, community, pot, to_call, my_stack,
      action, amount, blind
    """
    games_dir = _root() / "data/logs/games"
    if not games_dir.exists():
        return {"decisions": []}

    today = _latest_log_date()
    files = sorted(games_dir.glob(f"{today}_room*.jsonl"), reverse=True) if today else []
    # fallback: 전체 파일, modified time desc
    if not files:
        files = sorted(games_dir.glob("*_room*.jsonl"), key=lambda p: -p.stat().st_mtime)[:10]

    decisions: list[dict[str, Any]] = []
    for fp in files[:10]:   # 최근 방 10개까지.
        try:
            with fp.open() as f:
                lines = f.readlines()
        except Exception:
            continue
        pending_req: dict[str, Any] | None = None
        for raw in lines[-400:]:   # 각 파일 끝에서 400줄 탐색.
            try:
                rec = json.loads(raw)
            except Exception:
                continue
            pl = rec.get("payload") or {}
            if rec.get("direction") == "in" and rec.get("type") == "action_request":
                pending_req = {
                    "ts": rec.get("ts"),
                    "room_id": pl.get("room_id"),
                    "hand_number": pl.get("hand_number"),
                    "phase": pl.get("phase"),
                    "hole": pl.get("your_cards", []),
                    "community": pl.get("community_cards", []),
                    "pot": pl.get("pot", 0),
                    "to_call": pl.get("to_call", 0),
                    "my_stack": pl.get("my_stack", 0),
                    "min_raise": pl.get("min_raise", 0),
                    "blind": pl.get("blind", []),
                }
            elif rec.get("direction") == "out" and pending_req is not None:
                if pl.get("room_id") == pending_req["room_id"]:
                    entry = dict(pending_req)
                    entry["action"] = pl.get("action")
                    entry["amount"] = pl.get("amount")
                    entry["decision_ts"] = rec.get("ts")
                    decisions.append(entry)
                    pending_req = None
    decisions.sort(key=lambda d: d.get("decision_ts") or "")
    return {"decisions": decisions[-n:]}


def _latest_log_date() -> str | None:
    latest = _latest_log()
    if not latest:
        return None
    # session_YYYYMMDD_HHMMSS.log
    try:
        return latest.stem.split("_")[1]
    except Exception:
        return None


def _find_bot_pids() -> list[int]:
    """실행 중인 봇 프로세스들 탐색.

    bot-start.sh 가 `uv run holdem` 으로 띄우면 uv wrapper 가 먼저 exit 하고
    실제 python 자식(PID != PID_FILE 값)만 남음. 따라서 PID 파일에 의존하지 않고
    커맨드 패턴으로 직접 찾는다.
    """
    try:
        out = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], text=True)
    except Exception:
        return []
    pids: list[int] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        # "PID  COMMAND..."
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        cmd = parts[1]
        # 봇 식별: holdem CLI or holdem.cli module. dashboard 자체는 제외.
        if "dashboard" in cmd:
            continue
        if ("holdem --profile-db" in cmd
                or "/holdem " in cmd
                or "holdem.cli" in cmd
                or cmd.endswith("/holdem")):
            pids.append(pid)
    return pids


def api_bot_start(mode: str = "safe") -> dict[str, Any]:
    """봇 프로세스 시작 — bot-start.sh 와 동일한 커맨드로 기동.

    mode: "safe" (기본) | "ev-tree" | "full" (ev-tree + coordinator).
    이미 실행 중이면 거부. 기동 직후 1초 생존 확인 후 성공 반환.
    start_new_session=True 로 대시보드와 분리된 세션 → 대시보드 종료 무관.
    """
    existing = _find_bot_pids()
    if existing:
        return {"ok": False, "reason": "already_running", "pids": existing}

    root = _root()
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    session_log = log_dir / f"session_{ts}.log"

    args = [
        "uv", "run", "holdem",
        "--profile-db", str(_db_path()),
        "--log-level", "INFO",
    ]
    if mode == "ev-tree":
        args.append("--use-ev-tree")
    elif mode == "full":
        args.extend(["--use-ev-tree", "--use-coordinator"])
    elif mode != "safe":
        return {"ok": False, "reason": f"unknown_mode:{mode}"}

    try:
        log_fh = session_log.open("ab")
        proc = subprocess.Popen(
            args,
            cwd=str(root),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except Exception as e:
        return {"ok": False, "reason": "spawn_failed", "error": str(e)}

    pid_file = _pid_file()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(proc.pid))

    # 기동 직후 생존 체크 (stub fail-fast 방지).
    time.sleep(1.0)
    if proc.poll() is not None:
        pid_file.unlink(missing_ok=True)
        return {
            "ok": False,
            "reason": "died_immediately",
            "exit_code": proc.returncode,
            "log": str(session_log),
        }

    return {
        "ok": True,
        "pid": proc.pid,
        "log": str(session_log),
        "mode": mode,
    }


def api_bot_stop() -> dict[str, Any]:
    """봇 프로세스 종료 — SIGTERM → 3초 → SIGKILL fallback.

    PID 파일이 없거나 stale 이어도 ps 로 커맨드 패턴 매칭해 정리.
    로컬 루프백(127.0.0.1) 바인딩이므로 외부 접근 없음.
    """
    pids: list[int] = []
    pid_file = _pid_file()
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            if _pid_alive(pid):
                pids.append(pid)
        except Exception:
            pass

    # ps 로 추가 탐색 (uv wrapper 자식 포함).
    for p in _find_bot_pids():
        if p not in pids:
            pids.append(p)

    if not pids:
        pid_file.unlink(missing_ok=True)
        return {"ok": False, "reason": "no_bot_process"}

    killed: list[dict[str, Any]] = []
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as e:
            killed.append({"pid": pid, "method": "failed", "error": str(e)})
            continue

        method = "SIGTERM"
        for _ in range(30):
            if not _pid_alive(pid):
                break
            time.sleep(0.1)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
                method = "SIGKILL"
            except OSError:
                pass
        killed.append({"pid": pid, "method": method})

    pid_file.unlink(missing_ok=True)
    return {"ok": True, "killed": killed}


def api_events(n: int = 100) -> dict[str, Any]:
    """로그에서 게임 이벤트만 필터링해 최신 n개."""
    latest = _latest_log()
    if not latest:
        return {"path": None, "events": []}
    try:
        with latest.open("r", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return {"path": str(latest), "error": str(e), "events": []}

    events = []
    for ln in lines:
        low = ln.lower()
        if not any(k in low for k in _INTEREST_KEYS):
            continue
        m = _EVENT_RE.match(ln)
        if m:
            events.append({
                "ts": m["ts"],
                "level": m["lvl"],
                "logger": m["logger"],
                "msg": m["msg"].strip(),
            })
        else:
            events.append({"ts": "", "level": "", "logger": "", "msg": ln.strip()})
    return {"path": str(latest), "events": events[-n:]}


# --- HTTP 핸들러 ---

class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: D401
        log.debug("%s - %s", self.address_string(), fmt % args)

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/bot/stop":
            self._json(api_bot_stop())
            return
        if parsed.path == "/api/bot/start":
            length = int(self.headers.get("Content-Length", "0") or "0")
            mode = "safe"
            if length > 0:
                try:
                    body = json.loads(self.rfile.read(length))
                    mode = str(body.get("mode", "safe"))
                except Exception:
                    pass
            self._json(api_bot_start(mode))
            return
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"not found")

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self._serve_static("index.html", "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            self._serve_static(path[len("/static/"):], self._guess_mime(path))
            return

        if path == "/api/status":
            self._json(api_status())
            return
        if path == "/api/profiles":
            self._json(api_profiles())
            return
        if path == "/api/responses":
            self._json(api_responses())
            return
        if path == "/api/logs":
            n = int(qs.get("n", ["200"])[0])
            self._json(api_logs(n))
            return
        if path == "/api/events":
            n = int(qs.get("n", ["100"])[0])
            self._json(api_events(n))
            return
        if path == "/api/recent_decisions":
            n = int(qs.get("n", ["30"])[0])
            self._json(api_recent_decisions(n))
            return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"not found")

    # --- helpers ---

    def _serve_static(self, rel: str, mime: str) -> None:
        p = STATIC_DIR / rel
        if not p.exists() or not p.is_file():
            self.send_response(404)
            self.end_headers()
            return
        data = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: Any) -> None:
        body = json.dumps(payload, default=str, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _guess_mime(path: str) -> str:
        if path.endswith(".html"):
            return "text/html; charset=utf-8"
        if path.endswith(".css"):
            return "text/css; charset=utf-8"
        if path.endswith(".js"):
            return "text/javascript; charset=utf-8"
        if path.endswith(".json"):
            return "application/json"
        return "application/octet-stream"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.getenv("HOLDEM_DASHBOARD_PORT", "8765")))
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    url = f"http://{args.host}:{args.port}/"
    log.info(f"Dashboard listening on {url}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutdown")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
