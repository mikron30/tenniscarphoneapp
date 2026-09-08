#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Adaptive Tennis Car / Flask safe patch installer.
Install target: V15.0 COURT FETCH WHITE LINES
Source required: V14.3 PHONE SOFTWARE UPDATE backup created by the phone updater.
"""
SOFTWARE_VERSION = "V15.0 COURT FETCH WHITE LINES - SAFE PATCH INSTALLER"

import base64
import gzip
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

EXPECTED_OLD_VERSION = "V14.3 PHONE SOFTWARE UPDATE"
TARGET_VERSION = "V15.0 COURT FETCH WHITE LINES"
TARGET_SHA256 = "8ceb6f3821095012a0a732dea69bfa68658546a4cac4d4cf7e22599ac1b9c8e1"
PATCH_GZ_B64 = "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[... ELLIPSIZATION ...]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"


def version_of(text):
    m = re.search(r'^\s*SOFTWARE_VERSION\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    return m.group(1).strip() if m else None


def apply_unified_diff(original_text, patch_text):
    src = original_text.splitlines(keepends=True)
    lines = patch_text.splitlines(keepends=True)
    out = []
    src_i = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('--- ') or line.startswith('+++ '):
            i += 1
            continue
        if not line.startswith('@@ '):
            i += 1
            continue
        m = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
        if not m:
            raise RuntimeError('bad unified diff hunk header: ' + line.strip())
        old_start = int(m.group(1)) - 1
        if old_start < src_i:
            raise RuntimeError('overlapping patch hunk')
        out.extend(src[src_i:old_start])
        src_i = old_start
        i += 1
        while i < len(lines) and not lines[i].startswith('@@ '):
            h = lines[i]
            if h.startswith('--- ') or h.startswith('+++ '):
                break
            if h.startswith('\\ No newline at end of file'):
                i += 1
                continue
            if not h:
                i += 1
                continue
            op = h[0]
            payload = h[1:]
            if op == ' ':
                if src_i >= len(src) or src[src_i] != payload:
                    raise RuntimeError(f'context mismatch at source line {src_i+1}')
                out.append(src[src_i]); src_i += 1
            elif op == '-':
                if src_i >= len(src) or src[src_i] != payload:
                    raise RuntimeError(f'delete mismatch at source line {src_i+1}')
                src_i += 1
            elif op == '+':
                out.append(payload)
            else:
                raise RuntimeError('unknown patch operation: ' + repr(op))
            i += 1
    out.extend(src[src_i:])
    return ''.join(out)


def newest_valid_backup(current):
    candidates = sorted(current.parent.glob(current.name + '.bak_*'), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in candidates:
        try:
            text = p.read_text(encoding='utf-8')
            if version_of(text) == EXPECTED_OLD_VERSION:
                return p, text
        except Exception:
            pass
    return None, None


def main():
    current = Path(__file__).resolve()
    backup, old_text = newest_valid_backup(current)
    if backup is None:
        print('V15 installer: no V14.3 backup found; refusing to modify software', flush=True)
        time.sleep(5)
        return 2

    try:
        patch_text = gzip.decompress(base64.b64decode(PATCH_GZ_B64)).decode('utf-8')
        new_text = apply_unified_diff(old_text, patch_text)
        if version_of(new_text) != TARGET_VERSION:
            raise RuntimeError('target version check failed')
        digest = hashlib.sha256(new_text.encode('utf-8')).hexdigest()
        if digest != TARGET_SHA256:
            raise RuntimeError('target SHA256 mismatch: ' + digest)

        temp = current.with_name('.car_remote_v15_build.py')
        temp.write_text(new_text, encoding='utf-8')
        check = subprocess.run([sys.executable, '-m', 'py_compile', str(temp)], capture_output=True, text=True, timeout=30)
        if check.returncode != 0:
            raise RuntimeError('py_compile failed: ' + (check.stderr or check.stdout)[-1500:])

        os.replace(temp, current)
        print('V15 installer: SUCCESS ->', TARGET_VERSION, flush=True)
        os.execv(sys.executable, [sys.executable, str(current)])
    except Exception as e:
        print('V15 installer FAILED:', repr(e), flush=True)
        # Fail-safe rollback: restore the verified V14.3 source and immediately run it.
        shutil.copy2(backup, current)
        os.execv(sys.executable, [sys.executable, str(current)])


if __name__ == '__main__':
    raise SystemExit(main())
