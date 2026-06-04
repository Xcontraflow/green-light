"""Green Light - work time tracker."""

import base64 as _base64
import ctypes
import ctypes.wintypes
import json
import struct as _struct
import subprocess
import sys
import threading as _threading
import tkinter as tk
from tkinter import font as tkfont, messagebox
from datetime import datetime, timedelta, date
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None


APP_NAME = "GreenLight"
APP_DIR = Path(__file__).parent.resolve()
DATA_FILE = APP_DIR / "data.json"
CONFIG_FILE = APP_DIR / "config.json"

DEFAULT_CONFIG = {"target_minutes": 480, "autostart": False}

# Modern warm palette
BG = "#f7f6f3"
SURFACE = "#ffffff"
SURFACE_ALT = "#eeedea"
BORDER = "#e5e3dc"
BORDER_STRONG = "#d4d1c7"
TEXT = "#1a1a1a"
TEXT2 = "#6b6966"
TEXT3 = "#9e9a94"
ACCENT = "#cc785c"
ACCENT_DIM = "#e6b09e"
ACCENT_LIGHT = "#fef5f0"
RED = "#c14a3d"
GREEN = "#5e8a3d"
YELLOW = "#ddaa11"

# Font preference lists — first entry that's actually installed wins.
# Resolved at startup in main() after the Tk root exists.
FONT_UI_CANDIDATES = [
    "Source Han Serif SC",   # 思源宋体
    "Source Han Serif CN",
    "Noto Serif CJK SC",
    "LXGW WenKai",           # 霞鹜文楷
    "FZShuSong-Z01S",        # 方正书宋
    "宋体",                   # SimSun — Windows 内置
    "Microsoft YaHei UI",
    "Microsoft YaHei",
]
FONT_MONO_CANDIDATES = [
    "Sarasa Mono SC",
    "JetBrains Mono",
    "Cascadia Code",
    "Consolas",
    "Courier New",
]
FONT_UI = "宋体"              # resolved to best available in _resolve_fonts()
FONT_MONO = FONT_MONO_CANDIDATES[-1]


# ─── helpers ──────────────────────────────────────────────────────────────

def load_json(path, default):
    if not path.exists():
        return json.loads(json.dumps(default))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(default))


def save_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def fmt_hm(seconds):
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def fmt_clock(seconds):
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def set_autostart(enabled, command):
    if winreg is None:
        return False, "Windows registry unavailable"
    subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
        return True, None
    except OSError as e:
        return False, str(e)


def autostart_command():
    py = sys.executable
    if py.lower().endswith("python.exe"):
        cand = Path(py).with_name("pythonw.exe")
        if cand.exists():
            py = str(cand)
    return f'"{py}" "{APP_DIR / "green_light.py"}"'


def create_desktop_shortcut():
    py = sys.executable
    if py.lower().endswith("python.exe"):
        cand = Path(py).with_name("pythonw.exe")
        if cand.exists():
            py = str(cand)

    script   = str(APP_DIR / "green_light.py")
    work_dir = str(APP_DIR)

    desktop = None
    if winreg:
        try:
            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
                desktop, _ = winreg.QueryValueEx(k, "Desktop")
        except OSError:
            pass
    if not desktop:
        desktop = str(Path.home() / "Desktop")

    lnk = str(Path(desktop) / "Green Light.lnk")

    icon_ico = str(APP_DIR / "icon.ico")
    ps = (
        f"$ws = New-Object -ComObject WScript.Shell\n"
        f"$s  = $ws.CreateShortcut('{lnk}')\n"
        f"$s.TargetPath      = '{py}'\n"
        f"$s.Arguments       = '\"{script}\"'\n"
        f"$s.WorkingDirectory= '{work_dir}'\n"
        f"$s.IconLocation    = '{icon_ico},0'\n"
        f"$s.Save()"
    )
    enc = _base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        ["powershell", "-WindowStyle", "Hidden", "-NonInteractive",
         "-EncodedCommand", enc],
        capture_output=True, timeout=15,
    )
    if result.returncode == 0:
        return True, lnk
    err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
    return False, err or "未知错误"


def _resolve_fonts(root):
    """Pick the first installed font from each candidate list."""
    global FONT_UI, FONT_MONO
    available = {f.lower() for f in tkfont.families(root)}
    for name in FONT_UI_CANDIDATES:
        if name.lower() in available:
            FONT_UI = name
            break
    for name in FONT_MONO_CANDIDATES:
        if name.lower() in available:
            FONT_MONO = name
            break


# ─── widgets ──────────────────────────────────────────────────────────────

class ToggleSwitch(tk.Canvas):
    """Rounded pill toggle switch."""
    WIDTH = 46
    HEIGHT = 26

    def __init__(self, master, value=True, on_toggle=None, **kwargs):
        super().__init__(master, width=self.WIDTH, height=self.HEIGHT,
                         bg=master.cget("bg"), highlightthickness=0, bd=0, **kwargs)
        self._value = value
        self._on_toggle = on_toggle
        self._draw()
        self.bind("<Button-1>", self._click)
        self.configure(cursor="hand2")

    def _draw(self):
        self.delete("all")
        w, h = self.WIDTH, self.HEIGHT
        r = h // 2
        bg_color = ACCENT if self._value else "#cdc9bf"
        self.create_arc(0, 0, 2*r, h, start=90, extent=180, fill=bg_color, outline=bg_color)
        self.create_arc(w-2*r, 0, w, h, start=270, extent=180, fill=bg_color, outline=bg_color)
        self.create_rectangle(r, 0, w-r, h, fill=bg_color, outline="")
        pad = 3
        d = h - 2 * pad
        cx = w - d - pad if self._value else pad
        self.create_oval(cx, pad, cx + d, pad + d, fill="white", outline="")

    def _click(self, _event):
        self._value = not self._value
        self._draw()
        if self._on_toggle:
            self._on_toggle(self._value)

    @property
    def value(self):
        return self._value

    def set(self, value):
        if self._value != value:
            self._value = value
            self._draw()


