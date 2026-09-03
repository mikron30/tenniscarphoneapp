# Tennis Car Phone App

Installable PWA for controlling the Raspberry Pi tennis-ball collection car from a phone using Hebrew voice commands.

## Voice flow

1. Tap **התחל האזנה** once and allow microphone access.
2. Say **מכונית טניס תפעלי**.
3. The app beeps and opens a 7-second command window.
4. Say one of:
   - **תביא כדור** → sends `FETCH`
   - **עצור** → sends `STOP`
   - **חזור למקום** → sends `HOME`
5. The app returns to wake-phrase mode.

The Raspberry Pi receives only the command code. It does not receive audio or Hebrew speech.

## Raspberry Pi requirement

Run the Tennis Car server version that exposes:

- `GET /api/phone-status`
- `POST /api/phone-command`

The current compatible Raspberry Pi file is **V13.24 PHONE COMMAND API**.

`FETCH` starts the existing safe Stage-2 `kick_tag` flow. `STOP` is an emergency stop. `HOME` is accepted by V13.24 but intentionally does not move the car yet, until the dedicated return-home controller is implemented.

## Pi address and automatic reconnect

The Raspberry Pi host name is `mikipi`, so the app uses this as its default address:

```text
http://mikipi.local:5000
```

This uses local mDNS name resolution, so the app normally does not need to know the numeric IP address assigned by the home or tennis-court Wi-Fi network.

The app checks the Raspberry Pi immediately at startup and then retries every 5 seconds while the PWA is visible. It also checks immediately when the phone comes back online or when the user returns to the PWA.

If a phone previously stored the old first-version default `http://raspberrypi.local:5000`, the app automatically migrates it to `http://mikipi.local:5000`. A manually entered custom address is preserved.

The phone and Raspberry Pi must be reachable on the same local network, and that network must allow devices to communicate with each other. Some guest Wi-Fi networks use client isolation, which can prevent local connections even though both devices have internet access.

## GitHub Pages

This repository is a static site: no build step is required.

In GitHub:

1. Open **Settings → Pages**.
2. Under **Build and deployment**, choose **Deploy from a branch**.
3. Select branch **main** and folder **/(root)**.
4. Press **Save**.

The site should then be published under the repository's GitHub Pages URL.

## Files

- `index.html` — app UI
- `styles.css` — mobile UI styling
- `app.js` — speech recognition, wake phrase state machine, Pi communication and reconnect loop
- `manifest.webmanifest` — PWA metadata
- `sw.js` — offline app-shell service worker
- `icon.svg` — app icon
