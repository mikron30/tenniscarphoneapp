# Raspberry Pi latest software

Current court-test target: **V15.0 COURT FETCH WHITE LINES**.

## Update from the phone

The Raspberry Pi must already be running **V14.3 PHONE SOFTWARE UPDATE**.

1. On the phone, open `pi/latest_update.py` in this repository and download the file.
2. Connect the phone to the same Wi-Fi as the Raspberry Pi.
3. Open `http://mikipi.local:5000`.
4. Open **Software update from phone**.
5. Select the downloaded `latest_update.py`.
6. Press **UPDATE CAR SOFTWARE**.
7. Wait for the service to restart and reconnect.
8. Check `/api/phone-status`; `software_version` should be `V15.0 COURT FETCH WHITE LINES`.

The installer reconstructs V15.0 from the verified V14.3 backup made by the updater, verifies the target SHA-256, runs `py_compile`, and only then replaces the runtime file. On failure it restores V14.3.

## First court test

Do not start with autonomous FETCH immediately.

1. Put the car just inside one doubles sideline at the net, with the camera facing the player's baseline.
2. Open the normal car remote.
3. Inspect **COURT VISION**. Accepted white court lines should be overlaid in magenta.
4. Press **CALIBRATE COURT — NO MOTION**.
5. Confirm the detected start side is LEFT or RIGHT and that heading is close to 0 degrees toward the baseline.
6. First test with one clearly visible tennis ball and a person ready to press STOP.
7. Then use **FETCH BALL → BASELINE CENTER** / the phone FETCH command.

V15.0 works only on the same half of the court as the car. It does not cross the net. `HOME` remains for a later version.
