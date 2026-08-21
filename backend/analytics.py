import math
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional, Tuple

def get_station_tz(tz_name: Optional[str] = None) -> Any:
    """Restituisce il fuso orario configurato (default da settings.get_tz())."""
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    from backend.config import settings
    return settings.get_tz()

# ---------------------------------------------------------------------------
# 1. ALGORITMO DI ZAMBRETTI (Nowcasting Locale a 6-12 Ore)
# ---------------------------------------------------------------------------
# Negretti & Zambra (1915) - Formula barometrica classica per stazioni meteo
# ---------------------------------------------------------------------------

ZAMBRETTI_TEXTS = {
    # Pressione in aumento (A..J) - Tendenza al miglioramento
    "A": {"icon": "☀️", "text": "Bello stabile e soleggiato", "desc": "Anticiclone solido in consolidamento."},
    "B": {"icon": "🌤️", "text": "Bel tempo asciutto", "desc": "Condizioni ampiamente soleggiate e stabili."},
    "C": {"icon": "⛅", "text": "In miglioramento verso il bello", "desc": "Tendenza a schiarite sempre più ampie."},
    "D": {"icon": "🌤️", "text": "Variabile con ampie schiarite", "desc": "Tempo in rapido miglioramento."},
    "E": {"icon": "🌦️", "text": "Bello con possibili brevi piovaschi", "desc": "Prevalentemente asciutto con isolati rovesci passeggeri."},
    "F": {"icon": "⛅", "text": "Discreto in miglioramento", "desc": "Nubi residue in graduale diradamento."},
    "G": {"icon": "🌦️", "text": "Variabile, possibili rovesci all'inizio", "desc": "Miglioramento graduale nelle ore successive."},
    "H": {"icon": "🌦️", "text": "Discreto, possibili rovesci successivi", "desc": "Inizialmente asciutto con temporanee velature."},
    "I": {"icon": "🌧️", "text": "Instabile, piogge in attenuazione", "desc": "Tendenza a progressivo esaurimento dei fenomeni."},
    "J": {"icon": "🌦️", "text": "Variabile in miglioramento", "desc": "Instabilità residua in progressivo allontanamento."},

    # Pressione costante (K..Q) - Condizioni stazionarie
    "K": {"icon": "☀️", "text": "Bello stabile e asciutto", "desc": "Condizioni anticicloniche costanti e soleggiate."},
    "L": {"icon": "🌤️", "text": "Prevalentemente soleggiato", "desc": "Bel tempo persistente con poche nubi innocue."},
    "M": {"icon": "⛅", "text": "Variabile con ampie schiarite", "desc": "Alternanza di sole e nuvole innocue in clima asciutto."},
    "N": {"icon": "🌦️", "text": "Variabile con possibili brevi rovesci", "desc": "Nubi sparse con possibili piovaschi pomeridiani o locali."},
    "O": {"icon": "🌦️", "text": "Variabile a tratti instabile", "desc": "Copertura irregolare con rovesci a intervalli."},
    "P": {"icon": "🌧️", "text": "Instabile con piogge a intervalli", "desc": "Cielo nuvoloso con precipitazioni discontinue."},
    "Q": {"icon": "🌦️", "text": "Variabile con brevi intervalli asciutti", "desc": "Instabilità persistente intervallata da locali schiarite."},

    # Pressione in calo (R..Z) - Tendenza al peggioramento
    "R": {"icon": "🌤️", "text": "Bello ma tendente a instabile", "desc": "Inizio di un calo barometrico con velature in aumento."},
    "S": {"icon": "⛅", "text": "Nubi in aumento, peggioramento imminente", "desc": "Progressivo addensamento nuvoloso."},
    "T": {"icon": "🌦️", "text": "Variabile con piogge in arrivo", "desc": "Peggioramento con prime precipitazioni sparse."},
    "U": {"icon": "🌧️", "text": "Pioggia in arrivo nelle prossime ore", "desc": "Fronte perturbato in avvicinamento."},
    "V": {"icon": "🌧️", "text": "Pioggia e vento in rinforzo", "desc": "Peggioramento marcato con venti sostenuti."},
    "W": {"icon": "🌧️", "text": "Piogge diffuse e frequenti", "desc": "Forte perturbazione in transito."},
    "X": {"icon": "🌧️", "text": "Forte maltempo e pioggia continua", "desc": "Depressione marcata con precipitazioni intense."},
    "Y": {"icon": "🌪️", "text": "Burrasca con vento forte e pioggia", "desc": "Marcata depressione con venti burrascosi."},
    "Z": {"icon": "⛈️", "text": "Tempesta / Forte burrasca", "desc": "Crollo barometrico eccezionale con forte maltempo."}
}

def abs_to_rel_pressure(abs_pressure_hpa: Optional[float], elevation_m: Optional[float] = None, temp_c: Optional[float] = 15.0) -> Optional[float]:
    """
    Converte la pressione assoluta della stazione in pressione relativa a livello del mare (MSLP)
    usando la formula ipsometrica standard internazionale ICAO/WMO.
    """
    if abs_pressure_hpa is None:
        return None
    if elevation_m is None:
        from backend.config import settings
        elevation_m = settings.ELEVATION
    try:
        t_k = (temp_c if temp_c is not None else 15.0) + 273.15
        p_rel = float(abs_pressure_hpa) * math.pow(1.0 + (0.0065 * float(elevation_m)) / t_k, 5.255)
        return round(p_rel, 1)
    except Exception:
        return abs_pressure_hpa

