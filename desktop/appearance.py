"""Small, local Tk assets and a quiet desktop theme; no web engine or animation."""
import math
import tkinter as tk
from tkinter import font, ttk

BG = "#F7F8FA"
SIDEBAR = "#EFF1F5"
SURFACE = "#FFFFFF"
TEXT = "#20242D"
MUTED = "#707784"
LINE = "#E4E7ED"
BLUE = "#007AFF"


def _rounded_image(master, size, radius, fill, border=None, knob=False):
    """Render a tiny stretchable ttk element using Tk only."""
    width, height = size
    image = tk.PhotoImage(master=master, width=width, height=height)
    for y in range(height):
        dy = max(radius - y - .5, y + .5 - (height - radius), 0)
        inset = max(0, math.ceil(radius - math.sqrt(max(0, radius * radius - dy * dy)) - .5))
        if width > 2 * inset:
            image.put(border or fill, to=(inset, y, width - inset, y + 1))
            if border and 0 < y < height - 1 and width - 2 * inset > 2:
                image.put(fill, to=(inset + 1, y, width - inset - 1, y + 1))
    if knob:
        diameter = height - 6
        left = width - height + 3 if knob == "on" else 3
        for y in range(diameter):
            dy = y + .5 - diameter / 2
            inset = math.ceil(diameter / 2 - math.sqrt(max(0, (diameter / 2) ** 2 - dy * dy)) - .5)
            image.put("#FFFFFF", to=(left + inset, y + 3, left + diameter - inset, y + 4))
    return image


