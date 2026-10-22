"""Clipped live contents with optional scroll caches and coalesced wheel input.

Like QScrollArea, move one contents widget inside a viewport. A Canvas containing
native child windows mixes pixel scrolling and child-window painting. Here the
OS clips a retained contents surface; scrolling does not resize or copy controls.
"""
import contextlib
import math
from ctypes import byref, wintypes
import time
import tkinter as tk
from tkinter import ttk

from .rendering import PageCompositor


class ScrollViewport(ttk.Frame):
    def __init__(self, parent, padding):
        super().__init__(parent, takefocus=True)
        self.content = ttk.Frame(self, padding=padding)
        self.content.place(x=0, y=0, relwidth=1)
        self.offset = self.target = 0
        self.extent = 1
        self.content_size = None
        self.scrollcommand = None
        self.compositor = None
        self.layout_timer = self.motion_timer = None
        self.duration = .10
        self.lines_per_notch = 3
        self.wheel_remainder = 0
        self.scale = max(.75, float(self.tk.call("tk", "scaling")) / (96 / 72))
        self.bind("<Configure>", self.schedule_layout)
        self.content.bind("<Configure>", self.content_configured)
        self.bind("<Next>", lambda event: self.key_scroll(1))
        self.bind("<Prior>", lambda event: self.key_scroll(-1))
        self.bind("<Control-Home>", lambda event: self.key_edge(0))
        self.bind("<Control-End>", lambda event: self.key_edge(1))
        self.bind("<Destroy>", self.on_destroy, add=True)

    def prepare(self):
        self.compositor = PageCompositor([self.content], layered_pages=[])
        if self.compositor.user:
            lines = wintypes.UINT()
            if self.compositor.user.SystemParametersInfoW(0x68, 0, byref(lines), 0):
                self.lines_per_notch = lines.value

    def content_configured(self, event):
        # Native translation must never start another layout/paint cycle.
        size = event.width, event.height
        if size != self.content_size:
            self.content_size = size
            self.schedule_layout()

    def schedule_layout(self, event=None):
        if self.layout_timer is None:
            self.layout_timer = self.after_idle(self.finish_layout)

    def finish_layout(self):
        self.layout_timer = None
        self.stop_scroll()
        self.extent = max(1, self.content.winfo_height())
        # The geometry manager resets native coordinates when width changes.
        self.set_offset(self.offset, force=True)

    def limit(self, value):
        return max(0, min(max(0, self.extent-self.winfo_height()), value))

    def set_offset(self, value, force=False):
        offset = round(self.limit(value))
        if force or offset != self.offset:
            self.offset = offset
            if not self.compositor or not self.compositor.move(self.content, -offset):
                self.content.place_configure(y=-offset)
        if self.scrollcommand:
            self.scrollcommand(*self.yview())

    def yview(self, *args):
        if args:
            if args[0] == "moveto":
                self.yview_moveto(float(args[1]))
            elif args[0] == "scroll":
                self.yview_scroll(int(args[1]), args[2])
        return self.offset/self.extent, min(1, (self.offset+self.winfo_height())/self.extent)

    def yview_moveto(self, fraction):
        self.stop_scroll()
        self.prepare_scroll_surface()
        self.set_offset(float(fraction)*self.extent)

    def yview_scroll(self, number, what):
        self.stop_scroll()
        self.prepare_scroll_surface()
        self.set_offset(self.offset+int(number)*(16*self.scale if what == "units" else .9*self.winfo_height()))

    def key_scroll(self, direction):
        self.yview_scroll(direction, "pages")
        return "break"

    def key_edge(self, fraction):
        self.yview_moveto(fraction)
        return "break"

    def wheel(self, delta):
        stride = .9*self.winfo_height() if self.lines_per_notch == 0xffffffff else 16*self.scale*self.lines_per_notch
        self.wheel_remainder += -delta/120*stride
        distance = math.trunc(self.wheel_remainder)
        self.wheel_remainder -= distance
        if not distance:
            return
        active = self.motion_timer is not None
        # Reverse immediately rather than consuming a queue of old notches.
        base = self.target if active and distance*(self.target-self.offset) >= 0 else self.offset
        target = self.limit(base+distance)
        if target == self.offset:
            self.stop_scroll()
            return
        self.prepare_scroll_surface()
        reduced_motion = not self.compositor or not self.compositor.animate
        if reduced_motion:
            self.set_offset(target)
            return
        self.start_offset, self.target = self.offset, target
        self.started = time.perf_counter()
        if not active:
            self.compositor.begin_motion()
            self.next_frame = self.started
            self.motion_timer = self.after_idle(self.animate_frame)

    def prepare_scroll_surface(self):
        # Allocate only after real controls are visible and a scroll is needed.
        # Creating a layered child surface while the root is still withdrawn
        # exposed black textures during initial mapping on Windows.
        if self.compositor:
            self.compositor.retain(self.content)

    def animate_frame(self):
        self.motion_timer = None
        now = time.perf_counter()
        progress = min(1, (now-self.started)/self.duration)
        self.set_offset(self.start_offset+(self.target-self.start_offset)*(1-(1-progress)**3))
        if progress >= 1:
            self.stop_scroll()
            return
        self.next_frame += 1/60
        if self.next_frame <= now:
            self.next_frame = now+1/60
        self.motion_timer = self.after(max(1, round((self.next_frame-time.perf_counter())*1000)), self.animate_frame)

    def stop_scroll(self):
        if self.motion_timer is not None:
            self.after_cancel(self.motion_timer)
            self.motion_timer = None
        self.target = self.offset
        if self.compositor:
            self.compositor.end_motion()

    def on_destroy(self, event):
        if event.widget is self:
            self.stop_scroll()
            if self.layout_timer is not None:
                with contextlib.suppress(tk.TclError):
                    self.after_cancel(self.layout_timer)
            if self.compositor:
                self.compositor.close()
