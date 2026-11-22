"""Routine della casa: più azioni insieme, a mano o a un orario nei giorni scelti.

Azioni supportate:
- {"type": "lights", "state": "on" | "off"}       tutte le luci di Home Assistant raggiungibili
- {"type": "cover", "entity_id": "...", "mode": "open" | "close" | "half", "travel_sec": 20}
  "half": la persiana non dice la sua posizione (e si può muovere anche dall'interruttore a muro),
  quindi prima la chiude tutta per avere un punto fermo, poi la apre per metà del tempo di corsa e la ferma.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from backend.config import settings
from backend.database import get_connection

logger = logging.getLogger("weather_hub.routines")

DAYS = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
LATE_GRACE_MIN = 10  # se l'hub era spento all'orario, la routine parte solo se in ritardo di pochi minuti
DEFAULT_COVER = "cover.persiana_tenda"
DEFAULT_TRAVEL_SEC = 20
HALF_MARGIN_SEC = 2  # un po' di margine perché arrivi davvero a fine corsa

DEFAULT_ROUTINES = [
    {
        "id": "buongiorno", "name": "Buongiorno", "icon": "☀️", "time": "07:00", "days": list(range(7)),
        "enabled": False,
        "actions": [
            {"type": "lights", "state": "on"},
            {"type": "cover", "entity_id": DEFAULT_COVER, "mode": "half", "travel_sec": DEFAULT_TRAVEL_SEC},
        ],
    },
    {
        "id": "buonanotte", "name": "Buonanotte", "icon": "🌙", "time": "23:00", "days": list(range(7)),
        "enabled": False,
        "actions": [
            {"type": "lights", "state": "off"},
            {"type": "cover", "entity_id": DEFAULT_COVER, "mode": "close"},
        ],
    },
]


# --------------------------------------------------------------------------- DB
def init_routines_table() -> None:
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS routines (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            icon TEXT,
            time TEXT,
            days_json TEXT,
            actions_json TEXT NOT NULL,
            enabled INTEGER DEFAULT 0,
            position INTEGER DEFAULT 0,
            last_run_at TEXT,
            last_run_date TEXT,
            last_result_json TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def seed_default_routines() -> None:
    """Crea Buongiorno e Buonanotte solo la prima volta."""
    conn = get_connection()
    try:
        if conn.execute("SELECT COUNT(*) FROM routines").fetchone()[0]:
            return
    finally:
        conn.close()
    for i, r in enumerate(DEFAULT_ROUTINES):
        save_routine({**r, "position": i})


def _row(r) -> Dict[str, Any]:
    return {
        "id": r["id"], "name": r["name"], "icon": r["icon"] or "✨",
        "time": r["time"] or "", "days": json.loads(r["days_json"] or "[]"),
        "actions": json.loads(r["actions_json"] or "[]"),
        "enabled": bool(r["enabled"]), "position": r["position"] or 0,
        "last_run_at": r["last_run_at"], "last_run_date": r["last_run_date"],
        "last_result": json.loads(r["last_result_json"]) if r["last_result_json"] else None,
    }


def list_routines() -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM routines ORDER BY position, created_at").fetchall()
    conn.close()
    return [_row(r) for r in rows]


def get_routine(rid: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    r = conn.execute("SELECT * FROM routines WHERE id = ?", (rid,)).fetchone()
    conn.close()
    return _row(r) if r else None


def _clean_time(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return datetime.strptime(text[:5], "%H:%M").strftime("%H:%M")
    except ValueError:
        raise ValueError("Orario non valido, usa HH:MM")


def _clean_actions(actions: Any) -> List[Dict[str, Any]]:
    out = []
    for a in actions or []:
        t = a.get("type")
        if t == "lights" and a.get("state") in ("on", "off"):
            out.append({"type": "lights", "state": a["state"]})
        elif t == "cover" and a.get("mode") in ("open", "close", "half"):
            travel = int(a.get("travel_sec") or DEFAULT_TRAVEL_SEC)
            out.append({"type": "cover", "entity_id": str(a.get("entity_id") or DEFAULT_COVER),
                        "mode": a["mode"], "travel_sec": max(3, min(travel, 180))})
    if not out:
        raise ValueError("La routine non ha azioni")
    return out


def save_routine(data: Dict[str, Any]) -> Dict[str, Any]:
    rid = str(data.get("id") or "").strip() or "rt_" + uuid.uuid4().hex[:8]
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("Dai un nome alla routine")
    time = _clean_time(data.get("time"))
    days = sorted({int(d) for d in (data.get("days") or []) if 0 <= int(d) <= 6})
    actions = _clean_actions(data.get("actions"))
    enabled = bool(data.get("enabled")) and bool(time) and bool(days)
    conn = get_connection()
    old = conn.execute("SELECT position, created_at FROM routines WHERE id = ?", (rid,)).fetchone()
    position = data.get("position", old["position"] if old else 99)
    created = old["created_at"] if old else datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO routines (id, name, icon, time, days_json, actions_json, enabled, position, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET name=excluded.name, icon=excluded.icon, time=excluded.time,
            days_json=excluded.days_json, actions_json=excluded.actions_json, enabled=excluded.enabled,
            position=excluded.position
    """, (rid, name, data.get("icon") or "✨", time, json.dumps(days), json.dumps(actions, ensure_ascii=False),
          int(enabled), position, created))
    conn.commit()
    conn.close()
    return get_routine(rid)


