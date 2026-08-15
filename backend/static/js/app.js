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
                }
                if (d.apparent_temp_c !== undefined) {
                    const el = document.getElementById('apparent_temp_badge');
                    if (el) el.innerText = 'Percepita: ' + d.apparent_temp_c + '°C';
                }
                if (d.humidity !== undefined) {
                    const el = document.getElementById('humidity');
                    if (el) el.innerText = d.humidity + ' %';
                }
                if (d.dew_point_c !== undefined) {
                    const el = document.getElementById('dew_point');
                    if (el) el.innerText = d.dew_point_c + ' °C';
                }
                if (d.pressure_rel_hpa !== undefined) {
                    const el = document.getElementById('press_rel');
                    if (el) el.innerText = d.pressure_rel_hpa + ' hPa';
                }
                if (d.pressure_trend && d.pressure_trend.text) {
                    const el = document.getElementById('press_trend');
                    if (el) el.innerText = d.pressure_trend.text;
                }

                // Vento & Bussola
                if (d.wind_speed_kmh !== undefined) {
                    const el = document.getElementById('wind_spd');
                    if (el) el.innerText = d.wind_speed_kmh;
                }
                if (d.wind_gust_kmh !== undefined) {
                    const el = document.getElementById('wind_gst');
                    if (el) el.innerText = d.wind_gust_kmh + ' km/h';
                }
                if (d.max_daily_gust_kmh !== undefined) {
                    const el = document.getElementById('max_gust');
                    if (el) el.innerText = d.max_daily_gust_kmh + ' km/h';
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
                }
                if (d.daily_rain_mm !== undefined) {
                    const el = document.getElementById('rain_day');
                    if (el) el.innerText = d.daily_rain_mm + ' mm';
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

                // Interno
                if (d.temp_in_c !== undefined) {
                    const el = document.getElementById('temp_in');
                    if (el) el.innerText = d.temp_in_c + ' °C';
                }
                if (d.humidity_in !== undefined) {
                    const el = document.getElementById('hum_in');
                    if (el) el.innerText = d.humidity_in + ' %';
                }

                // Fulmini
                if (d.lightning_distance_km !== undefined && d.lightning_distance_km !== null) {
                    const el = document.getElementById('lightning');
                    if (el) el.innerText = '⚡ ' + d.lightning_distance_km + ' km';
                }

                // ANALYTICS & SMART ADVICE
                if (d.analytics) {
                    const a = d.analytics;

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

    setInterval(update, 5000);
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

async function checkPushSubscriptionStatus() {
    const btn = document.getElementById('btn-push-toggle');
    const statusText = document.getElementById('push-status-text');
    const badge = document.getElementById('push-status-badge');

    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        if (statusText) statusText.innerText = 'Notifiche Push non supportate in questa vista. Se usi iPhone (iOS 16.4+), tocca Condividi e poi "Aggiungi alla schermata Home", quindi apri l\'icona creata.';
        if (btn) btn.style.display = 'none';
        if (badge) {
            badge.className = 'status-pill badge-offline';
            badge.innerText = 'Non supportato';
        }
        return;
    }

    try {
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.getSubscription();

        if (sub) {
            if (statusText) statusText.innerText = '✅ Notifiche attive! Questo dispositivo riceverà gli avvisi meteo in tempo reale anche ad app chiusa.';
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
            if (statusText) statusText.innerText = 'Abilita le notifiche native per ricevere allarmi istantanei (fulmini, gelate, nubifragi, record e buongiorno meteo).';
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
            alert('Permesso notifiche non concesso. Per riceverle, autorizza le notifiche nelle impostazioni del browser/iOS.');
            checkPushSubscriptionStatus();
            return;
        }

        const vapidRes = await fetch('/api/push/vapid-public-key');
        const vapidData = await vapidRes.json();
        if (!vapidData.public_key) {
            throw new Error('Chiave VAPID non disponibile dal server.');
        }

        const reg = await navigator.serviceWorker.ready;
        let sub = await reg.pushManager.getSubscription();
        if (!sub) {
            sub = await reg.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(vapidData.public_key)
            });
        }

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
            alert('🎉 Notifiche Push PWA attivate con successo su questo dispositivo!');
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
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.getSubscription();
        if (sub) {
            await fetch('/api/push/unsubscribe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ endpoint: sub.endpoint })
            });
            await sub.unsubscribe();
            alert('Notifiche disattivate per questo dispositivo.');
        }
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
        alert(`🚀 Notifica di test inviata a ${data.devices_notified || 0} dispositivi PWA registrati e su canale ntfy '${data.ntfy_topic}'!`);
    } catch (e) {
        alert('Errore invio notifica di test: ' + e.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = '🚀 Invia Notifica di Test';
        }
    }
}

// Inizializza automaticamente lo stato Push al caricamento
document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('btn-push-toggle')) {
        checkPushSubscriptionStatus();
    }
});
