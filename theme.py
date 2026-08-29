"""
奥黛塔 · 深海冰晶主题：gui.py 的视觉皮肤（纯 tkinter，零第三方依赖）
========================================================================
配色取自奥黛塔的元素爆发演示：深海蓝 + 冰晶青 + 淡紫（眼睛/头饰）
- BG        #0d1b2e  窗口底色
- PANEL     #15263f  面板填充（圆角）
- FIELD     #0a1626  输入框底色
- ICE       #7fd4ff  冰晶青（主强调）
- LAV       #b48cff  淡紫（次强调）
- TEXT      #e6f2ff  文字
- OK / WARN / ERR 状态色
"""
from __future__ import annotations

import ctypes
import tkinter as tk
from tkinter import ttk

BG = "#0d1b2e"
PANEL = "#15263f"
PANEL_LINE = "#3d5a86"
FIELD = "#0a1626"
ICE = "#7fd4ff"
ICE_DEEP = "#3d9fd8"
LAV = "#b48cff"
TEXT = "#e6f2ff"
TEXT_DIM = "#9db8d8"
OK = "#6dff9e"
WARN = "#ffd479"
ERR = "#ff7d7d"
SECTION = "#9fdcff"

_ACCENTS = (ICE, LAV)


def apply_theme(root: tk.Tk):
    """应用全局主题样式。"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    root.configure(bg=BG)

    style.configure(".", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 10))
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Dim.TLabel", background=BG, foreground=TEXT_DIM)
    style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT,
                    insertcolor=TEXT, bordercolor=PANEL_LINE,
                    lightcolor=PANEL_LINE, darkcolor=PANEL_LINE)
    style.configure("TCombobox", fieldbackground=FIELD, foreground=TEXT,
                    background=PANEL, bordercolor=PANEL_LINE,
                    lightcolor=PANEL_LINE, darkcolor=PANEL_LINE, arrowcolor=ICE)
    style.map("TCombobox",
              fieldbackground=[("readonly", FIELD)],
              foreground=[("readonly", TEXT)])
    # 下拉弹出列表：深底 + 冰蓝选中（修复"又空又长"）
    style.configure("TCombobox.Listbox", background=FIELD, foreground=TEXT,
                    selectbackground=ICE_DEEP, selectforeground="#ffffff",
                    borderwidth=0, relief="flat", font=("Microsoft YaHei UI", 10))
    style.configure("TCheckbutton", background=BG, foreground=TEXT,
                    focuscolor=BG, indicatorcolor=FIELD)
    style.map("TCheckbutton",
              background=[("active", BG)],
              indicatorcolor=[("selected", ICE)],
              foreground=[("selected", ICE)])
    style.configure("TScale", background=BG, troughcolor=FIELD, bordercolor=PANEL_LINE,
                    lightcolor=ICE, darkcolor=LAV)
    style.configure("TSpinbox", fieldbackground=FIELD, foreground=TEXT,
                    background=PANEL, bordercolor=PANEL_LINE,
                    lightcolor=PANEL_LINE, darkcolor=PANEL_LINE, arrowcolor=ICE)
    style.configure("TButton", background=PANEL, foreground=TEXT, bordercolor=PANEL_LINE,
                    focuscolor=PANEL, padding=(12, 6))
    style.map("TButton",
              background=[("active", "#1e345f"), ("pressed", "#10203a")],
              foreground=[("disabled", TEXT_DIM)])
    style.configure("Accent.TButton", background=ICE, foreground="#06283f",
                    bordercolor=ICE, padding=(14, 7))
    style.map("Accent.TButton",
              background=[("active", "#a8e2ff"), ("pressed", ICE_DEEP)])
    style.configure("Danger.TButton", background="#a03040", foreground="#ffe3e3",
                    bordercolor="#a03040", padding=(14, 7))
    style.map("Danger.TButton",
              background=[("active", "#c04355"), ("pressed", "#80202e")])

    try:
        _set_whale_icon(root)
    except Exception:
        pass


# ---------------------------------------------------------------- 圆角面板
class RoundedFrame(tk.Canvas):
    """圆角面板：Canvas 绘制圆角矩形，内部承载控件。"""

    def __init__(self, master, title: str = "", radius: int = 16,
                 fill: str = PANEL, line: str = PANEL_LINE, **kw):
        super().__init__(master, bg=BG, highlightthickness=0, bd=0, **kw)
        self._title = title
        self._radius = radius
        self._fill = fill
        self._line = line
        self.bind("<Configure>", lambda e: self._draw())

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 20 or h < 20:
            return
        pts = rounded_rect(0, 0, w, h, self._radius)
        self.create_polygon(pts, smooth=True, fill=self._fill,
                            outline=self._line, width=1)
        if self._title:
            self.create_text(22, 20, text=self._title, anchor="w",
                             fill=SECTION, font=("Microsoft YaHei UI", 10, "bold"))
        # 标题下淡紫/冰青装饰短线
        if self._title:
            self.create_line(22, 32, 150, 32, fill=LAV, width=1)

    def add(self, widget, x=16, y=8):
        """把控件放进面板（y 相对面板顶部）。"""
        self.create_window(x, y, window=widget, anchor="nw")
        return widget


def rounded_rect(x0, y0, x1, y1, r):
    """圆角矩形路径点集（供 create_polygon smooth=True 使用）。"""
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    return [
        x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
        x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
        x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
    ]


# ---------------------------------------------------------------- 标题栏
class TitleBar(tk.Frame):
    """自定义标题栏：冰晶渐变底 + 钻石/羽毛装饰 + 最小化/关闭按钮。"""

    def __init__(self, master, title: str, on_close=None, on_min=None):
        super().__init__(master, bg=BG, height=48)
        self.pack_propagate(False)
        self._on_close = on_close or (lambda: None)
        self._on_min = on_min or (lambda: None)

        self._canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<Configure>", lambda e: self._draw())
        self._canvas.bind("<Button-1>", self._drag_start)
        self._canvas.bind("<B1-Motion>", self._drag_move)
        self._drag_off = (0, 0)

        # 标题文字（◆ 钻石 + ❋ 羽饰 + 标题）
        self._title = title
        self._draw()

        # 最小化/关闭按钮（放 Frame 上避免被 canvas 重绘）
        btns = tk.Frame(self, bg=BG)
        btns.place(relx=1.0, x=-8, y=8, anchor="ne")
        self._min_btn = tk.Label(btns, text="—", fg=TEXT_DIM, bg=BG,
                                 font=("Microsoft YaHei UI", 12), padx=10, cursor="hand2")
        self._min_btn.pack(side="left")
        self._min_btn.bind("<Button-1>", lambda e: self._on_min())
        self._min_btn.bind("<Enter>", lambda e: self._min_btn.config(bg=PANEL))
        self._min_btn.bind("<Leave>", lambda e: self._min_btn.config(bg=BG))
        self._close_btn = tk.Label(btns, text="✕", fg=TEXT_DIM, bg=BG,
                                   font=("Microsoft YaHei UI", 12), padx=10, cursor="hand2")
        self._close_btn.pack(side="left")
        self._close_btn.bind("<Button-1>", lambda e: self._on_close())
        self._close_btn.bind("<Enter>", lambda e: self._close_btn.config(bg="#a03040", fg="#fff"))
        self._close_btn.bind("<Leave>", lambda e: self._close_btn.config(bg=BG, fg=TEXT_DIM))

    def _draw(self):
        c = self._canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 10:
            return
        # 渐变底（深海蓝 → 冰晶蓝）
        for i in range(h):
            t = i / max(1, h)
            col = blend("#16294a", "#1d3d63", t)
            c.create_line(0, i, w, i, fill=col)
        # 底部冰晶描边
        c.create_line(0, h - 1, w, h - 1, fill=ICE_DEEP, width=2)
        # 装饰：左钻石 + 羽毛 + 标题（奥黛塔冰蓝紫）
        c.create_text(18, h // 2 + 1, text="❖", anchor="w", fill=ICE,
                      font=("Segoe UI Symbol", 13, "bold"))
        c.create_text(38, h // 2 + 1, text="❋", anchor="w", fill=LAV,
                      font=("Segoe UI Symbol", 13))
        c.create_text(60, h // 2 + 1, text=self._title, anchor="w", fill=TEXT,
                      font=("Microsoft YaHei UI", 12, "bold"))
        # 右侧小装饰（避免盖住按钮，按钮在 relx=1 处）
        c.create_text(w - 90, h // 2 + 1, text="◆", anchor="e", fill=ICE_DEEP,
                      font=("Segoe UI Symbol", 9))

    def _drag_start(self, e):
        self._drag_off = (e.x_root - self.winfo_rootx(), e.y_root - self.winfo_rooty())

    def _drag_move(self, e):
        root = self.winfo_toplevel()
        x = e.x_root - self._drag_off[0]
        y = e.y_root - self._drag_off[1]
        root.geometry(f"+{x}+{y}")


def blend(c1: str, c2: str, t: float) -> str:
    """两个 #rrggbb 颜色按 t 插值。"""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ---------------------------------------------------------------- 背景烘焙
