// Telecomando e scheda della TV (LG webOS tramite Home Assistant).
// Usato dalla pagina Casa (dettaglio TV) e dalla pagina /telecomando.
// La pagina che lo include può definire refreshCurrentDeviceDetail() per ricaricare lo stato.

// 14. Smart TV e media player (LG webOS, Google Cast, SmartThings)
function tvEsc(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Sorgenti mostrate per prime come scorciatoie (le altre restano nell'elenco completo)
const TV_FAVORITE_SOURCES = ['Netflix', 'YouTube', 'Prime Video', 'Disney+', 'RaiPlay', 'NOW', 'Canali TV', 'HDMI 1', 'PS5 Console giochi', 'Spotify - Musica e podcast'];

function renderTvDetail(dev) {
    const isOn = dev.is_on === true;
    const online = dev.is_online;
    const rawId = tvEsc(dev.raw_id);
    const vol = dev.volume_pct;
    const sources = Array.isArray(dev.source_list) ? dev.source_list : [];
    const favs = TV_FAVORITE_SOURCES.filter(s => sources.includes(s));
    // Pulsante power unico (stile telecomando): accende o spegne la TV direttamente.
    // Icona in SVG: il simbolo ⏻ manca in molti font (su Android compariva come un quadratino).
    const canPress = online && (isOn || dev.can_turn_on);
    const stateTxt = !online ? 'Non raggiungibile' : (isOn ? `Accesa${dev.source ? ' • ' + tvEsc(dev.source) : ''}` : 'Spenta');
    const subTxt = !online ? 'Home Assistant non la vede in rete'
        : (isOn ? 'Tocca per spegnere'
            : (dev.can_turn_on ? 'Tocca per accendere' : 'Accensione non disponibile: serve il Wake on LAN in Home Assistant'));

    let html = `
        <div class="tv-power-card ${isOn ? 'is-on' : 'is-off'}">
            <div class="tv-power-info">
                <span class="tv-power-state">${stateTxt}</span>
                <span class="tv-power-sub" id="tv-power-sub">${subTxt}</span>
            </div>
            <button type="button" class="tv-power-btn" ${canPress ? '' : 'disabled'}
                    onclick="tvPower(this, '${rawId}', ${isOn ? 'true' : 'false'})"
                    aria-label="${isOn ? 'Spegni la TV' : 'Accendi la TV'}" title="${isOn ? 'Spegni la TV' : 'Accendi la TV'}">
                <svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M12 2.5v9"/><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/>
                </svg>
            </button>
        </div>`;

    if (!dev.full_control) {
        html += `<p class="tv-hint" style="margin-top:1rem;">Questa voce arriva da ${tvEsc(dev.category_label || 'un\'integrazione')} di Home Assistant: mostra solo cosa si sta trasmettendo, senza controllo completo.</p>`;
        return html;
    }

    if (isOn) {
        html += renderTvRemote(rawId);
        html += `
        <div class="tv-panel">
            <div class="tv-volume">
                <span class="tv-label">🔊 Volume <b id="tv-vol-val">${vol ?? '--'}%</b>${dev.is_muted ? ' <span class="tv-muted">muto</span>' : ''}</span>
                <div class="tv-volume-row">
                    <input type="range" min="0" max="100" step="1" value="${vol ?? 0}" class="tv-vol-slider" aria-label="Volume"
                           oninput="document.getElementById('tv-vol-val').textContent=this.value+'%'"
                           onchange="tvService('${rawId}', 'volume_set', {volume_level: this.value/100})">
                    <button type="button" class="btn btn-outline tv-btn ${dev.is_muted ? 'active' : ''}" onclick="tvService('${rawId}', 'volume_mute', {is_volume_muted: ${dev.is_muted ? 'false' : 'true'}})" aria-label="Muto">${dev.is_muted ? '🔇' : '🔈'}</button>
                </div>
            </div>
            <div class="tv-media-row">
                <button type="button" class="btn btn-outline tv-btn" onclick="tvService('${rawId}', 'media_previous_track')" aria-label="Precedente">⏮</button>
                <button type="button" class="btn btn-outline tv-btn" onclick="tvService('${rawId}', 'media_play_pause')" aria-label="Play/Pausa">⏯</button>
                <button type="button" class="btn btn-outline tv-btn" onclick="tvService('${rawId}', 'media_next_track')" aria-label="Successivo">⏭</button>
            </div>
            <div class="tv-sources">
                <span class="tv-label">📺 App e sorgenti</span>
                <div class="tv-source-chips">
                    ${favs.map(s => `<button type="button" class="tv-chip ${s === dev.source ? 'active' : ''}" onclick="tvService('${rawId}', 'select_source', {source: ${tvEsc(JSON.stringify(s))}})">${tvEsc(s)}</button>`).join('')}
                </div>
                <select class="tv-source-select" aria-label="Tutte le sorgenti" onchange="if(this.value) tvService('${rawId}', 'select_source', {source: this.value})">
                    <option value="">Tutte le sorgenti (${sources.length})…</option>
                    ${sources.map(s => `<option value="${tvEsc(s)}" ${s === dev.source ? 'selected' : ''}>${tvEsc(s)}</option>`).join('')}
                </select>
            </div>
        </div>`;
    }
    return html;
}

// Telecomando LG webOS: frecce, OK, Indietro/Home, volume, canali e tastierino numerico.
// I tasti partono subito (senza ricaricare la finestra) e vibrano leggermente sul telefono.
let tvKeypadOpen = false;

function renderTvRemote(rawId) {
    const k = (button, label, extra = '', cls = '') =>
        `<button type="button" class="tv-key ${cls}" data-tv-key="${button}" onclick="tvKey(this, '${rawId}', '${button}')" aria-label="${label}" title="${label}" ${extra}>`;
    const arrow = d => `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${d}"/></svg>`;
    const digits = ['1', '2', '3', '4', '5', '6', '7', '8', '9'];
    return `
        <div class="tv-remote">
            <div class="tv-remote-top">
                ${k('BACK', 'Indietro')}<span>↩︎</span><small>Indietro</small></button>
                ${k('HOME', 'Home')}<span>⌂</span><small>Home</small></button>
                ${k('MENU', 'Impostazioni TV')}<span>⚙</span><small>Menu</small></button>
                ${k('EXIT', 'Esci')}<span>✕</span><small>Esci</small></button>
            </div>
            <div class="tv-dpad" role="group" aria-label="Frecce">
                ${k('UP', 'Su', '', 'dpad-up')}${arrow('M6 15l6-6 6 6')}</button>
                ${k('LEFT', 'Sinistra', '', 'dpad-left')}${arrow('M15 6l-6 6 6 6')}</button>
                ${k('ENTER', 'OK', '', 'dpad-ok')}OK</button>
                ${k('RIGHT', 'Destra', '', 'dpad-right')}${arrow('M9 6l6 6-6 6')}</button>
                ${k('DOWN', 'Giù', '', 'dpad-down')}${arrow('M6 9l6 6 6-6')}</button>
            </div>
            <div class="tv-rockers">
                <div class="tv-rocker">
                    ${k('VOLUMEUP', 'Alza volume')}+</button>
                    <span class="tv-rocker-label">VOL</span>
                    ${k('VOLUMEDOWN', 'Abbassa volume')}−</button>
                </div>
                <div class="tv-rocker-mid">
                    ${k('MUTE', 'Muto', '', 'tv-key-round')}🔇</button>
                    <button type="button" class="tv-key tv-key-round ${tvKeypadOpen ? 'active' : ''}" onclick="toggleTvKeypad(this)" aria-expanded="${tvKeypadOpen}" aria-label="Tastierino numerico" title="Tastierino numerico">123</button>
                </div>
                <div class="tv-rocker">
                    ${k('CHANNELUP', 'Canale successivo')}+</button>
                    <span class="tv-rocker-label">CH</span>
                    ${k('CHANNELDOWN', 'Canale precedente')}−</button>
                </div>
            </div>
            <div class="tv-keypad" id="tv-keypad" ${tvKeypadOpen ? '' : 'hidden'}>
                ${digits.map(d => `${k(d, 'Tasto ' + d)}${d}</button>`).join('')}
                ${k('INFO', 'Informazioni')}ℹ︎</button>
                ${k('0', 'Tasto 0')}0</button>
                ${k('GUIDE', 'Guida TV')}<small>Guida</small></button>
            </div>
        </div>`;
}

function toggleTvKeypad(btn) {
    tvKeypadOpen = !tvKeypadOpen;
    const pad = document.getElementById('tv-keypad');
    if (pad) pad.hidden = !tvKeypadOpen;
    btn.classList.toggle('active', tvKeypadOpen);
    btn.setAttribute('aria-expanded', String(tvKeypadOpen));
}

async function tvKey(btn, rawId, button) {
    if (navigator.vibrate) navigator.vibrate(12);
    btn.classList.add('is-pressed');
    setTimeout(() => btn.classList.remove('is-pressed'), 180);
    try {
        const resp = await fetch('/api/homeassistant/tv/button', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ entity_id: rawId, button })
        });
        const res = await resp.json().catch(() => ({}));
        if (!resp.ok || res.success === false) {
            showToast(res.error || 'La TV non ha ricevuto il tasto', 'danger');
        }
    } catch (e) {
        showToast('Errore di comunicazione: ' + (e.message || e), 'danger');
    }
}