def apply_theme(window, scale):
    style = ttk.Style(window)
    style.theme_use("clam")
    families = font.families(window)
    family = "Microsoft YaHei UI" if "Microsoft YaHei UI" in families else "Segoe UI"
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkTooltipFont"):
        font.nametofont(name).configure(family=family, size=10)
    window.configure(background=BG)
    style.configure(".", font=(family, 10), background=BG, foreground=TEXT)
    for name, color in (("TFrame", BG), ("Surface.TFrame", SURFACE), ("Sidebar.TFrame", SIDEBAR)):
        style.configure(name, background=color)
    for prefix, color in (("", BG), ("Surface.", SURFACE), ("Sidebar.", SIDEBAR)):
        style.configure(prefix + "TLabel", background=color, foreground=TEXT)
        style.configure(prefix + "Muted.TLabel", background=color, foreground=MUTED)
    style.configure("Title.TLabel", font=(family, 24, "bold"), foreground=TEXT)
    style.configure("Eyebrow.TLabel", font=("Segoe UI", 9, "bold"), foreground=BLUE)
    style.configure("Surface.Heading.TLabel", background=SURFACE, font=(family, 12, "bold"))
    style.configure("Surface.Pin.TLabel", background=SURFACE, foreground=TEXT, font=("Consolas", 35, "bold"))
    style.configure("Sidebar.Brand.TLabel", background=SIDEBAR, font=("Segoe UI", 13, "bold"))
    style.configure("Sidebar.Caption.TLabel", background=SIDEBAR, foreground=MUTED, font=(family, 9))
    style.configure("Pages.TNotebook", background=BG, borderwidth=0, tabmargins=0)
    style.layout("Pages.TNotebook.Tab", [])
    # Keep image references alive for this interpreter. The total pixel count is small.
    window.theme_images = []
    edge = max(6, round(8 * scale))
    for name, normal, hover, pressed, fg, border in (
        ("TButton", SURFACE, "#F0F4FA", "#E5EBF4", TEXT, LINE),
        ("Primary.TButton", BLUE, "#1685FF", "#0064DA", "#FFFFFF", BLUE),
        ("Quiet.TButton", BG, "#E9EDF3", "#DEE5EF", MUTED, BG),
        ("Nav.TButton", SIDEBAR, "#E3E7EE", "#D8E6F8", "#535D6F", SIDEBAR),
        ("Selected.Nav.TButton", "#DFEAFA", "#D5E5FB", "#C8DDF9", "#0065D5", "#DFEAFA"),
        ("Danger.TButton", SURFACE, "#FFF0F0", "#FFE0E0", "#C23B45", LINE),
    ):
        images = [_rounded_image(window, (edge * 2 + 2, edge * 2 + 2), edge, c, border if c == normal else c)
                  for c in (normal, hover, pressed, "#ECEEF2")]
        window.theme_images.extend(images)
        element = name + ".surface"
        style.element_create(element, "image", images[0], ("disabled", images[3]),
                             ("pressed", images[2]), ("active", images[1]), border=edge, padding=0, sticky="nsew")
        style.layout(name, [(element, {"sticky": "nsew", "children": [
            ("Button.focus", {"sticky": "nsew", "children": [("Button.padding", {"sticky": "nsew", "children": [
                ("Button.label", {"sticky": "nsew"})]})]})]})])
        background = SIDEBAR if "Nav." in name else SURFACE if name in {"Primary.TButton", "Danger.TButton"} else BG
        style.configure(name, foreground=fg, background=background, padding=(round(14 * scale), round(9 * scale)),
                        width=0, borderwidth=0, anchor="center", focusthickness=1, focuscolor=BLUE)
        style.map(name, foreground=[("disabled", "#9B9FAB")])
    for name in ("Nav.TButton", "Selected.Nav.TButton"):
        style.configure(name, anchor="w", padding=(round(13 * scale), round(11 * scale)))
    switch_size = round(38 * scale), round(22 * scale)
    switch_images = [_rounded_image(window, switch_size, switch_size[1] / 2, color, knob=knob)
                     for color, knob in (("#C4CAD4", "off"), (BLUE, "on"), ("#A4B5CC", "on"), ("#D8DCE3", "off"))]
    window.theme_images.extend(switch_images)
    style.element_create("Switch.indicator", "image", switch_images[0],
                         ("disabled", "selected", switch_images[2]), ("disabled", switch_images[3]),
                         ("selected", switch_images[1]), sticky="")
    style.layout("Switch.TCheckbutton", [("Checkbutton.focus", {"children": [("Switch.indicator", {"sticky": ""})]})])
    style.configure("Switch.TCheckbutton", background=SURFACE, focuscolor=BLUE, focusthickness=1)
    style.configure("TEntry", fieldbackground=SURFACE, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE,
                    padding=round(7 * scale), insertcolor=TEXT)
    for name in ("TCombobox", "TSpinbox"):
        style.configure(name, fieldbackground=SURFACE, background=SURFACE, bordercolor=LINE,
                        lightcolor=LINE, darkcolor=LINE, arrowcolor=MUTED, padding=round(6 * scale))
        style.map(name, fieldbackground=[("readonly", SURFACE)], bordercolor=[("focus", BLUE)])
    style.configure("Horizontal.TScale", background=SURFACE, troughcolor="#E8EDF4", borderwidth=0,
                    sliderwidth=round(14 * scale), sliderlength=round(18 * scale))
    track = _rounded_image(window, (12, max(4, round(4 * scale))), 2, "#E5EAF1")
    thumb_size = round(19 * scale)
    thumb = _rounded_image(window, (thumb_size, thumb_size), thumb_size / 2, SURFACE, "#9FAEC4")
    disabled_thumb = _rounded_image(window, (thumb_size, thumb_size), thumb_size / 2, "#F3F4F6", "#D8DCE3")
    window.theme_images.extend((track, thumb, disabled_thumb))
    style.element_create("Soft.Horizontal.Scale.trough", "image", track, border=2, padding=0, sticky="we")
    style.element_create("Soft.Horizontal.Scale.slider", "image", thumb, ("disabled", disabled_thumb), padding=0)
    style.layout("Horizontal.TScale", [("Soft.Horizontal.Scale.trough", {"sticky": "we", "children": [
        ("Soft.Horizontal.Scale.slider", {"side": "left", "sticky": ""})]})])
    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, borderwidth=0,
                    rowheight=round(40 * scale), font=(family, 10))
    style.map("Treeview", background=[("selected", "#E1EDFF")], foreground=[("selected", "#0062C9")])
    style.configure("Treeview.Heading", font=(family, 9), foreground=MUTED, background="#F5F7FA",
                    relief="flat", padding=(round(10 * scale), round(11 * scale)))
    style.configure("TScrollbar", background="#CAD0DA", troughcolor=BG, borderwidth=0,
                    arrowsize=round(11 * scale), lightcolor=BG, darkcolor=BG, bordercolor=BG)
    for direction in ("Vertical", "Horizontal"):
        vertical = direction == "Vertical"
        size = (max(6, round(6 * scale)), 12) if vertical else (12, max(6, round(6 * scale)))
        image = _rounded_image(window, size, 3, "#C7CDD7")
        window.theme_images.append(image)
        name = f"Soft.{direction}.Scrollbar.thumb"
        style.element_create(name, "image", image, border=3, padding=0, sticky="ns" if vertical else "we")
        style.layout(f"{direction}.TScrollbar", [(f"{direction}.Scrollbar.trough", {"sticky": "ns" if vertical else "we", "children": [
            (name, {"sticky": "nsew"})]})])
    return family