def bake_panels(src_path, out_path, rects, alpha: int = 150, fill=(21, 38, 63),
                title_band: int = 48):
    """把半透明圆角面板烘焙进背景图（奥黛塔透出来）。
    rects: [(x, y, w, h, radius), ...]  title_band: 顶部标题带高度。"""
    from PIL import Image, ImageDraw

    img = Image.open(src_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    # 顶部标题带：深海蓝 → 冰晶蓝渐变（不透明）
    for y in range(min(title_band, img.height)):
        t = y / max(1, title_band)
        col = (22 + int(12 * t), 41 + int(30 * t), 74 + int(38 * t), 255)
        d.line([(0, y), (img.width, y)], fill=col)
    # 半透明圆角面板
    for (x, y, w, h, r) in rects:
        d.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=(*fill, alpha))
    out = Image.alpha_composite(img, overlay).convert("RGB")
    out.save(out_path)


# ---------------------------------------------------------------- 胶囊按钮
def round_button(master, text: str, command, kind: str = "normal"):
    """胶囊形圆角按钮（PIL 现画渐变底 + tk 文字）。kind: normal/accent/danger。"""
    from PIL import Image, ImageDraw, ImageFilter

    # 按字符实际宽度估算（CJK 14px / 拉丁 8px），避免按钮互相堆叠
    width_px = sum(14 if ord(c) > 0x2E80 else 8 for c in text) + 36
    w = max(72, width_px)
    h = 32
    colors = {
        "normal": ((34, 55, 90), (26, 44, 74), (61, 90, 134)),
        "accent": ((127, 212, 255), (92, 184, 232), (168, 226, 255)),
        "danger": ((176, 64, 80), (142, 48, 64), (208, 96, 112)),
    }
    top, bot, border = colors[kind]

    def make(frac: float):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # 垂直渐变
        for y in range(h):
            t = y / h
            col = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
            d.line([(0, y), (w, y)], fill=(*col, 255))
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([1, 1, w - 2, h - 2], radius=h // 2, fill=255)
        # 底部微光（让胶囊有立体感）
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(glow).rounded_rectangle([1, 1, w - 2, h - 2], radius=h // 2,
                                               fill=(*border, 255))
        glow = glow.filter(ImageFilter.GaussianBlur(3))
        img = Image.alpha_composite(img, glow)
        img.putalpha(mask)
        return img

    tk_img = {"normal": None, "hover": None, "pressed": None}
    from PIL import ImageTk
    for name, frac in (("normal", 1.0), ("hover", 1.12), ("pressed", 0.92)):
        im = make(frac)
        tk_img[name] = ImageTk.PhotoImage(im.resize((w, h)))

    fg = "#06283f" if kind == "accent" else ("#ffe3e3" if kind == "danger" else TEXT)
    btn = tk.Button(master, image=tk_img["normal"], text=text, compound="center",
                    command=command, bd=0, borderwidth=0, relief="flat",
                    highlightthickness=0, takefocus=0,
                    bg=BG, activebackground=BG, fg=fg, activeforeground=fg,
                    font=("Microsoft YaHei UI", 10, "bold" if kind != "normal" else "normal"),
                    cursor="hand2")
    btn._imgs = tk_img
    btn.bind("<Enter>", lambda e: btn.config(image=tk_img["hover"]))
    btn.bind("<Leave>", lambda e: btn.config(image=tk_img["normal"]))
    btn.bind("<ButtonPress-1>", lambda e: btn.config(image=tk_img["pressed"]))
    btn.bind("<ButtonRelease-1>", lambda e: btn.config(image=tk_img["hover"]))
    return btn


# ---------------------------------------------------------------- 圆形滑块
class RoundSlider(tk.Canvas):
    """圆形滑块：圆角轨道 + 圆钮，鼠标拖拽。"""

    def __init__(self, master, from_: float, to: float, variable=None,
                 command=None, width: int = 300, height: int = 26, bg: str = BG):
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0)
        self._from, self._to = from_, to
        self.var = variable if variable is not None else tk.DoubleVar(value=from_)
        self.command = command
        self._pad = 14
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._release)
        self.var.trace_add("write", lambda *a: self._draw())
        self._draw()

    def _x(self, v):
        w = max(self.winfo_width(), 60)
        t = (v - self._from) / max(1e-9, (self._to - self._from))
        return self._pad + t * (w - 2 * self._pad)

    def _v(self, x):
        w = max(self.winfo_width(), 60)
        t = (x - self._pad) / max(1e-9, (w - 2 * self._pad))
        t = max(0.0, min(1.0, t))
        return self._from + t * (self._to - self._from)

    def _press(self, e):
        self.var.set(round(self._v(e.x), 3))
        if self.command:
            self.command(self.var.get())

    def _move(self, e):
        self.var.set(round(self._v(e.x), 3))
        if self.command:
            self.command(self.var.get())

    def _release(self, e):
        pass

    def _draw(self):
        self.delete("all")
        w = max(self.winfo_width(), 60)
        h = max(self.winfo_height(), 20)
        y = h // 2
        x = self._x(float(self.var.get()))
        # 轨道（圆角条）
        self.create_oval(self._pad, y - 4, w - self._pad, y + 4,
                         fill="#0a1626", outline="#3d5a86")
        # 已走部分（冰青）
        if x > self._pad:
            self.create_rectangle(self._pad, y - 4, x, y + 4, fill=ICE_DEEP, outline="")
        # 圆钮（冰青 + 高光）
        self.create_oval(x - 9, y - 9, x + 9, y + 9, fill=ICE, outline="#e8f8ff", width=2)
        self.create_oval(x - 3, y - 5, x + 1, y - 1, fill="#ffffff")


