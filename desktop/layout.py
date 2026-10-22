"""Window sizing, wrapped rows and scrollable pages for small/high-DPI screens."""
import contextlib
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk

from .scrolling import ScrollViewport


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
    window.initial_layout_size = width, height
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


class CachedPages(ttk.Frame):
    """Keep all real pages prepared, and switch only their stacking order.

    No page textures, native translation, intermediate backdrop or timers. The
    scroll viewports prepare their contents cache only when scrolling is used.
    """
    def __init__(self, parent):
        super().__init__(parent, takefocus=False)
        self.pages = []
        self.selected = 0
        self.focus_command = self.register(self.allow_focus)
        self.scroll_views = {}
        self.scheduler = self.winfo_toplevel()
        self.unmap_binding = self.scheduler.bind("<Unmap>", self.on_unmap, add=True)
        self.bind("<Destroy>", self.on_destroy, add=True)

    def add(self, page, text=None):
        self.pages.append(page)
        page.place(x=0, y=0, relwidth=1, relheight=1)
        self.pages[self.selected].tkraise()

    def prepare(self):
        def walk(widget):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)
        self.scheduler.update_idletasks()
        for index, page in enumerate(self.pages):
            viewports = []
            for widget in walk(page):
                if isinstance(widget, ScrollViewport):
                    widget.prepare()
                    viewports.append(widget)
                if "takefocus" in widget.keys():
                    original = widget.cget("takefocus")
                    if str(original) != "0":
                        widget.configure(takefocus=(self.focus_command, index, original))
            self.scroll_views[index] = viewports

    def on_unmap(self, event):
        if event.widget is self.scheduler:
            for viewports in self.scroll_views.values():
                for view in viewports:
                    view.stop_scroll()

    def on_destroy(self, event):
        if event.widget is self:
            self.scheduler.unbind("<Unmap>", self.unmap_binding)

    def allow_focus(self, index, original, widget):
        if int(index) != self.selected:
            return "0"
        if original in ("", "0", "1"):
            return original
        return self.tk.call(*self.tk.splitlist(original), widget)

    def index(self, page):
        if isinstance(page, int) or str(page).isdigit():
            index = int(page)
        else:
            index = next((i for i, widget in enumerate(self.pages) if str(widget) == str(page)), -1)
        if not 0 <= index < len(self.pages):
            raise tk.TclError(f"Unknown page: {page}")
        return index

    def select(self, page=None):
        if page is None:
            return str(self.pages[self.selected])
        index = self.index(page)
        if index == self.selected:
            return
        previous = self.selected
        for view in self.scroll_views.get(previous, ()):
            view.stop_scroll()
        ancestor = self.focus_get()
        while ancestor is not None and ancestor is not self.pages[previous]:
            ancestor = getattr(ancestor, "master", None)
        self.selected = index
        # Reveal a fully prepared real page before notifying observers. No
        # neutral surface is raised between old and new contents.
        self.pages[index].tkraise()
        self.event_generate("<<NotebookTabChanged>>")
        if ancestor is not None:
            self.focus_set()


class ScrollablePage(ttk.Frame):
    def __init__(self, parent, padding=16):
        super().__init__(parent)
        self.pack(fill="both", expand=True)
        self.rowconfigure(0, weight=1); self.columnconfigure(0, weight=1)
        self.viewport = ScrollViewport(self, padding)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.viewport.yview)
        self.viewport.scrollcommand = self.scrollbar.set
        self.viewport.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.content = self.viewport.content
        self.canvas = self.viewport  # yview compatibility for existing diagnostics.
        self.scheduler = self.winfo_toplevel()
        self.wheel_binding = self.scheduler.bind("<MouseWheel>", self.wheel, add=True)
        self.bind("<Destroy>", self.on_destroy, add=True)

    def on_destroy(self, event):
        if event.widget is self:
            self.scheduler.unbind("<MouseWheel>", self.wheel_binding)

    def wheel(self, event):
        if not event.delta:
            return
        widget = event.widget
        if isinstance(getattr(event, "x_root", None), int) and isinstance(getattr(event, "y_root", None), int):
            # Windows/Tk may deliver WM_MOUSEWHEEL to the focused menu even
            # when the pointer is over page contents. Route by hit testing;
            # otherwise the first wheel after clicking a menu is discarded.
            widget = self.winfo_containing(event.x_root, event.y_root) or widget
        while widget is not None:
            if widget is self:
                self.viewport.wheel(event.delta)
                return "break"
            widget = getattr(widget, "master", None)
