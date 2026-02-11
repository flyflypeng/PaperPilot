(() => {
  const supabaseUrl = (window.__SUPABASE_URL || "").trim();
  const supabaseAnonKey = (window.__SUPABASE_ANON_KEY || "").trim();
  if (!supabaseUrl || !supabaseAnonKey) return;
  if (!window.supabase || typeof window.supabase.createClient !== "function") return;

  const client = window.supabase.createClient(supabaseUrl, supabaseAnonKey);
  let accessToken = null;

  if (!window.__paperpilotFetchAuthPatched) {
    window.__paperpilotFetchAuthPatched = true;
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, init = {}) => {
      try {
        const url = typeof input === "string" ? input : input?.url;
        const isApiCall =
          typeof url === "string" && (url.startsWith("/api/") || url.includes("/api/"));
        if (isApiCall && accessToken) {
          const headers = new Headers(
            init.headers || (typeof input !== "string" ? input.headers : undefined)
          );
          if (!headers.has("Authorization")) {
            headers.set("Authorization", `Bearer ${accessToken}`);
          }
          init = { ...init, headers };
        }
      } catch (_e) {}
      return originalFetch(input, init);
    };
  }

  client.auth
    .getSession()
    .then(({ data }) => {
      accessToken = data?.session?.access_token || null;
    })
    .catch(() => {});

  client.auth.onAuthStateChange((_event, session) => {
    accessToken = session?.access_token || null;
  });
})();
