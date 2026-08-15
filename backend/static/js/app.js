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

                    // Consigli Comfort
                    if (a.comfort) {
                        // Finestre
                        if (a.comfort.window) {
                            const wIcon = document.getElementById('window_icon');
                            const wTitle = document.getElementById('window_title');
                            const wDesc = document.getElementById('window_desc');
                            if (wIcon) wIcon.innerText = a.comfort.window.icon;
                            if (wTitle) wTitle.innerText = a.comfort.window.title;
                            if (wDesc) wDesc.innerText = a.comfort.window.desc;
                        }
                        // Bucato
                        if (a.comfort.laundry) {
                            const lIcon = document.getElementById('laundry_icon');
                            const lTitle = document.getElementById('laundry_title');
                            const lDesc = document.getElementById('laundry_desc');
                            if (lIcon) lIcon.innerText = a.comfort.laundry.icon;
                            if (lTitle) lTitle.innerText = a.comfort.laundry.title + ' (' + a.comfort.laundry.time_estimate + ')';
                            if (lDesc) lDesc.innerText = a.comfort.laundry.desc;
                        }
                        // Humidex
                        if (a.comfort.humidex) {
                            const hIcon = document.getElementById('humidex_icon');
                            const hText = document.getElementById('humidex_text');
                            if (hIcon) hIcon.innerText = a.comfort.humidex.icon;
                            if (hText) hText.innerText = a.comfort.humidex.text;
                        }
                        // Outdoor
                        if (a.comfort.outdoor) {
                            const oIcon = document.getElementById('outdoor_icon');
                            const oTitle = document.getElementById('outdoor_title');
                            const oDesc = document.getElementById('outdoor_desc');
                            if (oIcon) oIcon.innerText = a.comfort.outdoor.icon;
                            if (oTitle) oTitle.innerText = a.comfort.outdoor.title;
                            if (oDesc) oDesc.innerText = a.comfort.outdoor.desc;
                        }
                        // Indoor Comfort
                        if (a.comfort.indoor) {
                            const ind = a.comfort.indoor;
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
                        const sRise = document.getElementById('ephem_sunrise');
                        const sSet = document.getElementById('ephem_sunset');
                        const sProg = document.getElementById('sun_progress');
                        const sStat = document.getElementById('sun_status');
                        if (sRise) sRise.innerText = a.sun_ephemeris.sunrise;
                        if (sSet) sSet.innerText = a.sun_ephemeris.sunset;
                        if (sProg) sProg.style.width = a.sun_ephemeris.sun_progress_pct + '%';
                        if (sStat) sStat.innerText = a.sun_ephemeris.status_text + ' (' + a.sun_ephemeris.daylight_duration + ' luce)';
                    }
                    if (a.moon_phase) {
                        const mIcon = document.getElementById('moon_icon');
                        const mPhase = document.getElementById('moon_phase');
                        const mIllum = document.getElementById('moon_illum');
                        if (mIcon) mIcon.innerText = a.moon_phase.icon;
                        if (mPhase) mPhase.innerText = a.moon_phase.phase_name;
                        if (mIllum) mIllum.innerText = a.moon_phase.illumination_pct + '%';
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
                        pBattEl.innerHTML = `+${Math.round(d.p_batteria)} <span class="unit">W (In Carica)</span>`;
                        if (battIcon) battIcon.innerText = '⚡🔋';
                    } else if (d.p_batteria < 0) {
                        pBattEl.innerHTML = `-${Math.round(Math.abs(d.p_batteria))} <span class="unit">W (In Scarica)</span>`;
                        if (battIcon) battIcon.innerText = '🔋';
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
                    hSub.innerHTML = `Fabbisogno stimato: <strong>${s.total_house_kwh} kWh</strong>`;
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
    updateEnergyLive();
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
        }
    });
}

// Inizializza automaticamente lo stato Push al caricamento
document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('btn-push-toggle')) {
        checkPushSubscriptionStatus();
    }
});
