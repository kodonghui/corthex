#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""corthex-uxui · media-check.py

Only measures video and sound files. It changes no file.
Needs: Python 3.8 or later, and ffmpeg and ffprobe (on PATH, or given with --ffmpeg and --ffprobe).
Reads local files only: ffmpeg is told to open no other protocol, so a playlist cannot reach the network.

What it measures
  File     length, resolution, fps, frame count, codec, pixel format, audio sample rate
  Sound    integrated loudness (LUFS), true peak (dBTP), loudness range (LRA), long silences
  Flashes  counts general and red flashes (WCAG 2.3.1) in every cell of the frame and, above three
           a second, estimates whether their area exceeds 25% of a 10° field. Flashing that goes on
           for five seconds gives a warning
  Other    black stretches, stretches with no change for more than 3 s, an empty first frame

Use
  python3 media-check.py out.mp4
  python3 media-check.py out.mp4 --target tv-kr
  python3 media-check.py out.mp4 --expect-size 1920x1080 --expect-fps 30 --json
  (on Windows, py instead of python3)

Exit code: 0 pass (there may be warnings), 1 fail, 2 could not measure (no ffmpeg, a file error)

The flash count is an approximation. It averages the frame down to a grid of cells and takes a
10° field to be a 4:3 box one third of the frame's width. When a result touches the limit or passes
by the area exception, check once more with an analysis tool (such as EA IRIS).
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import threading
from collections import deque

VERSION = "1.0"

# name: (integrated loudness LUFS, tolerance ±LU, true peak limit dBTP or None, label)
TARGETS = {
    "online": (-14.0, 1.0, -1.0, "online and presentation video"),
    "social": (-15.0, 1.0, -1.0, "social video (-16 to -14 LUFS)"),
    "tv-kr": (-24.0, 2.0, None, "South Korean TV"),
    "ebu": (-23.0, 0.5, -1.0, "EBU R 128 broadcast"),
    "atsc": (-24.0, 2.0, None, "ATSC A/85 broadcast"),
}

GEN_STEP = 0.10        # general flash: a change of 10% or more in relative luminance
GEN_DARK = 0.80        # only when the darker state is below 0.80 relative luminance
RED_RATIO = 0.80       # saturated red: R / (R + G + B) >= 0.8 (linear values)
RED_UV = 0.20          # CIE 1976 u'v' distance between the two states > 0.2
RED_HYST = 0.05        # the red ratio must come back this far to count as a change of direction (ignores noise)
FAIL_TRANSITIONS = 8   # 8 transitions in one second = 4 flashes -> more than 3
EXT_TRANSITIONS = 20   # 4 or more transitions (2 flashes) in every second of 5 -> extended flashing warning
AREA_LIMIT = 0.25      # 25% of a 10° field
D65_UV = (0.1978, 0.4683)


class MeasureError(Exception):
    pass


# ---------- Colour ----------
LIN = [(v / 255.0) / 12.92 if v / 255.0 <= 0.04045 else ((v / 255.0 + 0.055) / 1.055) ** 2.4 for v in range(256)]
LUM_R = [0.2126 * x for x in LIN]
LUM_G = [0.7152 * x for x in LIN]
LUM_B = [0.0722 * x for x in LIN]
_uv_cache = {}


def uv_of(r8, g8, b8):
    """CIE 1976 u'v' of one 8-bit sRGB colour. Near black counts as the D65 white point."""
    key = (r8 << 16) | (g8 << 8) | b8
    hit = _uv_cache.get(key)
    if hit is not None:
        return hit
    r, g, b = LIN[r8], LIN[g8], LIN[b8]
    x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b
    d = x + 15 * y + 3 * z
    uv = D65_UV if d < 1e-4 else (4 * x / d, 9 * y / d)
    if len(_uv_cache) < 200000:
        _uv_cache[key] = uv
    return uv


def red_ratio(r8, g8, b8):
    r, g, b = LIN[r8], LIN[g8], LIN[b8]
    s = r + g + b
    return 1.0 / 3.0 if s < 0.003 else r / s


def uv_dist(c1, c2):
    a = uv_of(*c1)
    b = uv_of(*c2)
    return math.hypot(a[0] - b[0], a[1] - b[1])


# ---------- Calling ffmpeg ----------
LOCAL = ["-protocol_whitelist", "file"]  # an input option: open local files only