class PillToggle(tk.Canvas):
    """Large sliding pill toggle with state label."""
    W = 180
    H = 52

    def __init__(self, master, value=True, on_toggle=None, **kwargs):
        super().__init__(master, width=self.W, height=self.H,
                         bg=master.cget("bg"), highlightthickness=0, bd=0, **kwargs)
        self._value = value
        self._on_toggle = on_toggle
        self._draw()
        self.bind("<Button-1>", self._click)
        self.configure(cursor="hand2")

    def _click(self, _e):
        self._value = not self._value
        self._draw()
        if self._on_toggle:
            self._on_toggle(self._value)

    @property
    def value(self):
        return self._value

    def set(self, value):
        if self._value != value:
            self._value = value
            self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.W, self.H
        r = h // 2
        bg = ACCENT if self._value else "#9a968e"

        self.create_arc(0, 0, 2*r, h, start=90,  extent=180,  fill=bg, outline=bg)
        self.create_arc(w-2*r, 0, w, h, start=270, extent=180, fill=bg, outline=bg)
        self.create_rectangle(r, 0, w-r, h, fill=bg, outline="")

        pad = 5
        hd  = h - 2*pad
        hx  = w - hd - pad if self._value else pad
        self.create_oval(hx, pad, hx+hd, pad+hd, fill="white", outline="")

        if self._value:
            tx = (hx - r) // 2 + r
            self.create_text(tx, h // 2, text="REC", fill="white",
                             font=(FONT_UI, 11, "bold"))
        else:
            tx = hx + hd + (w - r - hx - hd) // 2
            self.create_text(tx, h // 2, text="OFF", fill="#e0ddd6",
                             font=(FONT_UI, 11, "bold"))


class ProgressBar(tk.Canvas):
    """Rounded pill-shaped progress bar."""
    def __init__(self, master, height=8, **kwargs):
        super().__init__(master, height=height, bg=master.cget("bg"),
                         highlightthickness=0, bd=0, **kwargs)
        self._bar_h = height
        self._value = 0.0
        self.bind("<Configure>", lambda _e: self._draw())

    def set(self, value):
        self._value = max(0.0, min(100.0, value))
        self._draw()

    def _pill(self, x1, y1, x2, y2, r, fill):
        self.create_arc(x1, y1, x1 + 2*r, y2, start=90, extent=180, fill=fill, outline=fill)
        self.create_arc(x2 - 2*r, y1, x2, y2, start=270, extent=180, fill=fill, outline=fill)
        self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="")

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self._bar_h
        r = h // 2
        if w <= 1:
            return
        self._pill(0, 0, w, h, r, SURFACE_ALT)
        fw = (self._value / 100.0) * w
        if fw >= 2 * r:
            self._pill(0, 0, fw, h, r, ACCENT)
        elif fw >= 2:
            self.create_oval(0, 0, h, h, fill=ACCENT, outline=ACCENT)


