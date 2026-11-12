#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tennis Car - Raspberry Pi 3 motor test (V16.6 PI3 TEST).

Standalone, local-network test tool: NO camera, ball detection or autonomous movement.
It controls *one* TB6612FNG motor bridge at a time in short, timed pulses.

Raspberry Pi 3 BCM -> TB6612FNG (physical header pin):
  GPIO17 (11) -> AIN1        GPIO27 (13) -> AIN2
  GPIO23 (16) -> BIN1        GPIO24 (18) -> BIN2
  GPIO12 (32) -> PWMA        GPIO13 (33) -> PWMB
  GPIO16 (36) -> STBY        3V3 (1)   -> VCC
  GND (6)    -> GND         Battery + -> VM, Battery - -> GND

  AO1/AO2 -> BOTH wires of ONE independent motor (steering A)
  BO1/BO2 -> BOTH wires of ANOTHER independent motor (driving B)

DO NOT parallel any Raspberry Pi 3 GPIO outputs with Raspberry Pi 5 GPIO outputs.
DO NOT short AO*, BO* or the motor wires across the two bridges.
DO NOT drive motors which share a common return wire until physically separated.
Keep the old controller disconnected from motor wires during testing.

Start: python3 tennis_car_pi3_motor_test.py
Open:  http://<PI3-IP>:5001
On a Raspberry Pi 3, gpiozero automatically selects an available GPIO backend.
This intentionally DOES NOT force Pi 5's lgpio backend.
"""

import atexit
import secrets
import signal
import sys
import threading
import time

# Do not force GPIOZERO_PIN_FACTORY=lgpio: older Raspberry Pi OS installations
# often have the RPi.GPIO backend instead.
from flask import Flask, jsonify, request, render_template_string
from gpiozero import OutputDevice, PWMOutputDevice

VERSION = "V16.7 PI3 VOLTAGE TEST"
PORT = 5001
MAX_DRIVE_S = 0.28
MAX_STEER_S = 0.14
MAX_PWM_PCT = 75
MIN_PWM_PCT = 20
PWM_FREQUENCY = 400  # software PWM on the Pi 3 (safe for GPIO Zero)

app = Flask(__name__)

class MotorController:
    def __init__(self):
        self.lock = threading.RLock()
        # STBY LOW: motor bridge disabled while the other outputs are configured.
        self.stby = OutputDevice(16, initial_value=False)
        self.ain1 = OutputDevice(17, initial_value=False)
        self.ain2 = OutputDevice(27, initial_value=False)
        self.bin1 = OutputDevice(23, initial_value=False)
        self.bin2 = OutputDevice(24, initial_value=False)
        self.pwma = PWMOutputDevice(12, frequency=PWM_FREQUENCY, initial_value=0)
        self.pwmb = PWMOutputDevice(13, frequency=PWM_FREQUENCY, initial_value=0)
        self.current = "stopped"
        self.deadline = 0.0
        self.session = None
        self.lease_deadline = 0.0
        self.closed = False
        self._stop_locked()

    def _stop_locked(self):
        # Disable the bridge before changing direction to avoid overlap.
        self.stby.off()
        self.pwma.value = 0.0
        self.pwmb.value = 0.0
        self.ain1.off()
        self.ain2.off()
        self.bin1.off()
        self.bin2.off()
        self.current = "stopped"
        self.deadline = 0.0
        self.session = None
        self.lease_deadline = 0.0

    def stop(self):
        with self.lock:
            self._stop_locked()

    def pulse(self, action, power):
        choices = {
            "forward": ("B", self.bin2, self.pwmb, MAX_DRIVE_S),
            "backward": ("B", self.bin1, self.pwmb, MAX_DRIVE_S),
            "left": ("A", self.ain1, self.pwma, MAX_STEER_S),
            "right": ("A", self.ain2, self.pwma, MAX_STEER_S),
        }
        if action not in choices:
            raise ValueError("Unknown action")
        if isinstance(power, bool) or not isinstance(power, (int, float)):
            raise ValueError("Invalid power")
        if not MIN_PWM_PCT <= power <= MAX_PWM_PCT:
            raise ValueError("Power must be between 20% and 75%")
        channel, direction_pin, pwm_pin, duration = choices[action]
        with self.lock:
            if self.closed:
                raise RuntimeError("Motor GPIO controller is closed")
            self._stop_locked()
            time.sleep(0.025)  # H-bridge direction change dead time
            direction_pin.on()
            pwm_pin.value = float(power) / 100
            self.deadline = time.monotonic() + duration
            self.current = action
            self.stby.on()
        return {"action": action, "channel": channel, "power": power,
                "duration_ms": int(duration * 1000)}

    def hold_voltage(self, action, seconds, motors_disconnected):
        """100% steady output for a voltmeter only, both motors disconnected."""
        if motors_disconnected is not True:
            raise ValueError("Disconnect BOTH motors from driver outputs first")
        if type(seconds) is not int or seconds not in (10, 30, 60):
            raise ValueError("Choose 10, 30 or 60 seconds")
        if action not in ("forward", "backward", "left", "right"):
            raise ValueError("Invalid action")
        with self.lock:
            self.pulse(action, 75)
            if action in ("left", "right"):
                self.pwma.value = 1.0
                channel = "A"
            else:
                self.pwmb.value = 1.0
                channel = "B"
            self.deadline = time.monotonic() + seconds
            self.lease_deadline = time.monotonic() + 3.5
            self.session = secrets.token_hex(8)
            return {"action": action, "channel": channel, "seconds": seconds, "session": self.session}

    def heartbeat(self, session):
        with self.lock:
            if self.session and session == self.session and time.monotonic() < self.deadline:
                self.lease_deadline = time.monotonic() + 3.5
                return True
            return False

    def status(self):
        with self.lock:
            return {"version": VERSION, "current": self.current,
                    "milliseconds_remaining": max(0, int((self.deadline - time.monotonic()) * 1000)),
                    "bridge_enabled": bool(self.stby.value)}

    def watchdog(self):
        # Independent of HTTP: motors stop even if the phone disconnects.
        while True:
            time.sleep(0.01)
            with self.lock:
                if self.closed:
                    return
                if self.deadline and time.monotonic() >= self.deadline:
                    self._stop_locked()
                elif self.lease_deadline and time.monotonic() >= self.lease_deadline:
                    self._stop_locked()

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self._stop_locked()
            for device in (self.ain1, self.ain2, self.bin1, self.bin2,
                           self.pwma, self.pwmb, self.stby):
                device.close()

motors = MotorController()
atexit.register(motors.close)
threading.Thread(target=motors.watchdog, name="pi3-motor-watchdog", daemon=True).start()

HTML = '''<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tennis Car - Pi 3 motor test</title>
<style>
*{box-sizing:border-box}body{background:#0e1521;color:#f0f4f8;font-family:system-ui,Arial,sans-serif;margin:0;padding:16px}
main{margin:auto;max-width:560px}h1{font-size:24px;margin:6px 0}p{line-height:1.6}
.top{color:#98b6d3;font-size:13px;margin-bottom:16px}
.warning{background:#3e3225;border:1px solid #a5893e;padding:12px;border-radius:12px;font-size:14px}
.card{background:#1b2b3a;border-radius:16px;padding:16px;margin-top:14px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;direction:ltr}
button{background:#266fbd;color:white;border:0;border-radius:12px;font-size:21px;font-weight:700;min-height:76px;touch-action:manipulation;cursor:pointer}
button:active{background:#42a3df}.forward{grid-column:2}.left{grid-column:1;grid-row:2}.right{grid-column:3;grid-row:2}.backward{grid-column:2;grid-row:3}
button small{display:block;font-size:12px;margin-top:6px;font-weight:400}
button.stop{display:block;width:100%;background:#b33143;margin-top:16px;min-height:60px}
label{display:flex;justify-content:space-between;margin-bottom:10px}input[type=range]{width:100%;accent-color:#4aafff}
#state{min-height:32px;margin-top:16px;color:#c3d7ef;font-size:15px}code{color:#acd8ff}
.note{font-size:13px;color:#b9c8d7}
</style>
</head>
<body><main>
<h1>🚗 שלט ניסוי — Raspberry Pi 3</h1>
<div class="top">{{ version }} · פורט 5001 · ללא זיהוי כדורים</div>
<p class="warning"><strong>לפני בדיקה:</strong> נתק את חוטי הבקרה של הרספברי החדש מהדרייבר. ודא שלכל מנוע זוג חוטים עצמאי, ללא קצר או חוט שחור משותף בין המנועים. נתק את הכרטיס המקורי מהמנועים. התחל כשהגלגלים באוויר.</p>
<div class="card">
<label><strong>עוצמה</strong><span id="powerText">30%</span></label>
<input type="range" id="power" min="20" max="75" step="5" value="30">
<p class="note">לחיצה אחת = פולס קצר; אין צורך להחזיק. נסיעה 280ms, היגוי 140ms.</p>
<div class="grid">
<button class="forward" data-action="forward">▲ <small>קדימה — ערוץ B</small></button>
<button class="left" data-action="left">◀ <small>שמאלה — ערוץ A</small></button>
<button class="right" data-action="right">▶ <small>ימינה — ערוץ A</small></button>
<button class="backward" data-action="backward">▼ <small>אחורה — ערוץ B</small></button>
</div>
<button id="stop" class="stop">■ עצור הכול</button>
<div id="state" aria-live="polite">ממתין לבדיקה</div>
</div>
<div class="card">
<strong>החיבורים לבדיקה</strong>
<p>נסיעה (B): <code>BO1 / BO2</code> לשני חוטי המנוע האחורי.<br>
היגוי (A): <code>AO1 / AO2</code> לשני חוטי מנוע ההיגוי.</p>
<p class="note">התוצאה תישאר ניסיונית עד שנזהה את זוגות המנועים. אין לחבר את יציאות שני הערוצים יחד. עצירה אוטומטית גם בניתוק טלפון.</p>
</div>
<div class="card">
<h3>מדידת מתח רציף — עד דקה</h3>
<div class="warning"><strong>חובה לנתק את שני המנועים</strong> מהדרייבר לפני הפעלה ארוכה! אחרת מנוע ההיגוי עלול להישרף. המתח יהיה 100% DC; עצירה ידנית או אחרי 10/30/60 שניות, ובניתוק הדפדפן תוך כ-3.5 שניות. אל תקצר את יציאות המנוע במדידה.</div>
<label style="display:block;margin-top:12px"><input id="disconnected" type="checkbox"> אישרתי ששני המנועים מנותקים מ-AO1/AO2 וגם מ-BO1/BO2</label>
<label>משך מקסימלי <select id="holdSeconds" style="padding:10px"><option value="10">10 שניות</option><option value="30">30 שניות</option><option value="60" selected>60 שניות</option></select></label>
<p class="note">לחיצה אחת מפעילה מתח קבוע עד עצירה. אותו כפתור שנית = עצירה. מדוד ב-DC בין AO1 ל-AO2 (ימינה/שמאלה) או בין BO1 ל-BO2 (קדימה/אחורה), לא מול GND.</p>
<div class="grid">
<button class="forward" data-hold="forward">▲<small>קדימה · B</small></button>
<button class="left" data-hold="left">◀<small>שמאלה · A</small></button>
<button class="right" data-hold="right">▶<small>ימינה · A</small></button>
<button class="backward" data-hold="backward">▼<small>אחורה · B</small></button>
</div>
<button class="stop" id="holdStop">■ עצור מתח מדידה</button>
<div id="holdStatus">יציאות כבויות</div>
</div>
<script>
const out=document.getElementById('state');
const slider=document.getElementById('power');
slider.oninput=()=>document.getElementById('powerText').textContent=slider.value+'%';
let busy=false;
async function stop(){
 try{await fetch('/api/stop',{method:'POST',cache:'no-store'});out.textContent='המנועים נעצרו';}
 catch(err){out.textContent='אין תקשורת — נתק מתח מנועים אם צריך';}
}
for(const button of document.querySelectorAll('[data-action]')){
 button.onclick=async()=>{
  if(busy)return;busy=true;
  try{
    const response=await fetch('/api/pulse',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:button.dataset.action,power:Number(slider.value)}),cache:'no-store'});
    const result=await response.json();
    if(!response.ok || !result.ok)throw Error(result.error||'שגיאת שלט');
    out.textContent='הופעל '+result.action+' · ערוץ '+result.channel+' · '+result.power+'% · '+result.duration_ms+'ms';
  }catch(err){out.textContent='שגיאה: '+err.message;}finally{busy=false;}
 };
}
document.getElementById('stop').onclick=stop;
window.addEventListener('pagehide',()=>fetch('/api/stop',{method:'POST',keepalive:true}).catch(()=>{}));
</script>
<script>
let activeHold=null;
const holdStatus=document.getElementById('holdStatus');
async function stopHold(){
 activeHold=null;
 try{await fetch('/api/stop',{method:'POST'});holdStatus.textContent='המתח הופסק';}
 catch(e){holdStatus.textContent='שגיאת תקשורת: נתק את מתח הסוללה מיד';}
}
for(const button of document.querySelectorAll('[data-hold]'))button.onclick=async()=>{
 const action=button.dataset.hold;
 if(activeHold&&activeHold.action===action){await stopHold();return;}
 if(!document.getElementById('disconnected').checked){holdStatus.textContent='חובה לנתק שני מנועים ולאשר תחילה';return;}
 try{
  const response=await fetch('/api/hold',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({action:action,seconds:Number(document.getElementById('holdSeconds').value),motors_disconnected:true})});
  const data=await response.json();
  if(!response.ok||!data.ok)throw Error(data.error||'שגיאה');
  activeHold={action:action,session:data.session};
  holdStatus.textContent='מתח רציף 100% · '+action+' · עד '+data.seconds+' שניות. לחץ עצור בכל רגע.';
 }catch(e){activeHold=null;holdStatus.textContent='שגיאה: '+e.message;}
};
document.getElementById('holdStop').onclick=stopHold;
document.getElementById('stop').addEventListener('click',()=>activeHold=null);
setInterval(async()=>{
 if(!activeHold)return;
 try{
  const k=await fetch('/api/heartbeat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session:activeHold.session})});
  if(!k.ok){activeHold=null;holdStatus.textContent='ההפעלה הסתיימה או הופסקה';return;}
  const r=await fetch('/api/status',{cache:'no-store'});
  const s=await r.json();
  if(!s.bridge_enabled){activeHold=null;holdStatus.textContent='המתח הופסק אוטומטית';}
  else holdStatus.textContent='100% DC · '+activeHold.action+' · נשארו '+(s.milliseconds_remaining/1000).toFixed(1)+' שניות';
 }catch(e){holdStatus.textContent='אבד החיבור — הגנת הניתוק תעצור את המנועים';}
},1000);
</script>
</main></body></html>'''

@app.after_request
def disable_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.route('/', methods=['GET'])
def index():
    return render_template_string(HTML, version=VERSION)

@app.route('/api/status', methods=['GET'])
def status():
    return jsonify(motors.status())

@app.route('/api/pulse', methods=['POST'])
def pulse():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify({"ok": True, **motors.pulse(payload.get('action'), payload.get('power'))})
    except (ValueError, RuntimeError) as error:
        return jsonify({"ok": False, "error": str(error)}), 400

@app.route('/api/stop', methods=['POST'])
def stop():
    motors.stop()
    return jsonify({"ok": True})


@app.route('/api/hold', methods=['POST'])
def hold_voltage():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify({"ok": True, **motors.hold_voltage(payload.get('action'), payload.get('seconds'), payload.get('motors_disconnected'))})
    except (ValueError, RuntimeError) as error:
        return jsonify({"ok": False, "error": str(error)}), 400

@app.route('/api/heartbeat', methods=['POST'])
def voltage_heartbeat():
    payload = request.get_json(silent=True) or {}
    if motors.heartbeat(payload.get('session')):
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 409


def exit_signal(signum, frame):
    motors.stop()
    sys.exit(0)

if __name__ == '__main__':
    signal.signal(signal.SIGTERM, exit_signal)
    signal.signal(signal.SIGINT, exit_signal)
    print(VERSION, flush=True)
    print('Open http://<PI3-IP>:5001 from your phone. Motors start OFF.', flush=True)
    try:
        app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False, threaded=True)
    finally:
        motors.close()