/**
 * Smart Garage - Unified Frontend API Client (api.js)
 * 
 * Єдиний модуль взаємодії веб-інтерфейсів (index.html та dashboard.html)
 * із серверним бекендом SmartGarage.
 * 
 * Забезпечує:
 * - Уніфіковані виклики REST API з автоматичною передачею CSRF-токенів та PIN-авторизації.
 * - Керування автентифікацією адміністратора (verify, logout, стан сесії).
 * - Методи для керування світлом, воротами, проектором, звуком, телеметрією та присутністю.
 */

(function (root, factory) {
    if (typeof define === 'function' && define.amd) {
        define([], factory);
    } else if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else {
        root.GarageAPI = factory();
        root.SG_API = root.GarageAPI; // Аліас для сумісності
    }
}(typeof self !== 'undefined' ? self : this, function () {
    'use strict';

    const STORAGE_KEY_AUTH = 'sg_admin_auth';
    const STORAGE_KEY_CSRF = 'sg_csrf_token';

    /**
     * Отримання збереженого CSRF-токена
     */
    function getCsrfToken() {
        return sessionStorage.getItem(STORAGE_KEY_CSRF) || '';
    }

    /**
     * Збереження CSRF-токена
     */
    function setCsrfToken(token) {
        if (token) {
            sessionStorage.setItem(STORAGE_KEY_CSRF, token);
        } else {
            sessionStorage.removeItem(STORAGE_KEY_CSRF);
        }
    }

    /**
     * Базовий уніфікований метод виконання HTTP-запитів
     */
    async function request(endpoint, options = {}) {
        const method = (options.method || 'GET').toUpperCase();
        const headers = Object.assign({}, options.headers || {});

        const csrfToken = getCsrfToken();
        if (csrfToken && !headers['X-CSRF-Token']) {
            headers['X-CSRF-Token'] = csrfToken;
        }

        let body = options.body;
        if (body && typeof body === 'object' && !(body instanceof FormData) && !(body instanceof URLSearchParams)) {
            if (!headers['Content-Type']) {
                headers['Content-Type'] = 'application/json';
            }
            body = JSON.stringify(body);
        }

        const fetchOptions = {
            method: method,
            headers: headers,
            body: body,
            credentials: options.credentials || 'same-origin'
        };

        let response;
        try {
            response = await fetch(endpoint, fetchOptions);
        } catch (netErr) {
            const err = new Error('Помилка мережі: не вдалося встановити зв\'язок із сервером SmartGarage.');
            err.cause = netErr;
            window.dispatchEvent(new CustomEvent('sg:api-error', { detail: { endpoint, error: err } }));
            throw err;
        }

        let data = null;
        const contentType = response.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
            try {
                data = await response.json();
            } catch {
                data = null;
            }
        } else {
            data = await response.text();
        }

        if (data && data.csrf_token) {
            setCsrfToken(data.csrf_token);
        }

        if (!response.ok) {
            const errMsg = (data && (data.error || data.message))
                ? (data.error || data.message)
                : `Помилка сервера HTTP ${response.status} (${response.statusText})`;
            const httpErr = new Error(errMsg);
            httpErr.status = response.status;
            httpErr.data = data;

            if (response.status === 401 || response.status === 403) {
                sessionStorage.removeItem(STORAGE_KEY_AUTH);
                window.dispatchEvent(new CustomEvent('sg:auth-expired', { detail: { endpoint, status: response.status } }));
            }

            window.dispatchEvent(new CustomEvent('sg:api-error', { detail: { endpoint, error: httpErr } }));
            throw httpErr;
        }

        return data;
    }

    // =========================================================================
    // ПІДСИСТЕМА АВТЕНТИФІКАЦІЇ (AUTH)
    // =========================================================================
    const auth = {
        isAuthenticated() {
            return sessionStorage.getItem(STORAGE_KEY_AUTH) === 'true';
        },

        async fetchCsrf() {
            try {
                const res = await request('/api/csrf', { method: 'GET' });
                if (res && res.csrf_token) {
                    setCsrfToken(res.csrf_token);
                }
                return res;
            } catch (e) {
                return null;
            }
        },

        async verifyPin(pin) {
            const cleanPin = (pin || '').trim();
            if (!cleanPin) {
                throw new Error('Введіть PIN-код');
            }

            const data = await request('/api/admin/verify', {
                method: 'POST',
                body: { pin: cleanPin }
            });

            if (data && data.authenticated) {
                sessionStorage.setItem(STORAGE_KEY_AUTH, 'true');
                if (data.csrf_token) {
                    setCsrfToken(data.csrf_token);
                }
                window.dispatchEvent(new CustomEvent('sg:auth-changed', { detail: { authenticated: true } }));
                return { success: true, message: 'Авторизація успішна' };
            } else {
                throw new Error((data && data.error) || 'Невірний PIN-код');
            }
        },

        async logout() {
            try {
                await request('/api/admin/logout', { method: 'POST' });
            } finally {
                sessionStorage.removeItem(STORAGE_KEY_AUTH);
                sessionStorage.removeItem(STORAGE_KEY_CSRF);
                window.dispatchEvent(new CustomEvent('sg:auth-changed', { detail: { authenticated: false } }));
            }
            return { success: true };
        }
    };

    // =========================================================================
    // ПІДСИСТЕМА КЕРУВАННЯ ПРИСТРОЯМИ ТА РЕЛЕ (DEVICES)
    // =========================================================================
    const devices = {
        async getState() {
            return await request('/api/garage/state');
        },

        async setLight(state) {
            return await request('/api/light', {
                method: 'POST',
                body: { state: Boolean(state) }
            });
        },

        async toggleLight() {
            return await request('/api/light', {
                method: 'POST',
                body: { action: 'toggle' }
            });
        },

        async setZoneLight(zone, action) {
            return await request('/api/zone_light', {
                method: 'POST',
                body: { zone: zone, action: action }
            });
        },

        async triggerDoor() {
            return await request('/api/door', {
                method: 'POST',
                body: {}
            });
        },

        async projectorControl(action) {
            return await request('/api/projector', {
                method: 'POST',
                body: { action: action }
            });
        },

        async getProjectorStatus() {
            return await request('/api/projector/status');
        }
    };

    // =========================================================================
    // ПІДСИСТЕМА АУДІО ТА МУЛЬТИМЕДІА (SPEAKER)
    // =========================================================================
    const speaker = {
        async getStatus() {
            return await request('/api/speaker/status');
        },

        async setVolume(volume, target = 'clip5') {
            return await request('/api/speaker/volume', {
                method: 'POST',
                body: { volume: Number(volume), target: target }
            });
        },

        async control(action, target = 'clip5') {
            return await request('/api/speaker/control', {
                method: 'POST',
                body: { action: action, target: target }
            });
        },

        async playRadio(streamUrl, name, target = 'clip5') {
            return await request('/api/radio/play', {
                method: 'POST',
                body: { url: streamUrl, name: name, target: target }
            });
        },

        async connect(target = 'clip5') {
            return await request('/api/speaker/connect', {
                method: 'POST',
                body: { target: target }
            });
        },

        async disconnect(target = 'clip5') {
            return await request('/api/speaker/disconnect', {
                method: 'POST',
                body: { target: target }
            });
        }
    };

    // =========================================================================
    // ПІДСИСТЕМА ТЕЛЕМЕТРІЇ ТА ПРИСУТНОСТІ (TELEMETRY)
    // =========================================================================
    const telemetry = {
        async getLatest() {
            return await request('/api/telemetry');
        },

        async getHistory(limit = 100) {
            return await request(`/api/telemetry/history?limit=${limit}`);
        },

        async getPresence() {
            return await request('/api/presence');
        },

        async triggerScan(duration = 5) {
            return await request('/api/presence/scan', {
                method: 'POST',
                body: { duration: duration }
            });
        }
    };

    return {
        request: request,
        getCsrfToken: getCsrfToken,
        setCsrfToken: setCsrfToken,
        auth: auth,
        devices: devices,
        speaker: speaker,
        telemetry: telemetry
    };
}));
