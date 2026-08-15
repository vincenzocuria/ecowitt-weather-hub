// Service Worker con supporto PWA e Web Push Nativo (iOS 16.4+, Android, Desktop)
const CACHE_NAME = 'meteo-hub-v2';

self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim());
});

// Network-first per garantire sempre i dati meteo in tempo reale
self.addEventListener('fetch', (event) => {
    event.respondWith(
        fetch(event.request).catch(() => caches.match(event.request))
    );
});

// Gestione Notifiche Push in background
self.addEventListener('push', (event) => {
    let payload = {
        title: 'Meteo Alert',
        body: 'Nuovo aggiornamento meteo rilevato dalla tua stazione',
        tag: 'meteo-alert',
        data: { url: '/alerts-page' }
    };

    if (event.data) {
        try {
            const data = event.data.json();
            payload.title = data.title || payload.title;
            payload.body = data.body || data.message || payload.body;
            payload.tag = data.tag || payload.tag;
            payload.data = data.data || payload.data;
        } catch (e) {
            payload.body = event.data.text();
        }
    }

    const options = {
        body: payload.body,
        icon: 'data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🌤️</text></svg>',
        badge: 'data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🔔</text></svg>',
        tag: payload.tag,
        renotify: true,
        data: payload.data,
        vibrate: [200, 100, 200, 100, 200]
    };

    event.waitUntil(
        self.registration.showNotification(payload.title, options)
    );
});

// Click sulla notifica: apre o porta in primo piano l'applicazione
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const targetUrl = (event.notification.data && event.notification.data.url) ? event.notification.data.url : '/alerts-page';

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
            for (const client of clientList) {
                if (client.url.includes(targetUrl) && 'focus' in client) {
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow(targetUrl);
            }
        })
    );
});
