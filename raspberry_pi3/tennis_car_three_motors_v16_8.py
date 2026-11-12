#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tennis car V16.8 - Raspberry Pi 3 / TWO TB6612FNG drivers / THREE motors.

Driver 1 (steering + rear drive), unchanged from V16.6:
  Steering A: AIN1=GPIO17 (pin11), AIN2=GPIO27 (pin13), PWMA=GPIO12 (pin32)
  Rear B:     BIN1=GPIO23 (pin16), BIN2=GPIO24 (pin18), PWMB=GPIO13 (pin33)
Driver 2 (front drive only):
  Front A:    AIN1=GPIO5 (pin29), AIN2=GPIO6 (pin31), PWMA=GPIO18 (pin12)
Shared:       STBY (both boards) = GPIO16 (pin36)
Driver1 VCC=Pi 3V3 pin1, GND=Pi pin6.
Driver2 VCC=Pi 3V3 pin17, GND=Pi pin14.
Both VM=battery positive, both GND=battery negative, all grounds common.
Motors connect ONLY to their own two output terminals; never join motor outputs.
Unconnected driver2 B channel: leave BIN1, BIN2, PWMB disconnected.

Open http://<PI-IP>:5001. Small one-shot pulses only; no autonomous motion.
"""

import atexit
import signal
import sys
import threading
import time

from flask import Flask, jsonify, render_template_string, request
from gpiozero import OutputDevice, PWMOutputDevice

VERSION = "V16.8 THREE MOTORS TWO DRIVERS"
PORT = 5001
PWM_HZ = 400
DRIVE_PULSE_S = 0.27
STEER_PULSE_S = 0.12

app = Flask(__name__)

class ThreeMotors:
    def __init__(self):
        self.lock = threading.RLock()
        self.closed = False
        self.deadline = 0.0
        self.last_action = "stop"
        # Do not drive STBY until every motor pin is initialized LOW.
        self.stby = OutputDevice(16, initial_value=False)
        # (input1, input2, pwm), by BCM numbering.
        self.motors = {
            "steer": (OutputDevice(17, initial_value=False),
                      OutputDevice(27, initial_value=False),
                      PWMOutputDevice(12, frequency=PWM_HZ, initial_value=0)),
            "rear": (OutputDevice(23, initial_value=False),
                     OutputDevice(24, initial_value=False),
                     PWMOutputDevice(13, frequency=PWM_HZ, initial_value=0)),
            "front": (OutputDevice(5, initial_value=False),
                      OutputDevice(6, initial_value=False),
                      PWMOutputDevice(18, frequency=PWM_HZ, initial_value=0)),
        }
        self._off()

    def _off(self):
        self.stby.off()
        for in1, in2, pwm in self.motors.values():
            pwm.value = 0
            in1.off()
            in2.off()
        self.deadline = 0.0
        self.last_action = "stop"

    def stop(self):
        with self.lock:
            self._off()

    def pulse(self, action, mode, drive_power, steer_power, reverse):
        if action not in ("forward", "backward", "left", "right"):
            raise ValueError("Invalid action")
        if mode not in ("both", "front", "rear"):
            raise ValueError("Invalid drive mode")
        if type(drive_power) not in (int, float) or not 20 <= drive_power <= 85:
            raise ValueError("Drive power must be 20-85%")
        if type(steer_power) not in (int, float) or not 20 <= steer_power <= 75:
            raise ValueError("Steering power must be 20-75%")
        if not isinstance(reverse, dict):
            raise ValueError("Invalid inversion settings")
        if any(type(reverse.get(name, False)) is not bool for name in self.motors):
            raise ValueError("Invalid inversion values")
        with self.lock:
            if self.closed:
                raise RuntimeError("GPIO controller closed")
            self._off()
            time.sleep(0.025)  # direction change break-before-make
            if action in ("forward", "backward"):
                motor_names = ("front", "rear") if mode == "both" else (mode,)
                for name in motor_names:
                    in1, in2, pwm = self.motors[name]
                    # Match V16.6 rear wiring: forward uses IN2.
                    direction = 2 if action == "forward" else 1
                    if reverse.get(name, False):
                        direction = 3 - direction
                    (in1 if direction == 1 else in2).on()
                    pwm.value = drive_power / 100.0
                duration = DRIVE_PULSE_S
            else:
                in1, in2, pwm = self.motors["steer"]
                direction = 1 if action == "left" else 2
                if reverse.get("steer", False):
                    direction = 3 - direction
                (in1 if direction == 1 else in2).on()
                pwm.value = steer_power / 100.0
                duration = STEER_PULSE_S
            self.stby.on()  # BOTH TB6612 STBY pins wired to GPIO16
            self.last_action = action + ("/" + mode if action in ("forward", "backward") else "")
            self.deadline = time.monotonic() + duration
            return {"action": action, "mode": mode, "duration_ms": round(duration*1000),
                    "drive_power": drive_power, "steer_power": steer_power}

    def status(self):
        with self.lock:
            return {"version": VERSION, "action": self.last_action,
                    "bridge_enabled": bool(self.stby.value),
                    "ms_remaining": max(0, int((self.deadline-time.monotonic())*1000))}

    def watchdog(self):
        while True:
            time.sleep(0.01)
            with self.lock:
                if self.closed:
                    break
                if self.deadline and time.monotonic() >= self.deadline:
                    self._off()

    def close(self):
        with self.lock:
            if self.closed:
                return
            self._off()
            self.closed = True
            for devices in self.motors.values():
                for device in devices:
                    device.close()
            self.stby.close()

motors = ThreeMotors()
atexit.register(motors.close)
threading.Thread(target=motors.watchdog, daemon=True).start()

HTML = """<!doctype html>
<html lang="he" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tennis Car | 3 Motors</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}
body{font:16px system-ui,Arial;background:#111a26;color:#f5f7fa;margin:0;padding:15px}
main{max-width:540px;margin:auto}h1{font-size:24px;margin:6px 0 12px}
small,.muted{color:#bdc9d7}.card{background:#1c2d3f;border-radius:16px;padding:15px;margin:14px 0}
.warning{background:#4b392a;border:1px solid #c28c43;padding:12px;border-radius:12px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;direction:ltr}
button{border:0;border-radius:12px;background:#2677bc;color:white;padding:12px;font-weight:700;font-size:20px;min-height:77px;touch-action:manipulation}
button small{display:block;font-size:11px;font-weight:400;color:#f3f6fa}
.forward{grid-column:2;grid-row:1}.backward{grid-column:2;grid-row:3}
.left{grid-column:1;grid-row:2}.right{grid-column:3;grid-row:2}
.stop{background:#b5324a;width:100%;margin-top:12px;min-height:56px}
label{display:block;margin:11px 0}input[type=range]{display:block;width:100%;accent-color:#64b3f1}
select{font:16px system-ui;padding:9px;border-radius:8px;background:#273b50;color:#fff;width:100%;margin-top:8px}
p{line-height:1.5}#state{min-height:25px;color:#aad4fb}
</style></head><body><main>
<h1>🚗 Tennis Car — 3 מנועים</h1>
<div class="muted">{{ version }} · Raspberry Pi 3 · פורט 5001</div>
<p class="warning">הפעל רק כשהגלגלים באוויר בהתחלה. כל לחיצה היא פולס קצר; אל תחזיק את ההיגוי בקצה. כדי לבדוק מתח רציף, השתמש בכלי המדידה הקודם רק לאחר ניתוק המנועים.</p>
<section class="card">
<strong>איזה מנוע יניע קדימה/אחורה?</strong>
<select id="mode">
<option value="both">שני מנועי הנסיעה ביחד (4×4)</option>
<option value="front">קדמי בלבד — אחורי חופשי</option>
<option value="rear">אחורי בלבד — קדמי חופשי</option>
</select>
<label>עוצמת נסיעה: <span id="driveval">35%</span><input id="drive" type="range" min="20" max="85" step="5" value="35"></label>
<label>עוצמת היגוי: <span id="steerval">35%</span><input id="steer" type="range" min="20" max="75" step="5" value="35"></label>
<div class="grid">
<button class="forward" data-action="forward">▲<small>קדימה</small></button>
<button class="left" data-action="left">◀<small>שמאלה</small></button>
<button class="right" data-action="right">▶<small>ימינה</small></button>
<button class="backward" data-action="backward">▼<small>אחורה</small></button>
</div>
<button class="stop" id="stop">■ עצור הכול</button>
<p id="state">מוכן לבדיקה</p>
</section>
<section class="card">
<strong>היפוך כיוון בלי להחליף חוטים</strong>
<label><input type="checkbox" id="reverse_front"> הפוך קדימה/אחורה במנוע הקדמי</label>
<label><input type="checkbox" id="reverse_rear"> הפוך קדימה/אחורה במנוע האחורי</label>
<label><input type="checkbox" id="reverse_steer"> הפוך ימינה/שמאלה בהיגוי</label>
<p class="muted">ההגדרות נשמרות בדפדפן הזה בלבד. בדוק קדימה על שני מנועי הנסיעה בנפרד לפני מצב 4×4.</p>
</section>
<section class="card muted">
<p><b>דרייבר 1:</b> A = היגוי, B = אחורי.</p>
<p><b>דרייבר 2:</b> A = קדמי. B לא בשימוש.</p>
<p>פולס נסיעה 270ms · פולס היגוי 120ms. אין זיהוי כדורים בגרסת הבדיקה.</p>
</section>
<script>
const output=document.getElementById('state');
let busy=false;
for(const [id,label] of [['drive','driveval'],['steer','steerval']]){
 const item=document.getElementById(id);
 item.oninput=()=>document.getElementById(label).textContent=item.value+'%';
}
for(const key of ['front','rear','steer']){
 const item=document.getElementById('reverse_'+key);
 try{item.checked=localStorage.getItem('reverse_'+key)==='true';}catch(e){}
 item.onchange=()=>{try{localStorage.setItem('reverse_'+key,String(item.checked));}catch(e){}};
}
async function stop(){
 try{await fetch('/api/stop',{method:'POST'});output.textContent='עצור';}
 catch(e){output.textContent='אין תקשורת. נתק את מתח המנועים אם צריך.';}
}
document.getElementById('stop').onclick=stop;
for(const btn of document.querySelectorAll('[data-action]')){
 btn.onclick=async()=>{
  if(busy)return;
  busy=true;
  try{
   const reverse={};
   for(const key of ['front','rear','steer'])reverse[key]=document.getElementById('reverse_'+key).checked;
   const response=await fetch('/api/pulse',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:btn.dataset.action,mode:document.getElementById('mode').value,
      drive_power:Number(document.getElementById('drive').value),
      steer_power:Number(document.getElementById('steer').value),reverse})});
   const result=await response.json();
   if(!response.ok||!result.ok)throw Error(result.error||'שגיאה');
   output.textContent='נשלח: '+result.action+' · '+result.mode+' · '+result.duration_ms+'ms';
  }catch(e){output.textContent='שגיאה: '+e.message;}
  finally{busy=false;}
 };
}
addEventListener('pagehide',()=>{navigator.sendBeacon?.('/api/stop',new Blob([], {type:'text/plain'}));});
</script>
</main></body></html>"""

@app.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    return response

@app.route("/")
def index():
    return render_template_string(HTML, version=VERSION)

@app.route("/api/status")
def status():
    return jsonify(motors.status())

@app.route("/api/pulse", methods=["POST"])
def pulse():
    data = request.get_json(silent=True) or {}
    try:
        result = motors.pulse(data.get("action"), data.get("mode"),
                              data.get("drive_power"), data.get("steer_power"),
                              data.get("reverse"))
        return jsonify(ok=True, **result)
    except (ValueError, RuntimeError) as exc:
        return jsonify(ok=False, error=str(exc)), 400

@app.route("/api/stop", methods=["POST"])
def stop():
    motors.stop()
    return jsonify(ok=True)

def stop_signal(signum, frame):
    motors.stop()
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    print(VERSION)
    print("Open http://<PI-IP>:5001")
    try:
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)
    finally:
        motors.close()
