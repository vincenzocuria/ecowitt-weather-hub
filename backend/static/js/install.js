/*
 * Pulsante "Installa app"
 * - Android / Chrome / Edge / Samsung Internet: usa l'evento beforeinstallprompt per aprire la
 *   finestra di installazione nativa con un tocco.
 * - iPhone / iPad (Safari): Apple non permette l'installazione da codice, si mostrano i passaggi.
 * - Se il browser non ha ancora proposto l'installazione, si mostrano le istruzioni del menu.
 * Va caricato in <head> (sincrono): l'evento può arrivare prima che la pagina sia pronta.
 */
(function () {
    'use strict';

    var deferredPrompt = null;
    var DISMISS_KEY = 'hub_install_banner_dismissed';

    function isStandalone() {
        return (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) ||
            window.navigator.standalone === true;
    }

    var ua = navigator.userAgent || '';
    var isIOS = /iPhone|iPad|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    var isSamsung = /SamsungBrowser/.test(ua);

    window.addEventListener('beforeinstallprompt', function (e) {
        e.preventDefault();
        deferredPrompt = e;
        refresh();
    });

    window.addEventListener('appinstalled', function () {
        deferredPrompt = null;
        refresh();
        if (typeof showToast === 'function') showToast('App installata nella schermata Home 🎉', 'success');
    });

    function instructionsHtml() {
        if (isIOS) {
            return '<ol class="install-steps">' +
                '<li>Apri questa pagina in <strong>Safari</strong></li>' +
                '<li>Tocca il tasto <strong>Condividi</strong> <span aria-hidden="true">(il quadrato con la freccia ⬆️)</span></li>' +
                '<li>Scorri e scegli <strong>Aggiungi alla schermata Home</strong></li>' +
                '<li>Tocca <strong>Aggiungi</strong> in alto a destra</li>' +
                '</ol>';
        }
        if (isSamsung) {
            return '<ol class="install-steps">' +
                '<li>Tocca il menu <strong>≡</strong> in basso a destra</li>' +
                '<li>Scegli <strong>Aggiungi pagina a</strong> → <strong>Schermata Home</strong></li>' +
                '</ol>';
        }
        return '<ol class="install-steps">' +
            '<li>Tocca il menu <strong>⋮</strong> in alto a destra di Chrome</li>' +
            '<li>Scegli <strong>Installa app</strong> (oppure <strong>Aggiungi a schermata Home</strong>)</li>' +
            '<li>Conferma con <strong>Installa</strong></li>' +
            '</ol>' +
            '<p class="install-note">Se la voce non compare, ricarica la pagina e riprova: dopo una disinstallazione Chrome a volte la ripropone con qualche minuto di ritardo.</p>';
    }

    function showInstructions() {
        var existing = document.getElementById('install-dialog');
        if (existing) existing.remove();
        var dlg = document.createElement('div');
        dlg.id = 'install-dialog';
        dlg.className = 'install-dialog-backdrop';
        dlg.setAttribute('role', 'dialog');
        dlg.setAttribute('aria-modal', 'true');
        dlg.setAttribute('aria-labelledby', 'install-dialog-title');
        dlg.innerHTML =
            '<div class="install-dialog">' +
            '<img src="/static/icons/icon-192.png?v=2" alt="" width="64" height="64" class="install-dialog-icon">' +
            '<h2 id="install-dialog-title">Installa Weather Hub</h2>' +
            instructionsHtml() +
            '<button type="button" class="btn btn-primary install-dialog-close">Ho capito</button>' +
            '</div>';
        dlg.addEventListener('click', function (e) {
            if (e.target === dlg || e.target.classList.contains('install-dialog-close')) dlg.remove();
        });
        document.body.appendChild(dlg);
        dlg.querySelector('.install-dialog-close').focus();
    }

    function install() {
        if (deferredPrompt) {
            var p = deferredPrompt;
            deferredPrompt = null;
            p.prompt();
            p.userChoice.then(refresh, refresh);
            return;
        }
        showInstructions();
    }

    function refresh() {
        var installed = isStandalone();
        document.querySelectorAll('[data-install-app]').forEach(function (el) {
            el.hidden = installed;
        });
        var banner = document.getElementById('install-banner');
        if (banner) {
            var dismissed = false;
            try { dismissed = localStorage.getItem(DISMISS_KEY) === '1'; } catch (e) {}
            banner.hidden = installed || dismissed;
        }
    }

    document.addEventListener('click', function (e) {
        var trigger = e.target.closest && e.target.closest('[data-install-trigger]');
        if (trigger) {
            e.preventDefault();
            install();
            return;
        }
        var close = e.target.closest && e.target.closest('[data-install-dismiss]');
        if (close) {
            try { localStorage.setItem(DISMISS_KEY, '1'); } catch (err) {}
            refresh();
        }
    });

    document.addEventListener('DOMContentLoaded', refresh);
    window.HubInstall = { install: install, isStandalone: isStandalone };
})();
