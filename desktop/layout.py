"""Window sizing, wrapped rows and scrollable pages for small/high-DPI screens."""
import contextlib
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk


def enable_dpi_awareness():
    with contextlib.suppress(AttributeError, OSError):
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    with contextlib.suppress(AttributeError, OSError):
        ctypes.windll.shcore.SetProcessDpiAwareness(2)


def fit_window(window):
    scale = max(.75, min(3, float(window.tk.call("tk", "scaling")) / (96 / 72)))
    rect = wintypes.RECT(0, 0, window.winfo_screenwidth(), window.winfo_screenheight())
    with contextlib.suppress(AttributeError, OSError):
        ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0)
    available_width = max(240, rect.right - rect.left - round(32 * scale))
    available_height = max(200, rect.bottom - rect.top - round(48 * scale))
    width, height = min(round(1040 * scale), available_width), min(round(780 * scale), available_height)
    window.geometry(f"{width}x{height}+{rect.left + max(0, (rect.right - rect.left - width) // 2)}+{rect.top + max(0, (rect.bottom - rect.top - height) // 2)}")
    window.minsize(min(round(440 * scale), available_width), min(round(300 * scale), available_height))
    return scale


def wrapped_label(parent, **options):
    options.pop("wraplength", None)
    inset = options.pop("wrap_inset", 12)
    label = ttk.Label(parent, wraplength=300, **options)
    def resize(event):
        width = max(60, event.width - inset)
        if int(label.cget("wraplength")) != width:
            label.configure(wraplength=width)
    parent.bind("<Configure>", resize, add=True)
    return label


def check_option(parent, text, variable, command):
    row = ttk.Frame(parent)
    row.pack(fill="x", pady=9)
    checkbox = ttk.Checkbutton(row, variable=variable, command=command)
    checkbox.pack(side="left", anchor="n", pady=2)
    label = wrapped_label(row, text=text, wrap_inset=45)
    label.pack(side="left", fill="x", expand=True, padx=(5, 0))
    label.bind("<Button-1>", lambda event: checkbox.invoke())
    return checkbox


class FlowRow(ttk.Frame):
    def __init__(self, parent, **options):
        super().__init__(parent, **options)
        self.items, self.positions = [], None
        self.bind("<Configure>", lambda event: self.reflow())

    def add(self, widget):
        self.items.append(widget)
        widget.bind("<Configure>", lambda event: self.reflow(), add=True)
        self.after_idle(self.reflow)
        return widget

    def reflow(self):
        width = max(1, self.winfo_width())
        row = column = used = 0
        positions = []
        for widget in self.items:
            needed = widget.winfo_reqwidth() + 12
            if used and used + needed > width:
                row += 1; column = used = 0
            positions.append((row, column))
            column += 1; used += needed
        if positions == self.positions:
            return
        self.positions = positions
        for widget, (row, column) in zip(self.items, positions):
            widget.grid(row=row, column=column, sticky="w", padx=(0, 8), pady=4)


class ScrollablePage(ttk.Frame):
    def __init__(self, parent, padding=16):
        super().__init__(parent)
        self.pack(fill="both", expand=True)
        self.rowconfigure(0, weight=1); self.columnconfigure(0, weight=1)
        color = ttk.Style(self).lookup("TFrame", "background") or "#f0f0f0"
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, background=color, takefocus=True)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.content = ttk.Frame(self.canvas, padding=padding)
        self.item = self.canvas.create_window(0, 0, anchor="nw", window=self.content)
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.item, width=max(1, event.width)))
        self.content.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.winfo_toplevel().bind("<MouseWheel>", self.wheel, add=True)
        self.canvas.bind("<Next>", lambda event: self.canvas.yview_scroll(1, "pages"))
        self.canvas.bind("<Prior>", lambda event: self.canvas.yview_scroll(-1, "pages"))

    def wheel(self, event):
        if not event.delta:
            return
        widget = event.widget
        while widget is not None:
            if widget is self:
                self.canvas.yview_scroll(-max(1, abs(event.delta) // 120) * (1 if event.delta > 0 else -1) * 3, "units")
                return "break"
            widget = getattr(widget, "master", None)