class PixelTrafficLight(tk.Canvas):
    """3D pixel-art horizontal traffic light."""
    CELL = 2
    GW   = 114
    GH   = 45

    def __init__(self, master, **kwargs):
        super().__init__(master,
                         width=self.GW * self.CELL,
                         height=self.GH * self.CELL,
                         bg=BG, highlightthickness=0, bd=0, **kwargs)
        self._state = "red"
        self._draw()

    def update_state(self, recording, target_met):
        s = "yellow" if not recording else ("green" if target_met else "red")
        if s != self._state:
            self._state = s
            self._draw()

    def _r(self, x0, y0, x1, y1, fill):
        c = self.CELL
        self.create_rectangle(x0*c, y0*c, (x1+1)*c-1, (y1+1)*c-1,
                               fill=fill, outline="")

    def _px(self, x, y, fill):
        c = self.CELL
        self.create_rectangle(x*c, y*c, x*c+c-1, y*c+c-1, fill=fill, outline="")

    def _circle(self, cx, cy, r, fill):
        r2 = r * r + r
        for dy in range(-r-1, r+2):
            for dx in range(-r-1, r+2):
                if dx*dx + dy*dy <= r2:
                    self._px(cx+dx, cy+dy, fill)

    def _cap(self, bx, by, bw, bh, y):
        r = bh // 2
        yc = by + r
        dy = y - yc
        t = r * r + r
        if dy * dy > t:
            return None
        dx = int((t - dy * dy) ** 0.5)
        return (bx + r - dx, bx + bw - 1 - r + dx)

    def _draw(self):
        self.delete("all")

        BX, BY = 6, 12
        BW, BH = 90, 26
        DX = 6
        cy = BY + BH // 2

        # ── 3D top face ──────────────────────────────────────────────
        for x in range(BX, BX + BW):
            for y in range(BY - 1, BY + BH):
                b = self._cap(BX, BY, BW, BH, y)
                if b and b[0] <= x <= b[1]:
                    for d in range(1, DX + 1):
                        c = "#9a9a9a" if d == DX else "#808080"
                        self._px(x + d, y - d, c)
                    break

        # ── 3D right face ────────────────────────────────────────────
        for y in range(BY, BY + BH):
            b = self._cap(BX, BY, BW, BH, y)
            if b:
                for d in range(1, DX + 1):
                    self._px(b[1] + d, y - d, "#505050")

        # ── Front face (capsule, smooth gradient) ────────────────────
        for y in range(BY - 1, BY + BH + 1):
            b = self._cap(BX, BY, BW, BH, y)
            if not b:
                continue
            xl, xr = b
            t = max(0.0, min(1.0, (y - BY) / max(1, BH - 1)))
            v = int(0x88 * (1 - t) + 0x48 * t)
            rc = f"#{v:02x}{v:02x}{v:02x}"
            for x in range(xl, xr + 1):
                self._px(x, y, rc)

        # ── Ground shadow ────────────────────────────────────────────
        for x in range(BX + 6, BX + BW - 6):
            self._px(x, BY + BH + 1, "#d5d2cb")
            self._px(x, BY + BH + 2, "#e4e2dc")

        # ── Lights ───────────────────────────────────────────────────
        R_ON, R_OFF  = "#ff4433", "#4a1818"
        Y_ON, Y_OFF  = "#ffbb22", "#4a3510"
        G_ON, G_OFF  = "#44ee55", "#184a1e"

        lc = {
            "red":    (R_ON,  Y_OFF, G_OFF),
            "yellow": (R_OFF, Y_ON,  G_OFF),
            "green":  (R_OFF, Y_OFF, G_ON),
        }[self._state]

        cxs = (BX + BW // 6, BX + BW // 2, BX + 5 * BW // 6)
        lr = 9
        active_idx = {"red": 0, "yellow": 1, "green": 2}[self._state]
        glow_map = {"red": "#882222", "yellow": "#886600", "green": "#228840"}
        hi_map   = {"red": "#ffbbaa", "yellow": "#ffee88", "green": "#aaffcc"}

        for i, (cx, col) in enumerate(zip(cxs, lc)):
            is_active = i == active_idx

            self._circle(cx, cy, lr + 2, "#282828")

            if is_active:
                self._circle(cx, cy, lr + 3, glow_map[self._state])

            self._circle(cx, cy, lr, col)

            if is_active:
                hi = hi_map[self._state]
                thr = lr * lr * 0.45
                for dy in range(-lr + 1, 0):
                    for dx in range(-lr + 1, 0):
                        if dx * dx + dy * dy <= thr:
                            self._px(cx + dx, cy + dy, hi)


class WeekBarChart(tk.Canvas):
    """Screen Time-style weekly bar chart with dashed average line."""
    def __init__(self, master, **kwargs):
        super().__init__(master, bg=BG, highlightthickness=0, bd=0,
                         height=200, **kwargs)
        self._data = []
        self._target_secs = 480 * 60
        self.bind("<Configure>", lambda _e: self._draw())

    def update_data(self, data, target_secs):
        self._data = sorted(data.items())
        self._target_secs = target_secs
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 1 or h <= 1 or not self._data:
            return

        pad_l, pad_r = 36, 12
        pad_t, pad_b = 16, 20
        cw = w - pad_l - pad_r
        ch = h - pad_t - pad_b
        if cw < 50 or ch < 40:
            return

        values = [v for _, v in self._data]
        max_v = max(values) if values else 0
        nonzero = [v for v in values if v > 0]
        avg_v = sum(nonzero) / len(nonzero) if nonzero else 0

        # y-axis ceiling — round up to a clean number of hours
        upper_secs = max(max_v, self._target_secs * 0.4)
        upper_h = max(1.0, upper_secs / 3600)
        if upper_h <= 4:
            step_h = 1
        elif upper_h <= 8:
            step_h = 2
        elif upper_h <= 12:
            step_h = 3
        else:
            step_h = 4
        ceil_h = max(step_h, int((upper_h + step_h - 0.001) // step_h * step_h))
        ceil_secs = ceil_h * 3600

        # gridlines + y-axis labels
        f_axis = (FONT_UI, 9)
        n_lines = ceil_h // step_h
        for i in range(n_lines + 1):
            mark = i * step_h
            y = pad_t + ch - (mark / ceil_h) * ch
            self.create_text(pad_l - 6, y, text=f"{mark}h", anchor="e",
                             fill=TEXT3, font=f_axis)
            if i > 0:
                self.create_line(pad_l, y, w - pad_r, y, fill=SURFACE_ALT)
        self.create_line(pad_l, pad_t + ch, w - pad_r, pad_t + ch,
                         fill=BORDER_STRONG)

        # bars
        n = len(self._data)
        slot = cw / n
        bar_w = min(slot * 0.55, 30)
        today = date.today()
        names = ["一", "二", "三", "四", "五", "六", "日"]

        for i, (d, secs) in enumerate(self._data):
            x_center = pad_l + slot * (i + 0.5)
            x1 = x_center - bar_w / 2
            x2 = x_center + bar_w / 2
            y_bot = pad_t + ch
            bar_h = (secs / ceil_secs) * ch if ceil_secs else 0
            y_top = y_bot - bar_h
            is_today = d == today
            color = ACCENT if is_today else ACCENT_DIM

            if bar_h >= bar_w:
                br = bar_w / 2
                self.create_arc(x1, y_top, x2, y_top + bar_w,
                                start=0, extent=180, fill=color, outline=color)
                self.create_rectangle(x1, y_top + br, x2, y_bot, fill=color, outline="")
            elif bar_h >= 2:
                self.create_rectangle(x1, y_top, x2, y_bot, fill=color, outline="")
            else:
                self.create_rectangle(x_center - 1.5, y_bot - 2,
                                      x_center + 1.5, y_bot,
                                      fill=BORDER_STRONG, outline="")

            label_w = ("bold" if is_today else "normal")
            self.create_text(x_center, y_bot + 10,
                             text=names[d.weekday()],
                             fill=TEXT if is_today else TEXT2,
                             font=(FONT_UI, 9, label_w))

        # dashed average line
        if avg_v > 0:
            y_avg = pad_t + ch - (avg_v / ceil_secs) * ch
            self.create_line(pad_l, y_avg, w - pad_r, y_avg,
                             fill=TEXT2, dash=(4, 4), width=1)
            self.create_text(w - pad_r - 2, y_avg - 9,
                             text=f"日均 {fmt_hm(avg_v)}",
                             anchor="e", fill=TEXT2, font=(FONT_UI, 9))

# ─── Win32 system tray (pure ctypes, no extra dependencies) ───────────────

_shell32  = ctypes.windll.shell32
_user32   = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

# Explicit signatures prevent 64-bit WPARAM/LPARAM overflow
_user32.DefWindowProcW.restype  = ctypes.c_ssize_t
_user32.DefWindowProcW.argtypes = [
    ctypes.wintypes.HWND, ctypes.c_uint,
    ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]

_WM_USER_TRAY      = 0x8001
_WM_SHOW_INSTANCE  = 0x8002   # posted by a second instance to signal "show window"
_NIM_ADD           = 0
_NIM_DELETE       = 2
_NIF_MSG          = 1
_NIF_ICON         = 2
_NIF_TIP          = 4
_WM_LBUTTONUP     = 0x0202
_WM_LBUTTONDBLCLK = 0x0203
_WM_RBUTTONUP     = 0x0205
_WM_DESTROY       = 0x0002
_MFT_SEPARATOR    = 0x800
_TPM_RETURNCMD    = 0x0100
_TPM_RIGHTALIGN   = 0x0008

_WNDPROC_T = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    ctypes.wintypes.HWND, ctypes.c_uint,
    ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)

class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ('style',         ctypes.c_uint),
        ('lpfnWndProc',   _WNDPROC_T),
        ('cbClsExtra',    ctypes.c_int),
        ('cbWndExtra',    ctypes.c_int),
        ('hInstance',     ctypes.wintypes.HINSTANCE),
        ('hIcon',         ctypes.wintypes.HICON),
        ('hCursor',       ctypes.wintypes.HANDLE),
        ('hbrBackground', ctypes.wintypes.HBRUSH),
        ('lpszMenuName',  ctypes.wintypes.LPCWSTR),
        ('lpszClassName', ctypes.wintypes.LPCWSTR),
    ]

class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ('cbSize',           ctypes.c_ulong),
        ('hWnd',             ctypes.wintypes.HWND),
        ('uID',              ctypes.c_uint),
        ('uFlags',           ctypes.c_uint),
        ('uCallbackMessage', ctypes.c_uint),
        ('hIcon',            ctypes.wintypes.HICON),
        ('szTip',            ctypes.c_wchar * 128),
    ]

