// Service Worker con supporto PWA e Web Push Nativo (iOS 16.4+, Android, Desktop)
const CACHE_NAME = 'meteo-hub-v17';
const OFFLINE_URL = '/static/offline.html';
const PRECACHE_URLS = [
    OFFLINE_URL,
    '/static/css/style.css',
    '/static/js/app.js',
    '/static/js/theme.js',
    '/static/icons/icon-192.png',
    '/static/icons/icon.svg'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(PRECACHE_URLS))
            .catch(() => {})
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(
                keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
            );
        }).then(() => self.clients.claim())
    );
});

// Strategia:
// - Pagine HTML: network-first, offline -> pagina offline dedicata (mai pagine autenticate in cache)
// - Asset statici /static/: network-first con copia in cache, offline -> copia in cache
// - API, richieste non-GET e cross-origin (tile radar, CDN): non intercettate
self.addEventListener('fetch', (event) => {
    const req = event.request;
    if (req.method !== 'GET') return;
    const url = new URL(req.url);
    if (url.origin !== self.location.origin) return;

    if (req.mode === 'navigate') {
        event.respondWith(
            fetch(req).catch(() => caches.match(OFFLINE_URL).then((r) => r || Response.error()))
        );
        return;
    }

    if (url.pathname.startsWith('/static/')) {
        event.respondWith(
            fetch(req).then((resp) => {
                if (resp.ok) {
                    const copy = resp.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(req, copy)).catch(() => {});
                }
                return resp;
            }).catch(() => caches.match(req, { ignoreSearch: true }).then((r) => r || Response.error()))
        );
    }
});

// Rotazione della sottoscrizione push da parte del browser: ri-sottoscrive e aggiorna il server,
// altrimenti le notifiche smetterebbero di arrivare senza alcun avviso.
self.addEventListener('pushsubscriptionchange', (event) => {
    const oldOptions = event.oldSubscription && event.oldSubscription.options;
    event.waitUntil(
        (async () => {
            let options = oldOptions;
            if (!options || !options.applicationServerKey) {
                const res = await fetch('/api/push/vapid-public-key', { credentials: 'include' });
                const data = await res.json();
                const raw = atob(data.public_key.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - data.public_key.length % 4) % 4));
                options = { userVisibleOnly: true, applicationServerKey: Uint8Array.from(raw, (c) => c.charCodeAt(0)) };
            }
            const sub = event.newSubscription || await self.registration.pushManager.subscribe(options);
            const subJson = sub.toJSON();
            await fetch('/api/push/subscribe', {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ endpoint: sub.endpoint, keys: subJson.keys })
            });
        })().catch(() => {})
    );
});

// Gestione messaggi dal client principale (es. reset badge o sincronizzazione)
self.addEventListener('message', (event) => {
    if (event.data) {
        if (event.data.type === 'CLEAR_BADGE') {
            if ('clearAppBadge' in navigator) {
                navigator.clearAppBadge().catch(() => {});
            } else if ('setAppBadge' in navigator) {
                navigator.setAppBadge(0).catch(() => {});
            }
        } else if (event.data.type === 'SET_BADGE') {
            const count = parseInt(event.data.count, 10) || 0;
            if (count > 0 && 'setAppBadge' in navigator) {
                navigator.setAppBadge(count).catch(() => {});
            } else if ('clearAppBadge' in navigator) {
                navigator.clearAppBadge().catch(() => {});
            } else if ('setAppBadge' in navigator) {
                navigator.setAppBadge(0).catch(() => {});
            }
        }
    }
});

// Gestione Notifiche Push in background
self.addEventListener('push', (event) => {
    let payload = {
        title: 'Meteo Alert',
        body: 'Nuovo aggiornamento meteo rilevato dalla tua stazione',
        tag: 'meteo-alert',
        unread_count: 1,
        data: { url: '/alerts-page' }
    };

    if (event.data) {
        try {
            const data = event.data.json();
            payload.title = data.title || payload.title;
            payload.body = data.body || data.message || payload.body;
            payload.tag = data.tag || payload.tag;
            payload.unread_count = (typeof data.unread_count === 'number') ? data.unread_count : (data.data && typeof data.data.unread_count === 'number' ? data.data.unread_count : 1);
            payload.data = data.data || payload.data;
        } catch (e) {
            payload.body = event.data.text();
        }
    }

    const options = {
        body: payload.body,
        icon: '/static/icons/icon-192.png',
        badge: '/static/icons/badge-96.png',
        tag: payload.tag,
        renotify: true,
        data: payload.data
    };

    // App Badging API se supportata (imposta il conteggio esatto)
    if ('setAppBadge' in navigator) {
        if (payload.unread_count > 0) {
            navigator.setAppBadge(payload.unread_count).catch(() => {});
        } else if (payload.unread_count === 0 && 'clearAppBadge' in navigator) {
            navigator.clearAppBadge().catch(() => {});
        }
    }

    // Su browser che supportano la vibrazione (es. Android Chrome)
    if ('vibrate' in navigator) {
        options.vibrate = [200, 100, 200];
    }

    // Invia evento anche ai client aperti
    const notifyClients = clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
        for (const client of clientList) {
            client.postMessage({
                type: 'PUSH_RECEIVED',
                title: payload.title,
                body: payload.body,
                tag: payload.tag,
                unread_count: payload.unread_count
            });
        }
    });

    event.waitUntil(
        Promise.all([
            self.registration.showNotification(payload.title, options),
            notifyClients
        ])
    );
});

// Click sulla notifica: apre o porta in primo piano l'applicazione
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const targetUrl = (event.notification.data && event.notification.data.url) ? event.notification.data.url : '/alerts-page';

    // Il badge NON viene azzerato qui: lo aggiorna l'app con il conteggio reale dei non letti
    // quando l'utente apre la pagina allarmi (gli altri avvisi restano da leggere).

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
            for (const client of clientList) {
                if (client.url.includes(targetUrl) && 'focus' in client) {
                    return client.focus();
                }
            }
            if (clientList.length > 0) {
                const firstClient = clientList[0];
                if ('navigate' in firstClient) {
                    firstClient.navigate(targetUrl);
                }
                if ('focus' in firstClient) {
                    return firstClient.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow(targetUrl);
            }
        })
    );
});
