(() => {
  "use strict";

  const COMMAND_WINDOW_MS = 7000;
  const STATUS_POLL_MS = 5000;
  const DEFAULT_PI_URL = "http://raspberrypi.local:5000";

  const WAKE_PHRASES = [
    "מכונית טניס תפעלי",
    "מכונית טניס תפעילי"
  ];

  const COMMAND_PHRASES = {
    FETCH: ["תביא כדור", "תביאי כדור", "הביאי כדור", "תביא כדור טניס"],
    STOP: ["עצור", "עצרי", "סטופ"],
    HOME: ["חזור למקום", "תחזור למקום", "חזרי למקום", "חזרה למקום"]
  };

  const els = {
    modeBadge: document.getElementById("modeBadge"),
    mainStatus: document.getElementById("mainStatus"),
    instruction: document.getElementById("instruction"),
    countdown: document.getElementById("countdown"),
    listenButton: document.getElementById("listenButton"),
    stopListeningButton: document.getElementById("stopListeningButton"),
    heardText: document.getElementById("heardText"),
    lastAction: document.getElementById("lastAction"),
    piStatus: document.getElementById("piStatus"),
    piUrl: document.getElementById("piUrl"),
    savePiUrlButton: document.getElementById("savePiUrlButton"),
    testConnectionButton: document.getElementById("testConnectionButton")
  };

  let listeningWanted = false;
  let recognition = null;
  let recognitionRunning = false;
  let appMode = "wake";
  let commandDeadline = 0;
  let commandTimer = null;
  let restartTimer = null;
  let audioContext = null;

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  function normalizeText(value) {
    return String(value || "")
      .normalize("NFKD")
      .replace(/[\u0591-\u05C7]/g, "")
      .replace(/[.,!?;:'"״׳()\[\]{}\-_/\\]/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .toLowerCase();
  }

  function phraseMatches(text, phrases) {
    const normalizedText = normalizeText(text);
    return phrases.some((phrase) => normalizedText.includes(normalizeText(phrase)));
  }

  function detectCommand(text) {
    for (const [command, phrases] of Object.entries(COMMAND_PHRASES)) {
      if (phraseMatches(text, phrases)) return command;
    }
    return null;
  }

  function getPiUrl() {
    return (localStorage.getItem("tennisCarPiUrl") || DEFAULT_PI_URL).replace(/\/+$/, "");
  }

  function setPiUrl(value) {
    const cleaned = String(value || "").trim().replace(/\/+$/, "");
    if (!/^https?:\/\//i.test(cleaned)) {
      throw new Error("הכתובת חייבת להתחיל ב-http:// או https://");
    }
    localStorage.setItem("tennisCarPiUrl", cleaned);
    els.piUrl.value = cleaned;
    return cleaned;
  }

  function setModeBadge(text, className) {
    els.modeBadge.textContent = text;
    els.modeBadge.className = `mode-badge ${className}`;
  }

  function showWakeMode(message = "ממתין ל־“מכונית טניס תפעלי”") {
    appMode = "wake";
    commandDeadline = 0;
    if (commandTimer) clearInterval(commandTimer);
    commandTimer = null;
    els.countdown.classList.add("hidden");
    setModeBadge(listeningWanted ? "מאזין" : "ממתין להפעלה", listeningWanted ? "listening" : "waiting");
    els.mainStatus.textContent = message;
    els.instruction.textContent = "אמור: “מכונית טניס תפעלי”";
  }

  function enterCommandMode() {
    appMode = "command";
    commandDeadline = Date.now() + COMMAND_WINDOW_MS;
    setModeBadge("ממתין לפקודה", "command");
    els.mainStatus.textContent = "דבר עכשיו";
    els.instruction.textContent = "תביא כדור • עצור • חזור למקום";
    els.countdown.classList.remove("hidden");
    beep(880, 100);

    if (commandTimer) clearInterval(commandTimer);
    commandTimer = setInterval(() => {
      const remainingMs = Math.max(0, commandDeadline - Date.now());
      els.countdown.textContent = `${Math.ceil(remainingMs / 1000)} שנ׳`;
      if (remainingMs <= 0) {
        clearInterval(commandTimer);
        commandTimer = null;
        beep(360, 90);
        showWakeMode("לא זוהתה פקודה");
      }
    }, 100);
  }

  function ensureAudioContext() {
    if (!audioContext) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) audioContext = new AudioCtx();
    }
    if (audioContext?.state === "suspended") audioContext.resume().catch(() => {});
  }

  function beep(frequency = 880, durationMs = 100) {
    try {
      ensureAudioContext();
      if (!audioContext) return;
      const oscillator = audioContext.createOscillator();
      const gain = audioContext.createGain();
      oscillator.frequency.value = frequency;
      gain.gain.setValueAtTime(0.0001, audioContext.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.16, audioContext.currentTime + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, audioContext.currentTime + durationMs / 1000);
      oscillator.connect(gain);
      gain.connect(audioContext.destination);
      oscillator.start();
      oscillator.stop(audioContext.currentTime + durationMs / 1000 + 0.02);
    } catch (_) {}
  }

  function scheduleRecognitionRestart(delayMs = 250) {
    clearTimeout(restartTimer);
    if (!listeningWanted || recognitionRunning || !recognition) return;
    restartTimer = setTimeout(() => {
      if (!listeningWanted || recognitionRunning) return;
      try {
        recognition.start();
      } catch (_) {
        scheduleRecognitionRestart(600);
      }
    }, delayMs);
  }

  function createRecognition() {
    if (!SpeechRecognition) return null;

    const r = new SpeechRecognition();
    r.lang = "he-IL";
    r.continuous = false;
    r.interimResults = false;
    r.maxAlternatives = 3;

    r.onstart = () => {
      recognitionRunning = true;
      if (appMode === "wake") showWakeMode();
    };

    r.onresult = (event) => {
      const result = event.results[event.results.length - 1];
      const alternatives = [];
      for (let i = 0; i < result.length; i += 1) {
        if (result[i]?.transcript) alternatives.push(result[i].transcript.trim());
      }
      const heard = alternatives.join(" / ");
      els.heardText.textContent = heard || "—";

      if (appMode === "wake") {
        const wakeMatched = alternatives.some((text) => phraseMatches(text, WAKE_PHRASES));
        if (wakeMatched) enterCommandMode();
        return;
      }

      if (Date.now() > commandDeadline) {
        showWakeMode("חלון הפקודה הסתיים");
        return;
      }

      let command = null;
      for (const text of alternatives) {
        command = detectCommand(text);
        if (command) break;
      }

      if (!command) {
        els.mainStatus.textContent = "לא הבנתי — נסה שוב";
        els.instruction.textContent = "תביא כדור • עצור • חזור למקום";
        beep(430, 80);
        return;
      }

      executeVoiceCommand(command);
    };

    r.onerror = (event) => {
      const code = event.error || "unknown";
      if (code === "no-speech" || code === "aborted") return;

      if (code === "not-allowed" || code === "service-not-allowed") {
        listeningWanted = false;
        recognitionRunning = false;
        setModeBadge("אין הרשאת מיקרופון", "error");
        els.mainStatus.textContent = "צריך לאשר שימוש במיקרופון";
        els.instruction.textContent = "אפשר עדיין לבדוק את המכונית באמצעות הכפתורים הידניים.";
        updateListeningButtons();
        return;
      }

      els.mainStatus.textContent = `שגיאת זיהוי קול: ${code}`;
    };

    r.onend = () => {
      recognitionRunning = false;
      scheduleRecognitionRestart(220);
    };

    return r;
  }

  function updateListeningButtons() {
    els.listenButton.classList.toggle("hidden", listeningWanted);
    els.stopListeningButton.classList.toggle("hidden", !listeningWanted);
  }

  async function startListening() {
    ensureAudioContext();

    if (!SpeechRecognition) {
      setModeBadge("לא נתמך בדפדפן", "error");
      els.mainStatus.textContent = "זיהוי קולי לא זמין כאן";
      els.instruction.textContent = "נסה Chrome/Android או Safari/iPhone מעודכן. הכפתורים הידניים עדיין עובדים.";
      return;
    }

    if (!recognition) recognition = createRecognition();
    listeningWanted = true;
    updateListeningButtons();
    showWakeMode();
    scheduleRecognitionRestart(0);
  }

  function stopListening() {
    listeningWanted = false;
    clearTimeout(restartTimer);
    if (commandTimer) clearInterval(commandTimer);
    commandTimer = null;
    commandDeadline = 0;
    if (recognitionRunning && recognition) {
      try { recognition.abort(); } catch (_) {}
    }
    recognitionRunning = false;
    updateListeningButtons();
    showWakeMode("ההאזנה הופסקה");
  }

  async function localFetch(path, options = {}) {
    const url = `${getPiUrl()}${path}`;
    const requestOptions = {
      cache: "no-store",
      ...options,
      targetAddressSpace: "local"
    };
    return fetch(url, requestOptions);
  }

  function setPiStatus(state, text) {
    els.piStatus.className = `pi-status ${state}`;
    els.piStatus.querySelector("span:last-child").textContent = text;
  }

  async function checkPiConnection() {
    setPiStatus("unknown", "בודק...");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    try {
      const response = await localFetch("/api/phone-status", { signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const version = data.software_version ? ` • ${data.software_version}` : "";
      setPiStatus("online", `מחובר${version}`);
      return true;
    } catch (_) {
      setPiStatus("offline", "אין חיבור");
      return false;
    } finally {
      clearTimeout(timeout);
    }
  }

  async function sendCommand(command) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await localFetch("/api/phone-command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command }),
        signal: controller.signal
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.ok === false) {
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      setPiStatus("online", "מחובר");
      return data;
    } finally {
      clearTimeout(timeout);
    }
  }

  function commandHebrew(command) {
    return {
      FETCH: "תביא כדור",
      STOP: "עצור",
      HOME: "חזור למקום"
    }[command] || command;
  }

  async function executeVoiceCommand(command) {
    const label = commandHebrew(command);
    showWakeMode(`שולח: ${label}`);
    els.lastAction.textContent = `פקודה אחרונה: ${label} — שולח...`;

    try {
      const data = await sendCommand(command);
      const result = data.result || "בוצע";
      els.lastAction.textContent = `פקודה אחרונה: ${label} — ${result}`;
      els.mainStatus.textContent = `✅ ${label}`;
      beep(command === "STOP" ? 520 : 1040, 120);
    } catch (error) {
      setPiStatus("offline", "אין חיבור");
      els.lastAction.textContent = `פקודה אחרונה: ${label} — נכשלה`;
      els.mainStatus.textContent = `❌ לא הצלחתי לשלוח: ${label}`;
      els.instruction.textContent = error?.message || "בדוק את כתובת ה‑Raspberry Pi ואת ה‑Wi‑Fi";
      beep(240, 180);
    }

    setTimeout(() => {
      if (appMode === "wake") showWakeMode();
    }, 1800);
  }

  els.listenButton.addEventListener("click", startListening);
  els.stopListeningButton.addEventListener("click", stopListening);

  els.savePiUrlButton.addEventListener("click", async () => {
    try {
      setPiUrl(els.piUrl.value);
      await checkPiConnection();
    } catch (error) {
      alert(error.message);
    }
  });

  els.testConnectionButton.addEventListener("click", checkPiConnection);

  document.querySelectorAll("[data-command]").forEach((button) => {
    button.addEventListener("click", () => executeVoiceCommand(button.dataset.command));
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      if (recognitionRunning && recognition) {
        try { recognition.abort(); } catch (_) {}
      }
    } else if (listeningWanted) {
      scheduleRecognitionRestart(350);
    }
  });

  window.addEventListener("online", checkPiConnection);

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("./sw.js").catch((error) => {
        console.warn("Service worker registration failed", error);
      });
    });
  }

  els.piUrl.value = getPiUrl();
  updateListeningButtons();
  showWakeMode("לחץ על “התחל האזנה”");
  checkPiConnection();
  setInterval(() => {
    if (!document.hidden) checkPiConnection();
  }, STATUS_POLL_MS);
})();
