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
    # Pressione in aumento (A)
    "A": {"icon": "☀️", "text": "Tempo stabile e soleggiato", "desc": "Anticiclone solido in consolidamento."},
    "B": {"icon": "🌤️", "text": "Bello, tempo asciutto e piacevole", "desc": "Condizioni ampiamente soleggiate."},
    "C": {"icon": "⛅", "text": "Miglioramento del tempo", "desc": "Tendenza a schiarite sempre più ampie."},
    "D": {"icon": "🌤️", "text": "Variabile con ampie schiarite", "desc": "Tempo in rapido miglioramento."},
    "E": {"icon": "🌦️", "text": "Instabilità passeggera in attenuazione", "desc": "Possibili isolati piovaschi in esaurimento."},
    "F": {"icon": "⛅", "text": "Miglioramento graduale", "desc": "Nubi residue ma tempo in miglioramento."},
    "G": {"icon": "🌦️", "text": "Variabile con brevi rovesci", "desc": "Possibili rovesci alternati a schiarite."},
    "H": {"icon": "🌧️", "text": "Piogge sparse in attenuazione", "desc": "Miglioramento atteso nelle prossime ore."},
    "I": {"icon": "🌧️", "text": "Pioggia intermittente in miglioramento", "desc": "Tendenza a cessazione dei fenomeni."},
    "J": {"icon": "⛈️", "text": "Forte instabilità in lento miglioramento", "desc": "Rovesci intensi ma in progressivo allontanamento."},

    # Pressione costante (B)
    "K": {"icon": "☀️", "text": "Bello stabile e asciutto", "desc": "Condizioni anticicloniche costanti."},
    "L": {"icon": "🌤️", "text": "Prevalentemente soleggiato", "desc": "Bel tempo persistente."},
    "M": {"icon": "⛅", "text": "Variabile e asciutto", "desc": "Alternanza di sole e nuvole innocue."},
    "N": {"icon": "🌦️", "text": "Variabile con possibili piovaschi", "desc": "Instabilità pomeridiana o locale."},
    "O": {"icon": "🌧️", "text": "Tempo piovoso a tratti", "desc": "Copertura compatta con piogge a intervalli."},
    "P": {"icon": "🌧️", "text": "Piogge persistenti", "desc": "Cielo coperto e precipitazioni diffuse."},
    "Q": {"icon": "⛈️", "text": "Maltempo e temporali", "desc": "Bassa pressione costante con temporali."},

    # Pressione in calo (C)
    "R": {"icon": "🌤️", "text": "Bello ma tendente al peggioramento", "desc": "Inizio di un calo barometrico."},
    "S": {"icon": "⛅", "text": "Nubi in aumento, peggioramento imminente", "desc": "Aumento della copertura nuvolosa."},
    "T": {"icon": "🌦️", "text": "Variabile con piogge in arrivo", "desc": "Peggioramento con prime precipitazioni."},
    "U": {"icon": "🌧️", "text": "Pioggia in arrivo nelle prossime ore", "desc": "Fronte perturbato in avvicinamento."},
    "V": {"icon": "🌧️", "text": "Pioggia e vento in rinforzo", "desc": "Peggioramento marcato con venti sostenuti."},
    "W": {"icon": "🌧️", "text": "Piogge diffuse e continue", "desc": "Forte perturbazione in transito."},
    "X": {"icon": "⛈️", "text": "Forte maltempo con temporali", "desc": "Rischio temporali forti e nubifragi."},
    "Y": {"icon": "🌪️", "text": "Burrasca / Vento forte e pioggia intensa", "desc": "Marcata depressione con venti tempestosi."},
    "Z": {"icon": "⚠️", "text": "Allerta tempesta violenta", "desc": "Crollo barometrico eccezionale, forte burrasca."}
}