def find_program(name):
    """A program's full path: the path given, or the program in an absolute folder of PATH.

    Windows looks for a program in the current folder before PATH, and a relative
    PATH entry is the current folder too, so a folder being checked could supply its own ffmpeg.
    """
    if os.name == "nt" and not os.path.splitext(name)[1]:
        name += ".exe"
    if os.path.dirname(name):
        return name if os.path.isfile(name) else None
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        folder = folder.strip('"')
        path = os.path.join(folder, name)
        if os.path.isabs(folder) and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def run(cmd):
    try:
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        raise MeasureError("Could not run: %s (%s)" % (cmd[0], e))


def frac(s):
    try:
        a, b = str(s).split("/")
        a, b = float(a), float(b)
        return a / b if a > 0 and b > 0 else None
    except (ValueError, ZeroDivisionError):
        try:
            v = float(s)
            return v if v > 0 else None
        except (TypeError, ValueError):
            return None


def probe(ffprobe, path):
    cmd = [ffprobe] + LOCAL + ["-v", "error", "-show_entries",
           "format=duration,format_name:stream=index,codec_type,codec_name,width,height,r_frame_rate,"
           "avg_frame_rate,nb_frames,pix_fmt,sample_rate,channels,color_transfer,duration:stream_tags=alpha_mode",
           "-of", "json", path]
    r = run(cmd)
    if r.returncode != 0:
        raise MeasureError("ffprobe could not read the file: " + r.stderr.decode("utf-8", "replace").strip()[-300:])
    data = json.loads(r.stdout.decode("utf-8", "replace") or "{}")
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    info = {"format": fmt.get("format_name"), "duration": frac(fmt.get("duration")), "video": None, "audio": None,
            "audioStreams": sum(1 for s in streams if s.get("codec_type") == "audio")}
    if v:
        info["video"] = {
            "codec": v.get("codec_name"), "width": v.get("width"), "height": v.get("height"),
            "rFrameRate": v.get("r_frame_rate"), "fps": frac(v.get("r_frame_rate")),
            "avgFps": frac(v.get("avg_frame_rate")), "nbFrames": int(v["nb_frames"]) if str(v.get("nb_frames", "")).isdigit() else None,
            "pixFmt": v.get("pix_fmt"), "transfer": v.get("color_transfer"),
            "alpha": (v.get("tags") or {}).get("alpha_mode") == "1" or bool(re.match(r"(yuva|rgba|bgra|argb|abgr|gbrap|ya)", v.get("pix_fmt") or "")),
        }
        if info["duration"] is None:
            info["duration"] = frac(v.get("duration"))
    if a:
        info["audio"] = {"codec": a.get("codec_name"), "sampleRate": int(a["sample_rate"]) if str(a.get("sample_rate", "")).isdigit() else None,
                         "channels": a.get("channels")}
    return info


def loudness(ffmpeg, path, silence_db, silence_min):
    cmd = [ffmpeg, "-hide_banner", "-nostats", "-nostdin"] + LOCAL + ["-i", path, "-map", "0:a:0",
           "-af", "ebur128=peak=true:framelog=verbose,silencedetect=noise=%sdB:d=%s" % (silence_db, silence_min),
           "-f", "null", "-"]
    r = run(cmd)
    err = r.stderr.decode("utf-8", "replace")
    if r.returncode != 0:
        raise MeasureError("ffmpeg failed to measure the sound: " + err.strip()[-300:])
    s = err[err.rfind("Summary:"):]

    def num(pat):
        m = re.search(pat, s)
        if not m:
            return None
        return float("-inf") if m.group(1) == "-inf" else float(m.group(1))

    res = {
        "integrated": num(r"I:\s*(-inf|-?[\d.]+)\s*LUFS"),
        "lra": num(r"LRA:\s*(-inf|-?[\d.]+)\s*LU"),
        "truePeak": num(r"Peak:\s*(-inf|-?[\d.]+)\s*dBFS"),
        "silences": [],
    }
    start = None
    for m in re.finditer(r"silence_(start|end):\s*(-?[\d.]+)", err):
        t = float(m.group(2))
        if m.group(1) == "start":
            start = t
        elif start is not None:
            res["silences"].append([round(start, 2), round(t, 2)])
            start = None
    if start is not None:
        res["silences"].append([round(start, 2), None])
    return res


# ---------- Flashes ----------
class Zig:
    """Finds transitions (changes in one direction by at least a set step) in the rise and fall of one value."""
    __slots__ = ("trend", "a", "e")

    def __init__(self, v):
        self.trend, self.a, self.e = 0, v, v


