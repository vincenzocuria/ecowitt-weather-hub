/*
 * Tema Chiaro / Scuro / Automatico
 * ---------------------------------
 * L'interfaccia è stata disegnata in scuro con molti colori scritti a mano (CSS, <style> nei template,
 * stili inline e HTML generato da JavaScript). Invece di duplicare migliaia di regole, in modalità chiara
 * questo script converte i colori al volo con regole coerenti:
 *   - sfondi/bordi neutri scuri  -> chiari (luminosità invertita, stessa tinta e trasparenza)
 *   - testi chiari               -> scuri (con limite di luminosità per garantire il contrasto)
 *   - colori accesi (pulsanti, badge) restano invariati come sfondo, ma diventano più scuri come testo
 * Va caricato in <head> subito DOPO i fogli di stile (sincrono), così la conversione avviene prima del disegno.
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'hub_theme';
    var root = document.documentElement;

    function readPreference() {
        try {
            var v = localStorage.getItem(STORAGE_KEY);
            return (v === 'light' || v === 'dark' || v === 'auto') ? v : 'auto';
        } catch (e) {
            return 'auto';
        }
    }

    var media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;

    function resolve(pref) {
        if (pref === 'light' || pref === 'dark') return pref;
        return media && media.matches ? 'light' : 'dark';
    }

    var preference = readPreference();
    var theme = resolve(preference);
    root.setAttribute('data-theme', theme);
    root.setAttribute('data-theme-pref', preference);
    root.style.colorScheme = theme;

    window.HubTheme = {
        preference: preference,
        theme: theme,
        set: function (pref) {
            try { localStorage.setItem(STORAGE_KEY, pref); } catch (e) {}
            // Ricarica: la conversione dei colori si applica in modo pulito al caricamento
            if (resolve(pref) !== theme || pref !== preference) location.reload();
        }
    };

    if (media && media.addEventListener) {
        media.addEventListener('change', function () {
            if (readPreference() === 'auto' && resolve('auto') !== theme) location.reload();
        });
    }

    var LIGHT = theme === 'light';

    // Durante la conversione iniziale niente transizioni: altrimenti i colori "sfumerebbero"
    // da quelli originali a quelli del tema all'apertura della pagina.
    var noTransition = document.createElement('style');
    noTransition.textContent = '*, *::before, *::after { transition: none !important; }';
    (document.head || root).appendChild(noTransition);

    // ---------------------------------------------------------------- colori
    var NAMED = { white: [255, 255, 255, 1], black: [0, 0, 0, 1] };
    var COLOR_RE = /#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|\b(?:white|black)\b/g;

    function parseColor(str) {
        var s = str.trim().toLowerCase();
        if (NAMED[s]) return NAMED[s].slice();
        if (s[0] === '#') {
            var h = s.slice(1);
            if (h.length === 3 || h.length === 4) h = h.split('').map(function (c) { return c + c; }).join('');
            if (h.length !== 6 && h.length !== 8) return null;
            return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16),
                h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1];
        }
        var m = s.match(/rgba?\(([^)]*)\)/);
        if (!m) return null;
        var parts = m[1].replace(/\//g, ' ').split(/[\s,]+/).filter(Boolean);
        if (parts.length < 3) return null;
        var a = parts.length > 3 ? parts[3] : '1';
        a = a.indexOf('%') > -1 ? parseFloat(a) / 100 : parseFloat(a);
        return [parseFloat(parts[0]), parseFloat(parts[1]), parseFloat(parts[2]), isNaN(a) ? 1 : a];
    }

    function rgbToHsl(r, g, b) {
        r /= 255; g /= 255; b /= 255;
        var max = Math.max(r, g, b), min = Math.min(r, g, b);
        var l = (max + min) / 2, h = 0, s = 0;
        if (max !== min) {
            var d = max - min;
            s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
            if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
            else if (max === g) h = (b - r) / d + 2;
            else h = (r - g) / d + 4;
            h /= 6;
        }
        return [h, s, l];
    }

    function hslToRgb(h, s, l) {
        if (s === 0) { var v = Math.round(l * 255); return [v, v, v]; }
        function hue(p, q, t) {
            if (t < 0) t += 1; if (t > 1) t -= 1;
            if (t < 1 / 6) return p + (q - p) * 6 * t;
            if (t < 1 / 2) return q;
            if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
            return p;
        }
        var q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
        return [Math.round(hue(p, q, h + 1 / 3) * 255), Math.round(hue(p, q, h) * 255), Math.round(hue(p, q, h - 1 / 3) * 255)];
    }

    function luminance(c) {
        function f(v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }
        return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
    }

    function fmt(rgb, a) {
        a = Math.round(a * 1000) / 1000;
        return a >= 1 ? 'rgb(' + rgb[0] + ', ' + rgb[1] + ', ' + rgb[2] + ')'
            : 'rgba(' + rgb[0] + ', ' + rgb[1] + ', ' + rgb[2] + ', ' + a + ')';
    }

    // Tema scuro: il design originale resta invariato, si schiariscono solo i testi troppo spenti
    // (pillole colorate e grigi secondari) per arrivare a un contrasto sufficiente sugli sfondi tinti.
    function mapColorDark(c, mode) {
        if (mode !== 'text') return null;
        var hsl = rgbToHsl(c[0], c[1], c[2]), h = hsl[0], s = hsl[1], l = hsl[2];
        var lum = luminance(c), target = s < 0.25 ? 0.45 : 0.56;
        if (lum < 0.12 || lum >= target) return null;           // testo scuro voluto (su sfondi chiari) o già leggibile
        var nl = l, rgb = [c[0], c[1], c[2]];
        while (luminance(rgb) < target && nl < 0.95) {
            nl += 0.02;
            rgb = hslToRgb(h, s, nl);
        }
        return fmt(rgb, Math.max(c[3], 0.9));
    }

    function isAccent(c) {
        var hsl = rgbToHsl(c[0], c[1], c[2]);
        return hsl[1] >= 0.3 && hsl[2] >= 0.22;
    }

    // mode: 'text' | 'bg' | 'shadow'
    function mapColor(c, mode) {
        if (!LIGHT) return mapColorDark(c, mode);
        var hsl = rgbToHsl(c[0], c[1], c[2]), h = hsl[0], s = hsl[1], l = hsl[2], a = c[3];
        if (mode === 'text') {
            // Decisione sulla luminanza percepita (WCAG), non sulla L di HSL: verdi e gialli accesi
            // hanno L ~0.5 ma sono chiarissimi. Obiettivo: contrasto >= 4.5:1 anche su sfondi colorati tenui.
            var target = s < 0.25 ? 0.10 : 0.08;
            if (luminance(c) <= target) return null;           // già abbastanza scuro: invariato
            var nl = s < 0.25 ? Math.max(0.10, Math.min(1 - l, 0.42)) : Math.min(l, 0.45);
            var rgb = hslToRgb(h, s, nl);
            while (luminance(rgb) > target && nl > 0.05) {
                nl -= 0.02;
                rgb = hslToRgb(h, s, nl);
            }
            return fmt(rgb, Math.max(a, 0.9));
        }
        if (mode === 'shadow') {
            if (l > 0.6 && s < 0.3) return fmt([15, 23, 42], a * 0.5);
            return fmt([c[0], c[1], c[2]], a * 0.45);
        }
        // sfondi e bordi
        if (s < 0.3 || l < 0.22) {
            var nl = 1 - l;
            // sfondi molto scuri e coprenti -> quasi bianchi (le card risultano pulite)
            if (l < 0.22 && a > 0.6) nl = Math.max(nl, 0.94 + (0.22 - l) * 0.25);
            return fmt(hslToRgb(h, Math.min(s, 0.35), Math.min(1, nl)), a);
        }
        return null;                                           // colori accesi: invariati
    }

    function mapValue(value, mode) {
        if (!value) return null;
        COLOR_RE.lastIndex = 0;
        var changed = false;
        var out = value.replace(COLOR_RE, function (tok) {
            var c = parseColor(tok);
            if (!c) return tok;
            var mapped = mapColor(c, mode);
            if (mapped === null) return tok;
            changed = true;
            return mapped;
        });
        COLOR_RE.lastIndex = 0;
        return changed ? out : null;
    }

    var PROPS = {
        'color': 'text', 'fill': 'text', 'stroke': 'text', '-webkit-text-fill-color': 'text', 'caret-color': 'text',
        'background': 'bg', 'background-color': 'bg', 'background-image': 'bg',
        'border': 'bg', 'border-color': 'bg', 'border-top': 'bg', 'border-bottom': 'bg', 'border-left': 'bg', 'border-right': 'bg',
        'border-top-color': 'bg', 'border-bottom-color': 'bg', 'border-left-color': 'bg', 'border-right-color': 'bg',
        'outline': 'bg', 'outline-color': 'bg', 'column-rule-color': 'bg',
        'box-shadow': 'shadow', 'text-shadow': 'shadow'
    };

    function modeFor(prop, style) {
        var mode = PROPS[prop];
        if (!mode) return null;
        // Testo con gradiente (background-clip: text): il "background" è in realtà il colore del testo
        if (mode === 'bg' && prop.indexOf('background') === 0) {
            var clip = style.getPropertyValue('-webkit-background-clip') || style.getPropertyValue('background-clip');
            if (clip && clip.indexOf('text') > -1) return 'text';
        }
        return mode;
    }

    // ------------------------------------------------------- fogli di stile
    var overrideEl = document.createElement('style');
    overrideEl.id = 'hub-theme-overrides';
    var processedSheets = typeof WeakSet !== 'undefined' ? new WeakSet() : null;

    // :where() non aggiunge specificità: una regola originale più specifica (es. .tab.active)
    // continua a prevalere sulla versione convertita di una più generica (es. .tab).
    var SCOPE = ':where(html[data-theme="' + theme + '"])';
    function prefixSelector(sel) {
        return sel.split(',').map(function (part) {
            var p = part.trim();
            if (!p) return p;
            if (p === ':root' || p === 'html') return SCOPE;
            if (p.indexOf(':root') === 0) return SCOPE + p.slice(5);
            if (p.indexOf('html') === 0 && !/^html[\w-]/.test(p)) return SCOPE + p.slice(4);
            return SCOPE + ' ' + p;
        }).join(', ');
    }

    // Le variabili CSS (es. var(--primary)) vengono risolte con i valori del tema chiaro
    var rootStyle = null;
    function resolveVars(value) {
        if (!value || value.indexOf('var(') < 0) return value;
        rootStyle = rootStyle || getComputedStyle(root);
        return value.replace(/var\((--[\w-]+)(?:\s*,\s*([^)]*))?\)/g, function (_, name, fallback) {
            var v = rootStyle.getPropertyValue(name).trim();
            return v || fallback || '';
        });
    }

    function isTextClip(style) {
        var clip = style.getPropertyValue('-webkit-background-clip') || style.getPropertyValue('background-clip');
        return !!clip && clip.indexOf('text') > -1;
    }

    // Una regola con sfondo acceso e coprente (es. pulsante blu) mantiene il proprio testo chiaro:
    // scurirlo darebbe testo scuro su blu.
    function accentBackgroundLuminance(style) {
        if (isTextClip(style)) return -1;
        var props = ['background', 'background-color', 'background-image'];
        for (var i = 0; i < props.length; i++) {
            var v = resolveVars(style.getPropertyValue(props[i]));
            if (!v) continue;
            var toks = v.match(COLOR_RE) || [];
            COLOR_RE.lastIndex = 0;
            for (var k = 0; k < toks.length; k++) {
                var c = parseColor(toks[k]);
                if (c && c[3] >= 0.5 && isAccent(c)) return luminance(c);
            }
        }
        return -1;
    }

    // Shorthand con var(): le proprietà "lunghe" risultano vuote nel CSSOM, va letta la forma abbreviata
    var SHORTHANDS = ['background', 'border', 'border-top', 'border-bottom', 'border-left', 'border-right', 'outline'];

    function convertDecls(st, emit) {
        var accentLum = accentBackgroundLuminance(st);
        var keepText = accentLum >= 0;
        var handled = {};
        for (var s = 0; s < SHORTHANDS.length; s++) {
            var sh = SHORTHANDS[s], val = st.getPropertyValue(sh);
            if (!val || val.indexOf('var(') < 0) continue;
            var shMode = modeFor(sh, st);
            var shMapped = mapValue(val, shMode);
            if (shMapped !== null) emit(sh, shMapped, st.getPropertyPriority(sh));
            handled[sh] = true;
        }
        for (var j = st.length - 1; j >= 0; j--) {
            var prop = st[j];
            var base = prop.replace(/-(color|image|top-color|bottom-color|left-color|right-color|width|style)$/, '');
            if (handled[base] && !st.getPropertyValue(prop)) continue;
            var mode = modeFor(prop, st);
            if (!mode || (mode === 'text' && keepText && (prop === 'color' || prop === 'fill' || prop === 'stroke'))) continue;
            var raw = st.getPropertyValue(prop);
            // Per il testo si risolvono anche le variabili (es. color: var(--accent) su pillole tinte)
            var mapped = mapValue(mode === 'text' ? resolveVars(raw) : raw, mode);
            if (mapped !== null) emit(prop, mapped, st.getPropertyPriority(prop));
        }
        // Sfondo acceso scuro senza colore del testo dichiarato: il testo resta bianco
        // (altrimenti erediterebbe il colore scurito di una regola più generica, es. .btn)
        if (LIGHT && keepText && accentLum < 0.2) {
            var declared = parseColor(resolveVars(st.getPropertyValue('color')) || '');
            if (!st.getPropertyValue('color') || (declared && luminance(declared) < 0.2)) emit('color', '#ffffff', '');
        }
    }

    function convertRules(rules, out) {
        for (var i = 0; i < rules.length; i++) {
            var rule = rules[i];
            if (rule.type === 1) {                                     // CSSStyleRule
                // Regole già scritte per un tema specifico: non vanno riconvertite
                if (rule.selectorText.indexOf('data-theme') > -1) continue;
                var decls = [];
                convertDecls(rule.style, function (prop, val, prio) {
                    decls.push(prop + ': ' + val + (prio ? ' !important' : ''));
                });
                if (decls.length) out.push(prefixSelector(rule.selectorText) + ' { ' + decls.join('; ') + '; }');
            } else if (rule.type === 4 && rule.cssRules) {             // @media
                var inner = [];
                convertRules(rule.cssRules, inner);
                if (inner.length) out.push('@media ' + rule.conditionText + ' { ' + inner.join('\n') + ' }');
            } else if (rule.type === 12 && rule.cssRules) {            // @supports
                var inner2 = [];
                convertRules(rule.cssRules, inner2);
                if (inner2.length) out.push('@supports ' + rule.conditionText + ' { ' + inner2.join('\n') + ' }');
            }
        }
    }

    function convertSheet(sheet) {
        if (!sheet || sheet.ownerNode === overrideEl) return;
        // Fogli esterni (es. Leaflet da CDN) hanno già un loro aspetto chiaro: non si toccano
        if (sheet.href && sheet.href.indexOf(location.origin) !== 0) return;
        var rules;
        try { rules = sheet.cssRules; } catch (e) { return; }          // fogli cross-origin (font, CDN)
        // Un <style> appena inserito dal parser può essere ancora vuoto: lo si elabora solo quando ha regole
        if (!rules || !rules.length) return;
        if (processedSheets) {
            if (processedSheets.has(sheet)) return;
            processedSheets.add(sheet);
        }
        var out = [];
        convertRules(rules, out);
        if (out.length) overrideEl.appendChild(document.createTextNode(out.join('\n') + '\n'));
    }

    function convertAllSheets() {
        for (var i = 0; i < document.styleSheets.length; i++) convertSheet(document.styleSheets[i]);
        // Inserito una sola volta (in fondo al body a DOMContentLoaded): spostarlo a ogni nuovo foglio
        // genererebbe un ciclo infinito con il MutationObserver.
        if (!overrideEl.parentNode) (document.head || root).appendChild(overrideEl);
    }

    // ---------------------------------------------------------- stili inline
    var lastMapped = typeof WeakMap !== 'undefined' ? new WeakMap() : null;

    function convertInline(el) {
        var attr = el.getAttribute && el.getAttribute('style');
        if (!attr || (lastMapped && lastMapped.get(el) === attr)) return;
        var st = el.style;
        convertDecls(st, function (prop, val, prio) { st.setProperty(prop, val, prio); });
        if (lastMapped) lastMapped.set(el, el.getAttribute('style'));
    }

    function convertTree(node) {
        if (node.nodeType !== 1 || node === overrideEl) return;
        if (node.tagName === 'STYLE' || (node.tagName === 'LINK' && node.rel === 'stylesheet')) {
            if (node.sheet) convertSheet(node.sheet);
            else node.addEventListener('load', function () { convertSheet(node.sheet); convertAllSheets(); });
            convertAllSheets();
            return;
        }
        if (node.hasAttribute('style')) convertInline(node);
        var list = node.querySelectorAll ? node.querySelectorAll('[style], style') : [];
        for (var i = 0; i < list.length; i++) {
            if (list[i].tagName === 'STYLE') { convertSheet(list[i].sheet); convertAllSheets(); }
            else convertInline(list[i]);
        }
    }

    convertAllSheets();

    var observer = new MutationObserver(function (mutations) {
        for (var i = 0; i < mutations.length; i++) {
            var m = mutations[i];
            if (m.type === 'attributes') convertInline(m.target);
            else for (var k = 0; k < m.addedNodes.length; k++) convertTree(m.addedNodes[k]);
        }
    });
    observer.observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ['style'] });

    // Passata finale a documento completo: recupera <style> che erano vuoti quando sono stati inseriti
    document.addEventListener('DOMContentLoaded', function () {
        convertAllSheets();
        convertTree(document.body);
        // A parità di specificità vince l'ultima regola: le conversioni vanno dopo i <style> delle pagine
        document.body.appendChild(overrideEl);
        setTimeout(function () { noTransition.remove(); }, 300);
    });

    // Esposto per il controllo automatico del contrasto e per i grafici
    window.HubTheme.mapColor = function (value, mode) { return mapValue(value, mode || 'text') || value; };
})();
