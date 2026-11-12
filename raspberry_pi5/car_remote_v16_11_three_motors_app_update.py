#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Adaptive Tennis Car V16.11 - Raspberry Pi 5 / TWO TB6612FNG drivers / THREE motors.

Driver 1 (steering + rear drive), unchanged from V16.6:
  Steering A: AIN1=GPIO17 (pin11), AIN2=GPIO27 (pin13), PWMA=GPIO12 (pin32)
  Rear B:     BIN1=GPIO23 (pin16), BIN2=GPIO24 (pin18), PWMB=GPIO13 (pin33)
Driver 2 (front drive only):
  Front A:    AIN1=GPIO5 (pin29), AIN2=GPIO6 (pin31), PWMA=GPIO18 (pin12)
Driver 1 STBY = GPIO16 (pin36); Driver 2 STBY = GPIO22 (pin15).
Driver1 VCC=Pi 3V3 pin1, GND=Pi pin6.
Driver2 VCC=Pi 3V3 pin17, GND=Pi pin14.
Both VM=battery positive, both GND=battery negative, all grounds common.
Motors connect ONLY to their own two output terminals; never join motor outputs.
Unconnected driver2 B channel: leave BIN1, BIN2, PWMB disconnected.

Open http://<PI-IP>:5000. Small one-shot pulses only; no autonomous motion.
Requires Raspberry Pi 5-compatible lgpio backend (sudo apt install python3-lgpio).
"""

import os
os.environ["GPIOZERO_PIN_FACTORY"] = "lgpio"

import atexit
import ast
import gzip
import shutil
from datetime import datetime
from pathlib import Path
import signal
import sys
import threading
import time

from flask import Flask, jsonify, render_template_string, request
from gpiozero import OutputDevice, PWMOutputDevice

SOFTWARE_VERSION = "V16.11 PI5 THREE MOTORS APP UPDATE"
VERSION = SOFTWARE_VERSION
PORT = 5000
PWM_HZ = 400
DRIVE_PULSE_S = 0.27
STEER_PULSE_S = 0.12

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

class ThreeMotors:
    def __init__(self):
        self.lock = threading.RLock()
        self.closed = False
        self.deadline = 0.0
        self.last_action = "stop"
        # Do not drive STBY until every motor pin is initialized LOW.
        self.stby1 = OutputDevice(16, initial_value=False)  # driver 1: steering + rear
        self.stby2 = OutputDevice(22, initial_value=False)  # driver 2: front
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
        self.stby1.off()
        self.stby2.off()
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
            # Inactive motor channels coast (Hi-Z) while other channels run.
            # On TB6612FNG: IN1=IN2=LOW and PWM=HIGH => stop/coast.
            for name, (in1, in2, pwm) in self.motors.items():
                if not in1.value and not in2.value:
                    pwm.value = 1.0
            if action in ("left", "right") or mode in ("rear", "both"):
                self.stby1.on()
            if action in ("forward", "backward") and mode in ("front", "both"):
                self.stby2.on()
            self.last_action = action + ("/" + mode if action in ("forward", "backward") else "")
            self.deadline = time.monotonic() + duration
            return {"action": action, "mode": mode, "duration_ms": round(duration*1000),
                    "drive_power": drive_power, "steer_power": steer_power}

    def status(self):
        with self.lock:
            return {"version": VERSION, "action": self.last_action,
                    "bridge_enabled": bool(self.stby1.value or self.stby2.value),
                    "driver1_enabled": bool(self.stby1.value),
                    "driver2_enabled": bool(self.stby2.value),
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
            self.stby1.close()
            self.stby2.close()

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
<div class="muted">{{ version }} · Raspberry Pi 5 · פורט 5000</div>
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
<p><b>דרייבר 2:</b> A = קדמי. B לא בשימוש. STBY = GPIO22, פין 15.</p>
<p>פולס נסיעה 270ms · פולס היגוי 120ms. אין זיהוי כדורים בגרסת הבדיקה.</p>
</section>
<section class="card">
<strong>עדכון תוכנה מהטלפון</strong>
<p class="muted">אפשר להעלות קובץ car_remote.py או car_remote.py.gz. ייווצר גיבוי אוטומטי לפני ההחלפה.</p>
<input id="softwareFile" type="file" accept=".py,.gz" style="max-width:100%;margin:10px 0">
<button id="upload" style="display:block;width:100%;min-height:55px">עדכן תוכנה</button>
<p id="updateMsg" class="muted"></p>
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
document.getElementById('upload').onclick=async()=>{
 const msg=document.getElementById('updateMsg');
 const file=document.getElementById('softwareFile').files[0];
 if(!file){msg.textContent='בחר קובץ Python תחילה';return;}
 if(!confirm('להתקין תוכנה חדשה? כל המנועים ייעצרו ויישמר גיבוי.'))return;
 await stop();
 msg.textContent='מעלה ובודק קובץ...';
 const form=new FormData();form.append('file',file);
 try{
  const response=await fetch('/api/software-update',{method:'POST',
    headers:{'X-Tennis-Car-Update':'confirm'},body:form});
  const result=await response.json();
  if(!response.ok||!result.ok)throw Error(result.error||'עדכון נכשל');
  msg.textContent='עודכן ל-'+result.new_version+'. גיבוי: '+result.backup+'. המערכת מופעלת מחדש.';
  setTimeout(()=>location.reload(),4800);
 }catch(e){msg.textContent='שגיאה: '+e.message;}
};
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

@app.route("/api/software-update", methods=["POST"])
@app.route("/api/software_update", methods=["POST"])
def software_update():
    """Compatible with the existing Pi 5 phone application's software upload."""
    if request.headers.get("X-Tennis-Car-Update") != "confirm":
        return jsonify(ok=False, error="Missing update confirmation"), 403
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify(ok=False, error="No software file was selected"), 400
    name = Path(upload.filename).name.lower()
    if not (name.endswith(".py") or name.endswith(".py.gz")):
        return jsonify(ok=False, error="Upload a .py or .py.gz file"), 400
    temp_file = None
    try:
        raw = upload.stream.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024 or not raw:
            raise ValueError("Invalid file size")
        if name.endswith(".gz"):
            raw = gzip.decompress(raw)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("Uncompressed file is too large")
        source = raw.decode("utf-8")
        ast.parse(source, filename=name)
        if "SOFTWARE_VERSION" not in source or "Flask" not in source:
            raise ValueError("This does not look like Tennis Car software")
        tree = ast.parse(source)
        new_version = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "SOFTWARE_VERSION" for t in node.targets
            ):
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    new_version = node.value.value
                break
        if not new_version:
            raise ValueError("Missing SOFTWARE_VERSION in uploaded Python file")
        current = Path(__file__).resolve()
        backup = current.with_name(current.name + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        temp_file = current.with_name("." + current.name + ".new")
        temp_file.write_bytes(raw)
        import subprocess
        result = subprocess.run([sys.executable, "-m", "py_compile", str(temp_file)],
                                capture_output=True, text=True, timeout=25)
        if result.returncode:
            raise ValueError("Syntax check failed: " + result.stderr[-600:])
        motors.stop()
        shutil.copy2(current, backup)
        temp_file.replace(current)
        def restart():
            time.sleep(1.5)
            motors.stop()
            if os.environ.get("INVOCATION_ID"):
                os._exit(1)  # systemd Restart=on-failure
            os.execv(sys.executable, [sys.executable, str(current)])
        threading.Thread(target=restart, daemon=True).start()
        return jsonify(ok=True, new_version=new_version, backup=backup.name, restarting=True)
    except (Exception,) as exc:
        if temp_file is not None:
            try:
                temp_file.unlink(missing_ok=True)
            except Exception:
                pass
        return jsonify(ok=False, error=str(exc)), 400

def stop_signal(signum, frame):
    motors.stop()
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    print(VERSION)
    print("Open http://<PI-IP>:5000")
    try:
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)
    finally:
        motors.close()