def rounded_rect(canvas, x1, y1, x2, y2, radius, **options):
    radius = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
    return canvas.create_polygon(x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
                                 x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
                                 x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
                                 smooth=True, splinesteps=24, **options)


class Card(ttk.Frame):
    def __init__(self, parent, scale=1, padding=22, stretch=False):
        super().__init__(parent)
        self.inset = round(padding * scale)
        self.radius = round(16 * scale)
        self.stretch = stretch
        self.canvas = tk.Canvas(self, background=BG, highlightthickness=0, borderwidth=0, height=1)
        self.canvas.pack(fill="both", expand=True)
        self.content = ttk.Frame(self.canvas, style="Surface.TFrame")
        self.item = self.canvas.create_window(self.inset, self.inset, anchor="nw", window=self.content)
        self.canvas.bind("<Configure>", self.resize)
        self.content.bind("<Configure>", self.resize)

    def resize(self, event=None):
        width = max(1, self.canvas.winfo_width())
        options = {"width": max(1, width - self.inset * 2)}
        if self.stretch:
            options["height"] = max(1, self.canvas.winfo_height() - self.inset * 2)
        else:
            height = self.content.winfo_reqheight() + self.inset * 2
            if int(self.canvas.cget("height")) != height:
                self.canvas.configure(height=height)
        changed = {key: value for key, value in options.items() if round(float(self.canvas.itemcget(self.item, key))) != value}
        if changed:
            self.canvas.itemconfigure(self.item, **changed)
        self.canvas.delete("outline")
        height = max(1, self.canvas.winfo_height())
        rounded_rect(self.canvas, 1, 1, max(2, width - 1), max(2, height - 2), self.radius,
                     fill=SURFACE, outline=LINE, width=1, tags="outline")
        self.canvas.tag_lower("outline")


class Columns(ttk.Frame):
    """Two sections that stack when the window has less available space."""
    def __init__(self, parent, scale=1):
        super().__init__(parent, style="Surface.TFrame")
        self.scale, self.wide = scale, None
        self.left = ttk.Frame(self, style="Surface.TFrame")
        self.right = ttk.Frame(self, style="Surface.TFrame")
        self.columnconfigure(0, weight=1, uniform="sections")
        self.columnconfigure(1, weight=1, uniform="sections")
        self.bind("<Configure>", self.reflow)

    def reflow(self, event):
        wide = event.width >= round(660 * self.scale)
        if self.wide == wide:
            return
        self.wide = wide
        self.left.grid(row=0, column=0, columnspan=1 if wide else 2, sticky="nsew", padx=(0, round(18 * self.scale) if wide else 0))
        self.right.grid(row=0 if wide else 1, column=1 if wide else 0, columnspan=1 if wide else 2,
                        sticky="nsew", padx=(round(18 * self.scale) if wide else 0, 0), pady=(0 if wide else round(22 * self.scale), 0))