def video_pass(ffmpeg, path, info, opts):
    v = info["video"]
    w, h = v["width"] or 16, v["height"] or 9
    W = max(3, int(opts.grid))
    H = max(2, int(round(W * h / float(w))))
    N = W * H
    rate = v["fps"] if v["fps"] and v["fps"] <= 240 else (v["avgFps"] or 30.0)
    if v["fps"] and v["avgFps"] and abs(v["fps"] - v["avgFps"]) / v["fps"] > 0.01 and v["avgFps"] <= 240:
        rate = v["avgFps"]  # variable fps: sample evenly at the average fps
    rate_str = v["rFrameRate"] if rate == v["fps"] else "%.6f" % rate
    vf = ("freezedetect=n=0.001:d=%s,blackdetect=d=0.5:pix_th=0.10:pic_th=0.999,fps=%s,scale=%d:%d:flags=area,format=rgb24"
          % (opts.freeze, rate_str, W, H))
    cmd = [ffmpeg, "-hide_banner", "-nostats", "-nostdin"] + LOCAL + ["-i", path, "-map", "0:v:0", "-vf", vf,
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        raise MeasureError("Could not run ffmpeg: %s" % e)
    err_chunks = []
    t_err = threading.Thread(target=lambda: err_chunks.append(proc.stderr.read()))
    t_err.daemon = True
    t_err.start()

    fw = max(1, int(round(W / 3.0)))          # 10° field box: one third of the frame's width
    fh = max(1, min(H, int(round(fw * 0.75))))  # 4:3
    win1 = rate                               # one second (in frames)
    win5 = 5 * rate

    g_tr = [0] * N; g_a = [0.0] * N; g_e = [0.0] * N; g_c = [False] * N
    r_tr = [0] * N; r_a = [None] * N; r_e = [None] * N; r_ap = [0.0] * N; r_ep = [0.0] * N; r_c = [False] * N
    gq = [None] * N; rq = [None] * N
    x_flag = [-1e9] * N
    best = {"gen": (0, None, None), "red": (0, None, None)}
    area_max, area_at = 0.0, None
    fail_t, ext_t = [], []
    whole = Zig(0.0); whole_q = deque(); whole_best = (0, None)
    row_sum = [0.0] * H
    fsize = N * 3
    prev = None
    first = None
    i = -1

    def record(q, idx):
        q.append(idx)
        while q and q[0] <= idx - win5:
            q.popleft()
        n1 = 0
        for j in reversed(q):
            if j > idx - win1:
                n1 += 1
            else:
                break
        return n1, len(q)

    def sustained(q, idx):
        # Extended flashing: 4 or more transitions (2 flashes) in each of the last five one-second windows
        bins = [0] * 5
        for j in q:
            k = int((idx - j) / win1)
            if k < 5:
                bins[k] += 1
        return min(bins) >= 4

    def flashing(c, need, idx):
        # The cell made `need` or more general or red transitions in the second up to frame idx
        return any(q is not None and len(q) >= need and q[-need] > idx - win1 for q in (gq[c], rq[c]))

    def window_max(mask):
        S = [[0] * (W + 1) for _ in range(H + 1)]
        for y in range(H):
            run_, Sy, Sp, base = 0, S[y + 1], S[y], y * W
            for x in range(W):
                run_ += mask[base + x]
                Sy[x + 1] = Sp[x + 1] + run_
        top = 0
        for y in range(H - fh + 1):
            for x in range(W - fw + 1):
                s = S[y + fh][x + fw] - S[y][x + fw] - S[y + fh][x] + S[y][x]
                if s > top:
                    top = s
        return top / float(fw * fh)

    while True:
        buf = proc.stdout.read(fsize)
        if not buf or len(buf) < fsize:
            break
        i += 1
        if first is None:
            first = buf
        flag_area = flag_ext = False
        for y in range(H):
            lo_b, hi_b = y * W * 3, (y + 1) * W * 3
            if prev is not None and buf[lo_b:hi_b] == prev[lo_b:hi_b]:
                continue
            rs = 0.0
            for k in range(W):
                c = y * W + k
                o = c * 3
                r8, g8, b8 = buf[o], buf[o + 1], buf[o + 2]
                lum = LUM_R[r8] + LUM_G[g8] + LUM_B[b8]
                rs += lum
                if prev is None:
                    g_a[c] = g_e[c] = lum
                    r_a[c] = r_e[c] = (r8, g8, b8)
                    r_ap[c] = r_ep[c] = red_ratio(r8, g8, b8)
                    continue
                # General flash: the rise and fall of luminance
                hit = False
                tr = g_tr[c]
                if tr == 0:
                    if lum > g_e[c]:
                        g_e[c] = lum
                    if lum < g_a[c]:
                        g_a[c] = lum
                    if lum - g_a[c] >= GEN_STEP and lum == g_e[c]:
                        g_tr[c] = 1; g_e[c] = lum
                        g_c[c] = hit = g_a[c] < GEN_DARK
                    elif g_e[c] - lum >= GEN_STEP and lum == g_a[c]:
                        g_tr[c] = -1; g_a[c], g_e[c] = g_e[c], lum
                        g_c[c] = hit = lum < GEN_DARK
                elif tr == 1:
                    if lum > g_e[c]:
                        g_e[c] = lum
                    elif g_e[c] - lum >= GEN_STEP:
                        g_tr[c] = -1; g_a[c] = g_e[c]; g_e[c] = lum
                        g_c[c] = hit = lum < GEN_DARK
                else:
                    if lum < g_e[c]:
                        g_e[c] = lum
                        if not g_c[c] and lum < GEN_DARK:
                            g_c[c] = hit = True
                    elif lum - g_e[c] >= GEN_STEP:
                        g_tr[c] = 1; g_a[c] = g_e[c]; g_e[c] = lum
                        g_c[c] = hit = g_a[c] < GEN_DARK
                if hit:
                    if gq[c] is None:
                        gq[c] = deque()
                    n1, n5 = record(gq[c], i)
                    if n1 // 2 > best["gen"][0]:
                        best["gen"] = (n1 // 2, i, c)
                    if n1 >= FAIL_TRANSITIONS:
                        flag_area = True
                    if n5 >= EXT_TRANSITIONS and sustained(gq[c], i):
                        x_flag[c] = i; flag_ext = True
                # Red flash: the rise and fall of the red ratio, plus the u'v' distance
                cur = (r8, g8, b8)
                p = red_ratio(r8, g8, b8)
                hit = False
                tr = r_tr[c]
                if tr == 0:
                    if p > r_ep[c]:
                        r_e[c], r_ep[c] = cur, p
                    if p < r_ap[c]:
                        r_a[c], r_ap[c] = cur, p
                    if p - r_ap[c] >= RED_HYST and p == r_ep[c]:
                        r_tr[c] = 1; r_c[c] = False
                    elif r_ep[c] - p >= RED_HYST and p == r_ap[c]:
                        r_tr[c] = -1; r_c[c] = False
                        r_a[c], r_ap[c], r_e[c], r_ep[c] = r_e[c], r_ep[c], cur, p
                elif tr == 1:
                    if p > r_ep[c]:
                        r_e[c], r_ep[c] = cur, p
                    elif r_ep[c] - p >= RED_HYST:
                        r_tr[c] = -1; r_c[c] = False
                        r_a[c], r_ap[c], r_e[c], r_ep[c] = r_e[c], r_ep[c], cur, p
                else:
                    if p < r_ep[c]:
                        r_e[c], r_ep[c] = cur, p
                    elif p - r_ep[c] >= RED_HYST:
                        r_tr[c] = 1; r_c[c] = False
                        r_a[c], r_ap[c], r_e[c], r_ep[c] = r_e[c], r_ep[c], cur, p
                if r_tr[c] != 0 and not r_c[c] and max(r_ap[c], r_ep[c]) >= RED_RATIO and uv_dist(r_a[c], r_e[c]) > RED_UV:
                    r_c[c] = hit = True
                if hit:
                    if rq[c] is None:
                        rq[c] = deque()
                    n1, n5 = record(rq[c], i)
                    if n1 // 2 > best["red"][0]:
                        best["red"] = (n1 // 2, i, c)
                    if n1 >= FAIL_TRANSITIONS:
                        flag_area = True
                    if n5 >= EXT_TRANSITIONS and sustained(rq[c], i):
                        x_flag[c] = i; flag_ext = True
            row_sum[y] = rs
        # Mean of the whole frame (for reference)
        mean = sum(row_sum) / N
        if prev is None:
            whole = Zig(mean)
        else:
            z = whole
            hit = False
            if z.trend == 0:
                z.e = max(z.e, mean); z.a = min(z.a, mean)
                if mean - z.a >= GEN_STEP and mean == z.e:
                    z.trend = 1; hit = z.a < GEN_DARK
                elif z.e - mean >= GEN_STEP and mean == z.a:
                    z.trend = -1; z.a, z.e = z.e, mean; hit = mean < GEN_DARK
            elif z.trend == 1:
                if mean > z.e:
                    z.e = mean
                elif z.e - mean >= GEN_STEP:
                    z.trend = -1; z.a, z.e = z.e, mean; hit = mean < GEN_DARK
            else:
                if mean < z.e:
                    z.e = mean
                elif mean - z.e >= GEN_STEP:
                    z.trend = 1; z.a, z.e = z.e, mean; hit = z.a < GEN_DARK
            if hit:
                n1, _ = record(whole_q, i)
                if n1 // 2 > whole_best[0]:
                    whole_best = (n1 // 2, i)
        # Only cells that flash in the same second add up: a patch that has stopped flashing counts no more
        if flag_area:
            mask = [1 if flashing(c, FAIL_TRANSITIONS, i) else 0 for c in range(N)]
            frac_ = window_max(mask)
            if frac_ > area_max:
                area_max, area_at = frac_, i
            if frac_ > AREA_LIMIT:
                fail_t.append(i)
        if flag_ext:
            mask = [1 if i - x_flag[c] < win1 and flashing(c, EXT_TRANSITIONS // 5, i) else 0 for c in range(N)]
            if window_max(mask) > AREA_LIMIT:
                ext_t.append(i)
        prev = buf
    proc.stdout.close()
    proc.wait()
    t_err.join(5)
    err = b"".join(x for x in err_chunks if x).decode("utf-8", "replace")
    if proc.returncode != 0 and i < 0:
        raise MeasureError("ffmpeg failed to decode the video: " + err.strip()[-300:])
    decode_error = err.strip()[-300:] if proc.returncode != 0 else None

    def t(idx):
        return None if idx is None else round(idx / rate, 2)

    def spans(idxs, gap):
        out = []
        for idx in idxs:
            if out and idx - out[-1][1] <= gap:
                out[-1][1] = idx
            else:
                out.append([idx, idx])
        return [[t(a), t(b)] for a, b in out]

    def cell_xy(c):
        return None if c is None else [c % W, c // W]

    blacks = [[round(float(a), 2), round(float(b), 2)] for a, b in re.findall(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)", err)]
    freezes, fs = [], None
    for m in re.finditer(r"freeze_(start|end):\s*([\d.]+)", err):
        if m.group(1) == "start":
            fs = float(m.group(2))
        elif fs is not None:
            freezes.append([round(fs, 2), round(float(m.group(2)), 2)])
            fs = None
    if fs is not None:
        freezes.append([round(fs, 2), round(info["duration"], 2) if info["duration"] else None])

    first_empty = None
    if first:
        lums = [LUM_R[first[o]] + LUM_G[first[o + 1]] + LUM_B[first[o + 2]] for o in range(0, fsize, 3)]
        if max(lums) < 0.02:
            first_empty = "black"
        elif max(lums) - min(lums) < 0.01:
            first_empty = "a single colour"

    over = best["gen"][0] > 3 or best["red"][0] > 3
    result = "fail" if fail_t else ("pass-area" if over else "pass")
    return {
        "frames": i + 1, "rate": round(rate, 3), "grid": [W, H], "field": [fw, fh],
        "general": {"maxPerSec": best["gen"][0], "at": t(best["gen"][1]), "cell": cell_xy(best["gen"][2])},
        "red": {"maxPerSec": best["red"][0], "at": t(best["red"][1]), "cell": cell_xy(best["red"][2])},
        "wholeFrame": {"maxPerSec": whole_best[0], "at": t(whole_best[1])},
        "maxArea": round(area_max, 3), "maxAreaAt": t(area_at),
        "failSpans": spans(fail_t, rate), "extendedSpans": spans(ext_t, rate),
        "result": result, "black": blacks, "freeze": freezes, "firstFrameEmpty": first_empty,
        "decodeError": decode_error,
    }


# ---------- Verdicts ----------
def check_file(path, opts, ffmpeg, ffprobe):
    checks = []

    def add(level, check, msg):
        checks.append({"level": level, "check": check, "msg": msg})

    info = probe(ffprobe, path)
    v, a, dur = info["video"], info["audio"], info["duration"]
    rep = {"tool": "corthex-uxui media-check", "version": VERSION, "file": path, "info": info,
           "loudness": None, "flash": None, "checks": checks}

    # File: a size or fps that was asked for fails when there is no video at all
    if opts.expect_size:
        m = re.match(r"^(\d+)[x×X*](\d+)$", opts.expect_size.strip())
        if not m:
            raise MeasureError("Write --expect-size like 1920x1080")
        if not v:
            add("error", "size", "No video stream, expected %s" % opts.expect_size)
        elif (v["width"], v["height"]) != (int(m.group(1)), int(m.group(2))):
            add("error", "size", "Resolution %sx%s, expected %s" % (v["width"], v["height"], opts.expect_size))
    if opts.expect_fps and (not v or not v["fps"] or abs(v["fps"] - opts.expect_fps) > 0.01):
        add("error", "fps", "fps %s, expected %s" % (fmt_num(v["fps"]) if v else "none (no video stream)", fmt_num(opts.expect_fps)))
    if v:
        if v["fps"] and v["avgFps"] and abs(v["fps"] - v["avgFps"]) / v["fps"] > 0.01:
            add("warn", "vfr", "Uneven frame timing (stated %s, average %s fps). For a rendered video, fix one fps" % (fmt_num(v["fps"]), fmt_num(v["avgFps"])))
        if v["codec"] in ("h264", "hevc") and v["pixFmt"] not in ("yuv420p", "yuvj420p", "yuv420p10le"):
            add("warn", "pix-fmt", "Pixel format %s does not open in many players and browsers (encode with -pix_fmt yuv420p)" % v["pixFmt"])
        if v["transfer"] in ("smpte2084", "arib-std-b67"):
            add("warn", "hdr", "HDR video: this tool's flash calculation assumes sRGB and does not apply (use a tool built on ITU-R BT.1702)")
        if v["alpha"]:
            add("info", "alpha", "Video with a transparent background: measure flashes again over the background it will sit on")
    if opts.expect_duration is not None and (dur is None or abs(dur - opts.expect_duration) > opts.dur_tol):
        add("error", "duration", "Length %s s, expected %s s (±%s)" % (fmt_num(dur), fmt_num(opts.expect_duration), fmt_num(opts.dur_tol)))

    # Sound
    if a and not opts.no_audio:
        if a["sampleRate"] and a["sampleRate"] not in (44100, 48000):
            add("warn", "sample-rate", "Sample rate %d Hz. After loudnorm, -ar 48000 may be missing" % a["sampleRate"])
        if info["audioStreams"] > 1:
            add("info", "audio-streams", "%d audio tracks; only the first was measured" % info["audioStreams"])
        L = loudness(ffmpeg, path, opts.silence_db, opts.silence_min)
        rep["loudness"] = L
        I, TP = L["integrated"], L["truePeak"]
        tgt = list(TARGETS.get(opts.target, (None, None, None, "not judged")))
        if opts.lufs is not None:
            tgt[0], tgt[3] = opts.lufs, "set by hand"
        if opts.lu_tol is not None:
            tgt[1] = opts.lu_tol
        if opts.tp is not None:
            tgt[2] = opts.tp
        if tgt[1] is None and tgt[0] is not None:
            tgt[1] = 1.0
        L["target"] = {"name": opts.target, "lufs": tgt[0], "tol": tgt[1], "truePeakMax": tgt[2], "label": tgt[3]}
        silent = I is None or I <= -69.9 or TP == float("-inf")
        L["silent"] = silent
        for k in ("integrated", "lra", "truePeak"):
            if L[k] is not None and math.isinf(L[k]):
                L[k] = None  # never write -inf into JSON
        if silent:
            add("warn", "silent-track", "There is an audio track, but it is almost silent. If the video is meant to be silent, remove the track or say so")
        else:
            if tgt[0] is not None and abs(I - tgt[0]) > tgt[1] + 1e-9:
                add("error", "loudness", "Integrated loudness %s LUFS, target %s ±%s (%s)" % (fmt_num(I), fmt_num(tgt[0]), fmt_num(tgt[1]), tgt[3]))
            if tgt[2] is not None and TP is not None and TP > tgt[2] + 1e-9:
                add("error", "true-peak", "True peak %s dBTP, limit %s" % (fmt_num(TP), fmt_num(tgt[2])))
            elif opts.target == "online" and opts.tp is None and I > -14.0 and TP is not None and TP > -2.0:
                add("info", "true-peak-loud", "Mastered louder than -14 LUFS: a true peak below -2 dBTP is recommended (now %s)" % fmt_num(TP))
        long_sil = [s for s in L["silences"] if s[1] is None or s[1] - s[0] >= opts.silence_min]
        if long_sil and not silent:
            add("info", "silence", "Silent stretches (below %s dB for %s s or more): %s" % (opts.silence_db, fmt_num(opts.silence_min), spans_txt(long_sil, dur)))
    elif not a:
        if v and dur and dur > 15:
            add("info", "no-audio", "Longer than 15 s with no audio track. Check that no sound was the decision")
        elif v:
            add("info", "no-audio", "No audio track")

    # Picture
    if v and not opts.no_video:
        F = video_pass(ffmpeg, path, info, opts)
        rep["flash"] = F
        if F["decodeError"]:
            add("warn", "decode", "ffmpeg did not read to the end (measured up to frame %d): %s" % (F["frames"], F["decodeError"][-120:]))
        if F["result"] == "fail":
            add("error", "flash", "Flashes: at %s s, more than three flashes a second over %d%% of a 10° field (limit 25%%)"
                % (spans_txt(F["failSpans"], dur), round(F["maxArea"] * 100)))
        elif F["result"] == "pass-area":
            add("warn", "flash-area", "Some places flash more than three times a second (general %d, red %d), but over a small area (at most %d%%), so they pass by the area exception. Check once more with an analysis tool"
                % (F["general"]["maxPerSec"], F["red"]["maxPerSec"], round(F["maxArea"] * 100)))
        elif max(F["general"]["maxPerSec"], F["red"]["maxPerSec"]) == 3:
            add("info", "flash-edge", "Flashes reach the limit (three a second)")
        if F["extendedSpans"]:
            add("warn", "flash-extended", "Two or more flashes a second for five seconds (extended flashing): %s s" % spans_txt(F["extendedSpans"], dur))
        if F["firstFrameEmpty"]:
            add("warn", "first-frame", "The first frame is empty (%s). On social platforms the first frame becomes the thumbnail" % F["firstFrameEmpty"])
        if F["freeze"]:
            add("warn", "freeze", "No change for more than %s s: %s s. If the hold is intended, write it in the scene table" % (fmt_num(opts.freeze), spans_txt(F["freeze"], dur)))
        if F["black"]:
            add("info", "black", "Black for 0.5 s or more: %s s" % spans_txt(F["black"], dur))
        if v["nbFrames"] and F["frames"] and abs(v["nbFrames"] - F["frames"]) > 1 and not (v["fps"] and v["avgFps"] and abs(v["fps"] - v["avgFps"]) / v["fps"] > 0.01):
            add("info", "frames", "%d frames in the header, %d frames actually read" % (v["nbFrames"], F["frames"]))

    counts = {k: sum(1 for c in checks if c["level"] == k) for k in ("error", "warn", "info")}
    rep["counts"] = counts
    rep["pass"] = counts["error"] == 0
    rep["notMeasured"] = [
        "Watching and listening (this result is 'measured only')",
        "Sync of sound and picture (the lag between an effect and what causes it on screen)",
        "Text size, reading time and Korean line breaks (check the scene HTML with page-check)",
        "Pattern flashing (stripes, checkerboards)",
    ] + (["Flashes (--no-video)"] if opts.no_video and v else []) + (["Loudness (--no-audio)"] if opts.no_audio and a else [])
    return rep


def fmt_num(x):
    if x is None:
        return "?"
    if x == float("-inf"):
        return "-inf"
    return ("%.2f" % x).rstrip("0").rstrip(".")


def spans_txt(sp, dur=None):
    out = []
    for s in sp[:6]:
        b = s[1] if s[1] is not None else dur
        out.append("%s-%s" % (fmt_num(s[0]), fmt_num(b)) if b is not None and b != s[0] else fmt_num(s[0]))
    return ", ".join(out) + (" and %d more" % (len(sp) - 6) if len(sp) > 6 else "")


def print_text(rep):
    info, v, a = rep["info"], rep["info"]["video"], rep["info"]["audio"]
    print("media-check %s · %s" % (VERSION, rep["file"]))
    parts = []
    if v:
        parts.append("%sx%s · %s fps · %s s · %s %s" % (v["width"], v["height"], fmt_num(v["fps"]), fmt_num(info["duration"]),
                                                      v["codec"], v["pixFmt"]))
    else:
        parts.append("%s s · no video" % fmt_num(info["duration"]))
    parts.append("audio %s %sHz %sch" % (a["codec"], a["sampleRate"] or "?", a["channels"] or "?") if a else "no audio")
    print("[file]    " + " · ".join(parts))
    L = rep["loudness"]
    if L and L.get("silent"):
        print("[sound]   almost silent (integrated below -70 LUFS)")
    elif L:
        tg = L["target"]
        goal = ("target %s ±%s, %s" % (fmt_num(tg["lufs"]), fmt_num(tg["tol"]), tg["label"])) if tg["lufs"] is not None else "not judged"
        tp = (", limit %s" % fmt_num(tg["truePeakMax"])) if tg["truePeakMax"] is not None else ""
        print("[sound]   integrated %s LUFS (%s) · true peak %s dBTP%s · LRA %s LU"
              % (fmt_num(L["integrated"]), goal, fmt_num(L["truePeak"]), tp, fmt_num(L["lra"])))
    F = rep["flash"]
    if F:
        word = {"pass": "pass", "pass-area": "pass by the area exception", "fail": "fail"}[F["result"]]
        print("[flashes] general at most %d/s%s · red at most %d/s%s · whole frame %d/s → %s (grid %dx%d, field box %dx%d cells, %d frames)"
              % (F["general"]["maxPerSec"], (" (t=%ss)" % fmt_num(F["general"]["at"])) if F["general"]["at"] is not None else "",
                 F["red"]["maxPerSec"], (" (t=%ss)" % fmt_num(F["red"]["at"])) if F["red"]["at"] is not None else "",
                 F["wholeFrame"]["maxPerSec"], word, F["grid"][0], F["grid"][1], F["field"][0], F["field"][1], F["frames"]))
    c = rep["counts"]
    print("errors %d · warnings %d · info %d" % (c["error"], c["warn"], c["info"]))
    names = {"error": "error", "warn": "warning", "info": "info"}
    for ch in rep["checks"]:
        print("  %s %s: %s" % (names[ch["level"]], ch["check"], ch["msg"]))
    print("Not measured: " + " / ".join(rep["notMeasured"]))
    print("Result: " + ("pass" if rep["pass"] else "fail") + " (measured only; if nobody watched and listened, say so in the report)")


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="Measures the loudness and the flashes of video and sound files (changes no file).")
    ap.add_argument("files", nargs="+", help="files to measure (mp4, mov, webm, wav and so on)")
    ap.add_argument("--target", choices=sorted(TARGETS) + ["none"], default="online",
                    help="loudness target: online (-14 ±1, the default), social (-15 ±1), tv-kr (-24 ±2), ebu (-23 ±0.5), atsc (-24 ±2), none")
    ap.add_argument("--lufs", type=float, help="set the integrated loudness target by hand")
    ap.add_argument("--lu-tol", type=float, help="tolerance (LU)")
    ap.add_argument("--tp", type=float, help="true peak limit (dBTP)")
    ap.add_argument("--expect-size", help="expected resolution, such as 1920x1080")
    ap.add_argument("--expect-fps", type=float, help="expected fps, such as 30")
    ap.add_argument("--expect-duration", type=float, help="expected length (seconds)")
    ap.add_argument("--dur-tol", type=float, default=0.1, help="length tolerance (seconds, default 0.1)")
    ap.add_argument("--grid", type=int, default=48, help="number of cells across for counting flashes (default 48; fewer is faster and coarser)")
    ap.add_argument("--freeze", type=float, default=3.0, help="report stretches with no change for longer than this (seconds, default 3)")
    ap.add_argument("--silence-db", type=float, default=-50.0, help="level counted as silence (dB, default -50)")
    ap.add_argument("--silence-min", type=float, default=2.0, help="report silences of at least this length (seconds, default 2)")
    ap.add_argument("--no-video", action="store_true", help="skip the picture checks (flashes, black, freezes)")
    ap.add_argument("--no-audio", action="store_true", help="skip the sound checks")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    ap.add_argument("--ffmpeg", default="ffmpeg", help="path to ffmpeg")
    ap.add_argument("--ffprobe", default="ffprobe", help="path to ffprobe")
    opts = ap.parse_args(argv)

    ffmpeg, ffprobe = find_program(opts.ffmpeg), find_program(opts.ffprobe)
    if not ffmpeg or not ffprobe:
        sys.stderr.write("media-check needs ffmpeg and ffprobe (https://ffmpeg.org/download.html). If they are installed, put them on PATH or pass their paths with --ffmpeg and --ffprobe.\n")
        return 2
    reports, code = [], 0
    for path in opts.files:
        try:
            rep = check_file(path, opts, ffmpeg, ffprobe)
            code = max(code, 0 if rep["pass"] else 1)
        except MeasureError as e:
            rep = {"tool": "corthex-uxui media-check", "version": VERSION, "file": path, "pass": False, "error": str(e)}
            code = 2
        reports.append(rep)
    if opts.json:
        enc = (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "")
        out = reports[0] if len(reports) == 1 else reports
        print(json.dumps(out, ensure_ascii=enc != "utf8", indent=2, default=lambda o: None))
    else:
        for n, rep in enumerate(reports):
            if n:
                print()
            if "error" in rep:
                print("media-check %s · %s\nCould not measure: %s" % (VERSION, rep["file"], rep["error"]))
            else:
                print_text(rep)
    return code


if __name__ == "__main__":
    sys.exit(main())
