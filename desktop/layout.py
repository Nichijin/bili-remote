"""Window sizing, wrapped rows and scrollable pages for small/high-DPI screens."""
import contextlib
import ctypes
from ctypes import wintypes
import tkinter as tk
import time
from tkinter import ttk

from .rendering import PageCompositor


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


class CachedPages(ttk.Frame):
    """Keep each page laid out behind the current page; only change its z-order.

    Unmapping a Notebook page recursively remapped every Windows child control
    on return. Keeping pages mapped avoids that work and retains scroll state.
    Windows retains complete page surfaces. All pages follow the window size
    before navigation, and transitions change only opacity, never layout/input.
    Only the active page participates in keyboard traversal.
    """
    def __init__(self, parent):
        super().__init__(parent, takefocus=False)
        self.pages = []
        self.selected = 0
        self.focus_command = self.register(self.allow_focus)
        self.page_sizes = {}
        self.current_size = None
        scale = max(.75, float(self.tk.call("tk", "scaling")) / (96 / 72))
        self.max_page_width = round(640 * scale)
        self.compact_page_width = round(360 * scale)
        self.compositor = None
        self.transition_timer = None
        self.transition_page = None
        self.layout_timer = None
        self.scheduler = self.winfo_toplevel()
        # An opaque neutral background prevents the old page showing through
        # the new one's short fade. It never covers the active live controls.
        self.backdrop = ttk.Frame(self, takefocus=False)
        self.backdrop.place(x=0, y=0, relwidth=1, relheight=1)
        self.bind("<Configure>", self.resize)
        self.bind("<Destroy>", self.on_destroy, add=True)
        self.unmap_binding = self.scheduler.bind("<Unmap>", self.on_unmap, add=True)

    def add(self, page, text=None):
        self.pages.append(page)
        page.place(x=0, y=0, width=1, height=1)
        self.pages[self.selected].tkraise()

    def size_page(self, index, size):
        if self.page_sizes.get(index) != size:
            self.page_sizes[index] = size
            self.pages[index].place_configure(width=size[0], height=size[1])

    def resize(self, event):
        # Stable desktop/compact reading widths: dragging one more pixel must
        # not remeasure and wrap every label in every page. Only cross-layout
        # changes and unusually narrow accessibility layouts need reflow.
        width = self.max_page_width if event.width >= self.max_page_width else min(event.width, self.compact_page_width)
        size = max(1, width), max(1, event.height)
        offset = max(0, (event.width - size[0]) // 2)
        if offset != getattr(self, "page_offset", None):
            self.page_offset = offset
            for page in self.pages:
                page.place_configure(x=offset)
        if size == self.current_size:
            return
        self.finish_transition()
        if self.compositor:
            self.compositor.pause_layout()
        self.current_size = size
        for index in range(len(self.pages)):
            self.size_page(index, size)
        if self.layout_timer is not None:
            self.scheduler.after_cancel(self.layout_timer)
        self.layout_timer = self.scheduler.after_idle(self.finish_layout)

    def finish_layout(self):
        if self.layout_timer is not None:
            self.scheduler.after_cancel(self.layout_timer)
            self.layout_timer = None
        if self.compositor:
            self.compositor.resume_layout()

    def prepare(self):
        def walk(widget):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)
        for index, page in enumerate(self.pages):
            for widget in walk(page):
                if "takefocus" in widget.keys():
                    original = widget.cget("takefocus")
                    if str(original) != "0":
                        widget.configure(takefocus=(self.focus_command, index, original))
        self.compositor = PageCompositor(self.pages)

    def finish_transition(self):
        if self.transition_timer is not None:
            self.scheduler.after_cancel(self.transition_timer)
            self.transition_timer = None
        if self.transition_page is not None:
            self.compositor.opacity(self.transition_page, 255)
            self.transition_page = None

    def transition(self, page):
        if not self.compositor or not self.compositor.animate or not self.winfo_ismapped():
            return
        self.transition_page = page
        self.transition_started = time.perf_counter()
        self.animate_frame()

    def animate_frame(self):
        self.transition_timer = None
        elapsed = (time.perf_counter() - self.transition_started) / .14
        if elapsed >= 1:
            self.finish_transition()
            return
        # Ease out, starting at 90% opacity: the entire page is already usable.
        alpha = round(230 + 25 * (1 - (1 - elapsed) ** 3))
        if not self.compositor.opacity(self.transition_page, alpha):
            self.finish_transition()
            return
        self.transition_timer = self.scheduler.after(16, self.animate_frame)

    def on_unmap(self, event):
        if event.widget is self.scheduler:
            self.finish_transition()
            self.finish_layout()

    def on_destroy(self, event):
        if event.widget is self:
            self.finish_transition()
            self.finish_layout()
            if self.compositor:
                self.compositor.close()
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
        self.finish_transition()
        self.finish_layout()
        previous = self.selected
        focused = self.focus_get()
        ancestor = focused
        while ancestor is not None and ancestor is not self.pages[previous]:
            ancestor = getattr(ancestor, "master", None)
        self.selected = index
        self.backdrop.tkraise()
        self.transition(self.pages[index])
        self.pages[index].tkraise()
        if ancestor is not None:
            self.focus_set()
        self.event_generate("<<NotebookTabChanged>>")


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
        self.content_width = self.scroll_region = None
        self.max_content_width = round(652 * max(.75, float(self.tk.call("tk", "scaling")) / (96 / 72)))
        self.canvas.bind("<Configure>", self.resize)
        self.content.bind("<Configure>", self.update_scroll_region)
        self.winfo_toplevel().bind("<MouseWheel>", self.wheel, add=True)
        self.canvas.bind("<Next>", lambda event: self.canvas.yview_scroll(1, "pages"))
        self.canvas.bind("<Prior>", lambda event: self.canvas.yview_scroll(-1, "pages"))

    def resize(self, event):
        width = max(1, min(event.width, self.max_content_width))
        # A stable leading edge avoids moving every descendant HWND on each
        # pixel of a window drag. Extra desktop space stays as a quiet margin.
        if width != self.content_width:
            self.content_width = width
            self.canvas.itemconfigure(self.item, width=width)

    def update_scroll_region(self, event=None):
        region = self.canvas.bbox("all")
        if region != self.scroll_region:
            self.scroll_region = region
            self.canvas.configure(scrollregion=region)

    def wheel(self, event):
        if not event.delta:
            return
        widget = event.widget
        while widget is not None:
            if widget is self:
                self.canvas.yview_scroll(-max(1, abs(event.delta) // 120) * (1 if event.delta > 0 else -1) * 3, "units")
                return "break"
            widget = getattr(widget, "master", None)
