"""A live, keyboard-accessible miniature work area for subtitle positioning."""
import tkinter as tk
from tkinter import ttk
from .feedback import normalize_style, overlay_geometry, overlay_position
from .layout import wrapped_label


class SubtitlePreview(ttk.Frame):
    def __init__(self, parent, scale, on_drag):
        super().__init__(parent, style="Surface.TFrame")
        self.scale, self.on_drag = scale, on_drag
        self.style = normalize_style(None)
        self.enabled = True
        self.offset = None
        self.surface = tk.Frame(self, background="#E9EDF4", height=round(192 * scale), takefocus=True)
        self.surface.pack(fill="x")
        self.surface.pack_propagate(False)
        self.surface.configure(highlightthickness=1, highlightbackground="#DCE1EA", highlightcolor="#007AFF")
        self.hint = tk.Label(self.surface, text="预览工作区", bg="#E9EDF4", fg="#626975", font=("Microsoft YaHei UI", 9))
        self.hint.place(relx=.5, rely=.32, anchor="center")
        self.caption = tk.Label(self.surface, text="临时 2 倍速", bg="#191D2B", fg="white", padx=12, pady=7, cursor="fleur")
        self.caption.place(x=0, y=0)
        self.surface.bind("<Configure>", self.position)
        self.caption.bind("<ButtonPress-1>", self.begin_drag)
        self.caption.bind("<B1-Motion>", self.drag)
        self.caption.bind("<ButtonRelease-1>", self.end_drag)
        for key, dx, dy in (("Left", -1, 0), ("Right", 1, 0), ("Up", 0, -1), ("Down", 0, 1)):
            self.surface.bind(f"<{key}>", lambda event, dx=dx, dy=dy: self.nudge(dx, dy))
        wrapped_label(self, text="拖动字幕调整位置 · 方向键微调 · 自动保存", style="Surface.Muted.TLabel").pack(fill="x", pady=(round(8 * scale), 0))

    def set_style(self, style, enabled=True):
        self.style, self.enabled = normalize_style(style), enabled
        if not enabled:
            self.end_drag()
        bg = "#191D2B"
        def blend(color):
            opacity = self.style["opacity"] / 100 if enabled else .35
            return "#" + "".join(f"{round(int(color[i:i+2],16)*opacity+int('E9EDF4'[i:i+2],16)*(1-opacity)):02x}" for i in (0,2,4))
        self.caption.configure(fg=blend(self.style["color"][1:]), bg=blend(bg[1:]),
                               font=("Microsoft YaHei UI", -round(max(11, min(23, self.style["font_size"] * .75)) * self.scale)),
                               cursor="fleur" if enabled else "arrow")
        self.position()

    def position(self, event=None):
        width, height = max(1, self.surface.winfo_width()), max(1, self.surface.winfo_height())
        box = self.caption.winfo_reqwidth(), self.caption.winfo_reqheight()
        w, h, x, y = overlay_geometry((8, 8, max(9, width-8), max(9, height-8)), box, self.style["x"], self.style["y"])
        self.caption.place(x=x, y=y, width=w, height=h)

    def begin_drag(self, event):
        if self.enabled:
            self.surface.focus_set()
            self.offset = event.x, event.y
            self.caption.grab_set()

    def drag(self, event):
        if self.offset is not None and self.enabled:
            area = 8, 8, self.surface.winfo_width()-8, self.surface.winfo_height()-8
            x, y = overlay_position(area, (self.caption.winfo_reqwidth(), self.caption.winfo_reqheight()),
                                    event.x_root-self.surface.winfo_rootx()-self.offset[0],
                                    event.y_root-self.surface.winfo_rooty()-self.offset[1])
            self.on_drag(x, y)

    def end_drag(self, event=None):
        self.offset = None
        if self.caption.grab_current() is self.caption:
            self.caption.grab_release()

    def nudge(self, dx, dy):
        if self.enabled:
            self.on_drag(max(0, min(100, self.style["x"]+dx)), max(0, min(100, self.style["y"]+dy)))
        return "break"
