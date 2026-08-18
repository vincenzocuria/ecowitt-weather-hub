// Utility per formattare date
function formatDate(isoStr) {
    if (!isoStr) return "--";
    try {
        const d = new Date(isoStr);
        return d.toLocaleString('it-IT', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    } catch {
        return isoStr;
    }
}

// Live polling per la Dashboard principale
function startDashboardPolling() {
    function update() {
        fetch('/api/live')
            .then(r => r.json())
            .then(d => {
                if (!d) return;

                // Aggiorna badge stato stazione
                const badgeEl = document.getElementById('status-badge');
                if (badgeEl && d.status_info) {
                    badgeEl.className = 'status-pill ' + d.status_info.badge_class;
                    badgeEl.innerText = d.status_info.text;
                }

                const mobLiveInd = document.getElementById('mobile-live-indicator');
                if (mobLiveInd && d.status_info) {
                    mobLiveInd.innerText = d.status_info.text.toUpperCase();
                }

                if (d.message) return;
                
                // Aggiorna timestamp
                const tsEl = document.getElementById('ts');
                if (tsEl) tsEl.innerText = formatDate(d.timestamp);

                // Esterno
                if (d.temp_c !== undefined) {
                    const el = document.getElementById('temp_c');
                    if (el) el.innerText = d.temp_c;
                    const heroT = document.getElementById('hero_temp_val');
                    if (heroT) heroT.innerText = d.temp_c;
                }
                if (d.apparent_temp_c !== undefined) {
                    const el = document.getElementById('apparent_temp_badge');
                    if (el) el.innerText = 'Percepita: ' + d.apparent_temp_c + '°C';
                    const heroApp = document.getElementById('hero_apparent_val');
                    if (heroApp) heroApp.innerText = d.apparent_temp_c + '°C';
                }
                if (d.humidity !== undefined) {
                    const el = document.getElementById('humidity');
                    if (el) el.innerText = d.humidity + ' %';
                    const heroHum = document.getElementById('hero_hum_val');
                    if (heroHum) heroHum.innerText = d.humidity + '%';
                }
                if (d.dew_point_c !== undefined) {
                    const el = document.getElementById('dew_point');
                    if (el) el.innerText = d.dew_point_c + ' °C';
                    const heroDew = document.getElementById('hero_dew_val');
                    if (heroDew) heroDew.innerText = d.dew_point_c;
                }
                if (d.pressure_rel_hpa !== undefined) {
                    const el = document.getElementById('press_rel');
                    if (el) el.innerText = d.pressure_rel_hpa + ' hPa';
                    const heroPress = document.getElementById('hero_press_val');
                    if (heroPress) heroPress.innerHTML = d.pressure_rel_hpa + ' <small>hPa</small>';
                }
                if (d.pressure_trend && d.pressure_trend.text) {
                    const el = document.getElementById('press_trend');
                    if (el) el.innerText = d.pressure_trend.text;
                    const heroTrend = document.getElementById('hero_trend_val');
                    if (heroTrend) heroTrend.innerText = d.pressure_trend.text;
                }

                // Vento & Bussola
                if (d.wind_speed_kmh !== undefined) {
                    const el = document.getElementById('wind_spd');
                    if (el) el.innerText = d.wind_speed_kmh;
                    const heroWind = document.getElementById('hero_wind_val');
                    if (heroWind) heroWind.innerHTML = d.wind_speed_kmh + ' <small>km/h</small>';
                }
                if (d.wind_gust_kmh !== undefined) {
                    const el = document.getElementById('wind_gst');
                    if (el) el.innerText = d.wind_gust_kmh + ' km/h';
                }
                if (d.max_daily_gust_kmh !== undefined) {
                    const el = document.getElementById('max_gust');
                    if (el) el.innerText = d.max_daily_gust_kmh + ' km/h';
                    const heroGust = document.getElementById('hero_gust_val');
                    if (heroGust) heroGust.innerText = d.max_daily_gust_kmh;
                }
                if (d.wind_dir_deg !== undefined) {
                    const el = document.getElementById('wind_dir');
                    if (el) el.innerText = d.wind_dir_deg + '°';
                    const needle = document.getElementById('compass_needle');
                    if (needle) {
                        needle.style.transform = 'rotate(' + d.wind_dir_deg + 'deg)';
                    }
                }

                // Pioggia
                if (d.rain_rate_mm_hr !== undefined) {
                    const el = document.getElementById('rain_rate');
                    if (el) el.innerText = d.rain_rate_mm_hr;
                    const heroRate = document.getElementById('hero_rain_rate_val');
                    if (heroRate) heroRate.innerText = d.rain_rate_mm_hr;
                }
                if (d.daily_rain_mm !== undefined) {
                    const el = document.getElementById('rain_day');
                    if (el) el.innerText = d.daily_rain_mm + ' mm';
                    const heroRainDay = document.getElementById('hero_rain_day_val');
                    if (heroRainDay) heroRainDay.innerHTML = d.daily_rain_mm + ' <small>mm</small>';
                }
                if (d.yearly_rain_mm !== undefined) {
                    const el = document.getElementById('rain_year');
                    if (el) el.innerText = d.yearly_rain_mm + ' mm';
                }

                // Sole & UV
                if (d.solar_radiation !== undefined) {
                    const el = document.getElementById('solar');
                    if (el) el.innerText = d.solar_radiation + ' W/m²';
                }
                if (d.uv_index !== undefined) {
                    const el = document.getElementById('uv_val');
                    if (el) el.innerText = d.uv_index;
                    const pointer = document.getElementById('uv_pointer');
                    if (pointer) {
                        const pct = Math.min(100, Math.round((d.uv_index / 12) * 100));
                        pointer.style.left = pct + '%';
                    }
                }
                if (d.vpd !== undefined && d.vpd !== null) {
                    const el = document.getElementById('vpd');
                    if (el) el.innerText = d.vpd + ' kPa';
                } else if (d.vpd === null) {
                    const el = document.getElementById('vpd');
                    if (el) el.innerText = '-- kPa';
                }

                // Clima Interno (Casa)
                if (d.temp_in_c !== undefined) {
                    const el = document.getElementById('temp_in_c');
                    if (el) el.innerText = d.temp_in_c;
                }
                if (d.humidity_in !== undefined) {
                    const el = document.getElementById('humidity_in');
                    if (el) el.innerText = d.humidity_in + ' %';
                }

                // Fulmini
                if (d.lightning_distance_km !== undefined && d.lightning_distance_km !== null) {
                    const el = document.getElementById('lightning');
                    if (el) el.innerText = '⚡ ' + d.lightning_distance_km + ' km' + (d.lightning_count ? ' (' + d.lightning_count + ' totali)' : '');
                }
                if (d.lightning_last_time) {
                    const lt = document.getElementById('lightning_time');
                    if (lt) lt.innerText = d.lightning_last_time;
                }

                // ANALYTICS & SMART ADVICE
                if (d.analytics) {
                    const a = d.analytics;

                    // Condizione Cielo & Sky Theme Hero Animato
                    if (a.current_condition) {
                        const cc = a.current_condition;
                        const heroCard = document.getElementById('hero_weather_card');
                        if (heroCard && cc.sky_theme) {
                            heroCard.className = 'weather-hero-card ' + cc.sky_theme;
                        }
                        const heroIcon = document.getElementById('hero_sky_icon');
                        if (heroIcon && cc.icon) heroIcon.innerText = cc.icon;
                        const heroTitle = document.getElementById('hero_condition_title');
                        if (heroTitle && cc.title) heroTitle.innerText = cc.title;
                        const heroDesc = document.getElementById('hero_condition_desc');
                        if (heroDesc && cc.desc) heroDesc.innerText = cc.desc;
                    }

                    // Nowcasting Zambretti
                    if (a.zambretti) {
                        const nIcon = document.getElementById('nowcast_icon');
                        const nText = document.getElementById('nowcast_text');
                        const nDesc = document.getElementById('nowcast_desc');
                        if (nIcon) nIcon.innerText = a.zambretti.icon;
                        if (nText) nText.innerText = a.zambretti.text;
                        if (nDesc) nDesc.innerText = a.zambretti.desc;
                    }

                    // Consigli Comfort & Smart Advice
                    if (a.comfort) {
                        // 1. Finestre
                        if (a.comfort.window) {
                            const w = a.comfort.window;
                            const wCard = document.getElementById('card_window');
                            const wIcon = document.getElementById('window_icon');
                            const wBadge = document.getElementById('window_badge');
                            const wBadgeTxt = document.getElementById('window_badge_text');
                            const wDesc = document.getElementById('window_desc');
                            if (wIcon) wIcon.innerText = w.icon || '🪟';
                            if (wBadgeTxt) wBadgeTxt.innerText = w.title || 'Aerazione Normale';
                            else if (wBadge) wBadge.innerText = w.title || 'Aerazione Normale';
                            if (wBadge && w.badge_class) {
                                wBadge.className = 'comfort-status-badge ' + w.badge_class;
                            }
                            if (wCard && w.badge_class) {
                                const st = w.badge_class.replace('badge-', 'card-state-');
                                wCard.className = 'comfort-pill-card ' + st;
                            }
                            if (wDesc) wDesc.innerText = w.desc || '';
                        }
                        // 2. Bucato
                        if (a.comfort.laundry) {
                            const l = a.comfort.laundry;
                            const lCard = document.getElementById('card_laundry');
                            const lIcon = document.getElementById('laundry_icon');
                            const lBadge = document.getElementById('laundry_badge');
                            const lBadgeTxt = document.getElementById('laundry_badge_text');
                            const lTimeChip = document.getElementById('laundry_time');
                            const lTimeVal = document.getElementById('laundry_time_val');
                            const lDesc = document.getElementById('laundry_desc');
                            if (lIcon) lIcon.innerText = l.icon || '🧺';
                            if (lBadgeTxt) lBadgeTxt.innerText = l.title || 'Indice Bucato';
                            else if (lBadge) lBadge.innerText = l.title || 'Indice Bucato';
                            if (lBadge && l.badge_class) {
                                lBadge.className = 'comfort-status-badge ' + l.badge_class;
                            }
                            if (lCard && l.badge_class) {
                                const st = l.badge_class.replace('badge-', 'card-state-');
                                lCard.className = 'comfort-pill-card ' + st;
                            }
                            if (lTimeVal) lTimeVal.innerText = l.time_estimate || '--';
                            if (lDesc) lDesc.innerText = l.desc || '';
                        }
                        // 3. Humidex
                        if (a.comfort.humidex) {
                            const h = a.comfort.humidex;
                            const hCard = document.getElementById('card_humidex');
                            const hIcon = document.getElementById('humidex_icon');
                            const hBadge = document.getElementById('humidex_badge');
                            const hBadgeTxt = document.getElementById('humidex_badge_text');
                            const hDewVal = document.getElementById('humidex_dew_val');
                            const hDesc = document.getElementById('humidex_desc');
                            if (hIcon) hIcon.innerText = h.icon || '😊';
                            if (hBadgeTxt) hBadgeTxt.innerText = h.text || 'Normale';
                            else if (hBadge) hBadge.innerText = h.text || 'Normale';
                            if (hBadge && h.badge_class) {
                                hBadge.className = 'comfort-status-badge ' + h.badge_class;
                            }
                            if (hCard && h.badge_class) {
                                const st = h.badge_class.replace('badge-', 'card-state-');
                                hCard.className = 'comfort-pill-card ' + st;
                            }
                            if (hDewVal && a.dew_point_c !== undefined) {
                                hDewVal.innerText = 'Rugiada ' + a.dew_point_c + '°C';
                            }
                            if (hDesc) {
                                if (h.value !== undefined && h.value !== null) {
                                    hDesc.innerText = `Humidex a ${h.value}. Punto di rugiada: ${a.dew_point_c !== undefined ? a.dew_point_c + '°C' : '--'}.`;
                                } else {
                                    hDesc.innerText = `Punto di rugiada: ${a.dew_point_c !== undefined ? a.dew_point_c + '°C' : '--'}.`;
                                }
                            }
                        }
                        // 4. Outdoor
                        if (a.comfort.outdoor) {
                            const o = a.comfort.outdoor;
                            const oCard = document.getElementById('card_outdoor');
                            const oIcon = document.getElementById('outdoor_icon');
                            const oBadge = document.getElementById('outdoor_badge');
                            const oBadgeTxt = document.getElementById('outdoor_badge_text');
                            const oDesc = document.getElementById('outdoor_desc');
                            if (oIcon) oIcon.innerText = o.icon || '🏃';
                            if (oBadgeTxt) oBadgeTxt.innerText = o.title || 'Buono';
                            else if (oBadge) oBadge.innerText = o.title || 'Buono';
                            if (oBadge && o.badge_class) {
                                oBadge.className = 'comfort-status-badge ' + o.badge_class;
                            }
                            if (oCard && o.badge_class) {
                                const st = o.badge_class.replace('badge-', 'card-state-');
                                oCard.className = 'comfort-pill-card ' + st;
                            }
                            if (oDesc) oDesc.innerText = o.desc || '';
                        }
                        // 5. Indoor Comfort
                        if (a.comfort.indoor) {
                            const ind = a.comfort.indoor;
                            // Tab 3 Smart advice
                            const iCard = document.getElementById('card_indoor');
                            const iIcon = document.getElementById('indoor_icon');
                            const iBadge = document.getElementById('indoor_badge');
                            const iBadgeTxt = document.getElementById('indoor_badge_text');
                            const iDeltaChip = document.getElementById('indoor_delta_chip');
                            const iDeltaVal = document.getElementById('indoor_delta_val');
                            const iDesc = document.getElementById('indoor_desc');
                            if (iIcon) iIcon.innerText = ind.icon || '🏠';
                            if (iBadgeTxt) iBadgeTxt.innerText = ind.title || 'In attesa';
                            else if (iBadge) iBadge.innerText = ind.title || 'In attesa';
                            if (iBadge && ind.badge_class) {
                                iBadge.className = 'comfort-status-badge ' + ind.badge_class;
                            }
                            if (iCard && ind.badge_class) {
                                const st = ind.badge_class.replace('badge-', 'card-state-');
                                iCard.className = 'comfort-pill-card ' + st;
                            }
                            if (iDeltaChip && iDeltaVal) {
                                if (ind.diff_c !== null && ind.diff_c !== undefined) {
                                    iDeltaVal.innerText = `Δ ${(ind.diff_c > 0 ? '+' : '') + ind.diff_c}°C`;
                                    iDeltaChip.style.display = 'inline-flex';
                                } else {
                                    iDeltaChip.style.display = 'none';
                                }
                            }
                            if (iDesc) iDesc.innerText = ind.desc || '--';

                            // Tab 1 Weather Overview Card
                            const badge = document.getElementById('indoor_comfort_badge');
                            const dText = document.getElementById('indoor_delta_text');
                            const sDesc = document.getElementById('indoor_status_desc');
                            const dBadge = document.getElementById('indoor_delta_badge');
                            if (badge) {
                                badge.className = 'sub-badge ' + (ind.badge_class || '');
                                badge.innerText = `${ind.icon || '🏠'} ${ind.title || 'Ambiente Casa'}`;
                            }
                            if (dText) dText.innerText = ind.delta_text || '--';
                            if (sDesc) sDesc.innerText = ind.desc || '--';
                            if (dBadge) {
                                dBadge.className = 'delta-badge ' + (ind.diff_c > 0 ? 'warmer' : (ind.diff_c < 0 ? 'cooler' : 'neutral'));
                                dBadge.innerText = (ind.diff_c !== null && ind.diff_c !== undefined) ? (ind.diff_c > 0 ? `+${ind.diff_c}°C` : `${ind.diff_c}°C`) : '--';
                            }
                        }
                    }

                    // Punto rugiada interno
                    if (a.dew_point_in_c !== undefined) {
                        const dpIn = document.getElementById('dew_point_in');
                        if (dpIn) dpIn.innerText = a.dew_point_in_c !== null ? a.dew_point_in_c + ' °C' : '-- °C';
                    }

                    // Estremi di Oggi & vs Ieri
                    if (a.today_extremes) {
                        const tMin = document.getElementById('today_min');
                        const tMinTime = document.getElementById('today_min_time');
                        const tMax = document.getElementById('today_max');
                        const tMaxTime = document.getElementById('today_max_time');
                        if (tMin && a.today_extremes.temp_min !== null) tMin.innerText = a.today_extremes.temp_min + '°C';
                        if (tMinTime && a.today_extremes.temp_min_time) tMinTime.innerText = a.today_extremes.temp_min_time;
                        if (tMax && a.today_extremes.temp_max !== null) tMax.innerText = a.today_extremes.temp_max + '°C';
                        if (tMaxTime && a.today_extremes.temp_max_time) tMaxTime.innerText = a.today_extremes.temp_max_time;

                        const heroMin = document.getElementById('hero_today_min');
                        if (heroMin && a.today_extremes.temp_min !== null) heroMin.innerText = 'Min ' + a.today_extremes.temp_min + '°';
                        const heroMax = document.getElementById('hero_today_max');
                        if (heroMax && a.today_extremes.temp_max !== null) heroMax.innerText = 'Max ' + a.today_extremes.temp_max + '°';

                        // Estremi Casa
                        const inMin = document.getElementById('today_in_min');
                        const inMinTime = document.getElementById('today_in_min_time');
                        const inMax = document.getElementById('today_in_max');
                        const inMaxTime = document.getElementById('today_in_max_time');
                        if (inMin && a.today_extremes.temp_in_min !== null && a.today_extremes.temp_in_min !== undefined) inMin.innerText = a.today_extremes.temp_in_min + '°C';
                        if (inMinTime && a.today_extremes.temp_in_min_time) inMinTime.innerText = a.today_extremes.temp_in_min_time;
                        if (inMax && a.today_extremes.temp_in_max !== null && a.today_extremes.temp_in_max !== undefined) inMax.innerText = a.today_extremes.temp_in_max + '°C';
                        if (inMaxTime && a.today_extremes.temp_in_max_time) inMaxTime.innerText = a.today_extremes.temp_in_max_time;
                    }
                    if (a.yesterday_comparison) {
                        const yBadge = document.getElementById('yesterday_badge');
                        if (yBadge) {
                            yBadge.innerText = a.yesterday_comparison.text;
                            yBadge.className = 'delta-badge ' + (a.yesterday_comparison.diff_c > 0 ? 'warmer' : (a.yesterday_comparison.diff_c < 0 ? 'cooler' : 'neutral'));
                        }
                    }

                    // Scala Beaufort
                    if (a.beaufort) {
                        const bBadge = document.getElementById('beaufort_badge');
                        if (bBadge && a.beaufort.label) {
                            bBadge.innerText = a.beaufort.label + ' (F' + (a.beaufort.grade !== null && a.beaufort.grade !== undefined ? a.beaufort.grade : '0') + ')';
                        }
                    }

                    // Accumuli pioggia
                    if (a.rain_totals) {
                        const rWeek = document.getElementById('rain_week');
                        const rMonth = document.getElementById('rain_month');
                        if (rWeek) rWeek.innerText = a.rain_totals.week_rain_mm + ' mm';
                        if (rMonth) rMonth.innerText = a.rain_totals.month_rain_mm + ' mm';
                    }

                    // Effemeridi Sole & Luna
                    if (a.sun_ephemeris) {
                        const ep = a.sun_ephemeris;
                        const sRise = document.getElementById('ephem_sunrise');
                        const sRiseH = document.getElementById('sunrise_time');
                        const sSet = document.getElementById('ephem_sunset');
                        const sSetH = document.getElementById('sunset_time');
                        const sNoon = document.getElementById('ephem_noon');
                        const sNoonH = document.getElementById('solar_noon_time');
                        const sDur = document.getElementById('daylight_duration');
                        const sProg = document.getElementById('sun_arc_progress');
                        const sProgTxt = document.getElementById('sun_progress_pct_txt');
                        const sStatTxt = document.getElementById('sun_status_text');
                        const sStatTag = document.getElementById('sun_status_tag');
                        const orb = document.getElementById('celestial_orb');

                        if (sRise && ep.sunrise) sRise.innerText = ep.sunrise;
                        if (sRiseH && ep.sunrise) sRiseH.innerText = ep.sunrise;
                        if (sSet && ep.sunset) sSet.innerText = ep.sunset;
                        if (sSetH && ep.sunset) sSetH.innerText = ep.sunset;
                        if (sNoon && ep.solar_noon) sNoon.innerText = ep.solar_noon;
                        if (sNoonH && ep.solar_noon) sNoonH.innerText = ep.solar_noon;
                        if (sDur && ep.daylight_duration) sDur.innerText = ep.daylight_duration;
                        if (sProg && ep.sun_progress_pct !== undefined) sProg.style.width = ep.sun_progress_pct + '%';
                        if (sProgTxt && ep.sun_progress_pct !== undefined) sProgTxt.innerText = 'Progressione: ' + ep.sun_progress_pct + '%';
                        if (sStatTxt && ep.status_text) sStatTxt.innerText = ep.status_text;
                        if (sStatTag) {
                            sStatTag.className = 'sun-status-pill ' + (ep.is_daylight ? 'pill-daylight' : 'pill-night');
                        }
                        if (orb && ep.sun_progress_pct !== undefined) {
                            const p = Math.max(0, Math.min(100, Number(ep.sun_progress_pct)));
                            const t = p / 100;
                            const xPct = 5 + 90 * t;
                            const yBottomPct = 10 + 290 * t * (1 - t);
                            orb.style.left = xPct.toFixed(2) + '%';
                            orb.style.bottom = yBottomPct.toFixed(2) + '%';
                        }
                    }
                    if (a.moon_phase) {
                        const mIcon = document.getElementById('moon_icon');
                        const mPhase = document.getElementById('moon_name');
                        const mIllum = document.getElementById('moon_illum');
                        if (mIcon) mIcon.innerText = a.moon_phase.icon;
                        if (mPhase) mPhase.innerText = a.moon_phase.phase_name;
                        if (mIllum) mIllum.innerText = (a.moon_phase.illumination_pct || 0) + '%';
                    }


                    // Cross-Check Modello vs Stazione
                    if (a.cross_check && a.cross_check.available) {
                        const ccText = document.getElementById('cross_check_text');
                        const ccBadge = document.getElementById('cross_check_badge');
                        if (ccText) ccText.innerText = a.cross_check.text;
                        if (ccBadge) {
                            ccBadge.innerText = a.cross_check.status + ' (Δ ' + a.cross_check.delta_str + ')';
                            ccBadge.className = 'cross-check-badge ' + a.cross_check.badge_class;
                        }
                    }

                    // Elettrodomestici SmartThings
                    if (data.smartthings) {
                        updateSmartThingsUI(data.smartthings);
                    }

                    // Dispositivi Smart Life (Tuya)
                    if (data.tuya) {
                        updateTuyaUI(data.tuya);
                    }
                }
            })
            .catch(() => {});
    }


    // Polling energetico Aton Green Storage
    function updateEnergyLive() {
        fetch('/api/energy/latest')
            .then(r => r.json())
            .then(res => {
                if (!res || !res.enabled) return;
                const d = res.data;
                if (!d) return;

                // Aggiorna badge stato impianto
                const statusText = document.getElementById('energy_status_text');
                if (statusText) {
                    statusText.innerText = res.connected ? '🟢 Impianto Attivo' : '🟡 In attesa dati Aton';
                }

                const tsEl = document.getElementById('energy_ts');
                if (tsEl && d.data_aton) {
                    tsEl.innerText = d.data_aton;
                }

                // 1. Solare
                const pSolareEl = document.getElementById('p_solare_val');
                if (pSolareEl && d.p_solare !== undefined) {
                    pSolareEl.innerHTML = `${Math.round(d.p_solare)} <span class="unit">W</span>`;
                }

                // Aggiorna badge sul Tab Energia
                const tabBadgeEnergy = document.getElementById('tab_badge_energy');
                if (tabBadgeEnergy) {
                    if (d.p_solare !== undefined && d.p_solare > 50) {
                        tabBadgeEnergy.innerText = `${Math.round(d.p_solare)} W`;
                        tabBadgeEnergy.classList.add('badge-highlight');
                    } else if (d.soc !== undefined) {
                        tabBadgeEnergy.innerText = `🔋 ${Math.round(d.soc)}%`;
                        tabBadgeEnergy.classList.remove('badge-highlight');
                    }
                }

                const solSub = document.getElementById('solar_today_sub');
                if (solSub && d.solar_today_kwh !== undefined) {
                    solSub.innerHTML = `Oggi: <strong>${d.solar_today_kwh} kWh</strong>`;
                }

                // 2. Batteria
                const pBattEl = document.getElementById('p_batteria_val');
                const pctBadge = document.getElementById('battery_pct_badge');
                const barFill = document.getElementById('battery_bar_fill');
                const battIcon = document.getElementById('battery_icon');
                const battSub = document.getElementById('battery_temp_sub');

                if (pctBadge && d.soc !== undefined) {
                    pctBadge.innerText = Math.round(d.soc) + '%';
                    if (barFill) barFill.style.width = Math.min(100, Math.max(0, d.soc)) + '%';
                    
                    if (d.soc < 20) {
                        pctBadge.style.color = '#f87171';
                        pctBadge.style.borderColor = 'rgba(248, 113, 113, 0.4)';
                        if (barFill) barFill.style.background = '#f87171';
                    } else if (d.soc < 50) {
                        pctBadge.style.color = '#fbbf24';
                        pctBadge.style.borderColor = 'rgba(251, 191, 36, 0.4)';
                        if (barFill) barFill.style.background = '#fbbf24';
                    } else {
                        pctBadge.style.color = '#4ade80';
                        pctBadge.style.borderColor = 'rgba(34, 197, 94, 0.4)';
                        if (barFill) barFill.style.background = 'linear-gradient(90deg, #22c55e, #4ade80)';
                    }
                }

                if (pBattEl && d.p_batteria !== undefined) {
                    if (d.p_batteria > 0) {
                        pBattEl.innerHTML = `+${Math.round(d.p_batteria)} <span class="unit">W (In Scarica)</span>`;
                        if (battIcon) battIcon.innerText = '🔋⚡';
                    } else if (d.p_batteria < 0) {
                        pBattEl.innerHTML = `-${Math.round(Math.abs(d.p_batteria))} <span class="unit">W (In Carica)</span>`;
                        if (battIcon) battIcon.innerText = '⚡🔋';
                    } else {
                        pBattEl.innerHTML = `0 <span class="unit">W (Standby)</span>`;
                        if (battIcon) battIcon.innerText = '🔋';
                    }
                }

                if (battSub && (d.vb !== undefined || d.temp_battery !== undefined)) {
                    battSub.innerText = `Tensione: ${d.vb || '--'}V • Temp: ${d.temp_battery || '--'}°C`;
                }

                // 3. Consumo Casa
                const pUtenzeEl = document.getElementById('p_utenze_val');
                if (pUtenzeEl && d.p_utenze !== undefined) {
                    pUtenzeEl.innerHTML = `${Math.round(d.p_utenze)} <span class="unit">W</span>`;
                }

                // 4. Rete Elettrica
                const pReteEl = document.getElementById('p_rete_val');
                if (pReteEl && d.p_rete !== undefined) {
                    if (d.p_rete_in > 0 || d.p_rete > 0) {
                        const w = Math.round(d.p_rete_in || d.p_rete);
                        pReteEl.innerHTML = `Prelevati: ${w} <span class="unit">W</span>`;
                    } else if (d.p_rete_out > 0) {
                        pReteEl.innerHTML = `Immessa: ${Math.round(d.p_rete_out)} <span class="unit">W</span>`;
                    } else {
                        pReteEl.innerHTML = `0 <span class="unit">W (Autosufficiente)</span>`;
                    }
                }

                // 5. Stringhe e AC
                const s1El = document.getElementById('string1_val');
                if (s1El && (d.string1_v !== undefined || d.string1_i !== undefined)) {
                    s1El.innerText = `${d.string1_v || '--'}V / ${d.string1_i || '--'}A`;
                }
                const s2El = document.getElementById('string2_val');
                if (s2El && (d.string2_v !== undefined || d.string2_i !== undefined)) {
                    s2El.innerText = `${d.string2_v || '--'}V / ${d.string2_i || '--'}A`;
                }
                const gridAcEl = document.getElementById('grid_ac_val');
                if (gridAcEl && (d.grid_v !== undefined || d.grid_hz !== undefined)) {
                    gridAcEl.innerText = `${d.grid_v || '240'}V • ${d.grid_hz || '50.0'}Hz`;
                }
            })
            .catch(() => {});

        // Summary stats
        fetch('/api/energy/summary')
            .then(r => r.json())
            .then(s => {
                if (!s) return;
                const autEl = document.getElementById('autarky_val');
                if (autEl && s.autarky_pct !== undefined) autEl.innerText = s.autarky_pct + '%';

                const selfEl = document.getElementById('self_cons_val');
                if (selfEl && s.self_consumption_pct !== undefined) selfEl.innerText = s.self_consumption_pct + '%';

                const hSub = document.getElementById('house_today_sub');
                if (hSub && s.total_house_kwh !== undefined) {
                    hSub.innerHTML = `Consumo integrato: <strong>${s.total_house_kwh} kWh</strong>`;
                }

                const gSub = document.getElementById('grid_status_sub');
                if (gSub && s.bought_today_kwh !== undefined) {
                    gSub.innerHTML = `Acquistata oggi: <strong>${s.bought_today_kwh} kWh</strong>`;
                }
            })
            .catch(() => {});
    }

    // Avvia aggiornamenti periodici
    setInterval(update, 5000);
    setInterval(updateEnergyLive, 8000);
    setInterval(updateClimateLive, 10000);
    updateEnergyLive();
    updateClimateLive();
}

// ==========================================
// Gestione Climatizzazione Smart LG ThinQ
// ==========================================

function updateClimateLive() {
    fetch('/api/thinq/devices')
        .then(r => r.json())
        .then(res => {
            if (!res) return;
            const statusText = document.getElementById('climate_status_text');
            if (statusText) {
                statusText.innerText = res.connected ? '🟢 LG ThinQ Connesso' : '🟡 In attesa LG ThinQ';
            }
            if (res.devices && Array.isArray(res.devices)) {
                res.devices.forEach(dev => {
                    if (dev.device_type === 'DEVICE_AIR_CONDITIONER') {
                        updateSingleACUI(dev);
                    }
                });
            }
        })
        .catch(() => {});
}

function updateSingleACUI(dev) {
    const id = dev.device_id;
    const card = document.getElementById(`climate_card_${id}`);
    if (card) {
        if (dev.is_on) {
            card.classList.add('is-on');
            card.classList.remove('is-off');
        } else {
            card.classList.add('is-off');
            card.classList.remove('is-on');
        }
    }

    // Power button
    const pwrBtn = document.getElementById(`pwr_btn_${id}`);
    if (pwrBtn) {
        if (dev.is_on) {
            pwrBtn.className = 'climate-power-btn btn-on';
            pwrBtn.innerHTML = `<span class="pwr-icon">⏻</span> <span class="pwr-text">ACCESO</span>`;
            pwrBtn.setAttribute('onclick', `toggleThinQPower('${id}', false)`);
        } else {
            pwrBtn.className = 'climate-power-btn btn-off';
            pwrBtn.innerHTML = `<span class="pwr-icon">⏻</span> <span class="pwr-text">SPENTO</span>`;
            pwrBtn.setAttribute('onclick', `toggleThinQPower('${id}', true)`);
        }
    }

    // Current Temp
    const currEl = document.getElementById(`curr_temp_${id}`);
    if (currEl && dev.current_temp !== undefined && dev.current_temp !== null) {
        currEl.innerText = `${dev.current_temp}°C`;
    }

    // Target Temp
    const targetEl = document.getElementById(`target_temp_${id}`);
    if (targetEl && dev.target_temp !== undefined && dev.target_temp !== null) {
        targetEl.innerText = `${dev.target_temp}°C`;
    }

    // Mode chips
    if (card && dev.mode) {
        const chips = card.querySelectorAll('.mode-chip');
        chips.forEach(chip => {
            chip.className = 'mode-chip';
            const txt = chip.innerText.toLowerCase();
            if (dev.mode === 'COOL' && txt.includes('cool')) chip.classList.add('active-cool');
            if (dev.mode === 'HEAT' && txt.includes('heat')) chip.classList.add('active-heat');
            if (dev.mode === 'DRY' && txt.includes('dry')) chip.classList.add('active-dry');
            if (dev.mode === 'FAN' && txt.includes('fan')) chip.classList.add('active-fan');
            if (dev.mode === 'AUTO' && txt.includes('auto')) chip.classList.add('active-auto');
        });
    }

    // Fan pills
    if (card && dev.fan_speed) {
        const pills = card.querySelectorAll('.climate-fan-group .climate-ctrl-pill');
        pills.forEach(pill => {
            pill.classList.remove('active');
            const txt = pill.innerText.toUpperCase();
            if (dev.fan_speed === 'AUTO' && txt === 'AUTO') pill.classList.add('active');
            if (dev.fan_speed === 'LOW' && (txt === 'MIN' || txt === 'LOW')) pill.classList.add('active');
            if (dev.fan_speed === 'MID' && (txt === 'MED' || txt === 'MID')) pill.classList.add('active');
            if (dev.fan_speed === 'HIGH' && (txt === 'MAX' || txt === 'HIGH')) pill.classList.add('active');
        });
    }

    // Swing switch
    if (card) {
        const swingBtn = card.querySelector('.climate-switches .climate-ctrl-pill');
        if (swingBtn) {
            if (dev.rotate_up_down) {
                swingBtn.classList.add('active');
                swingBtn.setAttribute('onclick', `toggleThinQSwing('${id}', false)`);
            } else {
                swingBtn.classList.remove('active');
                swingBtn.setAttribute('onclick', `toggleThinQSwing('${id}', true)`);
            }
        }
    }
}

async function sendThinQCommand(deviceId, command) {
    try {
        const res = await fetch(`/api/thinq/device/${deviceId}/control`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(command)
        });
        const data = await res.json();
        if (data.status === 'success') {
            setTimeout(updateClimateLive, 1000);
        }
        return data;
    } catch (e) {
        console.error('Errore invio comando LG ThinQ:', e);
    }
}