def calc_zambretti_forecast(
    pressure_hpa: Optional[float],
    pressure_diff_3h: Optional[float],
    wind_deg: Optional[float] = None,
    month: Optional[int] = None
) -> Dict[str, Any]:
    """
    Calcola la previsione locale a 6-12 ore usando l'algoritmo barometrico standard di Zambretti (Negretti & Zambra).
    Utilizza la Pressione Relativa standardizzata a livello del mare (MSLP).
    """
    if pressure_hpa is None:
        return {
            "letter": "M",
            "icon": "🌤️",
            "text": "In attesa di dati barometrici",
            "desc": "La stazione deve raccogliere letture di pressione.",
            "confidence": "bassa"
        }

    p = float(pressure_hpa)
    diff = float(pressure_diff_3h) if pressure_diff_3h is not None else 0.0
    if month is None:
        month = datetime.now().month

    # Trend di pressione:
    # diff >= 0.8 hPa/3h -> In aumento (rising)
    # diff <= -0.8 hPa/3h -> In calo (falling)
    # altrimenti -> Stabile (steady)
    
    # Range normalizzato MSLP 950 - 1050 hPa
    p = max(950.0, min(1050.0, p))

    if diff >= 0.8:
        # Pressione in aumento: Z = 0.174 * (1050 - P) + 1 (1..10 -> A..J)
        z = 0.174 * (1050.0 - p) + 1.0
        if wind_deg is not None:
            if (315 <= wind_deg <= 360) or (0 <= wind_deg <= 45):
                z -= 1.0
            elif 135 <= wind_deg <= 225:
                z += 1.0
        if month in (12, 1, 2):
            z -= 1.0
        elif month in (6, 7, 8):
            z += 0.5

        z_idx = max(1, min(10, int(round(z))))
        letters = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
        letter = letters[z_idx - 1]

    elif diff <= -0.8:
        # Pressione in calo: Z = 0.155 * (1050 - P) + 18 (18..26 -> R..Z)
        z = 0.155 * (1050.0 - p) + 18.0
        if wind_deg is not None:
            if 135 <= wind_deg <= 225: # venti meridionali più umidi
                z += 1.0
            elif (315 <= wind_deg <= 360) or (0 <= wind_deg <= 45):
                z -= 1.0
        if month in (10, 11, 3, 4):
            z += 0.5

        z_idx = max(18, min(26, int(round(z))))
        letters = ["R", "S", "T", "U", "V", "W", "X", "Y", "Z"]
        letter = letters[z_idx - 18]

    else:
        # Pressione costante: formula barometrica calibrata Negretti & Zambra
        # A 1025+ hPa -> K (Bello stabile)
        # A 1018-1024 hPa -> L (Prevalentemente soleggiato)
        # A 1012-1017 hPa -> M (Variabile con ampie schiarite)
        # A 1006-1011 hPa -> N (Variabile con possibili rovesci)
        # A 1000-1005 hPa -> O (Variabile a tratti instabile)
        # A 994-999 hPa -> P (Instabile con piogge a intervalli)
        # Sotto 994 hPa -> Q (Variabile con brevi intervalli asciutti)
        if p >= 1025.0:
            letter = "K"
        elif p >= 1018.0:
            letter = "L"
        elif p >= 1012.0:
            letter = "M"
        elif p >= 1006.0:
            letter = "N"
        elif p >= 1000.0:
            letter = "O"
        elif p >= 994.0:
            letter = "P"
        else:
            letter = "Q"

        # Correzioni vento/stagione per trend stazionario
        letters_steady = ["K", "L", "M", "N", "O", "P", "Q"]
        curr_idx = letters_steady.index(letter)
        if wind_deg is not None:
            if (315 <= wind_deg <= 360) or (0 <= wind_deg <= 45):
                curr_idx = max(0, curr_idx - 1)
            elif 135 <= wind_deg <= 225:
                curr_idx = min(len(letters_steady) - 1, curr_idx + 1)
        letter = letters_steady[curr_idx]

    res = ZAMBRETTI_TEXTS.get(letter, ZAMBRETTI_TEXTS["M"]).copy()
    res["letter"] = letter
    res["confidence"] = "alta" if abs(diff) >= 0.5 else "media"
    return res


# ---------------------------------------------------------------------------
# 2. INDICI DI COMFORT & CONSIGLI PRATICI PER LA CASA
# ---------------------------------------------------------------------------