# ---------------------------------------------------------------- 圆形勾选
def round_check(parent, text: str, variable, command=None):
    """圆形指示器的勾选框（off=暗环, on=冰青实心）。"""
    from PIL import Image, ImageDraw, ImageTk

    def circle_img(fill, outline, width=2):
        img = Image.new("RGBA", (22, 22), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse([2, 2, 19, 19], fill=fill, outline=outline, width=width)
        if fill is not None and fill != (0, 0, 0, 0):
            d.ellipse([7, 7, 14, 14], fill=(255, 255, 255, 200))
        return ImageTk.PhotoImage(img)

    off = circle_img("#0a1626", PANEL_LINE)
    on = circle_img(ICE, ICE)
    cb = tk.Checkbutton(parent, text=text, variable=variable, command=command,
                        image=off, selectimage=on, indicatoron=False,
                        bd=0, relief="flat", bg=BG, activebackground=BG,
                        fg=TEXT, activeforeground=ICE, selectcolor=BG,
                        font=("Microsoft YaHei UI", 10), cursor="hand2")
    cb._imgs = (off, on)
    return cb


# ---------------------------------------------------------------- 标题横幅
class HeaderBanner(tk.Frame):
    """窗内标题横幅：渐变底 + ❖ 钻石 + ❋ 羽饰 + 标题。"""

    def __init__(self, master, title: str, height: int = 44):
        super().__init__(master, bg=BG, height=height)
        self.pack_propagate(False)
        self._title = title
        c = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        c.pack(fill="both", expand=True)
        c.bind("<Configure>", lambda e: self._draw(c))
        self._c = c

    def _draw(self, c: tk.Canvas):
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 10:
            return
        for i in range(h):
            t = i / max(1, h)
            col = blend("#16294a", "#1d3d63", t)
            c.create_line(0, i, w, i, fill=col)
        c.create_line(0, h - 1, w, h - 1, fill=ICE_DEEP, width=2)
        c.create_text(18, h // 2 + 1, text="❖", anchor="w", fill=ICE,
                      font=("Segoe UI Symbol", 13, "bold"))
        c.create_text(38, h // 2 + 1, text="❋", anchor="w", fill=LAV,
                      font=("Segoe UI Symbol", 13))
        c.create_text(60, h // 2 + 1, text=self._title, anchor="w", fill=TEXT,
                      font=("Microsoft YaHei UI", 12, "bold"))
        c.create_text(w - 26, h // 2 + 1, text="◆", anchor="e", fill=ICE_DEEP,
                      font=("Segoe UI Symbol", 9))


# ---------------------------------------------------------------- 图标/日志
def _set_whale_icon(root: tk.Tk):
    from PIL import Image, ImageDraw
    import tempfile
    from pathlib import Path

    size = 128
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((18, 40, 108, 96), fill=(127, 212, 255, 255))
    d.polygon([(100, 58), (124, 40), (116, 64), (126, 86), (100, 76)],
              fill=(127, 212, 255, 255))
    d.ellipse((30, 68, 96, 94), fill=(230, 248, 255, 255))
    d.ellipse((66, 52, 78, 64), fill=(6, 32, 46, 255))
    d.ellipse((70, 54, 75, 59), fill=(255, 255, 255, 255))
    d.ellipse((46, 64, 58, 74), fill=(255, 170, 190, 160))
    d.arc((30, 14, 58, 44), start=180, end=360, fill=(160, 230, 255, 230), width=5)
    p = Path(tempfile.gettempdir()) / "dsh_whale_icon.png"
    img.save(p)
    photo = tk.PhotoImage(file=str(p))
    root.iconphoto(True, photo)
    root._whale_icon = photo


def log_tag_for(msg: str) -> str:
    if "[错误]" in msg or "失败" in msg:
        return "err"
    if "[触发]" in msg or "命中" in msg or ("启动" in msg and "未" not in msg):
        return "ok"
    if "[跳过]" in msg or "[放弃]" in msg or "警告" in msg:
        return "warn"
    return "info"


def configure_log_tags(text: tk.Text):
    text.tag_config("info", foreground="#cfe3ff")
    text.tag_config("ok", foreground=OK)
    text.tag_config("warn", foreground=WARN)
    text.tag_config("err", foreground=ERR)