function toggleThinQPower(deviceId, targetPower) {
    const btn = document.getElementById(`pwr_btn_${deviceId}`);
    if (btn) {
        btn.innerHTML = `<span class="pwr-icon">⏳</span> <span class="pwr-text">INVIO...</span>`;
    }
    sendThinQCommand(deviceId, { power: targetPower });
}

function changeThinQTemp(deviceId, delta) {
    const targetEl = document.getElementById(`target_temp_${deviceId}`);
    if (!targetEl) return;
    let curr = parseFloat(targetEl.innerText);
    if (isNaN(curr)) curr = 26.0;
    let newTemp = Math.min(30.0, Math.max(18.0, curr + delta));
    targetEl.innerText = newTemp.toFixed(1) + '°C';
    sendThinQCommand(deviceId, { target_temp: newTemp });
}

function setThinQMode(deviceId, mode) {
    sendThinQCommand(deviceId, { mode: mode });
}

function setThinQFan(deviceId, speed) {
    sendThinQCommand(deviceId, { fan_speed: speed });
}

function toggleThinQSwing(deviceId, swingState) {
    sendThinQCommand(deviceId, { rotate_up_down: swingState });
}

function syncThinQDevices() {
    const btn = document.getElementById('climate_sync_btn');
    if (btn) {
        btn.innerHTML = `<span class="pulse-dot"></span> <span>⏳ Sincronizzazione...</span>`;
    }
    fetch('/api/thinq/sync', { method: 'POST' })
        .then(r => r.json())
        .then(() => {
            updateClimateLive();
        })
        .finally(() => {
            setTimeout(updateClimateLive, 1000);
        });
}


