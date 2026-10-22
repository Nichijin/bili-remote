"""Focusable menu items with an immediate rounded selection background."""
import tkinter as tk
from .appearance import SIDEBAR, _rounded_image


class NavigationButton(tk.Canvas):
    """A real keyboard/mouse target; the moving background is drawn underneath."""
    def __init__(self, parent, text, icons, command, scale, family):
        super().__init__(parent, background=SIDEBAR, width=round(180*scale), height=round(50*scale),
                         borderwidth=0, highlightthickness=0, takefocus=True)
        self.command, self.scale, self.icons = command, scale, icons
        self.compact = self.selected = self.pressed = self.pointer_focus = False
        self.family = family
        self.selection = None
        self.indicator = self.create_image(0, -10000, anchor="nw")
        self.icon_item = self.create_image(round(13*scale), round(25*scale), image=icons[0], anchor="w")
        self.label_item = self.create_text(round(41*scale), round(25*scale), text=text, anchor="w",
                                           font=(family, 10), fill="#535D6F")
        self.focus_item = self.create_line(0, 0, 0, 0, fill="#007AFF", width=max(1, round(1.5*scale)),
                                           smooth=True, splinesteps=20, state="hidden")
        self.bind("<Configure>", self.resize)
        self.bind("<ButtonPress-1>", self.press)
        self.bind("<ButtonRelease-1>", self.release)
        self.bind("<Return>", lambda event: self.invoke())
        self.bind("<space>", lambda event: self.invoke())
        self.bind("<FocusIn>", self.focus_in)
        self.bind("<FocusOut>", self.focus_out)

    def focus_in(self, event):
        self.itemconfigure(self.focus_item, state="hidden" if self.pointer_focus else "normal")

    def focus_out(self, event):
        self.pointer_focus = False
        self.itemconfigure(self.focus_item, state="hidden")

    def press(self, event):
        self.pointer_focus = True
        self.itemconfigure(self.focus_item, state="hidden")
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
        self.itemconfigure(self.label_item, font=(self.family, 10, "bold" if selected else "normal"))

    def resize(self, event=None):
        width, height = self.winfo_width(), self.winfo_height()
        self.coords(self.icon_item, width//2 if self.compact else round(13*self.scale), height//2)
        self.itemconfigure(self.icon_item, anchor="center" if self.compact else "w")
        self.coords(self.label_item, round(41*self.scale), height//2)
        inset, radius = round(2*self.scale), round(9*self.scale)
        left, top, right, bottom = inset, round(3*self.scale), max(inset+2, width-inset), max(inset+2, height-round(3*self.scale))
        radius = min(radius, (right-left)/2, (bottom-top)/2)
        self.coords(self.focus_item, left+radius, top, right-radius, top, right, top,
                    right, top+radius, right, bottom-radius, right, bottom,
                    right-radius, bottom, left+radius, bottom, left, bottom,
                    left, bottom-radius, left, top+radius, left, top, left+radius, top)
        if self.selection:
            self.selection.resize()


class NavigationSelection:
    """Share one small rounded image; selection changes do not animate."""
    def __init__(self, buttons, scale):
        self.buttons, self.scale = buttons, scale
        self.current = None
        self.closed = False
        self.y = self.target_y = None
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
            self.asset = _rounded_image(button, size, round(9*self.scale), "#FFFFFF", border="#D5DBE4", background=SIDEBAR)
            for item in self.buttons:
                item.itemconfigure(item.indicator, image=self.asset)
        if self.target_y != self.target():
            self.y = self.target_y = self.target()
        self.draw()

    def select(self, index):
        self.current = index
        self.target_y = self.target()
        self.resize()
        self.y = self.target_y
        self.draw()

    def draw(self):
        if self.y is not None and not self.closed:
            for button in self.buttons:
                button.coords(button.indicator, 0, round(self.y-button.winfo_y()))
