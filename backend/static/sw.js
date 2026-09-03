// Service Worker con supporto PWA e Web Push Nativo (iOS 16.4+, Android, Desktop)
const CACHE_NAME = 'meteo-hub-v15';

self.addEventListener('install', (event) => {
    self.skipWaiting();
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

// Network-first per garantire sempre i dati meteo in tempo reale
self.addEventListener('fetch', (event) => {
    event.respondWith(
        fetch(event.request).catch(() => caches.match(event.request))
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
        const badgeCount = (payload.unread_count && payload.unread_count > 0) ? payload.unread_count : 1;
        navigator.setAppBadge(badgeCount).catch(() => {});
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

    // Azzeramento o pulizia badge al click
    if ('clearAppBadge' in navigator) {
        navigator.clearAppBadge().catch(() => {});
    } else if ('setAppBadge' in navigator) {
        navigator.setAppBadge(0).catch(() => {});
    }

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