// ==========================================
// Gestione Notifiche Push PWA (Web Push VAPID)
// ==========================================

function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding)
        .replace(/\-/g, '+')
        .replace(/_/g, '/');

    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);

    for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
}

async function getServiceWorkerRegistration() {
    if (!('serviceWorker' in navigator)) return null;
    try {
        let reg = await navigator.serviceWorker.getRegistration('/static/');
        if (!reg) {
            reg = await navigator.serviceWorker.register('/static/sw.js');
        }
        await navigator.serviceWorker.ready;
        return reg;
    } catch (e) {
        console.warn('Errore registrazione Service Worker:', e);
        return null;
    }
}

async function checkPushSubscriptionStatus() {
    const btn = document.getElementById('btn-push-toggle');
    const statusText = document.getElementById('push-status-text');
    const badge = document.getElementById('push-status-badge');

    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        if (statusText) statusText.innerText = 'Notifiche Push non supportate in questa vista del browser. Su iPhone (iOS 16.4+): tocca il tasto Condividi e scegli "Aggiungi alla schermata Home", poi apri la Web App.';
        if (btn) btn.style.display = 'none';
        if (badge) {
            badge.className = 'status-pill badge-offline';
            badge.innerText = 'Non supportato';
        }
        return;
    }

    try {
        const reg = await getServiceWorkerRegistration();
        if (!reg) return;

        const sub = await reg.pushManager.getSubscription();

        if (sub && Notification.permission === 'granted') {
            if (statusText) statusText.innerText = '✅ Notifiche PWA attive e sincronizzate! Questo dispositivo riceverà tutti gli avvisi meteo in tempo reale anche ad applicazione chiusa.';
            if (badge) {
                badge.className = 'status-pill badge-live';
                badge.innerText = 'Notifiche Attive 🟢';
            }
            if (btn) {
                btn.className = 'btn btn-outline';
                btn.style.display = 'inline-block';
                btn.innerText = '🔕 Disattiva Notifiche su questo Dispositivo';
                btn.onclick = unsubscribeFromPush;
            }
        } else {
            if (statusText) statusText.innerText = 'Abilita le notifiche native per ricevere allarmi istantanei (fulmini, burrasche, gelate, nubifragi, record e buongiorno meteo).';
            if (badge) {
                badge.className = 'status-pill badge-waiting';
                badge.innerText = 'Non Attive ⚪';
            }
            if (btn) {
                btn.className = 'btn btn-primary';
                btn.style.display = 'inline-block';
                btn.innerText = '🔔 Attiva Notifiche Push PWA';
                btn.onclick = subscribeToPush;
            }
        }
    } catch (e) {
        console.error('Errore verifica stato push:', e);
    }
}