def evaluate_window_ventilation(
    temp_out: Optional[float],
    hum_out: Optional[float],
    temp_in: Optional[float],
    hum_in: Optional[float],
    rain_rate: Optional[float] = 0.0,
    air_quality: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Determina se conviene aprire o chiudere le finestre confrontando clima interno ed esterno
    e incrociando i dati di Qualità dell'Aria (PM2.5, PM10, AQI) e Pollini.
    """
    if rain_rate and rain_rate > 0.1:
        return {
            "status": "close",
            "icon": "🌧️",
            "badge_class": "badge-danger",
            "title": "Finestre Chiuse",
            "desc": "Pioggia in corso all'esterno."
        }

    # Verifica Qualità dell'Aria (CAMS)
    aqi_warning = None
    if air_quality:
        eaqi_val = air_quality.get("eaqi", {}).get("value", 1)
        pm25_val = air_quality.get("pollutants", {}).get("pm2_5", {}).get("val")
        dominant_pollen = air_quality.get("dominant_pollen", {})
        
        if pm25_val is not None and pm25_val >= 35.0:
            aqi_warning = f"Qualità aria scadente all'esterno (PM2.5: {pm25_val} µg/m³): sconsigliato arieggiare o limitare a brevissimo ricambio."
        elif eaqi_val >= 4:
            aqi_warning = "Inquinamento atmosferico elevato all'esterno: meglio tenere chiuso o usare purificatore d'aria."
        elif dominant_pollen.get("severity_score", 0) >= 3:
            aqi_warning = f"Allerta allergeni: concentrazione elevata di pollini ({dominant_pollen.get('name')})."

    if temp_out is None or temp_in is None:
        return {
            "status": "neutral",
            "icon": "🪟",
            "badge_class": "badge-neutral",
            "title": "Aerazione Normale",
            "desc": aqi_warning or "Sensori interni o esterni in attesa di sincronizzazione."
        }

    diff_temp = round(temp_out - temp_in, 1)

    # Se c'è allerta aria scadente e fuori è più fresco, segnala il trade-off intelligente!
    if aqi_warning and temp_out < temp_in - 1.0:
        return {
            "status": "close_aqi",
            "icon": "🪟 ⚠️",
            "badge_class": "badge-warning",
            "title": "Arieggiare con Cautela",
            "desc": f"Fuori fa più fresco ({temp_out}°C vs {temp_in}°C), ma {aqi_warning}"
        }

    # ESTATE / AMBIENTE CALDO (> 23°C dentro)
    if temp_in >= 23.0:
        if temp_out < temp_in - 1.2:
            return {
                "status": "open_cool",
                "icon": "🪟 🟢",
                "badge_class": "badge-success",
                "title": "Apri Finestre (Rinfresca!)",
                "desc": f"Fuori fa più fresco di dentro ({temp_out}°C vs {temp_in}°C, {diff_temp:+}°C). Ottimo per rinfrescare."
            }
        elif temp_out >= temp_in + 1.0:
            return {
                "status": "close_heat",
                "icon": "🪟 🔴",
                "badge_class": "badge-danger",
                "title": "Chiudi Finestre (Caldo Fuori)",
                "desc": f"Fuori è più caldo dell'interno ({temp_out}°C vs {temp_in}°C). Tieni chiuso per mantenere fresco."
            }
        else:
            return {
                "status": "neutral",
                "icon": "🪟 🟡",
                "badge_class": "badge-warning",
                "title": "Aerazione Facoltativa",
                "desc": f"Temperature simili ({temp_out}°C vs {temp_in}°C)."
            }

    # INVERNO / AMBIENTE FRESCO (< 20°C dentro)
    elif temp_in < 20.0:
        if temp_out < 12.0:
            return {
                "status": "short_air",
                "icon": "🪟 🟡",
                "badge_class": "badge-warning",
                "title": "Solo Ricambio Breve (5 min)",
                "desc": f"Fuori fa freddo ({temp_out}°C). Arieggia brevemente per evitare dispersioni termiche."
            }
        else:
            return {
                "status": "open_mild",
                "icon": "🪟 🟢",
                "badge_class": "badge-success",
                "title": "Buono per Arieggiare",
                "desc": f"Temperatura esterna mite ({temp_out}°C)."
            }

    # MEZZE STAGIONI (20°C - 23°C dentro)
    return {
        "status": "open_good",
        "icon": "🪟 🟢",
        "badge_class": "badge-success",
        "title": "Condizioni Ottimali",
        "desc": f"Clima confortevole ({temp_out}°C fuori, {temp_in}°C dentro)."
    }


def evaluate_laundry_index(
    temp_out: Optional[float],
    hum_out: Optional[float],
    wind_speed: Optional[float],
    solar_rad: Optional[float],
    rain_rate: Optional[float] = 0.0
) -> Dict[str, Any]:
    """
    Calcola l'indice di asciugatura del bucato all'aperto.
    """
    if rain_rate and rain_rate > 0.0:
        return {
            "score": 0,
            "status": "bad",
            "icon": "🧺 🌧️",
            "badge_class": "badge-danger",
            "title": "Bucato Sconsigliato",
            "time_estimate": "N/D (Pioggia)",
            "desc": "Rischio pioggia: non stendere all'aperto."
        }

    if temp_out is None or hum_out is None:
        return {
            "score": 50,
            "status": "neutral",
            "icon": "🧺",
            "badge_class": "badge-neutral",
            "title": "Indice Bucato",
            "time_estimate": "--",
            "desc": "In attesa di dati meteo."
        }

    t = float(temp_out)
    h = float(hum_out)
    w = float(wind_speed) if wind_speed is not None else 0.0
    s = float(solar_rad) if solar_rad is not None else 0.0

    # Calcolo punteggio 0-100
    # Temperatura: 10°C -> 10pt, 25°C -> 35pt, 35°C -> 45pt
    score_temp = max(0, min(45, (t - 5.0) * 1.5))
    # Umidità: 90% -> 0pt, 50% -> 25pt, 30% -> 35pt
    score_hum = max(0, min(35, (100.0 - h) * 0.5))
    # Vento: 5 km/h -> 5pt, 20 km/h -> 15pt
    score_wind = max(0, min(15, w * 0.75))
    # Sole: 100 W/m² -> 2pt, 800 W/m² -> 15pt
    score_sun = max(0, min(15, (s / 800.0) * 15))

    total_score = round(score_temp + score_hum + score_wind + score_sun)

    if h >= 88.0:
        total_score = min(total_score, 30)

    if total_score >= 70:
        vent_desc = f"buona ventilazione ({w} km/h)" if w >= 6.0 else f"bava di vento / brezza debole ({w} km/h)"
        return {
            "score": total_score,
            "status": "excellent",
            "icon": "🧺 🟢",
            "badge_class": "badge-success",
            "title": "Asciugatura Rapida",
            "time_estimate": "~1-2 ore",
            "desc": f"Ottimo: aria calda e asciutta ({h}%), {vent_desc}."
        }
    elif total_score >= 45:
        return {
            "score": total_score,
            "status": "moderate",
            "icon": "🧺 🟡",
            "badge_class": "badge-warning",
            "title": "Asciugatura Media",
            "time_estimate": "~3-5 ore",
            "desc": f"Discreto: asciugatura regolare (T {t}°C, UR {h}%, vento {w} km/h)."
        }
    else:
        return {
            "score": total_score,
            "status": "poor",
            "icon": "🧺 🔴",
            "badge_class": "badge-danger",
            "title": "Asciugatura Molto Lenta",
            "time_estimate": "> 6 ore / sconsigliato",
            "desc": f"Umidità elevata ({h}%) o aria stagnante/fredda."
        }


def calc_humidex(temp_c: Optional[float], dew_point_c: Optional[float]) -> Dict[str, Any]:
    """
    Indice Humidex canadese standard / Disagio bioclimatico da calore e umidità.
    Classificazione ufficiale Meteorological Service of Canada (MSC):
    - < 20: Confortevole / Nessun disagio
    - 20-29: Lieve disagio termico
    - 30-39: Disagio moderato (evitare sforzi prolungati nelle ore di punta)
    - 40-45: Forte disagio / Evitare sforzi fisici non necessari
    - >= 46: Pericoloso / Alto rischio colpo di calore
    """
    if temp_c is None or dew_point_c is None:
        return {"value": None, "level": "normal", "text": "Normale", "badge_class": "badge-neutral", "icon": "🌡️"}

    t = float(temp_c)
    dp = float(dew_point_c)

    # Formula Humidex: H = T + (5/9) * (e - 10) dove e = 6.11 * exp(5417.7530 * (1/273.16 - 1/(273.15 + dp)))
    e = 6.11 * math.exp(5417.7530 * ((1.0 / 273.16) - (1.0 / (273.15 + dp))))
    h = round(t + (5.0 / 9.0) * (e - 10.0), 1)

    if h < 20.0:
        return {"value": h, "level": "comfortable", "text": "Confortevole", "badge_class": "badge-success", "icon": "😊"}
    elif h < 30.0:
        return {"value": h, "level": "slight_discomfort", "text": "Lieve disagio", "badge_class": "badge-info", "icon": "🙂"}
    elif h < 40.0:
        return {"value": h, "level": "moderate_discomfort", "text": "Disagio moderato", "badge_class": "badge-warning", "icon": "😐"}
    elif h < 46.0:
        return {"value": h, "level": "severe_discomfort", "text": "Forte disagio / Evitare sforzi", "badge_class": "badge-danger", "icon": "🥵"}
    else:
        return {"value": h, "level": "extreme_danger", "text": "Pericoloso / Rischio colpo di calore", "badge_class": "badge-danger", "icon": "🚨"}


def evaluate_outdoor_activity(
    temp_c: Optional[float],
    wind_gust_kmh: Optional[float],
    rain_rate: Optional[float],
    uv_index: Optional[int],
    humidex_val: Optional[float] = None,
    lightning_dist: Optional[float] = None
) -> Dict[str, Any]:
    """
    Valutazione idoneità per attività all'aperto (running, bici, camminate, sport).
    Pesa in modo integrato: temperatura, indice humidex, vento/raffiche, pioggia, fulmini e radiazione UV.
    """
    # 1. Rischio Temporale / Fulmini
    if lightning_dist is not None and lightning_dist <= 25.0:
        return {
            "level": "bad",
            "icon": "🏃 ⚡",
            "badge_class": "badge-danger",
            "title": "Pericolo Temporale",
            "desc": f"Attività elettrica a {lightning_dist} km: sconsigliato stare all'aperto."
        }

    # 2. Pioggia
    if rain_rate and rain_rate > 0.5:
        return {
            "level": "bad",
            "icon": "🏃 🌧️",
            "badge_class": "badge-danger",
            "title": "Sconsigliato (Pioggia)",
            "desc": f"Precipitazioni in corso ({rain_rate} mm/h)."
        }
    
    # 3. Vento Forte
    if wind_gust_kmh and wind_gust_kmh >= 45.0:
        return {
            "level": "warning",
            "icon": "🏃 💨",
            "badge_class": "badge-warning",
            "title": "Vento Forte",
            "desc": f"Raffiche sostenute fino a {wind_gust_kmh} km/h."
        }

    t = float(temp_c) if temp_c is not None else 20.0
    h_val = float(humidex_val) if humidex_val is not None else t
    uv = uv_index or 0
    uv_note = f" • Protezione solare alta (UV {uv})" if uv >= 6 else ""

    # 4. Caldo Estremo / Canicola (Humidex >= 40 o T >= 35°C)
    if t >= 35.0 or h_val >= 40.0:
        return {
            "level": "bad",
            "icon": "🏃 🔥",
            "badge_class": "badge-danger",
            "title": "Caldo Eccessivo / Sconsigliato",
            "desc": f"Temperatura {t}°C (Humidex {h_val}): alto rischio colpi di calore, rimandare a tarda sera{uv_note}."
        }

    # 5. Caldo Moderato / Afa (Humidex >= 35 o T >= 30°C)
    if t >= 30.0 or h_val >= 35.0:
        return {
            "level": "warning",
            "icon": "🏃 🟡",
            "badge_class": "badge-warning",
            "title": "Caldo Intenso / Attività Leggera",
            "desc": f"Clima caldo ({t}°C, Humidex {h_val}): evitare sport intenso nelle ore centrali, idratarsi spesso{uv_note}."
        }

    # 6. Freddo Intenso / Gelo (T <= 0°C)
    if t <= 0.0:
        return {
            "level": "warning",
            "icon": "🏃 ❄️",
            "badge_class": "badge-warning",
            "title": "Gelo Esterno",
            "desc": f"Temperatura sottozero ({t}°C): attenzione a fondo stradale scivoloso o ghiaccio."
        }

    # 7. Condizioni Ottimali
    return {
        "level": "excellent",
        "icon": "🏃 🟢",
        "badge_class": "badge-success",
        "title": "Condizioni Favorevoli",
        "desc": f"Clima gradevole per sport e passeggiate ({t}°C){uv_note}."
    }


# ---------------------------------------------------------------------------
# 3. EFFEMERIDI ASTRONOMICHE (Alba, Tramonto, Sole e Luna)
# ---------------------------------------------------------------------------

def calc_sun_ephemeris(lat: float, lon: float, current_dt: Optional[datetime] = None, tz_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Calcola gli orari di Alba e Tramonto e la progressione della luce solare odierna
    espressi nel fuso orario locale della stazione meteo (default Europe/Rome).
    Algoritmo solare NOAA standard ad alta precisione con gestione automatica Ora Legale/Solare.
    """
    tz = get_station_tz(tz_name)
    if current_dt is None:
        current_dt = datetime.now(tz)
    elif current_dt.tzinfo is None:
        current_dt = current_dt.replace(tzinfo=tz)
    else:
        current_dt = current_dt.astimezone(tz)

    # Giorno dell'anno
    day_of_year = current_dt.timetuple().tm_yday
    
    # Declinazione solare approssimata (radianti)
    gamma = 2.0 * math.pi / 365.0 * (day_of_year - 1 + (12.0 - 12.0) / 24.0)
    
    # Equazione del tempo (in minuti)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma) \
             - 0.014615 * math.cos(2.0 * gamma) - 0.040849 * math.sin(2.0 * gamma))
    
    # Declinazione solare (radianti)
    decl = 0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma) \
           - 0.006758 * math.cos(2.0 * gamma) + 0.000907 * math.sin(2.0 * gamma) \
           - 0.002697 * math.cos(3.0 * gamma) + 0.00148 * math.sin(3.0 * gamma)

    lat_rad = math.radians(lat)
    
    # Angolo zenitale per alba/tramonto (90.833° tiene conto della rifrazione atmosferica)
    zenith = math.radians(90.833)
    
    try:
        cos_ha = (math.cos(zenith) / (math.cos(lat_rad) * math.cos(decl))) - (math.tan(lat_rad) * math.tan(decl))
        cos_ha = max(-1.0, min(1.0, cos_ha))
        ha_deg = math.degrees(math.acos(cos_ha))
    except Exception:
        ha_deg = 90.0

    # Orario solare medio UTC in minuti dal mezzogiorno
    # Mezzogiorno solare UTC = 720 - (4 * lon) - eqtime
    solar_noon_utc_min = 720.0 - (4.0 * lon) - eqtime
    
    sunrise_utc_min = solar_noon_utc_min - (ha_deg * 4.0)
    sunset_utc_min = solar_noon_utc_min + (ha_deg * 4.0)
    
    # Offset fuso orario locale calcolato per il momento esatto corrente (CET +1 / CEST +2)
    offset_sec = current_dt.utcoffset().total_seconds() if current_dt.utcoffset() is not None else 3600.0
    local_offset_hours = offset_sec / 3600.0
    
    sunrise_local_min = sunrise_utc_min + (local_offset_hours * 60.0)
    sunset_local_min = sunset_utc_min + (local_offset_hours * 60.0)
    solar_noon_local_min = solar_noon_utc_min + (local_offset_hours * 60.0)
    
    # Formatta in HH:MM
    sr_h = int(sunrise_local_min // 60) % 24
    sr_m = int(sunrise_local_min % 60)
    ss_h = int(sunset_local_min // 60) % 24
    ss_m = int(sunset_local_min % 60)
    sn_h = int(solar_noon_local_min // 60) % 24
    sn_m = int(solar_noon_local_min % 60)
    
    sunrise_str = f"{sr_h:02d}:{sr_m:02d}"
    sunset_str = f"{ss_h:02d}:{ss_m:02d}"
    solar_noon_str = f"{sn_h:02d}:{sn_m:02d}"
    
    daylight_minutes = int(sunset_local_min - sunrise_local_min)
    daylight_hours = daylight_minutes // 60
    daylight_rem_min = daylight_minutes % 60
    daylight_str = f"{daylight_hours}h {daylight_rem_min}m"
    
    # Calcolo stato luce attuale
    now_min = current_dt.hour * 60 + current_dt.minute
    is_daylight = sunrise_local_min <= now_min <= sunset_local_min
    
    if now_min < sunrise_local_min:
        mins_to_sunrise = int(sunrise_local_min - now_min)
        status_text = f"Alba tra {mins_to_sunrise // 60}h {mins_to_sunrise % 60}m"
        night_duration = max(1, 1440 - daylight_minutes)
        mins_since_sunset = int(1440 - sunset_local_min + now_min)
        sun_progress_pct = round((mins_since_sunset / night_duration) * 100)
    elif now_min > sunset_local_min:
        mins_since_sunset = int(now_min - sunset_local_min)
        night_duration = max(1, 1440 - daylight_minutes)
        status_text = "Sole tramontato"
        sun_progress_pct = round((mins_since_sunset / night_duration) * 100)
    else:
        mins_to_sunset = int(sunset_local_min - now_min)
        status_text = f"Tramonto tra {mins_to_sunset // 60}h {mins_to_sunset % 60}m"
        sun_progress_pct = round(((now_min - sunrise_local_min) / max(1, daylight_minutes)) * 100)

    return {
        "sunrise": sunrise_str,
        "sunset": sunset_str,
        "solar_noon": solar_noon_str,
        "daylight_duration": daylight_str,
        "is_daylight": is_daylight,
        "status_text": status_text,
        "sun_progress_pct": max(0, min(100, sun_progress_pct))
    }



def calc_moon_phase(target_date: Optional[date] = None, tz_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Calcola la fase lunare attuale, l'icona corrispondente e la percentuale di illuminazione.
    Metodo trigonometrico basato sull'epoca di riferimento (Luna Nuova del 6 Gennaio 2000).
    """
    if target_date is None:
        target_date = datetime.now(get_station_tz(tz_name)).date()

    # Giorno Giuliano approssimato
    year = target_date.year
    month = target_date.month
    day = target_date.day

    if month < 3:
        year -= 1
        month += 12

    a = int(year / 100)
    b = 2 - a + int(a / 4)
    jd = int(365.25 * (year + 4716)) + int(30.6001 * (month + 1)) + day + b - 1524.5

    # Giorni trascorsi dalla Luna Nuova di riferimento (JD 2451549.5)
    days_since_new = jd - 2451549.5
    synodic_month = 29.53058867
    phase_age = (days_since_new % synodic_month)
    phase_ratio = phase_age / synodic_month

    # Percentuale di illuminazione (0% = Nuova, 100% = Piena)
    illumination = round((1.0 - math.cos(phase_ratio * 2.0 * math.pi)) / 2.0 * 100)

    if phase_age < 1.84566:
        name = "Luna Nuova"
        icon = "🌑"
    elif phase_age < 5.53699:
        name = "Luna Crescente"
        icon = "🌒"
    elif phase_age < 9.22831:
        name = "Primo Quarto"
        icon = "🌓"
    elif phase_age < 12.91963:
        name = "Gibbosa Crescente"
        icon = "🌔"
    elif phase_age < 16.61096:
        name = "Luna Piena"
        icon = "🌕"
    elif phase_age < 20.30228:
        name = "Gibbosa Calante"
        icon = "🌖"
    elif phase_age < 23.99361:
        name = "Ultimo Quarto"
        icon = "🌗"
    elif phase_age < 27.68493:
        name = "Luna Calante"
        icon = "🌘"
    else:
        name = "Luna Nuova"
        icon = "🌑"

    return {
        "phase_name": name,
        "icon": icon,
        "age_days": round(phase_age, 1),
        "illumination_pct": illumination
    }


def calc_vpd(temp_c: Optional[float], humidity: Optional[float]) -> Optional[float]:
    """
    Calcola il VPD (Vapor Pressure Deficit / Deficit di Pressione di Vapore) in kPa.
    Formula agrometeorologica standard:
    VPsat = 0.61078 * exp((17.27 * T) / (T + 237.3))
    VPD = VPsat * (1 - RH / 100)
    """
    if temp_c is None or humidity is None:
        return None
    try:
        t = float(temp_c)
        rh = float(humidity)
        if rh < 0 or rh > 100:
            return None
        vp_sat = 0.61078 * math.exp((17.27 * t) / (t + 237.3))
        vpd = vp_sat * (1.0 - (rh / 100.0))
        return round(max(0.0, vpd), 2)
    except Exception:
        return None


def calc_beaufort_scale(wind_speed_kmh: Optional[float]) -> Dict[str, Any]:
    """
    Calcola il grado della scala Beaufort e la relativa descrizione in lingua italiana.
    """
    if wind_speed_kmh is None:
        return {"grade": None, "label": "--", "desc": "In attesa dati", "icon": "💨"}
    
    spd = float(wind_speed_kmh)
    if spd < 1.0:
        return {"grade": 0, "label": "Calma", "desc": "Fumo sale verticalmente, assenza di vento.", "icon": "🍃"}
    elif spd <= 5.0:
        return {"grade": 1, "label": "Bava di vento", "desc": "Il fumo indica la direzione, banderuole ferme.", "icon": "🍃"}
    elif spd <= 11.0:
        return {"grade": 2, "label": "Brezza leggera", "desc": "Si avverte il vento sulla pelle, foglie si muovono.", "icon": "🍃"}
    elif spd <= 19.0:
        return {"grade": 3, "label": "Brezza tesa", "desc": "Foglie e rami piccoli in movimento continuo.", "icon": "💨"}
    elif spd <= 28.0:
        return {"grade": 4, "label": "Vento moderato", "desc": "Solleva polvere e muove piccoli rami.", "icon": "💨"}
    elif spd <= 38.0:
        return {"grade": 5, "label": "Vento teso", "desc": "Piccoli alberi oscillano, onde con creste bianche.", "icon": "💨"}
    elif spd <= 49.0:
        return {"grade": 6, "label": "Vento fresco", "desc": "Grandi rami in movimento, fischi tra i cavi.", "icon": "💨"}
    elif spd <= 61.0:
        return {"grade": 7, "label": "Vento forte", "desc": "Interi alberi si muovono, camminare controvento è faticoso.", "icon": "⚠️ 💨"}
    elif spd <= 74.0:
        return {"grade": 8, "label": "Burrasca", "desc": "Rami spezzati, forte resistenza nel cammino.", "icon": "⚠️ 🌪️"}
    elif spd <= 88.0:
        return {"grade": 9, "label": "Burrasca forte", "desc": "Lievi danni a edifici e tetti (tegole rimosse).", "icon": "🚨 🌪️"}
    elif spd <= 102.0:
        return {"grade": 10, "label": "Tempesta", "desc": "Alberi sradicati, danni considerevoli a strutture.", "icon": "🚨 🌪️"}
    elif spd <= 117.0:
        return {"grade": 11, "label": "Fortunale", "desc": "Danni estesi e gravi.", "icon": "🚨 🌪️"}
    else:
        return {"grade": 12, "label": "Uragano", "desc": "Devastazione e danni catastrofici.", "icon": "🚨 🌀"}


# ---------------------------------------------------------------------------
# 5. MOTORE STATO ATMOSFERICO & ANIMAZIONE CIELO IN TEMPO REALE
# ---------------------------------------------------------------------------

def calc_current_weather_condition(
    temp_c: Optional[float],
    humidity: Optional[float],
    dew_point_c: Optional[float],
    rain_rate: Optional[float],
    solar_rad: Optional[float],
    uv_index: Optional[int],
    wind_spd: Optional[float],
    wind_gust: Optional[float],
    lightning_dist: Optional[float],
    sun_ephemeris: Optional[Dict[str, Any]] = None,
    zambretti: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Sintetizza in tempo reale le letture dei sensori e le effemeridi per determinare
    lo stato visivo del cielo, il tema cromatico e l'animazione grafica principale.
    """
    is_daylight = sun_ephemeris.get("is_daylight", True) if sun_ephemeris else True
    r_rate = float(rain_rate) if rain_rate is not None else 0.0
    s_rad = float(solar_rad) if solar_rad is not None else 0.0
    uv = int(uv_index) if uv_index is not None else 0
    w_spd = float(wind_spd) if wind_spd is not None else 0.0
    w_gst = float(wind_gust) if wind_gust is not None else 0.0
    hum = float(humidity) if humidity is not None else 50.0
    dp = float(dew_point_c) if dew_point_c is not None else 10.0
    t = float(temp_c) if temp_c is not None else 20.0

    z_letter = zambretti.get("letter", "M") if zambretti else "M"

    # 1. Temporale con fulmini
    if (lightning_dist is not None and lightning_dist <= 25.0) and (r_rate > 0.2 or w_gst >= 35.0):
        return {
            "code": "thunderstorm",
            "title": "Temporale con Attività Elettrica",
            "icon": "⛈️",
            "desc": f"Scariche a {lightning_dist} km • Rovesci e forti raffiche ({w_gst} km/h)",
            "sky_theme": "theme-thunderstorm",
            "is_daylight": is_daylight,
            "animation": "storm"
        }

    # 2. Pioggia Forte / Nubifragio
    if r_rate >= 8.0:
        return {
            "code": "heavy_rain",
            "title": "Pioggia Battente / Nubifragio",
            "icon": "🌧️",
            "desc": f"Precipitazioni intense in corso: rateo di {r_rate} mm/h",
            "sky_theme": "theme-rain",
            "is_daylight": is_daylight,
            "animation": "rain-heavy"
        }

    # 3. Pioggia Moderata
    if r_rate >= 1.0:
        return {
            "code": "rain",
            "title": "Pioggia in Corso",
            "icon": "🌧️",
            "desc": f"Pioggia continua ({r_rate} mm/h)",
            "sky_theme": "theme-rain",
            "is_daylight": is_daylight,
            "animation": "rain"
        }

    # 4. Pioviggine / Gocce
    if r_rate > 0.0:
        return {
            "code": "drizzle",
            "title": "Pioviggine Debole",
            "icon": "🌦️",
            "desc": f"Deboli gocce intermittenti ({r_rate} mm/h)",
            "sky_theme": "theme-rain",
            "is_daylight": is_daylight,
            "animation": "rain-light"
        }

    # 5. Vento Forte / Burrasca
    if w_gst >= 50.0 or w_spd >= 35.0:
        return {
            "code": "windy",
            "title": "Vento Intenso & Burrasca",
            "icon": "💨",
            "desc": f"Raffiche sostenute fino a {w_gst} km/h (Vento medio: {w_spd} km/h)",
            "sky_theme": "theme-windy",
            "is_daylight": is_daylight,
            "animation": "wind"
        }

    # 6. Nebbia / Visibilità ridotta
    if hum >= 96.0 and abs(t - dp) <= 0.6 and s_rad < 80.0:
        return {
            "code": "fog",
            "title": "Nebbia / Foschia Densa",
            "icon": "🌫️",
            "desc": "Umidità saturata con forte riduzione della visibilità",
            "sky_theme": "theme-cloudy",
            "is_daylight": is_daylight,
            "animation": "fog"
        }

    # 7. Diurno
    if is_daylight:
        if s_rad >= 350.0 or uv >= 3:
            return {
                "code": "clear_day",
                "title": "Cielo Sereno & Soleggiato",
                "icon": "☀️",
                "desc": f"Sole splendente • Radiazione {int(s_rad)} W/m² (UV {uv})",
                "sky_theme": "theme-clear-day",
                "is_daylight": True,
                "animation": "sun"
            }
        elif s_rad >= 120.0 or z_letter in ("B", "C", "D", "L", "M"):
            return {
                "code": "partly_cloudy_day",
                "title": "Poco Nuvoloso / Schiarite",
                "icon": "🌤️",
                "desc": "Alternanza di sole e nuvole sparse passeggere",
                "sky_theme": "theme-partly-cloudy-day",
                "is_daylight": True,
                "animation": "sun-clouds"
            }
        else:
            return {
                "code": "cloudy",
                "title": "Cielo Nuvoloso / Coperto",
                "icon": "☁️",
                "desc": "Copertura nuvolosa uniforme, assenza di precipitazioni",
                "sky_theme": "theme-cloudy",
                "is_daylight": True,
                "animation": "clouds"
            }

    # 8. Notturno
    else:
        if z_letter in ("A", "B", "K", "L") or hum < 80.0:
            return {
                "code": "clear_night",
                "title": "Notte Serena & Stellata",
                "icon": "🌙",
                "desc": "Cielo notturno sgombro con ottima limpidezza e visibilità",
                "sky_theme": "theme-clear-night",
                "is_daylight": False,
                "animation": "stars"
            }
        elif z_letter in ("C", "D", "E", "F", "M", "N"):
            return {
                "code": "partly_cloudy_night",
                "title": "Notte con Nubi Sparse",
                "icon": "☁️🌙",
                "desc": "Cielo notturno parzialmente velato da nubi alte o passeggere",
                "sky_theme": "theme-partly-cloudy-night",
                "is_daylight": False,
                "animation": "stars-clouds"
            }
        else:
            return {
                "code": "cloudy_night",
                "title": "Notte Coperta",
                "icon": "☁️",
                "desc": "Cielo notturno uniformemente coperto da nuvole",
                "sky_theme": "theme-cloudy",
                "is_daylight": False,
                "animation": "clouds"
            }


def evaluate_indoor_comfort(
    temp_in_c: Optional[float],
    humidity_in: Optional[float],
    temp_out_c: Optional[float] = None
) -> Dict[str, Any]:
    """
    Valuta il microclima interno di casa (temperatura, umidità, delta vs esterno, benessere igrometrico).
    """
    if temp_in_c is None or humidity_in is None:
        return {
            "status": "unknown",
            "icon": "🏠",
            "badge_class": "badge-neutral",
            "title": "In attesa dati",
            "desc": "Nessuna lettura interna disponibile.",
            "delta_text": "--",
            "diff_c": None
        }
    
    t = float(temp_in_c)
    h = float(humidity_in)
    
    delta_str = ""
    diff_val = None
    if temp_out_c is not None:
        diff_val = round(t - float(temp_out_c), 1)
        if diff_val > 0:
            delta_str = f"Casa più calda dell'esterno (+{diff_val}°C)"
        elif diff_val < 0:
            delta_str = f"Casa più fresca dell'esterno ({diff_val}°C)"
        else:
            delta_str = "Temperatura interna uguale all'esterno (Δ 0.0°C)"
            
    # Benessere termico e igrometrico (comfort standard ISO 7730 / ASHRAE 55)
    if 20.0 <= t <= 26.0 and 40.0 <= h <= 60.0:
        return {
            "status": "optimal",
            "icon": "🟢",
            "badge_class": "badge-success",
            "title": "Comfort Ottimale",
            "desc": f"Microclima interno ideale ({t}°C, {h}% UR). {delta_str}",
            "delta_text": delta_str,
            "diff_c": diff_val
        }
    elif t > 27.5:
        return {
            "status": "warm",
            "icon": "🔴",
            "badge_class": "badge-danger",
            "title": "Ambiente Caldo",
            "desc": f"Temperatura interna alta ({t}°C). {delta_str}",
            "delta_text": delta_str,
            "diff_c": diff_val
        }
    elif t < 18.0:
        return {
            "status": "cold",
            "icon": "🔵",
            "badge_class": "badge-info",
            "title": "Ambiente Fresco/Freddo",
            "desc": f"Temperatura interna bassa ({t}°C). {delta_str}",
            "delta_text": delta_str,
            "diff_c": diff_val
        }
    elif h > 65.0:
        return {
            "status": "humid",
            "icon": "🟡",
            "badge_class": "badge-warning",
            "title": "Umidità Elevata",
            "desc": f"Umidità interna al {h}%: arieggiare o deumidificare.",
            "delta_text": delta_str,
            "diff_c": diff_val
        }
    elif h < 35.0:
        return {
            "status": "dry",
            "icon": "🟡",
            "badge_class": "badge-warning",
            "title": "Aria Secca",
            "desc": f"Umidità bassa ({h}%): consigliato umidificare.",
            "delta_text": delta_str,
            "diff_c": diff_val
        }
    else:
        return {
            "status": "good",
            "icon": "🟢",
            "badge_class": "badge-success",
            "title": "Condizioni Buone",
            "desc": f"Clima interno gradevole ({t}°C, {h}%). {delta_str}",
            "delta_text": delta_str,
            "diff_c": diff_val
        }


# ---------------------------------------------------------------------------
# 7. EVAPOTRASPIRAZIONE & IRRIGAZIONE INTELLIGENTE WH51
# ---------------------------------------------------------------------------

def calc_evapotranspiration(
    temp_c: Optional[float],
    humidity: Optional[float],
    solar_rad: Optional[float] = None,
    wind_kmh: Optional[float] = 5.0,
    temp_min_c: Optional[float] = None,
    temp_max_c: Optional[float] = None
) -> float:
    """
    Stima l'Evapotraspirazione di Riferimento Giornaliera (ET₀ in mm/giorno)
    usando il metodo standard FAO-56 / Hargreaves-Samani e radiazione solare.
    """
    if temp_c is None:
        return 3.0
    
    t_mean = float(temp_c)
    h = float(humidity) if humidity is not None else 50.0
    w_ms = (float(wind_kmh) if wind_kmh is not None else 5.0) / 3.6
    
    # Se abbiamo la radiazione solare istantanea o giornaliera
    if solar_rad is not None and solar_rad > 0:
        # Conversione stimata radiazione W/m² in MJ/m²/giorno
        # Un valore medio diurno di 400 W/m² corrisponde a ~17 MJ/m²/giorno
        rad_mj = max(5.0, min(32.0, (solar_rad / 25.0)))
    else:
        # Metodo Hargreaves con delta termico giornaliero
        t_max = temp_max_c if temp_max_c is not None else (t_mean + 5.0)
        t_min = temp_min_c if temp_min_c is not None else (t_mean - 5.0)
        delta_t = max(2.0, t_max - t_min)
        # Radiazione extraterrestre stimata per lat ~39°N
        ra = 30.0
        rad_mj = 0.16 * math.sqrt(delta_t) * ra

    # Formula Makkink / Priestley-Taylor semplificata per ET0
    slope = 4098.0 * (0.6108 * math.exp((17.27 * t_mean) / (t_mean + 237.3))) / ((t_mean + 237.3) ** 2)
    gamma = 0.067
    
    et0 = 0.7 * (slope / (slope + gamma)) * (rad_mj / 2.45)
    
    # Correzione per vento e deficit igrometrico
    if h < 45.0:
        et0 *= 1.15
    elif h > 75.0:
        et0 *= 0.85
        
    if w_ms > 4.0:
        et0 *= 1.1

    return round(max(0.5, min(9.5, et0)), 1)


def evaluate_smart_irrigation(
    soil_moisture_pct: Optional[float],
    temp_c: Optional[float],
    solar_rad: Optional[float] = None,
    rain_forecast_24h_mm: float = 0.0,
    recent_rain_48h_mm: float = 0.0,
    et_mm: Optional[float] = None
) -> Dict[str, Any]:
    """
    Sistema decisionale per l'irrigazione intelligente (Sensore WH51 + Meteo Predittivo):
    Incrocia:
    1. Umidità del suolo WH51 (%)
    2. Evapotraspirazione stimata (mm/giorno)
    3. Pioggia prevista nelle prossime 24h
    4. Pioggia caduta nelle ultime 48h
    """
    if et_mm is None:
        et_mm = calc_evapotranspiration(temp_c, 50.0, solar_rad)

    # Se non c'è sensore WH51 collegato, usa stima agrometeo standard
    has_sensor = soil_moisture_pct is not None
    sm = float(soil_moisture_pct) if has_sensor else 40.0

    # 1. PIOGGIA PREVISTA IMMINENTE
    if rain_forecast_24h_mm >= 4.0:
        return {
            "has_sensor": has_sensor,
            "soil_moisture_pct": round(sm, 1) if has_sensor else None,
            "et_mm": et_mm,
            "rain_forecast_24h_mm": round(rain_forecast_24h_mm, 1),
            "status": "skip_rain",
            "icon": "🌧️ 🛑",
            "badge_class": "badge-info",
            "title": "Irrigazione NON Necessaria",
            "desc": f"Previsti {rain_forecast_24h_mm:.1f} mm di pioggia nelle prossime 24h: risparmia acqua, la natura irrigherà per te!",
            "liters_sqm_rec": 0.0
        }

    # 2. PIOGGE RECENTI ABBONDANTI
    if recent_rain_48h_mm >= 8.0:
        return {
            "has_sensor": has_sensor,
            "soil_moisture_pct": round(sm, 1) if has_sensor else None,
            "et_mm": et_mm,
            "rain_forecast_24h_mm": round(rain_forecast_24h_mm, 1),
            "status": "skip_recent",
            "icon": "💧 🟢",
            "badge_class": "badge-success",
            "title": "Suolo Ben Idratato",
            "desc": f"Accumulo recente di {recent_rain_48h_mm:.1f} mm nelle 48h. Riserva idrica del terreno ottimale.",
            "liters_sqm_rec": 0.0
        }

    # 3. TERRENO UMIDO / OTTIMALE (>= 32%)
    if sm >= 32.0:
        return {
            "has_sensor": has_sensor,
            "soil_moisture_pct": round(sm, 1) if has_sensor else None,
            "et_mm": et_mm,
            "rain_forecast_24h_mm": round(rain_forecast_24h_mm, 1),
            "status": "optimal",
            "icon": "🌱 🟢",
            "badge_class": "badge-success",
            "title": "Umidità Ideale",
            "desc": f"Umidità suolo al {sm:.0f}% (ET stimata: {et_mm} mm/die). Nessuna irrigazione richiesta oggi.",
            "liters_sqm_rec": 0.0
        }

    # 4. TERRENO SECCO (<= 30%) SENZA PIOGGIA PREVISTA -> CONSIGLIO IRRIGAZIONE
    rec_liters = round(max(2.0, min(6.0, et_mm * 0.9)), 1)
    return {
        "has_sensor": has_sensor,
        "soil_moisture_pct": round(sm, 1) if has_sensor else None,
        "et_mm": et_mm,
        "rain_forecast_24h_mm": round(rain_forecast_24h_mm, 1),
        "status": "water_needed",
        "icon": "🌱 💧",
        "badge_class": "badge-warning",
        "title": "Irrigazione Consigliata",
        "desc": f"Terreno secco ({sm:.0f}%), ET {et_mm} mm e pioggia assente. Consiglio: irrigare stasera circa {rec_liters} L/m².",
        "liters_sqm_rec": rec_liters
    }


# ---------------------------------------------------------------------------
# 8. GENERATORE INTELLIGENZA DINAMICA "COSA DEVO SAPERE ORA" (NOW HIGHLIGHTS)
# ---------------------------------------------------------------------------

def generate_now_highlights(
    latest: Dict[str, Any],
    analytics_ctx: Dict[str, Any],
    air_quality: Optional[Dict[str, Any]] = None,
    solar_forecast: Optional[Dict[str, Any]] = None,
    nowcasting: Optional[Dict[str, Any]] = None,
    aton_data: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Genera da 3 a 5 pillole sintetiche, intelligenti e azionabili in primo piano
    per rispondere subito alla domanda: "Cosa devo sapere adesso?".
    """
    highlights = []

    # 1. PILLOLA FINESTRE & AERAZIONE (con incrocio AQI)
    window_info = analytics_ctx.get("comfort", {}).get("window", {})
    w_status = window_info.get("status", "neutral")
    w_icon = "🪟"
    
    if "open" in w_status:
        highlights.append({
            "category": "windows",
            "icon": "🪟 🟢",
            "title": window_info.get("title", "Apri le finestre"),
            "subtitle": window_info.get("desc", "Ottimo per rinfrescare casa"),
            "badge_class": "badge-success",
            "action_text": "Aerazione"
        })
    elif "close" in w_status:
        highlights.append({
            "category": "windows",
            "icon": "🪟 🔴",
            "title": window_info.get("title", "Tieni le finestre chiuse"),
            "subtitle": window_info.get("desc", "Mantieni fresco l'interno"),
            "badge_class": "badge-danger",
            "action_text": "Isolamento"
        })
    else:
        highlights.append({
            "category": "windows",
            "icon": "🪟",
            "title": "Aerazione Regolare",
            "subtitle": window_info.get("desc", "Temperature interno/esterno simili"),
            "badge_class": "badge-neutral",
            "action_text": "Clima Casa"
        })

    # 2. PILLOLA NOWCASTING PIOGGIA
    if nowcasting:
        highlights.append({
            "category": "rain_nowcast",
            "icon": nowcasting.get("icon", "🌧️"),
            "title": nowcasting.get("headline", "Meteo stabile"),
            "subtitle": nowcasting.get("desc", "Monitoraggio radar live attivo"),
            "badge_class": f"badge-{nowcasting.get('status_class', 'info')}",
            "action_text": "Nowcasting"
        })

    # 3. PILLOLA ENERGIA & FOTOVOLTAICO / BATTERIA
    if aton_data and aton_data.get("soc") is not None:
        soc = int(aton_data.get("soc", 0))
        p_sol = aton_data.get("p_solare", 0)
        p_ut = aton_data.get("p_utenze", 0)
        
        if p_sol > p_ut and p_sol > 200:
            e_title = f"⚡ Casa Autosufficiente (Surplus {(p_sol - p_ut):.0f} W)"
            e_sub = f"Batteria al {soc}%. Ottimo momento per avviare elettrodomestici."
            e_badge = "badge-success"
            e_icon = "⚡ 🟢"
        elif soc <= 20:
            e_title = f"🔋 Batteria in Riserva ({soc}%)"
            e_sub = "Prelievo da rete o ricarica minima."
            e_badge = "badge-warning"
            e_icon = "🔋 🟡"
        else:
            e_title = f"🔋 Batteria Aton al {soc}%"
            e_sub = f"Produzione FV: {p_sol:.0f} W • Consumo casa: {p_ut:.0f} W."
            e_badge = "badge-info"
            e_icon = "🔋"

        highlights.append({
            "category": "energy",
            "icon": e_icon,
            "title": e_title,
            "subtitle": e_sub,
            "badge_class": e_badge,
            "action_text": "Energia"
        })
    elif solar_forecast:
        highlights.append({
            "category": "energy_forecast",
            "icon": "☀️ ⚡",
            "title": f"Previsione FV Domani: {solar_forecast.get('tomorrow_est_kwh', 0)} kWh",
            "subtitle": f"Finestra elettrodomestici consigliata: {solar_forecast.get('best_appliances_window', '11:00-15:00')}",
            "badge_class": "badge-info",
            "action_text": "Solar Forecast"
        })

    # 4. PILLOLA GIARDINO & IRRIGAZIONE WH51
    irrigation = analytics_ctx.get("irrigation_advice")
    if irrigation:
        highlights.append({
            "category": "irrigation",
            "icon": irrigation.get("icon", "🌱"),
            "title": irrigation.get("title", "Aiuola & Suolo"),
            "subtitle": irrigation.get("desc", "Gestione idrica del terreno"),
            "badge_class": irrigation.get("badge_class", "badge-neutral"),
            "action_text": "Irrigazione"
        })

    # 5. PILLOLA QUALITÀ DELL'ARIA & POLLINI (se presente allerta o eccellente)
    if air_quality:
        eaqi = air_quality.get("eaqi", {})
        dom_pollen = air_quality.get("dominant_pollen", {})
        if eaqi.get("value", 1) >= 3:
            highlights.append({
                "category": "air_quality",
                "icon": "🌬️ ⚠️",
                "title": f"Qualità Aria {eaqi.get('label')}",
                "subtitle": air_quality.get("window_advice", "Attenzione agli inquinanti"),
                "badge_class": eaqi.get("badge_class", "badge-warning"),
                "action_text": "Aria & CAMS"
            })
        elif dom_pollen.get("severity_score", 0) >= 3:
            highlights.append({
                "category": "pollen",
                "icon": "🌾 ⚠️",
                "title": f"Pollini Elevati: {dom_pollen.get('name')}",
                "subtitle": f"Livello {dom_pollen.get('level')}. Cautela per soggetti allergici.",
                "badge_class": "badge-warning",
                "action_text": "Allergeni"
            })

    return highlights[:5]