def preference_row(parent, text, description, variable, command, scale=1):
    row = ttk.Frame(parent, style="Surface.TFrame")
    row.pack(fill="x", pady=round(10 * scale))
    row.columnconfigure(0, weight=1)
    from .layout import wrapped_label
    title = wrapped_label(row, text=text, style="Surface.TLabel", wrap_inset=round(64 * scale))
    title.grid(row=0, column=0, sticky="w")
    detail = wrapped_label(row, text=description, style="Surface.Muted.TLabel", wrap_inset=round(64 * scale))
    detail.grid(row=1, column=0, sticky="ew", pady=(round(3 * scale), 0))
    switch = ttk.Checkbutton(row, text=text, variable=variable, command=command, style="Switch.TCheckbutton", takefocus=True)
    switch.grid(row=0, column=1, rowspan=2, padx=(round(16 * scale), 0))
    for label in (title, detail):
        label.bind("<Button-1>", lambda event: switch.invoke())
    return switch


def line_icon(master, kind, size=20, color=MUTED):
    """Original line drawings for navigation; no bundled third-party icon font."""
    image = tk.PhotoImage(master=master, width=size, height=size)
    # Rasterize at logical 20 px, then scale. A few hundred pixels per icon.
    segments = {
        "remote": [(4, 3, 16, 3), (16, 3, 16, 17), (16, 17, 4, 17), (4, 17, 4, 3),
                   (7, 7, 13, 7), (7, 10, 13, 10), (9, 14, 11, 14)],
        "devices": [(2, 3, 16, 3), (16, 3, 16, 13), (16, 13, 2, 13), (2, 13, 2, 3),
                    (7, 13, 7, 17), (4, 17, 10, 17), (13, 9, 18, 9), (18, 9, 18, 18),
                    (18, 18, 13, 18), (13, 18, 13, 9)],
        "history": [(5, 3, 15, 3), (15, 3, 15, 17), (15, 17, 5, 17), (5, 17, 5, 3),
                    (8, 7, 12, 7), (8, 10, 12, 10), (8, 13, 11, 13)],
        "settings": [(3, 5, 17, 5), (3, 10, 17, 10), (3, 15, 17, 15),
                     (7, 3, 7, 7), (13, 8, 13, 12), (8, 13, 8, 17)],
        "help": [(7, 6, 8, 4), (8, 4, 12, 4), (12, 4, 14, 6), (14, 6, 14, 8),
                 (14, 8, 10, 11), (10, 11, 10, 12), (10, 15, 10, 16)],
    }
    width = max(1, round(size / 14))
    for x1, y1, x2, y2 in segments[kind]:
        steps = max(abs(x2 - x1), abs(y2 - y1)) * size
        for i in range(steps + 1):
            x = round((x1 + (x2 - x1) * i / max(1, steps)) * (size - 1) / 20)
            y = round((y1 + (y2 - y1) * i / max(1, steps)) * (size - 1) / 20)
            image.put(color, to=(x, y, min(size, x + width), min(size, y + width)))
    return image


def tooltip(widget, text):
    """A transient label for compact navigation, created only on hover/focus."""
    state = {"timer": None, "window": None}
    def hide(event=None):
        if state["timer"]:
            widget.after_cancel(state["timer"])
            state["timer"] = None
        if state["window"]:
            state["window"].destroy()
            state["window"] = None
    def show():
        state["timer"] = None
        if not widget.winfo_ismapped():
            return
        popup = tk.Toplevel(widget)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        tk.Label(popup, text=text, background="#29313E", foreground="white", padx=10, pady=6,
                 font="TkDefaultFont", borderwidth=0).pack()
        popup.geometry(f"+{widget.winfo_rootx() + widget.winfo_width() + 7}+{widget.winfo_rooty() + 3}")
        popup.deiconify()
        state["window"] = popup
    def schedule(event=None):
        hide()
        state["timer"] = widget.after(600, show)
    for event in ("<Enter>", "<FocusIn>"):
        widget.bind(event, schedule, add=True)
    for event in ("<Leave>", "<FocusOut>", "<ButtonPress>", "<Unmap>"):
        widget.bind(event, hide, add=True)