async function subscribeToPush() {
    const btn = document.getElementById('btn-push-toggle');
    if (btn) {
        btn.disabled = true;
        btn.innerText = '⏳ Richiesta permesso in corso...';
    }

    try {
        const permission = await Notification.requestPermission();
        if (permission !== 'granted') {
            alert('Permesso notifiche non concesso. Per riceverle, autorizza le notifiche nelle impostazioni del browser/dispositivo.');
            checkPushSubscriptionStatus();
            return;
        }

        const vapidRes = await fetch('/api/push/vapid-public-key');
        const vapidData = await vapidRes.json();
        if (!vapidData.public_key) {
            throw new Error('Chiave VAPID non disponibile dal server.');
        }

        const reg = await getServiceWorkerRegistration();
        if (!reg) throw new Error('Service Worker non pronto.');

        // Rimuovi eventuale sottoscrizione precedente obsoleta per garantire chiave VAPID aggiornata
        const existingSub = await reg.pushManager.getSubscription();
        if (existingSub) {
            await existingSub.unsubscribe().catch(() => {});
        }

        const sub = await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(vapidData.public_key)
        });

        const subJson = sub.toJSON();
        const res = await fetch('/api/push/subscribe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                endpoint: sub.endpoint,
                keys: subJson.keys
            })
        });

        if (res.ok) {
            // Mostra notifica di benvenuto
            if (Notification.permission === 'granted') {
                reg.showNotification('🌤️ Weather Hub Notifiche Attive', {
                    body: 'Le notifiche push sono state collegate con successo alla tua stazione meteo!',
                    icon: '/static/icons/icon.svg',
                    tag: 'welcome-alert'
                }).catch(() => {});
            }
            alert('🎉 Notifiche Push PWA collegate con successo a questo dispositivo!');
        } else {
            alert('Errore durante la registrazione sul server.');
        }
    } catch (err) {
        console.error('Errore iscrizione push:', err);
        alert('Errore durante l\'attivazione: ' + err.message);
    } finally {
        if (btn) btn.disabled = false;
        checkPushSubscriptionStatus();
    }
}