class _POINT(ctypes.Structure):
    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]


def _traffic_light_pixels(w, h):
    """BGRA pixel list (top-to-bottom) for a horizontal traffic-light icon."""
    cy  = h // 2
    r   = max(2, w // 8)
    r_sq = r * r + r
    cx0 = w * 3 // 16
    cx1 = w // 2
    cx2 = w * 13 // 16

    hx0 = max(0, cx0 - r - 1)
    hx1 = min(w - 1, cx2 + r + 1)
    hy0 = max(0, cy - r - 1)
    hy1 = min(h - 1, cy + r + 1)

    TRAN    = (0x00, 0x00, 0x00, 0x00)
    BODY    = (0x3a, 0x3a, 0x3a, 0xff)   # dark gray #3a3a3a
    BODY_HI = (0x58, 0x58, 0x58, 0xff)   # lighter #585858
    CRED    = (0x33, 0x44, 0xee, 0xff)
    CYLW    = (0x11, 0xaa, 0xdd, 0xff)
    CGRN    = (0x55, 0xcc, 0x44, 0xff)

    out = []
    for y in range(h):
        for x in range(w):
            d0 = (x - cx0) ** 2 + (y - cy) ** 2
            d1 = (x - cx1) ** 2 + (y - cy) ** 2
            d2 = (x - cx2) ** 2 + (y - cy) ** 2
            if d0 <= r_sq:
                out.append(CRED)
            elif d1 <= r_sq:
                out.append(CYLW)
            elif d2 <= r_sq:
                out.append(CGRN)
            elif hx0 <= x <= hx1 and hy0 <= y <= hy1:
                out.append(BODY_HI if y <= hy0 + 1 else BODY)
            else:
                out.append(TRAN)
    return out


def _pixels_to_dib(pixels, w, h):
    """Pack a BGRA pixel list into a BMP DIB bytes object (bottom-to-top row order)."""
    bih = _struct.pack('<lllHHllllll', 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    xor = b''.join(
        _struct.pack('4B', b, g, r, a)
        for row in range(h - 1, -1, -1)
        for col in range(w)
        for b, g, r, a in [pixels[row * w + col]]
    )
    and_mask = b'\x00' * ((w + 31) // 32 * 4 * h)
    return bih + xor + and_mask


def _build_tray_icon():
    """16×16 traffic-light circles → HICON for the system tray."""
    W = H = 16
    data = _pixels_to_dib(_traffic_light_pixels(W, H), W, H)
    buf  = ctypes.create_string_buffer(data)
    return _user32.CreateIconFromResourceEx(buf, len(data), True, 0x00030000, W, H, 0)


def _create_ico_file(path):
    """Write a 16 / 32 / 48 px multi-size ICO file with the traffic-light design."""
    sizes  = [16, 32, 48]
    dibs   = [_pixels_to_dib(_traffic_light_pixels(s, s), s, s) for s in sizes]
    n      = len(sizes)
    header = _struct.pack('<HHH', 0, 1, n)

    data_offset = 6 + 16 * n
    offset, directory = data_offset, b''
    for i, s in enumerate(sizes):
        wb = 0 if s >= 256 else s
        directory += _struct.pack('<BBBBHHII', wb, wb, 0, 0, 1, 32, len(dibs[i]), offset)
        offset += len(dibs[i])

    Path(path).write_bytes(header + directory + b''.join(dibs))


def _single_instance_check():
    """
    Acquire a named mutex to enforce single-instance launch.
    Returns True  → this is the first instance, proceed normally.
    Returns False → another instance is already running; it has been told to
                    show its window via _WM_SHOW_INSTANCE, so we should exit.
    The mutex handle is intentionally never closed so it lives for the
    entire process lifetime.
    """
    _kernel32.CreateMutexW(None, False, "GreenLightSingleInstanceMutex")
    if _kernel32.GetLastError() == 183:       # ERROR_ALREADY_EXISTS
        hwnd = _user32.FindWindowW("GreenLightTrayWnd", None)
        if hwnd:
            _user32.PostMessageW(hwnd, _WM_SHOW_INSTANCE, 0, 0)
        return False
    return True


class SystemTray:
    """Minimal Win32 system tray icon running its own message thread."""
    _cls = "GreenLightTrayWnd"

    def __init__(self, tooltip, on_click, on_quit, on_show=None):
        self._tooltip  = tooltip
        self._on_click = on_click
        self._on_quit  = on_quit
        self._on_show  = on_show if on_show is not None else on_click
        self._hwnd     = None
        self._icon     = _build_tray_icon()
        self._ready    = _threading.Event()
        t = _threading.Thread(target=self._run, daemon=True)
        t.start()
        self._ready.wait(timeout=3)

    def _run(self):
        hinst = _kernel32.GetModuleHandleW(None)
        proc  = _WNDPROC_T(self._wndproc)
        self._proc = proc   # prevent GC
        wc = _WNDCLASSW()
        wc.lpfnWndProc   = proc
        wc.hInstance     = hinst
        wc.lpszClassName = self._cls
        _user32.RegisterClassW(ctypes.byref(wc))
        self._hwnd = _user32.CreateWindowExW(
            0, self._cls, self._cls, 0, 0, 0, 0, 0,
            None, None, hinst, None)   # NULL parent → desktop-level hidden window
        self._add_icon()
        self._ready.set()
        msg = ctypes.wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        self._remove_icon()

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == _WM_USER_TRAY:
            if lparam in (_WM_LBUTTONUP, _WM_LBUTTONDBLCLK):
                self._on_click()
            elif lparam == _WM_RBUTTONUP:
                self._show_menu()
        elif msg == _WM_SHOW_INSTANCE:
            self._on_show()
        elif msg == _WM_DESTROY:
            _user32.PostQuitMessage(0)
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self):
        hmenu = _user32.CreatePopupMenu()
        _user32.AppendMenuW(hmenu, 0,             1, "Green Light")
        _user32.AppendMenuW(hmenu, _MFT_SEPARATOR, 0, None)
        _user32.AppendMenuW(hmenu, 0,             2, "退出")
        pt = _POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        _user32.SetForegroundWindow(self._hwnd)
        cmd = _user32.TrackPopupMenu(
            hmenu, _TPM_RETURNCMD | _TPM_RIGHTALIGN,
            pt.x, pt.y, 0, self._hwnd, None)
        _user32.DestroyMenu(hmenu)
        if cmd == 1:
            self._on_click()
        elif cmd == 2:
            self._on_quit()

    def _nid(self):
        nid = _NOTIFYICONDATAW()
        nid.cbSize           = ctypes.sizeof(_NOTIFYICONDATAW)
        nid.hWnd             = self._hwnd
        nid.uID              = 1
        nid.uFlags           = _NIF_MSG | _NIF_ICON | _NIF_TIP
        nid.uCallbackMessage = _WM_USER_TRAY
        nid.hIcon            = self._icon
        nid.szTip            = self._tooltip
        return nid

    def _add_icon(self):
        nid = self._nid()
        _shell32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(nid))

    def _remove_icon(self):
        if self._hwnd:
            nid = self._nid()
            _shell32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(nid))

    def destroy(self):
        if self._hwnd:
            _user32.PostMessageW(self._hwnd, _WM_DESTROY, 0, 0)