def calc_zambretti_forecast(
    pressure_hpa: Optional[float],
    pressure_diff_3h: Optional[float],
    wind_deg: Optional[float] = None,
    month: Optional[int] = None
) -> Dict[str, Any]:
    """
    Calcola la previsione locale a 6-12 ore usando l'algoritmo di Zambretti.
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
    # diff > 0.8 hPa/3h -> In aumento (rising)
    # diff < -0.8 hPa/3h -> In calo (falling)
    # altrimenti -> Stabile (steady)
    
    # Range normalizzato (hPa a livello del mare) tipico 950 - 1050
    p = max(950.0, min(1050.0, p))

    if diff >= 0.8:
        # Pressione in aumento: Z = 0.174 * (1050 - P) + 1 (1..10 -> A..J)
        z = 0.174 * (1050.0 - p) + 1.0
        # Correzione vento (venti settentrionali favoriscono bel tempo nell'emisfero nord)
        if wind_deg is not None:
            if (315 <= wind_deg <= 360) or (0 <= wind_deg <= 45):
                z -= 1.0
            elif 135 <= wind_deg <= 225:
                z += 1.0
        # Correzione stagionale (inverno favorisce alta pressione fredda, estate temporali termoconvettivi)
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
            if 135 <= wind_deg <= 225: # venti meridionali carichi di umidità
                z += 1.0
            elif (315 <= wind_deg <= 360) or (0 <= wind_deg <= 45):
                z -= 1.0
        if month in (10, 11, 3, 4): # autunno/primavera più instabile
            z += 0.5

        z_idx = max(18, min(26, int(round(z))))
        letters = ["R", "S", "T", "U", "V", "W", "X", "Y", "Z"]
        letter = letters[z_idx - 18]

    else:
        # Pressione costante: Z = 0.169 * (1050 - P) + 11 (11..17 -> K..Q)
        z = 0.169 * (1050.0 - p) + 11.0
        z_idx = max(11, min(17, int(round(z))))
        letters = ["K", "L", "M", "N", "O", "P", "Q"]
        letter = letters[z_idx - 11]

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
    rain_rate: Optional[float] = 0.0
) -> Dict[str, Any]:
    """
    Determina se conviene aprire o chiudere le finestre confrontando clima interno ed esterno.
    """
    if rain_rate and rain_rate > 0.1:
        return {
            "status": "close",
            "icon": "🌧️",
            "badge_class": "badge-danger",
            "title": "Finestre Chiuse",
            "desc": "Pioggia in corso all'esterno."
        }

    if temp_out is None or temp_in is None:
        return {
            "status": "neutral",
            "icon": "🪟",
            "badge_class": "badge-neutral",
            "title": "Aerazione Normale",
            "desc": "Sensori interni o esterni in attesa di sincronizzazione."
        }

    diff_temp = round(temp_out - temp_in, 1)

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
        return {
            "score": total_score,
            "status": "excellent",
            "icon": "🧺 🟢",
            "badge_class": "badge-success",
            "title": "Asciugatura Rapida",
            "time_estimate": "~1-2 ore",
            "desc": f"Ottimo: aria asciutta ({h}%) e buona ventilazione ({w} km/h)."
        }
    elif total_score >= 45:
        return {
            "score": total_score,
            "status": "moderate",
            "icon": "🧺 🟡",
            "badge_class": "badge-warning",
            "title": "Asciugatura Media",
            "time_estimate": "~3-5 ore",
            "desc": f"Discreto: asciugatura regolare (T {t}°C, UR {h}%)."
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
    Indice Humidex canadese / Disagio bioclimatico estivo.
    """
    if temp_c is None or dew_point_c is None:
        return {"value": None, "level": "normal", "text": "Normale", "badge_class": "badge-neutral"}

    t = float(temp_c)
    dp = float(dew_point_c)

    # Formula Humidex: H = T + (5/9) * (e - 10) dove e = 6.11 * exp(5417.7530 * (1/273.16 - 1/(273.15 + dp)))
    e = 6.11 * math.exp(5417.7530 * ((1.0 / 273.16) - (1.0 / (273.15 + dp))))
    h = round(t + (5.0 / 9.0) * (e - 10.0), 1)

    if h < 27.0:
        return {"value": h, "level": "comfortable", "text": "Confortevole", "badge_class": "badge-success", "icon": "😊"}
    elif h < 35.0:
        return {"value": h, "level": "slight_discomfort", "text": "Afa leggera", "badge_class": "badge-warning", "icon": "😐"}
    elif h < 40.0:
        return {"value": h, "level": "discomfort", "text": "Afa intensa / Disagio", "badge_class": "badge-danger", "icon": "😓"}
    elif h < 46.0:
        return {"value": h, "level": "severe_discomfort", "text": "Forte disagio termico", "badge_class": "badge-danger", "icon": "🥵"}
    else:
        return {"value": h, "level": "extreme_danger", "text": "Afa estrema / Pericolosa", "badge_class": "badge-danger", "icon": "🚨"}


def evaluate_outdoor_activity(
    temp_c: Optional[float],
    wind_gust_kmh: Optional[float],
    rain_rate: Optional[float],
    uv_index: Optional[int]
) -> Dict[str, Any]:
    """
    Valutazione idoneità per attività all'aperto (running, bici, passeggiate).
    """
    if rain_rate and rain_rate > 0.5:
        return {"level": "bad", "icon": "🏃 🌧️", "badge_class": "badge-danger", "title": "Sconsigliato", "desc": "Pioggia in corso."}
    
    if wind_gust_kmh and wind_gust_kmh >= 45.0:
        return {"level": "warning", "icon": "🏃 💨", "badge_class": "badge-warning", "title": "Vento Forte", "desc": f"Raffiche fino a {wind_gust_kmh} km/h."}

    if temp_c is not None:
        if temp_c >= 35.0:
            return {"level": "bad", "icon": "🏃 🔥", "badge_class": "badge-danger", "title": "Troppo Caldo", "desc": "Rischio colpi di calore, rimandare a sera."}
        elif temp_c <= 0.0:
            return {"level": "warning", "icon": "🏃 ❄️", "badge_class": "badge-warning", "title": "Gelo Esterno", "desc": "Attenzione a fondo stradale scivoloso o ghiaccio."}

    uv = uv_index or 0
    uv_note = f" (Protezione solare UV {uv})" if uv >= 6 else ""

    return {
        "level": "excellent",
        "icon": "🏃 🟢",
        "badge_class": "badge-success",
        "title": "Condizioni Favorevoli",
        "desc": f"Tempo piacevole per sport e passeggiate{uv_note}."
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
    
    # Formatta in HH:MM
    sr_h = int(sunrise_local_min // 60) % 24
    sr_m = int(sunrise_local_min % 60)
    ss_h = int(sunset_local_min // 60) % 24
    ss_m = int(sunset_local_min % 60)
    
    sunrise_str = f"{sr_h:02d}:{sr_m:02d}"
    sunset_str = f"{ss_h:02d}:{ss_m:02d}"
    
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
        sun_progress_pct = 0
    elif now_min > sunset_local_min:
        status_text = "Sole tramontato"
        sun_progress_pct = 100
    else:
        mins_to_sunset = int(sunset_local_min - now_min)
        status_text = f"Tramonto tra {mins_to_sunset // 60}h {mins_to_sunset % 60}m"
        sun_progress_pct = round(((now_min - sunrise_local_min) / max(1, daylight_minutes)) * 100)

    return {
        "sunrise": sunrise_str,
        "sunset": sunset_str,
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
            "delta_text": "--"
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