async function unsubscribeFromPush() {
    const btn = document.getElementById('btn-push-toggle');
    if (btn) {
        btn.disabled = true;
        btn.innerText = '⏳ Disattivazione...';
    }

    try {
        const reg = await getServiceWorkerRegistration();
        if (reg) {
            const sub = await reg.pushManager.getSubscription();
            if (sub) {
                await fetch('/api/push/unsubscribe', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ endpoint: sub.endpoint })
                }).catch(() => {});
                await sub.unsubscribe();
            }
        }
        alert('Notifiche disattivate per questo dispositivo.');
    } catch (err) {
        console.error('Errore disiscrizione push:', err);
    } finally {
        if (btn) btn.disabled = false;
        checkPushSubscriptionStatus();
    }
}

async function testPushNotification() {
    const btn = document.getElementById('btn-test-alert');
    if (btn) {
        btn.disabled = true;
        btn.innerText = '⏳ Invio test in corso...';
    }

    try {
        const res = await fetch('/api/test-alert', { method: 'POST' });
        const data = await res.json();
        
        let msg = `🚀 Notifica inviata con successo!\n• Dispositivi PWA registrati: ${data.devices_notified || 0}`;
        if (data.ntfy_topic) {
            msg += `\n• Canale ntfy: '${data.ntfy_topic}'`;
        }
        if (data.devices_notified === 0) {
            msg += `\n\n💡 Suggerimento: Per ricevere le notifiche direttamente su questo smartphone o PC, tocca prima "Attiva Notifiche Push PWA"!`;
        }
        alert(msg);
    } catch (e) {
        alert('Errore invio notifica di test: ' + e.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = '🚀 Invia Notifica di Test';
        }
    }
}