def delete_routine(rid: str) -> bool:
    conn = get_connection()
    n = conn.execute("DELETE FROM routines WHERE id = ?", (rid,)).rowcount
    conn.commit()
    conn.close()
    return n > 0


def _mark_run(rid: str, day: str, result: Dict[str, Any]) -> None:
    conn = get_connection()
    conn.execute("UPDATE routines SET last_run_at = ?, last_run_date = ?, last_result_json = ? WHERE id = ?",
                 (datetime.now(timezone.utc).isoformat(), day, json.dumps(result, ensure_ascii=False), rid))
    conn.commit()
    conn.close()


def _claim_day(rid: str, day: str) -> bool:
    """Segna la routine come eseguita oggi prima di farla partire: mai due volte nello stesso giorno."""
    conn = get_connection()
    n = conn.execute("UPDATE routines SET last_run_date = ? WHERE id = ? AND COALESCE(last_run_date, '') != ?",
                     (day, rid, day)).rowcount
    conn.commit()
    conn.close()
    return n > 0


# --------------------------------------------------------------------------- testo
def describe_action(a: Dict[str, Any]) -> str:
    if a["type"] == "lights":
        return "Accende le luci" if a["state"] == "on" else "Spegne le luci"
    if a["type"] == "cover":
        return {"open": "Apre la persiana", "close": "Chiude la persiana",
                "half": "Apre la persiana a metà"}[a["mode"]]
    return ""


def describe_when(r: Dict[str, Any]) -> str:
    if not r.get("time") or not r.get("days"):
        return "Solo a mano"
    days = r["days"]
    if len(days) == 7:
        d = "Ogni giorno"
    elif days == [0, 1, 2, 3, 4]:
        d = "Lun–Ven"
    elif days == [5, 6]:
        d = "Sab e Dom"
    else:
        d = " ".join(DAYS[i] for i in days)
    return f"{d} alle {r['time']}"