// Accende/spegne la TV e ricontrolla lo stato mentre si avvia o si spegne
async function tvPower(btn, rawId, isOn) {
    const sub = document.getElementById('tv-power-sub');
    if (sub) sub.textContent = isOn ? 'Spegnimento in corso…' : 'Accensione in corso… (qualche secondo)';
    btn.classList.add('is-busy');
    if (typeof performDeviceToggle === 'function') {
        await performDeviceToggle('homeassistant', rawId, !isOn, btn);
    } else {
        btn.disabled = true;
        try {
            const resp = await fetch(`/api/homeassistant/device/${encodeURIComponent(rawId)}/toggle`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({state: !isOn})
            });
            const res = await resp.json().catch(() => ({}));
            if (!resp.ok || res.success !== true) showToast(res.error || 'La TV non ha risposto', 'danger');
        } catch (e) {
            showToast('Errore di comunicazione: ' + (e.message || e), 'danger');
        }
        btn.disabled = false;
        btn.classList.remove('is-busy');
    }
    [4000, 10000, 20000].forEach(ms => setTimeout(() => {
        if (typeof refreshCurrentDeviceDetail === 'function') refreshCurrentDeviceDetail();
    }, ms));
}

async function tvService(rawId, service, data) {
    try {
        const resp = await fetch('/api/homeassistant/service', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ domain: 'media_player', service, entity_id: rawId, data: data || {} })
        });
        const res = await resp.json().catch(() => ({}));
        if (!resp.ok || res.success === false) {
            showToast(res.error || 'Comando non eseguito dalla TV', 'danger');
            return;
        }
        // La TV aggiorna lo stato in Home Assistant dopo un attimo
        setTimeout(() => { if (typeof refreshCurrentDeviceDetail === 'function') refreshCurrentDeviceDetail(); }, 1200);
    } catch (e) {
        showToast('Errore di comunicazione: ' + (e.message || e), 'danger');
    }
}