// Ascolta messaggi Push in foreground dal Service Worker
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', (event) => {
        if (event.data && event.data.type === 'PUSH_RECEIVED') {
            console.log('Push ricevuto in foreground:', event.data);
            if (typeof event.data.unread_count === 'number') {
                updateBadgeElements(event.data.unread_count);
            } else {
                refreshAlertBadges();
            }
        }
    });
}

// Sincronizzazione Badge Allerte (Mobile Tab & Desktop Navbar & PWA Icon Badge)
async function refreshAlertBadges() {
    try {
        const res = await fetch('/api/alerts/unread-count');
        if (!res.ok) return;
        const data = await res.json();
        const count = (data && typeof data.unread_count === 'number') ? data.unread_count : 0;
        updateBadgeElements(count);
    } catch (e) {
        // fail silently
    }
}

function updateBadgeElements(count) {
    const safeCount = Math.max(0, parseInt(count, 10) || 0);
    const mobBadge = document.getElementById('mobile-alert-badge');
    const deskBadge = document.getElementById('desktop-alert-badge');
    const unreadHeaderBadge = document.getElementById('unread-count-badge');
    const unreadFilterCount = document.getElementById('unread-filter-count');
    const unreadStatusPill = document.getElementById('unread-status-pill');

    if (mobBadge) {
        if (safeCount > 0) {
            mobBadge.innerText = safeCount > 99 ? '99+' : safeCount;
            mobBadge.style.display = 'block';
        } else {
            mobBadge.innerText = '0';
            mobBadge.style.display = 'none';
        }
    }
    if (deskBadge) {
        if (safeCount > 0) {
            deskBadge.innerText = safeCount > 99 ? '99+' : safeCount;
            deskBadge.style.display = 'inline-block';
        } else {
            deskBadge.innerText = '0';
            deskBadge.style.display = 'none';
        }
    }
    if (unreadHeaderBadge) {
        unreadHeaderBadge.innerText = safeCount;
    }
    if (unreadFilterCount) {
        unreadFilterCount.innerText = safeCount;
    }
    if (unreadStatusPill) {
        if (safeCount > 0) {
            unreadStatusPill.className = 'status-pill badge-warning';
            unreadStatusPill.innerHTML = `<span id="unread-count-badge">${safeCount}</span> da leggere`;
        } else {
            unreadStatusPill.className = 'status-pill badge-live';
            unreadStatusPill.innerHTML = 'Nessuna da leggere';
        }
    }
    const kpiUnreadVal = document.getElementById('kpi-unread-val');
    const kpiUnreadSub = document.getElementById('kpi-unread-sub');
    if (kpiUnreadVal) {
        kpiUnreadVal.innerText = safeCount;
        kpiUnreadVal.style.color = safeCount > 0 ? '#f59e0b' : '#10b981';
    }
    if (kpiUnreadSub) {
        kpiUnreadSub.innerText = safeCount > 0 ? 'Richiedono attenzione' : 'Tutte lette ✨';
    }

    // App Badging API su PWA installata (iOS 16.4+ / Android / Chrome Desktop)
    if (safeCount > 0) {
        if ('setAppBadge' in navigator) {
            navigator.setAppBadge(safeCount).catch(() => {});
        }
    } else {
        if ('clearAppBadge' in navigator) {
            navigator.clearAppBadge().catch(() => {});
        }
        if ('setAppBadge' in navigator) {
            navigator.setAppBadge(0).catch(() => {});
        }
    }

    // Comunica al Service Worker lo stato aggiornato del badge
    if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
        navigator.serviceWorker.controller.postMessage({
            type: safeCount > 0 ? 'SET_BADGE' : 'CLEAR_BADGE',
            count: safeCount
        });
    }
}

async function markAlertAsRead(alertId) {
    const item = document.getElementById(`alert-item-${alertId}`);
    try {
        const res = await fetch(`/api/alerts/${alertId}/read`, { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            if (item) {
                item.classList.remove('unread');
                item.setAttribute('data-unread', '0');
                const btnRead = item.querySelector('.btn-mark-read');
                if (btnRead) {
                    btnRead.outerHTML = `<span class="badge-tag read-status-tag" style="background: rgba(16, 185, 129, 0.15); color: #10b981; font-size: 0.75rem;">✓ Letta</span>`;
                }
                const unreadDot = item.querySelector('.unread-dot');
                if (unreadDot) unreadDot.remove();
            }
            if (typeof data.unread_count === 'number') {
                updateBadgeElements(data.unread_count);
            }
        }
    } catch (err) {
        console.error('Errore segna notifica come letta:', err);
    }
}

async function markAllAlertsAsRead() {
    const btn = document.getElementById('btn-mark-all-read');
    if (btn) {
        btn.disabled = true;
        btn.innerText = '⏳ Aggiornamento...';
    }
    try {
        const res = await fetch('/api/alerts/mark-all-read', { method: 'POST' });
        if (res.ok) {
            const items = document.querySelectorAll('.notification-item');
            items.forEach(item => {
                item.classList.remove('unread');
                item.setAttribute('data-unread', '0');
                const btnRead = item.querySelector('.btn-mark-read');
                if (btnRead) {
                    btnRead.outerHTML = `<span class="badge-tag read-status-tag" style="background: rgba(16, 185, 129, 0.15); color: #10b981; font-size: 0.75rem;">✓ Letta</span>`;
                }
                const unreadDot = item.querySelector('.unread-dot');
                if (unreadDot) unreadDot.remove();
            });
            updateBadgeElements(0);
            const btnUnread = document.getElementById('filter-btn-unread');
            if (btnUnread && btnUnread.classList.contains('active')) {
                filterAlerts('unread');
            }
        }
    } catch (err) {
        console.error('Errore durante la marcatura di tutte le notifiche:', err);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '✓ Tutte lette';
        }
    }
}