# --------------------------------------------------------------------------- esecuzione
class RoutineRunner:
    def __init__(self, hass=None, notifier=None):
        self._hass = hass
        self._notifier = notifier
        self._running = False
        self._busy: set = set()

    @property
    def hass(self):
        if self._hass is None:
            from backend.homeassistant_service import homeassistant_service
            self._hass = homeassistant_service
        return self._hass

    @property
    def notifier(self):
        if self._notifier is None:
            from backend.notifier import notifier
            self._notifier = notifier
        return self._notifier

    def _lights(self) -> List[Dict[str, Any]]:
        return [d for d in self.hass.get_catalog_devices()
                if str(d.get("raw_id", "")).startswith("light.") and d.get("is_online") and d.get("can_toggle")]

    async def _run_action(self, a: Dict[str, Any]) -> Dict[str, Any]:
        if a["type"] == "lights":
            want = a["state"] == "on"
            done, failed = [], []
            for d in self._lights():
                if d.get("is_on") == want:
                    continue
                res = await self.hass.toggle_device(d["raw_id"], want)
                (done if res.get("success") else failed).append(d.get("name") or d["raw_id"])
            return {"ok": not failed, "text": describe_action(a), "done": done, "failed": failed}
        if a["type"] == "cover":
            eid, mode = a["entity_id"], a["mode"]
            if mode == "half":
                travel = a.get("travel_sec", DEFAULT_TRAVEL_SEC)
                res = await self.hass.call_service("cover", "close_cover", eid)
                if res.get("success"):
                    await asyncio.sleep(travel + HALF_MARGIN_SEC)  # tutta chiusa, qualunque fosse la posizione
                    res = await self.hass.call_service("cover", "open_cover", eid)
                if res.get("success"):
                    await asyncio.sleep(travel / 2)
                    res = await self.hass.call_service("cover", "stop_cover", eid)
            else:
                res = await self.hass.call_service("cover", f"{mode}_cover", eid)
            return {"ok": bool(res.get("success")), "text": describe_action(a),
                    "error": None if res.get("success") else res.get("error")}
        return {"ok": False, "text": "Azione sconosciuta"}

    async def run(self, routine: Dict[str, Any], source: str = "manual") -> Dict[str, Any]:
        rid = routine["id"]
        if rid in self._busy:
            return {"ok": False, "error": "La routine è già in corso"}
        self._busy.add(rid)
        try:
            steps = []
            for a in routine["actions"]:
                try:
                    steps.append(await self._run_action(a))
                except Exception as e:  # una azione fallita non blocca le altre
                    logger.error("Routine %s, azione %s: %s", rid, a, e)
                    steps.append({"ok": False, "text": describe_action(a), "error": str(e)})
            ok = all(s["ok"] for s in steps)
            result = {"ok": ok, "source": source, "steps": steps}
            _mark_run(rid, datetime.now(settings.get_tz()).date().isoformat(), result)
            if source == "schedule" or not ok:
                lines = [("✓ " if s["ok"] else "✗ ") + s["text"] for s in steps]
                self.notifier.send_alert(
                    alert_type="routine_done" if ok else "routine_failed",
                    title=f"{routine.get('icon', '')} {routine['name']}".strip(),
                    message="\n".join(lines),
                    priority="normal" if ok else "high",
                    extra_data={"routine_id": rid},
                    force=True,
                )
            return result
        finally:
            self._busy.discard(rid)

    def due(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        now = (now or datetime.now(settings.get_tz())).astimezone(settings.get_tz())
        today = now.date().isoformat()
        out = []
        for r in list_routines():
            if not r["enabled"] or not r["time"] or now.weekday() not in r["days"] or r["last_run_date"] == today:
                continue
            h, m = map(int, r["time"].split(":"))
            at = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if at <= now < at + timedelta(minutes=LATE_GRACE_MIN):
                out.append(r)
        return out

    async def tick(self, now: Optional[datetime] = None) -> int:
        started = 0
        for r in self.due(now):
            day = (now or datetime.now(settings.get_tz())).astimezone(settings.get_tz()).date().isoformat()
            if _claim_day(r["id"], day):
                logger.info("🕒 Routine '%s' avviata dall'orario", r["name"])
                asyncio.create_task(self.run(r, source="schedule"))
                started += 1
        return started

    async def worker_loop(self):
        self._running = True
        try:
            init_routines_table()
            seed_default_routines()
        except Exception as e:
            logger.error("Routine: impossibile preparare la tabella: %s", e)
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Routine: errore nel controllo orari: %s", e)
            await asyncio.sleep(20)

    def stop(self):
        self._running = False


routine_runner = RoutineRunner()
