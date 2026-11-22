"""API delle routine della casa (Buongiorno, Buonanotte, ...)."""
import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.routines import (
    delete_routine, describe_action, describe_when, get_routine, init_routines_table,
    list_routines, routine_runner, save_routine, seed_default_routines,
)

router = APIRouter()


def _view(r):
    return {**r, "when": describe_when(r), "summary": [describe_action(a) for a in r["actions"]]}


def _ready():
    init_routines_table()
    seed_default_routines()


@router.get("/api/routines")
def api_list_routines():
    _ready()
    return {"routines": [_view(r) for r in list_routines()]}


@router.get("/api/routines/devices")
def api_routine_devices():
    """Luci e persiane di Home Assistant che una routine può comandare, con i nomi scelti dall'utente."""
    from backend.database import get_device_aliases
    from backend.homeassistant_service import homeassistant_service
    try:
        aliases = get_device_aliases()
    except Exception:
        aliases = {}
    lights, covers = [], []
    for d in homeassistant_service.get_catalog_devices():
        raw = str(d.get("raw_id", ""))
        if not raw.startswith(("light.", "cover.")):
            continue
        item = {"id": raw, "name": aliases.get(f"hass_{raw}") or aliases.get(raw) or d.get("name") or raw,
                "online": bool(d.get("is_online"))}
        (lights if raw.startswith("light.") else covers).append(item)
    key = lambda x: x["name"].lower()
    return {"lights": sorted(lights, key=key), "covers": sorted(covers, key=key)}


@router.post("/api/routines")
async def api_save_routine(request: Request):
    _ready()
    try:
        data = await request.json()
    except Exception:
        data = {}
    try:
        return {"status": "ok", "routine": _view(save_routine(data))}
    except (ValueError, TypeError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/routines/{rid}/enabled")
async def api_toggle_routine(rid: str, request: Request):
    r = get_routine(rid)
    if not r:
        return JSONResponse({"error": "Routine non trovata"}, status_code=404)
    try:
        data = await request.json()
    except Exception:
        data = {}
    r["enabled"] = bool(data.get("enabled"))
    saved = save_routine(r)
    if r["enabled"] and not saved["enabled"]:
        return JSONResponse({"error": "Scegli prima orario e giorni"}, status_code=400)
    return {"status": "ok", "routine": _view(saved)}


@router.post("/api/routines/{rid}/run")
async def api_run_routine(rid: str):
    r = get_routine(rid)
    if not r:
        return JSONResponse({"error": "Routine non trovata"}, status_code=404)
    # La persiana a una posizione intermedia impiega qualche secondo: la routine continua in background
    asyncio.create_task(routine_runner.run(r, source="manual"))
    return {"status": "started", "routine": _view(r)}


@router.delete("/api/routines/{rid}")
def api_delete_routine(rid: str):
    if not delete_routine(rid):
        return JSONResponse({"error": "Routine non trovata"}, status_code=404)
    return {"status": "deleted"}
