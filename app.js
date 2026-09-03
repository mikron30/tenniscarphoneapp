(() => {
  "use strict";

  const APP_VERSION = "V2 VOICE DEBUG";
  const COMMAND_WINDOW_MS = 7000;
  const STATUS_POLL_MS = 5000;
  const DEFAULT_PI_URL = "http://mikipi.local:5000";
  const OLD_DEFAULT_PI_URL = "http://raspberrypi.local:5000";

  const WAKE_PHRASES = [
    "מכונית טניס תפעלי",
    "מכונית טניס תפעילי",
    "מכונית טניס תפעל",
    "מכונית טניס תפעיל",
    "מכונית טניס הפעלי",
    "מכונית טניס תתחילי"
  ];

  const COMMAND_PHRASES = {
    FETCH: [
      "תביא כדור",
      "תביאי כדור",
      "הביאי כדור",
      "תביא כדור טניס",
      "תביאי כדור טניס"
    ],
    STOP: ["עצור", "עצרי", "סטופ"],
    HOME: [
      "חזור למקום",
      "תחזור למקום",
      "חזרי למקום",
      "חזרה למקום",
      "תחזרי למקום"
    ]
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
  let connectionCheckRunning = false;
  let wakeTriggeredAt = 0;

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

  function containsAny(text, values) {
    const normalized = normalizeText(text);
    return values.some((value) => normalized.includes(normalizeText(value)));
  }

  function matchesWakePhrase(text) {
    if (phraseMatches(text, WAKE_PHRASES)) return true;

    // Hebrew speech recognition often returns a grammatically different
    // inflection than the exact phrase that was spoken. Keep the wake phrase
    // semantically strict (car + tennis + activation), but tolerate those
    // normal recognition variants.
    const hasCar = containsAny(text, ["מכונית", "מכונת", "מכונה"]);
    const hasTennis = containsAny(text, ["טניס"]);
    const hasActivation = containsAny(text, [
      "תפעלי",
      "תפעילי",
      "תפעל",
      "תפעיל",
      "הפעלי",
      "תתחילי",
      "תתחיל"
    ]);

    return hasCar && hasTennis && hasActivation;
  }

  function detectCommand(text) {
    if (phraseMatches(text, COMMAND_PHRASES.STOP)) return "STOP";

    const normalized = normalizeText(text);

    // FETCH: require both the action and the word ball, so ordinary tennis
    // conversation does not accidentally trigger the car.
    const hasBall = normalized.includes("כדור");
    const hasFetchVerb = containsAny(normalized, ["תביא", "תביאי", "הביאי", "הבא"]);
    if (hasBall && hasFetchVerb) return "FETCH";

    // HOME: require both a return word and place/home word.
    const hasPlace = containsAny(normalized, ["מקום", "הביתה", "בית"]);
    const hasReturnVerb = containsAny(normalized, ["חזור", "תחזור", "תחזרי", "חזרי", "חזרה"]);
    if (hasPlace && hasReturnVerb) return "HOME";

    for (const [command, phrases] of Object.entries(COMMAND_PHRASES)) {
      if (phraseMatches(text, phrases)) return command;
    }

    return null;
  }

  function getPiUrl() {
    let saved = String(localStorage.getItem("tennisCarPiUrl") || "").trim().replace(/\/+$/, "");

    if (!saved || saved.toLowerCase() === OLD_DEFAULT_PI_URL.toLowerCase()) {
      saved = DEFAULT_PI_URL;
      localStorage.setItem("tennisCarPiUrl", saved);
    }

    return saved;
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
    setModeBadge(
      listeningWanted ? "מאזין" : "ממתין להפעלה",
      listeningWanted ? "listening" : "waiting"
    );
    els.mainStatus.textContent = message;
    els.instruction.textContent = "אמור: “מכונית טניס תפעלי”";
  }

  function enterCommandMode() {
    if (Date.now() - wakeTriggeredAt < 800) return;
    wakeTriggeredAt = Date.now();

    appMode = "command";
    commandDeadline = Date.now() + COMMAND_WINDOW_MS;
    setModeBadge("ממתין לפקודה", "command");
    els.mainStatus.textContent = "✅ שמעתי את משפט ההפעלה — דבר אחרי הביפ";
    els.instruction.textContent = "תביא כדור • עצור • חזור למקום";
    els.countdown.classList.remove("hidden");
    beep(880, 100);

    // Start the command window with a fresh recognition session. This avoids
    // the tail of the wake phrase being interpreted as the command.
    if (recognitionRunning && recognition) {
      setTimeout(() => {
        try { recognition.abort(); } catch (_) {}
      }, 120);
    }

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
    if (audioContext?.state === "suspended") {
      audioContext.resume().catch(() => {});
    }
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
    if (!listeningWanted || recognitionRunning || !recognition || document.hidden) return;

    restartTimer = setTimeout(() => {
      if (!listeningWanted || recognitionRunning || document.hidden) return;
      try {
        recognition.start();
      } catch (_) {
        scheduleRecognitionRestart(600);
      }
    }, delayMs);
  }

  function collectAlternatives(result) {
    const alternatives = [];
    for (let i = 0; i < result.length; i += 1) {
      const transcript = result[i]?.transcript?.trim();
      if (transcript && !alternatives.includes(transcript)) alternatives.push(transcript);
    }
    return alternatives;
  }

  function createRecognition() {
    if (!SpeechRecognition) return null;

    const r = new SpeechRecognition();
    r.lang = "he-IL";
    r.continuous = true;
    r.interimResults = true;
    r.maxAlternatives = 5;

    r.onstart = () => {
      recognitionRunning = true;
      if (appMode === "wake") showWakeMode("🎤 המיקרופון פעיל — אני מאזין");
    };

    r.onaudiostart = () => {
      if (listeningWanted) setModeBadge("מיקרופון פעיל", "listening");
    };

    r.onsoundstart = () => {
      if (listeningWanted) els.mainStatus.textContent = "🔊 שומע קול...";
    };

    r.onspeechstart = () => {
      if (listeningWanted) els.mainStatus.textContent = "🗣️ מזהה דיבור...";
    };

    r.onresult = (event) => {
      for (let resultIndex = event.resultIndex; resultIndex < event.results.length; resultIndex += 1) {
        const result = event.results[resultIndex];
        const alternatives = collectAlternatives(result);
        if (!alternatives.length) continue;

        const prefix = result.isFinal ? "" : "… ";
        els.heardText.textContent = `${prefix}${alternatives.join(" / ")}`;

        if (appMode === "wake") {
          // Wake phrase may be acted on even from an interim transcript. This
          // makes activation much faster and avoids waiting for Chrome to end
          // the utterance before opening the command window.
          if (alternatives.some(matchesWakePhrase)) {
            enterCommandMode();
            return;
          }
          continue;
        }

        if (Date.now() > commandDeadline) {
          showWakeMode("חלון הפקודה הסתיים");
          return;
        }

        // Actual car commands are executed only on FINAL recognition results.
        // That prevents an unstable interim transcript from moving the car.
        if (!result.isFinal) continue;

        let command = null;
        for (const text of alternatives) {
          command = detectCommand(text);
          if (command) break;
        }

        if (!command) {
          els.mainStatus.textContent = "שמעתי, אבל לא זיהיתי פקודה — נסה שוב";
          els.instruction.textContent = "תביא כדור • עצור • חזור למקום";
          beep(430, 80);
          continue;
        }

        executeVoiceCommand(command);
        return;
      }
    };

    r.onnomatch = () => {
      els.mainStatus.textContent = "שמעתי קול אבל לא הצלחתי לזהות מילים";
    };

    r.onerror = (event) => {
      const code = event.error || "unknown";

      if (code === "no-speech") {
        if (listeningWanted) els.mainStatus.textContent = "🎤 מאזין — עדיין לא שמעתי דיבור";
        return;
      }

      if (code === "aborted") return;

      if (code === "not-allowed" || code === "service-not-allowed") {
        listeningWanted = false;
        recognitionRunning = false;
        setModeBadge("אין הרשאת מיקרופון", "error");
        els.mainStatus.textContent = "צריך לאשר שימוש במיקרופון";
        els.instruction.textContent = "פתח הרשאות אתר/אפליקציה ואשר Microphone.";
        updateListeningButtons();
        return;
      }

      if (code === "network") {
        els.mainStatus.textContent = "שגיאת זיהוי קול: network";
        els.instruction.textContent = "זיהוי הדיבור של הדפדפן צריך גם חיבור אינטרנט פעיל.";
        return;
      }

      els.mainStatus.textContent = `שגיאת זיהוי קול: ${code}`;
    };

    r.onend = () => {
      recognitionRunning = false;
      if (listeningWanted && !document.hidden) {
        scheduleRecognitionRestart(180);
      }
    };

    return r;
  }

  function updateListeningButtons() {
    els.listenButton.classList.toggle("hidden", listeningWanted);
    els.stopListeningButton.classList.toggle("hidden", !listeningWanted);
  }

  async function verifyMicrophonePermission() {
    if (!navigator.mediaDevices?.getUserMedia) return true;

    let stream = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });
      return true;
    } catch (error) {
      setModeBadge("אין הרשאת מיקרופון", "error");
      els.mainStatus.textContent = "הטלפון לא נתן גישה למיקרופון";
      els.instruction.textContent = `Microphone: ${error?.name || "permission denied"}`;
      return false;
    } finally {
      stream?.getTracks().forEach((track) => track.stop());
    }
  }

  async function startListening() {
    ensureAudioContext();

    if (!SpeechRecognition) {
      setModeBadge("לא נתמך בדפדפן", "error");
      els.mainStatus.textContent = "זיהוי קולי לא זמין כאן";
      els.instruction.textContent = "נסה Chrome באנדרואיד. הכפתורים הידניים עדיין עובדים.";
      return;
    }

    els.mainStatus.textContent = "בודק מיקרופון...";
    const micAllowed = await verifyMicrophonePermission();
    if (!micAllowed) return;

    if (!recognition) recognition = createRecognition();
    listeningWanted = true;
    updateListeningButtons();
    showWakeMode("🎤 המיקרופון אושר — מתחיל להאזין");
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
    return fetch(url, {
      cache: "no-store",
      ...options,
      targetAddressSpace: "local"
    });
  }

  function setPiStatus(state, text) {
    els.piStatus.className = `pi-status ${state}`;
    els.piStatus.querySelector("span:last-child").textContent = text;
  }

  async function checkPiConnection() {
    if (connectionCheckRunning) return false;
    connectionCheckRunning = true;

    setPiStatus("unknown", "בודק mikipi.local...");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);

    try {
      const response = await localFetch("/api/phone-status", { signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const data = await response.json();
      const version = data.software_version ? ` • ${data.software_version}` : "";
      setPiStatus("online", `מחובר ל-mikipi${version}`);
      return true;
    } catch (_) {
      setPiStatus("offline", "mikipi לא נמצא — מנסה שוב אוטומטית");
      return false;
    } finally {
      clearTimeout(timeout);
      connectionCheckRunning = false;
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

      setPiStatus("online", "מחובר ל-mikipi");
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
      setPiStatus("offline", "אין חיבור ל-mikipi — ממשיך לנסות");
      els.lastAction.textContent = `פקודה אחרונה: ${label} — נכשלה`;
      els.mainStatus.textContent = `❌ לא הצלחתי לשלוח: ${label}`;
      els.instruction.textContent = error?.message || "ודא שהטלפון וה-Raspberry Pi באותה רשת Wi-Fi";
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
      return;
    }

    checkPiConnection();
    if (listeningWanted) scheduleRecognitionRestart(350);
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
  showWakeMode(`לחץ על “התחל האזנה” • ${APP_VERSION}`);

  checkPiConnection();
  setInterval(() => {
    if (!document.hidden) checkPiConnection();
  }, STATUS_POLL_MS);
})();