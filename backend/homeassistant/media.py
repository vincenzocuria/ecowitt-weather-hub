"""
TV e media player di Home Assistant: riconoscimento, nome leggibile e accensione.

Le TV LG webOS possono comparire due volte: dall'integrazione "LG webOS TV" (stato reale,
volume, sorgenti) e da Google Cast (vede solo le trasmissioni). Se c'è la prima, la seconda
viene nascosta. L'accensione di una TV spenta richiede un "risveglio via rete": si usa il
supporto nativo (feature TURN_ON) oppure un pulsante Wake on LAN configurato in Home Assistant.
"""
from typing import Any, Dict, Optional

from backend.config import settings

MEDIA_FEATURE_TURN_ON = 128
ON_STATES = ("on", "playing", "paused", "idle", "buffering")


def is_full_tv(state_obj: Dict[str, Any]) -> bool:
    """TV con controllo completo (es. LG webOS): espone l'elenco delle sorgenti."""
    attrs = state_obj.get("attributes") or {}
    return bool(attrs.get("source_list")) and str(attrs.get("device_class") or "").lower() == "tv"


def has_full_tv(entities: Dict[str, Dict[str, Any]]) -> bool:
    return any(eid.startswith("media_player.") and is_full_tv(st) for eid, st in entities.items())


def is_cast_duplicate(entity_id: str, state_obj: Dict[str, Any], entities: Dict[str, Dict[str, Any]]) -> bool:
    """Voce Google Cast di una TV LG già presente tramite l'integrazione webOS."""
    name = str((state_obj.get("attributes") or {}).get("friendly_name") or "").lower()
    return "webos tv" in name and not is_full_tv(state_obj) and has_full_tv(entities)


def display_name(entity_id: str, friendly_name: str) -> str:
    """Nome leggibile: "TV" da solo diventa ad es. "Soggiorno TV" (dall'entity_id)."""
    if friendly_name and len(friendly_name.strip()) > 3:
        return friendly_name
    words = entity_id.split(".", 1)[-1].replace("_", " ").split()
    pretty = " ".join("TV" if w.lower() == "tv" else w.capitalize() for w in words)
    return pretty or friendly_name or entity_id


def find_wake_button(entities: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """Pulsante Wake on LAN per la TV (impostazione esplicita o riconoscimento per nome)."""
    configured = (settings.HASS_TV_WAKE_BUTTON or "").strip()
    if configured:
        return configured if configured in entities or not entities else None
    for eid, st in entities.items():
        if not eid.startswith("button."):
            continue
        text = (eid + " " + str((st.get("attributes") or {}).get("friendly_name") or "")).lower()
        if any(k in text for k in ("wake", "wol", "accendi", "accensione")) and "tv" in text:
            return eid
    return None


def supports_turn_on(state_obj: Dict[str, Any]) -> bool:
    feats = int((state_obj.get("attributes") or {}).get("supported_features") or 0)
    return bool(feats & MEDIA_FEATURE_TURN_ON)


def tv_fields(entity_id: str, state_obj: Dict[str, Any], entities: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Campi extra per la card e il dettaglio della TV."""
    attrs = state_obj.get("attributes") or {}
    vol = attrs.get("volume_level")
    wake = find_wake_button(entities)
    return {
        "is_tv": True,
        "full_control": is_full_tv(state_obj),
        "source": attrs.get("source") or attrs.get("app_name"),
        "source_list": attrs.get("source_list") or [],
        "volume_pct": round(float(vol) * 100) if vol is not None else None,
        "is_muted": bool(attrs.get("is_volume_muted")),
        "media_title": attrs.get("media_title"),
        "can_turn_on": supports_turn_on(state_obj) or bool(wake),
        "wake_button": wake,
    }
