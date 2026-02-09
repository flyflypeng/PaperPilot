const SUPABASE_URL = window.__SUPABASE_URL || '';
const SUPABASE_ANON_KEY = window.__SUPABASE_ANON_KEY || '';

const supabaseClient = (window.supabase?.createClient && SUPABASE_URL && SUPABASE_ANON_KEY)
    ? window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY)
    : null;

let currentSession = null;
let appLoaded = false;
let appLoading = false;

document.addEventListener('DOMContentLoaded', async () => {
    bindAuthUIHandlers();

    if (!supabaseClient) {
        showLoginOverlay();
        setAuthError('Supabase 未配置：请在后端设置 SUPABASE_URL 和 SUPABASE_ANON_KEY');
        return;
    }

    const { data: { session } } = await supabaseClient.auth.getSession();
    currentSession = session;
    updateAuthUI(session);

    supabaseClient.auth.onAuthStateChange((_event, session) => {
        currentSession = session;
        updateAuthUI(session);
    });
});

function bindAuthUIHandlers() {
    const loginForm = document.getElementById('auth-form');
    if (loginForm) {
        loginForm.addEventListener('submit', handleAuth);
    }

    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', handleLogout);
    }

    const loginBtn = document.getElementById('login-btn');
    if (loginBtn) {
        loginBtn.addEventListener('click', () => {
            showLoginOverlay();
            clearAuthError();
        });
    }

    const toggleAuthModeBtn = document.getElementById('toggle-auth-mode');
    if (toggleAuthModeBtn) {
        toggleAuthModeBtn.addEventListener('click', toggleAuthMode);
    }
}

function getAccessToken() {
    return currentSession?.access_token || null;
}

function showLoginOverlay() {
    const loginOverlay = document.getElementById('login-overlay');
    if (loginOverlay) {
        loginOverlay.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    }
}

function hideLoginOverlay() {
    const loginOverlay = document.getElementById('login-overlay');
    if (loginOverlay) {
        loginOverlay.style.display = 'none';
        document.body.style.overflow = '';
    }
}

function updateAuthUI(session) {
    const loginBtn = document.getElementById('login-btn');
    const logoutBtn = document.getElementById('logout-btn');
    const userNameDisplay = document.getElementById('setting-user-name');

    if (session) {
        hideLoginOverlay();
        if (loginBtn) loginBtn.style.display = 'none';
        if (logoutBtn) logoutBtn.style.display = 'inline-flex';

        if (userNameDisplay && userNameDisplay.textContent === 'Paper Reader') {
            userNameDisplay.textContent = session.user.email.split('@')[0];
        }

        ensureAppLoaded();
        return;
    }

    showLoginOverlay();
    if (loginBtn) loginBtn.style.display = 'inline-flex';
    if (logoutBtn) logoutBtn.style.display = 'none';
}

function ensureAppLoaded() {
    if (appLoaded || appLoading) return;
    if (!getAccessToken()) return;

    const existing = document.getElementById('resophy-app-script');
    if (existing) {
        appLoading = true;
        return;
    }

    patchFetchWithAuth();

    appLoading = true;
    const script = document.createElement('script');
    script.id = 'resophy-app-script';
    script.src = '/static/js/app.js?v=1.2';
    script.onload = () => {
        appLoaded = true;
        appLoading = false;
    };
    script.onerror = () => {
        appLoading = false;
    };
    document.body.appendChild(script);
}

function patchFetchWithAuth() {
    if (window.__fetchPatchedForAuth) return;
    window.__fetchPatchedForAuth = true;

    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, init = {}) => {
        try {
            const url = typeof input === 'string' ? input : input.url;
            const isApiCall = typeof url === 'string' && url.startsWith('/api/');
            const token = getAccessToken();
            if (isApiCall && token) {
                const headers = new Headers(init.headers || (typeof input !== 'string' ? input.headers : undefined));
                if (!headers.has('Authorization')) {
                    headers.set('Authorization', `Bearer ${token}`);
                }
                init = { ...init, headers };
            }
        } catch {
        }
        return originalFetch(input, init);
    };
}

let isSignUp = false;

function syncAuthModeUI() {
    const title = document.getElementById('auth-title');
    const submitBtn = document.getElementById('auth-submit');
    const toggleBtn = document.getElementById('toggle-auth-mode');
    const toggleText = document.getElementById('auth-toggle-text');

    if (isSignUp) {
        if (title) title.textContent = 'Sign Up';
        if (submitBtn) submitBtn.textContent = 'Sign Up';
        if (toggleText) toggleText.textContent = 'Already have an account?';
        if (toggleBtn) toggleBtn.textContent = 'Log In';
    } else {
        if (title) title.textContent = 'Log In';
        if (submitBtn) submitBtn.textContent = 'Log In';
        if (toggleText) toggleText.textContent = "Don't have an account?";
        if (toggleBtn) toggleBtn.textContent = 'Sign Up';
    }
}

function toggleAuthMode(e) {
    e.preventDefault();
    clearAuthError();
    isSignUp = !isSignUp;
    syncAuthModeUI();
}

function setAuthError(message, color = '#ef5350') {
    const errorMsg = document.getElementById('auth-error');
    if (!errorMsg) return;
    errorMsg.style.color = color;
    errorMsg.textContent = message;
    errorMsg.style.display = 'block';
}

function clearAuthError() {
    const errorMsg = document.getElementById('auth-error');
    if (!errorMsg) return;
    errorMsg.style.display = 'none';
    errorMsg.textContent = '';
}

async function handleAuth(e) {
    e.preventDefault();
    if (!supabaseClient) return;

    const email = (document.getElementById('auth-email')?.value || '').trim();
    const password = (document.getElementById('auth-password')?.value || '').trim();
    const submitBtn = document.getElementById('auth-submit');

    clearAuthError();
    if (!email || !password) {
        setAuthError('请输入邮箱和密码');
        return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = isSignUp ? 'Signing up...' : 'Logging in...';

    try {
        if (isSignUp) {
            const emailRedirectTo = `${window.location.origin}/`;
            const { error } = await supabaseClient.auth.signUp({
                email,
                password,
                options: {
                    emailRedirectTo,
                },
            });
            if (error) throw error;
            setAuthError('注册成功，请登录。', '#16a34a');
            isSignUp = false;
            syncAuthModeUI();
            return;
        }

        const { error } = await supabaseClient.auth.signInWithPassword({ email, password });
        if (error) throw error;
    } catch (error) {
        setAuthError(error.message || '操作失败');
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = isSignUp ? 'Sign Up' : 'Log In';
    }
}

async function handleLogout() {
    if (!supabaseClient) return;
    await supabaseClient.auth.signOut();
}
