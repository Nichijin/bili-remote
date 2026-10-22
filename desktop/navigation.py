"""Focusable menu items sharing one smoothly translated selection surface."""
import tkinter as tk
from .appearance import SIDEBAR, _rounded_image


class NavigationButton(tk.Canvas):
    """A real keyboard/mouse target; the moving background is drawn underneath."""
    def __init__(self, parent, text, icons, command, scale, family):
        super().__init__(parent, background=SIDEBAR, width=round(180*scale), height=round(50*scale),
                         borderwidth=0, highlightthickness=0, takefocus=True)
        self.command, self.scale, self.icons = command, scale, icons
        self.compact = self.selected = self.pressed = False
        self.selection = None
        self.indicator = self.create_image(0, -10000, anchor="nw")
        self.icon_item = self.create_image(round(13*scale), round(25*scale), image=icons[0], anchor="w")
        self.label_item = self.create_text(round(41*scale), round(25*scale), text=text, anchor="w",
                                           font=(family, 10), fill="#535D6F")
        self.focus_item = self.create_rectangle(2, 2, 2, 2, outline="#007AFF", dash=(2, 2), state="hidden")
        self.bind("<Configure>", self.resize)
        self.bind("<ButtonPress-1>", self.press)
        self.bind("<ButtonRelease-1>", self.release)
        self.bind("<Return>", lambda event: self.invoke())
        self.bind("<space>", lambda event: self.invoke())
        self.bind("<FocusIn>", lambda event: self.itemconfigure(self.focus_item, state="normal"))
        self.bind("<FocusOut>", lambda event: self.itemconfigure(self.focus_item, state="hidden"))

    def press(self, event):
        self.focus_set()
        self.pressed = True

    def release(self, event):
        if self.pressed and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.invoke()
        self.pressed = False

    def invoke(self):
        self.command()

    def set_compact(self, compact):
        self.compact = compact
        self.itemconfigure(self.label_item, state="hidden" if compact else "normal")
        self.resize()

    def set_selected(self, selected):
        self.selected = selected
        self.itemconfigure(self.icon_item, image=self.icons[int(selected)])
        self.itemconfigure(self.label_item, fill="#0065D5" if selected else "#535D6F")

    def resize(self, event=None):
        width, height = self.winfo_width(), self.winfo_height()
        self.coords(self.icon_item, width//2 if self.compact else round(13*self.scale), height//2)
        self.itemconfigure(self.icon_item, anchor="center" if self.compact else "w")
        self.coords(self.label_item, round(41*self.scale), height//2)
        self.coords(self.focus_item, 2, round(3*self.scale), max(3, width-2), max(4, height-round(3*self.scale)))
        if self.selection:
            self.selection.resize()


class NavigationSelection:
    """Reuse a single rounded image across rows; every frame only moves items.

    CachedPages drives progress, so the highlight and content share one timer.
    Each Canvas clips its part of the same moving pill. Text remains fixed.
    """
    def __init__(self, buttons, scale):
        self.buttons, self.scale = buttons, scale
        self.current = None
        self.closed = False
        self.y = self.start_y = self.target_y = None
        self.asset = self.asset_size = None
        for button in buttons:
            button.selection = self
            button.bind("<Destroy>", lambda event: setattr(self, "closed", True), add=True)

    def target(self):
        button = self.buttons[self.current]
        return button.winfo_y() + round(3*self.scale)

    def resize(self):
        if self.current is None or self.closed:
            return
        button = self.buttons[self.current]
        size = max(1, button.winfo_width()), max(1, button.winfo_height()-round(6*self.scale))
        if size != self.asset_size:
            self.asset_size = size
            self.asset = _rounded_image(button, size, round(9*self.scale), "#DFEAFA", background=SIDEBAR)
            for item in self.buttons:
                item.itemconfigure(item.indicator, image=self.asset)
        if self.target_y != self.target():
            self.y = self.start_y = self.target_y = self.target()
        self.draw()

    def select(self, index, animate):
        self.current = index
        self.start_y = self.y if self.y is not None else self.target()
        self.target_y = self.target()
        self.resize()
        self.y = self.start_y if animate else self.target_y
        self.draw()

    def progress(self, fraction):
        if self.current is not None and not self.closed:
            self.y = self.start_y + (self.target_y-self.start_y)*fraction
            self.draw()

    def draw(self):
        if self.y is not None and not self.closed:
            for button in self.buttons:
                button.coords(button.indicator, 0, round(self.y-button.winfo_y()))
