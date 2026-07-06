/**
 * Session-token auth — reads ?token= from the launch URL once, persists it,
 * and attaches it to every API fetch and WebSocket connect.
 */

const STORAGE_KEY = 'lumakit_session_token';

function initToken() {
    const params = new URLSearchParams(location.search);
    const fromUrl = params.get('token');
    if (fromUrl) {
        try {
            localStorage.setItem(STORAGE_KEY, fromUrl);
        } catch (e) {
            // Private mode without storage — keep the token in memory only.
        }
        params.delete('token');
        const query = params.toString();
        history.replaceState(null, '', location.pathname + (query ? `?${query}` : '') + location.hash);
        return fromUrl;
    }
    try {
        return localStorage.getItem(STORAGE_KEY) || '';
    } catch (e) {
        return '';
    }
}

const token = initToken();

export function getToken() {
    return token;
}

export function wsUrl(path) {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const sep = path.includes('?') ? '&' : '?';
    const suffix = token ? `${sep}token=${encodeURIComponent(token)}` : '';
    return `${protocol}//${location.host}${path}${suffix}`;
}

// Attach the token header to same-origin API calls without touching every
// fetch('/api/...') call site.
const rawFetch = window.fetch.bind(window);
window.fetch = (input, init = {}) => {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (token && url.startsWith('/api/')) {
        init = { ...init, headers: { ...(init.headers || {}), 'X-LumaKit-Token': token } };
    }
    return rawFetch(input, init);
};