def _remove_maximize_btn(root):
    """Remove maximize button while keeping minimize."""
    root.update_idletasks()
    hwnd = _user32.GetParent(root.winfo_id()) or root.winfo_id()
    GWL_STYLE      = -16
    WS_MAXIMIZEBOX = 0x00010000
    style = _user32.GetWindowLongW(hwnd, GWL_STYLE)
    _user32.SetWindowLongW(hwnd, GWL_STYLE, style & ~WS_MAXIMIZEBOX)
    _user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)  # NOMOVE|NOSIZE|NOZORDER|FRAMECHANGED


# ─── main app ─────────────────────────────────────────────────────────────

class GreenLight:
    def __init__(self, root):
        self.root = root
        self.config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
        self.data = load_json(DATA_FILE, {"sessions": [], "current": None})
        self._recover_previous()

        self.recording = True
        self.session_start = datetime.now()

        self._build_ui()
        self._tick()
        self._autosave()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._tray = SystemTray(
            "Green Light",
            on_click=lambda: root.after(0, self._toggle_window),
            on_quit=lambda: root.after(0, self._quit_app),
            on_show=lambda: root.after(0, self._show_window),
        )

    # session lifecycle ----------------------------------------------------

    def _recover_previous(self):
        cur = self.data.get("current")
        if cur:
            try:
                start = datetime.fromisoformat(cur["start"])
                end = datetime.fromisoformat(cur["last"])
                if end > start:
                    self.data["sessions"].append({
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "duration": (end - start).total_seconds(),
                    })
            except (KeyError, ValueError):
                pass
            self.data["current"] = None
            save_json(DATA_FILE, self.data)

    def _autosave(self):
        if self.recording and self.session_start:
            self.data["current"] = {
                "start": self.session_start.isoformat(),
                "last": datetime.now().isoformat(),
            }
        else:
            self.data["current"] = None
        save_json(DATA_FILE, self.data)
        self.root.after(30_000, self._autosave)

    def _close_session(self):
        if not (self.recording and self.session_start):
            return
        end = datetime.now()
        if end > self.session_start:
            self.data["sessions"].append({
                "start": self.session_start.isoformat(),
                "end": end.isoformat(),
                "duration": (end - self.session_start).total_seconds(),
            })
        self.data["current"] = None
        save_json(DATA_FILE, self.data)

    def _on_close(self):
        self.root.withdraw()   # hide to tray; keep recording

    def _show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _toggle_window(self):
        if self.root.state() == 'withdrawn':
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        else:
            self.root.withdraw()

    def _quit_app(self):
        self._close_session()
        self._tray.destroy()
        self.root.destroy()

    def _set_recording(self, on):
        if on and not self.recording:
            self.recording = True
            self.session_start = datetime.now()
        elif not on and self.recording:
            self._close_session()
            self.recording = False
            self.session_start = None

    # aggregation ---------------------------------------------------------

    def _today_seconds(self):
        return self._seconds_per_day(date.today(), date.today())[date.today()]

    def _seconds_per_day(self, start_day, end_day):
        days = {}
        d = start_day
        while d <= end_day:
            days[d] = 0.0
            d += timedelta(days=1)
        for s in self.data["sessions"]:
            try:
                d = datetime.fromisoformat(s["start"]).date()
            except (KeyError, ValueError):
                continue
            if start_day <= d <= end_day:
                days[d] = days.get(d, 0.0) + s.get("duration", 0)
        if self.recording and self.session_start:
            d = self.session_start.date()
            if start_day <= d <= end_day:
                days[d] = days.get(d, 0.0) + (datetime.now() - self.session_start).total_seconds()
        return days

    # UI ------------------------------------------------------------------

    def _build_ui(self):
        r = self.root
        r.title("Green Light")
        r.configure(bg=BG)

        self._pages_frame = tk.Frame(r, bg=BG)
        self._pages_frame.pack(fill="both", expand=True)

        self.home_frame     = tk.Frame(self._pages_frame, bg=BG)
        self.week_frame     = tk.Frame(self._pages_frame, bg=BG)
        self.month_frame    = tk.Frame(self._pages_frame, bg=BG)
        self.settings_frame = tk.Frame(self._pages_frame, bg=BG)

        self._build_home_page()
        self._build_week_page()
        self._build_month()
        self._build_settings()
        self._build_bottom_nav(r)
        self._show_page(0)

        r.update_idletasks()
        r.geometry("380x620")
        r.resizable(False, False)
        r.after(100, lambda: _remove_maximize_btn(r))

    def _build_home_page(self):
        f = self.home_frame

        tk.Frame(f, bg=BG, height=22).pack()

        # ── Pixel traffic light ───────────────────────────────────────────
        tl_wrap = tk.Frame(f, bg=BG)
        tl_wrap.pack(anchor="center")
        self._pixel_tl = PixelTrafficLight(tl_wrap)
        self._pixel_tl.pack()

        tk.Frame(f, bg=BG, height=22).pack()

        # ── Status: dot + title ───────────────────────────────────────────
        status_row = tk.Frame(f, bg=BG)
        status_row.pack(anchor="center")
        self.status_dot = tk.Canvas(status_row, width=14, height=14,
                                    bg=BG, highlightthickness=0, bd=0)
        self.status_dot.pack(side="left", padx=(0, 8), pady=(4, 0))
        self.status_dot_id = self.status_dot.create_oval(1, 1, 13, 13,
                                                         fill=RED, outline="")
        self.title_var = tk.StringVar(value="Red Light")
        tk.Label(status_row, textvariable=self.title_var, bg=BG, fg=TEXT,
                 font=(FONT_UI, 20, "bold")).pack(side="left")

        tk.Frame(f, bg=BG, height=6).pack()

        # ── Session clock — large hero element ────────────────────────────
        self.session_var = tk.StringVar(value="00:00:00")
        tk.Label(f, textvariable=self.session_var,
                 font=(FONT_MONO, 28), bg=BG, fg=TEXT).pack(anchor="center")

        tk.Frame(f, bg=BG, height=24).pack()

        # ── Today progress — card style ───────────────────────────────────
        card_wrap = tk.Frame(f, bg=BG)
        card_wrap.pack(fill="x", padx=26)
        card = tk.Frame(card_wrap, bg=SURFACE,
                        highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x")
        card_inner = tk.Frame(card, bg=SURFACE)
        card_inner.pack(fill="x", padx=18, pady=14)

        top_row = tk.Frame(card_inner, bg=SURFACE)
        top_row.pack(fill="x")
        self.today_left = tk.StringVar(value="今日 0m / 8h")
        tk.Label(top_row, textvariable=self.today_left, bg=SURFACE, fg=TEXT,
                 font=(FONT_UI, 10)).pack(side="left")
        self.today_right = tk.StringVar(value="0%")
        tk.Label(top_row, textvariable=self.today_right, bg=SURFACE, fg=ACCENT,
                 font=(FONT_UI, 12, "bold")).pack(side="right")
        self.progress = ProgressBar(card_inner, height=8)
        self.progress.pack(fill="x", pady=(10, 0))

        tk.Frame(f, bg=BG).pack(expand=True)

        # ── Pill toggle ───────────────────────────────────────────────────
        self._pill_toggle = PillToggle(f, value=True,
                                       on_toggle=self._on_recording_toggle)
        self._pill_toggle.pack(anchor="center", pady=(0, 30))

    def _build_week_page(self):
        f = self.week_frame
        inner = tk.Frame(f, bg=BG)
        inner.pack(fill="both", expand=True, padx=26, pady=20)

        tk.Label(inner, text="本周概览", bg=BG, fg=TEXT,
                 font=(FONT_UI, 14, "bold")).pack(anchor="w", pady=(0, 14))

        card = tk.Frame(inner, bg=SURFACE,
                        highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="both", expand=True)
        chart_pad = tk.Frame(card, bg=BG)
        chart_pad.pack(fill="both", expand=True, padx=6, pady=8)

        self.bar_chart = WeekBarChart(chart_pad)
        self.bar_chart.pack(fill="both", expand=True)

        self.week_summary = tk.StringVar(value="")
        tk.Label(inner, textvariable=self.week_summary,
                 bg=BG, fg=TEXT2, font=(FONT_UI, 10)).pack(pady=(10, 0))

    @staticmethod
    def _hover_bind(widget, enter_bg, leave_bg):
        widget.bind("<Enter>", lambda _e: widget.configure(bg=enter_bg))
        widget.bind("<Leave>", lambda _e: widget.configure(bg=leave_bg))

    def _build_bottom_nav(self, parent):
        nav = tk.Frame(parent, bg=SURFACE)
        nav.pack(fill="x", side="bottom")
        tk.Frame(nav, bg=BORDER, height=1).pack(fill="x")
        row = tk.Frame(nav, bg=SURFACE)
        row.pack(fill="x")
        self._nav_btns = []
        self._nav_indicators = []
        for i, label in enumerate(["主页", "本周", "本月", "设置"]):
            col = tk.Frame(row, bg=SURFACE)
            col.pack(side="left", expand=True, fill="both")
            indicator = tk.Frame(col, bg=SURFACE, height=3)
            indicator.pack(fill="x")
            btn = tk.Label(col, text=label, bg=SURFACE, fg=TEXT2,
                           font=(FONT_UI, 10), pady=10, cursor="hand2")
            btn.pack(expand=True)
            btn.bind("<Button-1>", lambda _e, idx=i: self._show_page(idx))
            col.bind("<Button-1>", lambda _e, idx=i: self._show_page(idx))
            self._hover_bind(btn, SURFACE_ALT, SURFACE)
            self._nav_btns.append(btn)
            self._nav_indicators.append(indicator)

    def _show_page(self, idx):
        for p in (self.home_frame, self.week_frame,
                  self.month_frame, self.settings_frame):
            p.pack_forget()
        (self.home_frame, self.week_frame,
         self.month_frame, self.settings_frame)[idx].pack(fill="both", expand=True)
        for i, btn in enumerate(self._nav_btns):
            active = i == idx
            btn.configure(fg=ACCENT if active else TEXT2,
                          font=(FONT_UI, 10, "bold") if active else (FONT_UI, 10))
            self._nav_indicators[i].configure(bg=ACCENT if active else SURFACE)

    def _build_month(self):
        f = self.month_frame
        inner = tk.Frame(f, bg=BG)
        inner.pack(fill="both", expand=True, padx=26, pady=20)

        self.month_title = tk.StringVar(value="")
        tk.Label(inner, textvariable=self.month_title, bg=BG, fg=TEXT,
                 font=(FONT_UI, 14, "bold")).pack(anchor="w", pady=(0, 16))

        card = tk.Frame(inner, bg=SURFACE,
                        highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x")
        card_inner = tk.Frame(card, bg=SURFACE)
        card_inner.pack(fill="x", padx=18, pady=4)

        self.month_rows = []
        labels = ["总工时", "工作天数", "日均", "达标天数", "最长一天"]
        for i, label_key in enumerate(labels):
            if i > 0:
                tk.Frame(card_inner, bg=SURFACE_ALT, height=1).pack(fill="x")
            row = tk.Frame(card_inner, bg=SURFACE)
            row.pack(fill="x", pady=13)
            tk.Label(row, text=label_key, bg=SURFACE, fg=TEXT2,
                     font=(FONT_UI, 10)).pack(side="left")
            v = tk.StringVar(value="—")
            tk.Label(row, textvariable=v, bg=SURFACE, fg=TEXT,
                     font=(FONT_UI, 11, "bold")).pack(side="right")
            self.month_rows.append(v)

    def _build_settings(self):
        f = self.settings_frame
        inner = tk.Frame(f, bg=BG)
        inner.pack(fill="both", expand=True, padx=26, pady=20)

        tk.Label(inner, text="设置", bg=BG, fg=TEXT,
                 font=(FONT_UI, 14, "bold")).pack(anchor="w", pady=(0, 16))

        # ── Card 1: target ────────────────────────────────────────────────
        card1 = tk.Frame(inner, bg=SURFACE,
                         highlightthickness=1, highlightbackground=BORDER)
        card1.pack(fill="x", pady=(0, 12))
        c1_inner = tk.Frame(card1, bg=SURFACE)
        c1_inner.pack(fill="x", padx=18, pady=14)

        target_row = tk.Frame(c1_inner, bg=SURFACE)
        target_row.pack(fill="x")
        tk.Label(target_row, text="每日目标", bg=SURFACE, fg=TEXT,
                 font=(FONT_UI, 11)).pack(side="left")

        ctrl = tk.Frame(target_row, bg=SURFACE_ALT,
                        highlightthickness=1, highlightbackground=BORDER)
        ctrl.pack(side="right")

        def step(delta):
            new = max(30, min(1440, self.config["target_minutes"] + delta))
            if new != self.config["target_minutes"]:
                self.config["target_minutes"] = new
                self._refresh_target_display()
                save_json(CONFIG_FILE, self.config)

        minus = tk.Label(ctrl, text="−", bg=SURFACE_ALT, fg=TEXT,
                         font=(FONT_UI, 13), padx=12, pady=3, cursor="hand2")
        minus.pack(side="left")
        minus.bind("<Button-1>", lambda _e: step(-30))
        self._hover_bind(minus, BORDER, SURFACE_ALT)

        self.target_label_var = tk.StringVar(value="")
        tk.Label(ctrl, textvariable=self.target_label_var, bg=SURFACE_ALT, fg=TEXT,
                 font=(FONT_UI, 11), padx=8, pady=3, width=7).pack(side="left")

        plus = tk.Label(ctrl, text="+", bg=SURFACE_ALT, fg=TEXT,
                        font=(FONT_UI, 13), padx=12, pady=3, cursor="hand2")
        plus.pack(side="left")
        plus.bind("<Button-1>", lambda _e: step(30))
        self._hover_bind(plus, BORDER, SURFACE_ALT)

        self._refresh_target_display()

        # ── Card 2: autostart + shortcut ──────────────────────────────────
        card2 = tk.Frame(inner, bg=SURFACE,
                         highlightthickness=1, highlightbackground=BORDER)
        card2.pack(fill="x", pady=(0, 12))
        c2_inner = tk.Frame(card2, bg=SURFACE)
        c2_inner.pack(fill="x", padx=18, pady=4)

        auto_row = tk.Frame(c2_inner, bg=SURFACE)
        auto_row.pack(fill="x", pady=13)
        tk.Label(auto_row, text="开机自启动", bg=SURFACE, fg=TEXT,
                 font=(FONT_UI, 11)).pack(side="left")
        self.autostart_toggle = ToggleSwitch(
            auto_row, value=self.config.get("autostart", False),
            on_toggle=self._on_autostart_toggle)
        self.autostart_toggle.pack(side="right")

        tk.Frame(c2_inner, bg=SURFACE_ALT, height=1).pack(fill="x")

        shortcut_row = tk.Frame(c2_inner, bg=SURFACE)
        shortcut_row.pack(fill="x", pady=13)
        tk.Label(shortcut_row, text="桌面快捷方式", bg=SURFACE, fg=TEXT,
                 font=(FONT_UI, 11)).pack(side="left")

        def _do_create_shortcut():
            ok, info = create_desktop_shortcut()
            if ok:
                messagebox.showinfo("Green Light",
                                    "桌面快捷方式已创建！\n双击桌面上的 Green Light 图标即可启动。")
            else:
                messagebox.showerror("Green Light", f"创建失败：\n{info}")

        sc_btn = tk.Label(shortcut_row, text="创 建",
                          bg=ACCENT_LIGHT, fg=ACCENT,
                          font=(FONT_UI, 10), padx=14, pady=4,
                          cursor="hand2",
                          highlightthickness=1,
                          highlightbackground=ACCENT_DIM)
        sc_btn.pack(side="right")
        sc_btn.bind("<Button-1>", lambda _e: _do_create_shortcut())
        self._hover_bind(sc_btn, ACCENT_DIM, ACCENT_LIGHT)

        # ── Data path info ────────────────────────────────────────────────
        tk.Label(inner, text="数据存储位置", bg=BG, fg=TEXT3,
                 font=(FONT_UI, 9)).pack(anchor="w", pady=(12, 2))
        tk.Label(inner, text=str(APP_DIR), bg=BG, fg=TEXT2,
                 font=(FONT_UI, 9), wraplength=300, justify="left").pack(anchor="w")

    def _refresh_target_display(self):
        m = self.config["target_minutes"]
        h, mm = divmod(m, 60)
        if h and mm:
            txt = f"{h}h {mm:02d}m"
        elif h:
            txt = f"{h}h"
        else:
            txt = f"{mm}m"
        self.target_label_var.set(txt)

    # handlers ------------------------------------------------------------

    def _on_recording_toggle(self, on):
        self._set_recording(on)

    def _on_autostart_toggle(self, on):
        ok, err = set_autostart(on, autostart_command())
        if not ok:
            messagebox.showerror("Green Light", f"无法设置自启动：\n{err}")
            self.autostart_toggle.set(not on)
            return
        self.config["autostart"] = on
        save_json(CONFIG_FILE, self.config)

    # tick ----------------------------------------------------------------

    def _set_status(self, target_met):
        if not self.recording:
            self.status_dot.itemconfig(self.status_dot_id, fill=YELLOW)
            self.title_var.set("Pause")
            self._pixel_tl.update_state(False, False)
        elif target_met:
            self.status_dot.itemconfig(self.status_dot_id, fill=GREEN)
            self.title_var.set("Green Light")
            self._pixel_tl.update_state(True, True)
        else:
            self.status_dot.itemconfig(self.status_dot_id, fill=RED)
            self.title_var.set("Red Light")
            self._pixel_tl.update_state(True, False)

    def _tick(self):
        if self.recording and self.session_start:
            secs = (datetime.now() - self.session_start).total_seconds()
        else:
            secs = 0
        self.session_var.set(fmt_clock(secs))

        target = self.config["target_minutes"] * 60
        today = self._today_seconds()
        pct = min(100.0, today / target * 100) if target else 0
        self.progress.set(pct)
        self.today_left.set(f"今日 {fmt_hm(today)} / {fmt_hm(target)}")
        self.today_right.set(f"{int(pct)}%")
        self._set_status(today >= target)

        self._refresh_stats()
        self.root.after(1000, self._tick)

    def _refresh_stats(self):
        today = date.today()
        target_secs = self.config["target_minutes"] * 60

        # week — current Sun-Sat natural week
        days_since_sun = (today.weekday() + 1) % 7
        week_start = today - timedelta(days=days_since_sun)
        week_end = week_start + timedelta(days=6)
        week = self._seconds_per_day(week_start, week_end)
        self.bar_chart.update_data(week, target_secs)
        total_w = sum(week.values())
        active_w = sum(1 for v in week.values() if v > 0)
        avg_w = total_w / max(1, active_w)
        self.week_summary.set(f"日均  {fmt_hm(avg_w)}")

        # month
        first = today.replace(day=1)
        if today.month == 12:
            last = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            last = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        month = self._seconds_per_day(first, last)
        total_m = sum(month.values())
        active = sum(1 for v in month.values() if v > 0)
        avg_m = total_m / max(1, active)
        target_hit = sum(1 for v in month.values() if v >= target_secs)
        if any(v > 0 for v in month.values()):
            best_day, best_secs = max(month.items(), key=lambda x: x[1])
            best_str = f"{fmt_hm(best_secs)}（{best_day.month}/{best_day.day}）"
        else:
            best_str = "—"
        self.month_title.set(f"{today.year} 年 {today.month} 月")
        self.month_rows[0].set(fmt_hm(total_m))
        self.month_rows[1].set(f"{active} 天")
        self.month_rows[2].set(fmt_hm(avg_m))
        self.month_rows[3].set(f"{target_hit} 天")
        self.month_rows[4].set(best_str)


def main():
    if not _single_instance_check():
        return   # another instance is running; it has been signalled to show itself

    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    ico_path = APP_DIR / "icon.ico"
    try:
        _create_ico_file(ico_path)
    except Exception:
        ico_path = None

    root = tk.Tk()
    _resolve_fonts(root)

    if ico_path:
        try:
            root.iconbitmap(str(ico_path))
        except Exception:
            pass

    GreenLight(root)
    root.mainloop()


if __name__ == "__main__":
    main()