async function deleteAlertItem(alertId) {
    if (!confirm('Vuoi eliminare questa notifica dal registro?')) return;
    const item = document.getElementById(`alert-item-${alertId}`);
    try {
        const res = await fetch(`/api/alerts/${alertId}`, { method: 'DELETE' });
        if (res.ok) {
            const data = await res.json();
            if (item) item.remove();
            if (typeof data.unread_count === 'number') {
                updateBadgeElements(data.unread_count);
            }
            const totalBadge = document.getElementById('total-count-badge');
            if (totalBadge) {
                const cur = parseInt(totalBadge.innerText, 10) || 0;
                totalBadge.innerText = Math.max(0, cur - 1);
            }
            const remaining = document.querySelectorAll('.notification-item');
            if (remaining.length === 0) {
                const list = document.getElementById('notifications-list-container');
                if (list) {
                    list.innerHTML = `<div class="card" style="text-align: center; padding: 2.5rem 1rem; color: var(--text-dim);"><p style="font-size: 1.1rem; margin-bottom: 0.5rem;">✨ Nessuna notifica presente</p><p style="font-size: 0.85rem;">Il registro notifiche è vuoto.</p></div>`;
                }
            }
        }
    } catch (err) {
        console.error('Errore eliminazione notifica:', err);
    }
}

async function clearAllAlerts() {
    if (!confirm('Sei sicuro di voler svuotare l\'intero registro delle notifiche?')) return;
    try {
        const res = await fetch('/api/alerts/clear-all', { method: 'POST' });
        if (res.ok) {
            const list = document.getElementById('notifications-list-container');
            if (list) {
                list.innerHTML = `<div class="card" style="text-align: center; padding: 2.5rem 1rem; color: var(--text-dim);"><p style="font-size: 1.1rem; margin-bottom: 0.5rem;">✨ Nessuna notifica presente</p><p style="font-size: 0.85rem;">Il registro notifiche è vuoto.</p></div>`;
            }
            updateBadgeElements(0);
            const totalBadge = document.getElementById('total-count-badge');
            if (totalBadge) totalBadge.innerText = '0';
        }
    } catch (err) {
        console.error('Errore svuotamento registro:', err);
    }
}

function filterAlerts(mode) {
    const btnAll = document.getElementById('filter-btn-all');
    const btnUnread = document.getElementById('filter-btn-unread');
    const items = document.querySelectorAll('.notification-item');

    if (mode === 'unread') {
        if (btnUnread) btnUnread.classList.add('active');
        if (btnAll) btnAll.classList.remove('active');
        items.forEach(it => {
            if (it.getAttribute('data-unread') === '1') {
                it.style.display = 'flex';
            } else {
                it.style.display = 'none';
            }
        });
    } else {
        if (btnAll) btnAll.classList.add('active');
        if (btnUnread) btnUnread.classList.remove('active');
        items.forEach(it => {
            it.style.display = 'flex';
        });
    }
}

// Inizializza automaticamente lo stato Push e Badge al caricamento
document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('btn-push-toggle')) {
        checkPushSubscriptionStatus();
    }
    refreshAlertBadges();
    // Aggiornamento periodico badge notifiche (ogni 20s)
    setInterval(refreshAlertBadges, 20000);
});

// Sincronizza badge quando l'utente torna sull'app/scheda
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
        refreshAlertBadges();
    }
});

/* ==========================================================================
   SAMSUNG SMARTTHINGS CLIENT CONTROLLERS & LIVE POLLING
   ========================================================================== */
function updateSmartThingsUI(st) {
    if (!st || !st.enabled) return;

    // Presenza
    if (st.presence) {
        const presBadge = document.getElementById('presence_status_badge');
        const presText = document.getElementById('presence_status_text');
        const devName = st.presence.device_name || 'S26 Ultra';
        if (presText) presText.innerText = `Vincenzo (${devName}): ` + st.presence.presence_label;
        if (presBadge) {
            presBadge.className = 'presence-badge ' + (st.presence.is_present ? 'badge-present' : 'badge-away');
        }
    }


    // Banner Sinergia Solare
    if (st.solar_synergy) {
        const solMsg = document.getElementById('st_solar_message');
        if (solMsg && st.solar_synergy.solar_message) {
            solMsg.innerText = st.solar_synergy.solar_message;
        }
    }

    // Lavatrice
    if (st.washer) {
        const w = st.washer;
        const wCard = document.getElementById('washer_card');
        const wPill = document.getElementById('washer_status_pill');
        const wJob = document.getElementById('washer_job_state');
        const wTemp = document.getElementById('washer_water_temp');
        const wSpin = document.getElementById('washer_spin_speed');
        const wRem = document.getElementById('washer_remaining_time');

        if (wPill) {
            wPill.innerText = w.job_state_label || 'In Standby';
            wPill.className = 'appliance-status-pill ' + (w.is_running ? 'pill-active' : (w.is_on ? 'pill-on' : 'pill-standby'));
        }
        if (wCard) {
            wCard.className = 'appliance-card ' + (w.is_running ? 'is-running' : (w.is_on ? 'is-on' : 'is-standby'));
        }
        if (wJob) wJob.innerText = w.job_state_label || 'Pronto';
        if (wTemp) wTemp.innerText = w.water_temp || 'Auto';
        if (wSpin) wSpin.innerText = w.spin_speed || 'Auto';
        if (wRem) wRem.innerText = w.remaining_min ? (w.remaining_min + ' min') : '--';
    }

    // Lavastoviglie
    if (st.dishwasher) {
        const dw = st.dishwasher;
        const dwCard = document.getElementById('dishwasher_card');
        const dwPill = document.getElementById('dishwasher_status_pill');
        const dwJob = document.getElementById('dishwasher_job_state');
        const dwCycle = document.getElementById('dishwasher_cycle_name');
        const dwRem = document.getElementById('dishwasher_remaining_time');
        const dwEst = document.getElementById('dishwasher_finish_est');

        if (dwPill) {
            dwPill.innerText = dw.job_state_label || 'In Standby';
            dwPill.className = 'appliance-status-pill ' + (dw.is_running ? 'pill-active' : (dw.is_on ? 'pill-on' : 'pill-standby'));
        }
        if (dwCard) {
            dwCard.className = 'appliance-card ' + (dw.is_running ? 'is-running' : (dw.is_on ? 'is-on' : 'is-standby'));
        }
        if (dwJob) dwJob.innerText = dw.job_state_label || 'Pronto';
        if (dwCycle) dwCycle.innerText = dw.cycle_name || 'Auto / Eco';
        if (dwRem) dwRem.innerText = dw.remaining_min ? (dw.remaining_min + ' min') : '--';
        if (dwEst) dwEst.innerText = dw.finish_estimate || '--:--';
    }
}

function syncSmartThingsDevices() {
    const btn = document.getElementById('st_sync_btn');
    if (btn) {
        btn.innerHTML = `<span class="pulse-dot"></span> <span>⏳ Sincronizzazione...</span>`;
    }
    fetch('/api/smartthings/sync', { method: 'POST' })
        .then(r => r.json())
        .then(res => {
            if (res) updateSmartThingsUI(res);
        })
        .finally(() => {
            const btn2 = document.getElementById('st_sync_btn');
            if (btn2) {
                btn2.innerHTML = `<span class="pulse-dot"></span> <span id="st_status_text">🟢 SmartThings Connesso</span>`;
            }
        });
}

function updateTuyaUI(tuya) {
    if (!tuya) return;

    // Totale potenza assorbita
    const totalWEl = document.getElementById('tuya_total_w_val');
    if (totalWEl && tuya.total_plug_power_w !== undefined) {
        totalWEl.innerText = `${tuya.total_plug_power_w} W`;
    }

    // Badge status
    const statusText = document.getElementById('tuya_status_text');
    if (statusText && tuya.enabled_devices_count !== undefined) {
        statusText.innerText = `🟢 ${tuya.enabled_devices_count} Attivi`;
    }

    // Aggiornamento singole card
    const devs = tuya.enabled_devices || [];
    devs.forEach(dev => {
        const id = dev.id;
        
        // Power W
        const pEl = document.getElementById(`tuya_p_${id}`);
        if (pEl && dev.power_w !== undefined) {
            pEl.innerText = `${dev.power_w} W`;
            pEl.style.color = (dev.power_w > 50) ? '#38bdf8' : 'var(--text)';
        }

        // Voltage V
        const vEl = document.getElementById(`tuya_v_${id}`);
        if (vEl && dev.voltage_v !== undefined) {
            vEl.innerText = `${dev.voltage_v} V`;
        }

        // Current A
        const iEl = document.getElementById(`tuya_i_${id}`);
        if (iEl && dev.current_a !== undefined) {
            iEl.innerText = `${dev.current_a} A`;
        }

        // State Text
        const stateEl = document.getElementById(`tuya_state_${id}`);
        if (stateEl && dev.is_on !== null && dev.is_on !== undefined) {
            stateEl.innerText = dev.is_on ? 'Alimentato' : 'Spento';
        }

        // Pill button
        const pill = document.getElementById(`tuya_pill_${id}`);
        if (pill && dev.is_on !== null && dev.is_on !== undefined) {
            pill.className = `appliance-status-pill ${dev.is_on ? 'pill-active' : 'pill-standby'}`;
            pill.innerText = dev.is_on ? '🟢 ON' : '⚪ OFF';
        }

        // Card container class
        const card = document.getElementById(`tuya_card_${id}`);
        if (card && dev.is_on !== null && dev.is_on !== undefined) {
            if (dev.is_on) {
                card.classList.add('is-on');
                card.classList.remove('is-standby');
            } else {
                card.classList.remove('is-on');
                card.classList.add('is-standby');
            }
        }
    });
}

