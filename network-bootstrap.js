(() => {
  "use strict";

  const nativeFetch = window.fetch.bind(window);
  const DISCOVERY_ORIGINS = [
    "http://mikipi.local:5000",
    "http://mikipi:5000"
  ];
  const DISCOVERY_ATTEMPT_MS = 1100;

  function cleanOrigin(value) {
    try {
      return new URL(String(value || "")).origin;
    } catch (_) {
      return "";
    }
  }

  function unique(values) {
    return values.filter((value, index, all) => value && all.indexOf(value) === index);
  }

  function carStatusRequest(url, init) {
    if ((init?.method || "GET").toUpperCase() !== "GET") return false;
    try {
      const parsed = new URL(url, window.location.href);
      return parsed.pathname === "/api/phone-status";
    } catch (_) {
      return false;
    }
  }

  function fetchAttempt(url, init, timeoutMs) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    const options = {
      ...init,
      signal: controller.signal,
      cache: "no-store",
      targetAddressSpace: "local"
    };

    return nativeFetch(url, options).finally(() => clearTimeout(timeout));
  }

  window.fetch = async (input, init = {}) => {
    const requestedUrl = typeof input === "string" ? input : input?.url;
    if (!requestedUrl || !carStatusRequest(requestedUrl, init)) {
      return nativeFetch(input, init);
    }

    const parsed = new URL(requestedUrl, window.location.href);
    const stored = cleanOrigin(localStorage.getItem("tennisCarPiUrl"));
    const lastWorking = cleanOrigin(localStorage.getItem("tennisCarLastWorkingPiUrl"));
    const requestedOrigin = parsed.origin;
    const origins = unique([
      requestedOrigin,
      lastWorking,
      stored,
      ...DISCOVERY_ORIGINS
    ]);

    let lastError = null;
    for (const origin of origins) {
      const candidate = `${origin}${parsed.pathname}${parsed.search}`;
      try {
        const response = await fetchAttempt(candidate, init, DISCOVERY_ATTEMPT_MS);
        // Any HTTP response proves that this is a reachable web server.  The
        // normal application still decides whether the response itself is OK.
        localStorage.setItem("tennisCarPiUrl", origin);
        localStorage.setItem("tennisCarLastWorkingPiUrl", origin);
        const inputBox = document.getElementById("piUrl");
        if (inputBox) inputBox.value = origin;
        return response;
      } catch (error) {
        lastError = error;
      }
    }

    throw lastError || new TypeError("Tennis Car was not found on the local network");
  };

  window.addEventListener("DOMContentLoaded", () => {
    const footer = document.querySelector("footer");
    if (footer) footer.textContent = "V4 AUTO NETWORK DISCOVERY • Tennis Car Phone PWA";

    const hint = document.querySelector(".connection-card .hint");
    if (hint) {
      hint.textContent = "האפליקציה מנסה אוטומטית את הכתובת האחרונה, mikipi.local ו-mikipi. הטלפון והמכונית צריכים להיות באותה רשת Wi‑Fi.";
    }

    const status = document.getElementById("mainStatus");
    if (status && status.textContent.includes("V3 HIT COMMUNICATION TEST")) {
      status.textContent = status.textContent.replace("V3 HIT COMMUNICATION TEST", "V4 AUTO NETWORK DISCOVERY");
    }
  });
})();
