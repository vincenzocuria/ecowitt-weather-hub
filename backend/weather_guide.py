"""
Guida ai venti e agli stati del mare (finestra aperta dal pulsante "?").

I nomi e i settori dei venti vengono da analytics.WIND_NAMES, la forza da calc_beaufort_scale
e gli stati del mare da marine_service.DOUGLAS: la guida usa le stesse soglie del resto dell'app.
Le note "sulla tua costa" valgono per lo Ionio settentrionale calabrese (costa rivolta a nord-est).
"""
from typing import Any, Dict, List

from backend.analytics import WIND_NAMES, calc_beaufort_scale
from backend.marine_service import DOUGLAS

WIND_DETAILS: Dict[str, Dict[str, str]] = {
    "Tramontana": {
        "origin": "Da \"tra i monti\": arriva da oltre le montagne del nord.",
        "character": "Freddo e secco, cielo limpido e aria tersa. Più frequente in inverno.",
        "sea": "Attraversa il Golfo di Taranto e arriva dal mare: con vento forte le onde battono la costa.",
        "level": "mare",
    },
    "Grecale": {
        "origin": "Dalla Grecia, la direzione da cui soffia vista dal centro del Mediterraneo.",
        "character": "Freddo, spesso forte e a raffiche. In inverno porta nuvole, pioggia e neve in montagna.",
        "sea": "Tra i venti peggiori per questa costa: soffia dal largo e solleva le mareggiate più forti.",
        "level": "mare",
    },
    "Levante": {
        "origin": "Dal punto in cui \"si leva\" il sole.",
        "character": "Mite e umido, porta cielo coperto e piogge sul versante ionico, soprattutto da autunno a primavera.",
        "sea": "Arriva dal mare aperto: mare mosso e mareggiate, anche giorni dopo che il vento è calato.",
        "level": "mare",
    },
    "Scirocco": {
        "origin": "Dall'arabo, \"vento di levante\": nasce sul deserto del Sahara.",
        "character": "Caldo e umido, cielo lattiginoso, afa e a volte sabbia africana sulle auto. In autunno e inverno porta piogge forti.",
        "sea": "Gonfia il mare ionico da sud-est: mare mosso al largo, sotto costa di solito meno.",
        "level": "medio",
    },
    "Ostro": {
        "origin": "Dal latino auster, vento del sud; detto anche Mezzogiorno.",
        "character": "Caldo e umido, spesso con nubi e piogge. Meno frequente degli altri.",
        "sea": "Per te soffia da terra (Sila): vicino a riva il mare resta in genere calmo.",
        "level": "terra",
    },
    "Libeccio": {
        "origin": "Dalla Libia, la direzione da cui arriva.",
        "character": "Sul Tirreno è il vento delle burrasche. Qui arriva dopo aver scavalcato la Sila: più secco, caldo e a raffiche.",
        "sea": "Soffia da terra: mare calmo sotto costa, ma raffiche forti in spiaggia.",
        "level": "terra",
    },
    "Ponente": {
        "origin": "Dal punto in cui il sole \"si pone\", cioè tramonta.",
        "character": "Fresco, spesso arriva dopo il passaggio di una perturbazione e rasserena.",
        "sea": "Soffia da terra: mare calmo vicino a riva.",
        "level": "terra",
    },
    "Maestrale": {
        "origin": "Il \"vento maestro\", il più importante del Mediterraneo.",
        "character": "Fresco o freddo e secco, cielo terso. Forte e persistente, può durare alcuni giorni.",
        "sea": "Soffia quasi parallelo alla costa: poco mosso vicino a riva, più mosso al largo.",
        "level": "medio",
    },
}

SEA_EFFECT_LABELS = {"mare": "Agita il mare qui", "medio": "Mare variabile", "terra": "Da terra: mare calmo a riva"}

# Cosa significa in pratica ogni grado Douglas (bagno e piccola barca)
SEA_PRACTICAL = {
    0: "Bagno e barca senza problemi.",
    1: "Bagno e barca senza problemi.",
    2: "Bagno tranquillo; piccole barche ok.",
    3: "Bagno con attenzione, soprattutto con i bambini; piccole barche a disagio.",
    4: "Bagno sconsigliato; le piccole barche restano in porto.",
    5: "Niente bagno: mareggiata sulla spiaggia. Escono solo navi.",
    6: "Pericoloso anche per barche grandi; l'acqua può arrivare oltre la spiaggia.",
    7: "Mare impraticabile, onde molto alte.",
    8: "Condizioni rarissime nel Mediterraneo.",
    9: "Condizioni eccezionali, da oceano in tempesta.",
}

BEAUFORT_LIMITS = [1, 5, 11, 19, 28, 38, 49, 61, 74, 88, 102, 117]


def _num(v: float) -> str:
    return f"{v:g}".replace(".", ",")


def build_weather_guide() -> Dict[str, Any]:
    winds: List[Dict[str, Any]] = []
    for w in WIND_NAMES:
        d = WIND_DETAILS.get(w["name"], {})
        winds.append({
            "name": w["name"], "abbr": w["abbr"], "deg": w["deg"], "from": w["from"],
            "origin": d.get("origin", ""), "character": d.get("character", w.get("desc", "")),
            "sea": d.get("sea", ""), "level": d.get("level", "medio"),
            "level_label": SEA_EFFECT_LABELS.get(d.get("level", "medio"), ""),
        })

    beaufort: List[Dict[str, Any]] = []
    low = 0
    for grade in range(13):
        if grade < len(BEAUFORT_LIMITS):
            high = BEAUFORT_LIMITS[grade]
            info = calc_beaufort_scale(high - 0.5 if grade else 0)
            rng = "< 1" if grade == 0 else f"{low}–{high}"
        else:
            info = calc_beaufort_scale(200)
            rng = f"> {BEAUFORT_LIMITS[-1]}"
        beaufort.append({"grade": grade, "label": info["label"], "desc": info["desc"], "range": rng})
        low = BEAUFORT_LIMITS[grade] if grade < len(BEAUFORT_LIMITS) else low

    sea: List[Dict[str, Any]] = []
    prev = None
    for limit, grade, label, desc in DOUGLAS:
        if prev is None:
            rng = "0 m"
        else:
            rng = f"{_num(prev)}–{_num(limit)} m"
        sea.append({"grade": grade, "label": label, "desc": desc, "range": rng, "practical": SEA_PRACTICAL.get(grade, "")})
        prev = limit
    sea.append({"grade": 9, "label": "Tempestoso", "desc": "Condizioni eccezionali.", "range": f"oltre {_num(prev)} m",
                "practical": SEA_PRACTICAL[9]})
    return {"winds": winds, "beaufort": beaufort, "sea": sea}