async function toggleTuyaFromDashboard(deviceId) {
    const pill = document.getElementById(`tuya_pill_${deviceId}`);
    if (pill) {
        pill.innerText = '⏳ ...';
    }
    try {
        const resp = await fetch(`/api/tuya/device/${deviceId}/toggle`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const res = await resp.json();
        // Refresh immediato
        setTimeout(async () => {
            const sumResp = await fetch('/api/tuya/summary');
            const summary = await sumResp.json();
            updateTuyaUI(summary);
        }, 1200);
    } catch (e) {
        console.error('Errore toggle Tuya:', e);
    }
}

async function sendTuyaCommand(deviceId, commands) {
    try {
        const resp = await fetch(`/api/tuya/device/${deviceId}/command`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ commands: commands })
        });
        const res = await resp.json();
        setTimeout(async () => {
            const sumResp = await fetch('/api/tuya/summary');
            const summary = await sumResp.json();
            updateTuyaUI(summary);
        }, 1200);
        return res;
    } catch (e) {
        console.error('Errore invio comando Tuya:', e);
    }
}

function syncTuyaLiveDevices() {
    const btn = document.getElementById('tuya_sync_btn');
    if (btn) {
        btn.innerHTML = `<span class="pulse-dot"></span> <span>⏳ Sincronizzazione...</span>`;
    }
    fetch('/api/tuya/sync', { method: 'POST' })
        .then(r => r.json())
        .then(res => {
            if (res) updateTuyaUI(res);
        })
        .finally(() => {
            const btn2 = document.getElementById('tuya_sync_btn');
            if (btn2) {
                btn2.innerHTML = `<span class="pulse-dot"></span> <span id="tuya_status_text">🟢 Sincronizzato</span>`;
            }
        });
}

/* ==========================================================================
   DASHBOARD TAB NAVIGATION & HASH ROUTING
   ========================================================================== */
function switchDashboardTab(tabId) {
    if (!tabId) return;

    // Seleziona tutti i bottoni e i panelli
    const tabButtons = document.querySelectorAll('.dash-tab-btn');
    const tabPanes = document.querySelectorAll('.dashboard-tab-pane');

    if (!tabButtons.length || !tabPanes.length) return;

    // Disattiva tutti i tab
    tabButtons.forEach(btn => btn.classList.remove('active'));
    tabPanes.forEach(pane => pane.classList.remove('active'));

    // Normalizza ID
    const cleanId = tabId.replace(/^#/, '').toLowerCase();
    const btnId = 'tab_btn_' + cleanId.replace(/-/g, '_');
    const paneId = 'pane_' + cleanId.replace(/-/g, '_');

    // Attiva bottone e pannello corrispondente
    const targetBtn = document.getElementById(btnId);
    const targetPane = document.getElementById(paneId);

    if (targetBtn && targetPane) {
        targetBtn.classList.add('active');
        targetPane.classList.add('active');

        // Salva preferenza in localStorage
        try {
            localStorage.setItem('ecowitt_dashboard_active_tab', cleanId);
        } catch (e) {
            console.warn('LocalStorage error:', e);
        }

        // Aggiorna URL Hash senza causare jump
        if (history.replaceState) {
            history.replaceState(null, null, '#' + cleanId);
        }

        // Se passiamo al tab meteo, ridimensiona grafici Chart.js se presenti
        if (cleanId === 'weather' && window.quickChartInstance) {
            try {
                window.quickChartInstance.resize();
            } catch (e) {}
        }
    }
}

function initDashboardTabs() {
    const tabsNav = document.getElementById('dashboard_tabs');
    if (!tabsNav) return;

    // 1. Controlla se c'è un hash nell'URL
    const hash = window.location.hash ? window.location.hash.replace(/^#/, '') : null;

    // 2. Controlla se c'è un tab salvato in localStorage
    let savedTab = null;
    try {
        savedTab = localStorage.getItem('ecowitt_dashboard_active_tab');
    } catch (e) {}

    const validTabs = ['weather', 'energy-home', 'astro-comfort'];
    const initialTab = (hash && validTabs.includes(hash)) ? hash : ((savedTab && validTabs.includes(savedTab)) ? savedTab : 'weather');

    switchDashboardTab(initialTab);

    // Ascolta cambi hash manuali (es. back button del browser)
    window.addEventListener('hashchange', () => {
        const currentHash = window.location.hash ? window.location.hash.replace(/^#/, '') : 'weather';
        if (validTabs.includes(currentHash)) {
            switchDashboardTab(currentHash);
        }
    });
}

// ----------------- GESTIONE DATABASE & SENSOR ALIASES -----------------

async function triggerDbMaintenance() {
    const resEl = document.getElementById('db_maintenance_result');
    if (resEl) {
        resEl.style.display = 'block';
        resEl.style.color = '#38bdf8';
        resEl.innerText = '⏳ Compattazione e ottimizzazione in corso...';
    }
    try {
        const resp = await fetch('/api/system/maintenance?retention_days=60', { method: 'POST' });
        const data = await resp.json();
        if (data.status === 'success') {
            if (resEl) {
                resEl.style.color = '#10b981';
                resEl.innerText = `✅ Manutenzione completata con successo! Ore compattate: ${data.compressed_hours}, record purificati: ${data.weather_records_purged}.`;
            }
            if (data.stats_after) {
                const s = data.stats_after;
                const sizeEl = document.getElementById('db_size_val');
                const wCntEl = document.getElementById('db_weather_cnt');
                const eCntEl = document.getElementById('db_energy_cnt');
                if (sizeEl) sizeEl.innerText = s.db_size_mb + ' MB';
                if (wCntEl) wCntEl.innerText = s.weather_records_count;
                if (eCntEl) eCntEl.innerText = s.energy_records_count;
            }
        } else {
            if (resEl) {
                resEl.style.color = '#ef4444';
                resEl.innerText = '❌ Errore durante la manutenzione.';
            }
        }
    } catch (e) {
        if (resEl) {
            resEl.style.color = '#ef4444';
            resEl.innerText = '❌ Errore di connessione: ' + e.message;
        }
    }
}

async function saveSensorAlias(sensorId, aliasVal) {
    const statusEl = document.getElementById('sensor_alias_status');
    if (statusEl) {
        statusEl.style.display = 'block';
        statusEl.style.color = '#38bdf8';
        statusEl.innerText = 'Salvataggio...';
    }
    try {
        const resp = await fetch('/api/sensors/aliases', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sensor_id: sensorId, alias: aliasVal })
        });
        const d = await resp.json();
        if (d.status === 'saved') {
            if (statusEl) {
                statusEl.style.color = '#10b981';
                statusEl.innerText = `✅ Alias per ${sensorId} salvato con successo: "${aliasVal || '(predefinito)'}"`;
                setTimeout(() => { statusEl.style.display = 'none'; }, 4000);
            }
        }
    } catch (e) {
        if (statusEl) {
            statusEl.style.color = '#ef4444';
            statusEl.innerText = '❌ Errore durante il salvataggio: ' + e.message;
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initDashboardTabs();
});



