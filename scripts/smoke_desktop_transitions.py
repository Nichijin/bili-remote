"""Verify immediate page switching, native input, screen pixels and resource reuse."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
from tkinter import ttk
from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.gui import Companion

class Preview(Companion):
    def start(self):
        pass

def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)

def main():
    user = ctypes.WinDLL("user32")
    user.WindowFromPoint.argtypes, user.WindowFromPoint.restype = [wintypes.POINT], wintypes.HWND
    user.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowLongPtrW.argtypes, user.GetWindowLongPtrW.restype = [wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t
    user.GetGuiResources.argtypes, user.GetGuiResources.restype = [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD
    user.mouse_event.argtypes = [wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.c_size_t]
    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    cursor = wintypes.POINT()
    user.GetCursorPos(ctypes.byref(cursor))
    with tempfile.TemporaryDirectory(prefix="bili-instant-pages-") as directory:
        with patch.dict(os.environ, {"BILI_REMOTE_DATA_DIR": directory}), patch("desktop.gui.startup_enabled", return_value=False):
            app = Preview(hidden=True)
        errors = []
        app.window.report_callback_exception = lambda *error: errors.append(str(error[1]))
        try:
            app.window.geometry("1040x780+30+30")
            app.window.attributes("-topmost",True)
            app.window.deiconify()
            app.window.focus_force()
            app.window.update()
            first, second = app.navigation[0][0], app.navigation[1][0]
            first.event_generate("<ButtonPress-1>",x=12,y=12)
            first.event_generate("<ButtonRelease-1>",x=12,y=12)
            app.window.update()
            assert first.itemcget(first.focus_item,"state")=="hidden"
            second.focus_set();app.window.update()
            assert second.itemcget(second.focus_item,"state")=="normal"
            second.event_generate("<Return>");app.window.update()
            assert app.tabs.selected==1
            assert not hasattr(app.tabs,"transition_timer"), "A page animation scheduler remains"
            assert not hasattr(app.tabs,"compositor"), "Full-page textures are still allocated"
            assert not any(user.GetWindowLongPtrW(page.winfo_id(),-20)&0x80000 for page in app.tabs.pages)
            controls={str(widget):widget.winfo_id() for widget in walk(app.tabs)}
            images=app.window.tk.call("image","names")
            gdi=user.GetGuiResources(kernel.GetCurrentProcess(),0)
            # All pages are already mapped; a change must not recreate, resize or
            # translate them. Native origins must match their parent immediately.
            configured=[]
            for page in app.tabs.pages:
                for widget in walk(page):
                    widget.bind("<Configure>",lambda event:configured.append(str(event.widget)),add=True)
            samples=[]
            for _ in range(30):
                for index in (0,1,2,3):
                    started=time.perf_counter();app.tabs.select(index);app.window.update()
                    samples.append(round((time.perf_counter()-started)*1000,3))
                    rect,parent=wintypes.RECT(),wintypes.RECT()
                    user.GetWindowRect(app.tabs.pages[index].winfo_id(),ctypes.byref(rect))
                    user.GetWindowRect(app.tabs.winfo_id(),ctypes.byref(parent))
                    assert rect.top==parent.top and rect.left==parent.left
                    assert app.navigation_selection.y==app.navigation_selection.target()
            assert not configured,"Switching deferred a layout pass"
            assert controls=={str(widget):widget.winfo_id() for widget in walk(app.tabs)}
            assert images==app.window.tk.call("image","names")
            assert user.GetGuiResources(kernel.GetCurrentProcess(),0)-gdi<8
            switch=next(widget for widget in walk(app.tabs.pages[3]) if isinstance(widget,ttk.Checkbutton)
                        and str(widget.cget("variable"))==str(app.close_to_tray))
            point=wintypes.POINT(switch.winfo_rootx()+switch.winfo_width()//2,switch.winfo_rooty()+switch.winfo_height()//2)
            hit=user.WindowFromPoint(point)
            physical=hit==switch.winfo_id()
            if physical:
                value=app.close_to_tray.get();user.SetCursorPos(point.x,point.y)
                user.mouse_event(2,0,0,0,0);user.mouse_event(4,0,0,0,0);app.window.update()
                assert value!=app.close_to_tray.get()
            else:
                name=ctypes.create_unicode_buffer(128)
                user.GetClassNameW(wintypes.HWND(hit),name,128)
                assert name.value.startswith("LockScreen"),f"Test control obscured: {name.value}"
                value=app.close_to_tray.get()
                switch.event_generate("<ButtonPress-1>",x=8,y=8)
                switch.event_generate("<ButtonRelease-1>",x=8,y=8)
                app.window.update()
                assert value!=app.close_to_tray.get()
            # Read actual screen pixels while switching, without PrintWindow or
            # forced redraws. Black text occupies far less than a black frame.
            rect=wintypes.RECT();user.GetWindowRect(app.tabs.winfo_id(),ctypes.byref(rect))
            box=(rect.left+5,rect.top+5,rect.right-5,rect.bottom-5)
            black=[]
            for index in ((0,1,2,3,1,0,1) if physical else ()):
                app.tabs.select(index)
                for frame in range(3):
                    app.window.update()
                    image=ImageGrab.grab(bbox=box).convert("L")
                    ratio=sum(image.histogram()[:16])/(image.width*image.height)
                    black.append(round(ratio,6));assert ratio<.2,"Black page frame sampled"
                    time.sleep(.008)
            app.tabs.select(3);app.window.update()
            # Incremental table updates preserve identity, selection and focus.
            rows=[{"name":"chrome.exe","version":"1.0","kind":"browser","path":"C:/example/chrome.exe",
                   "running":True,"capabilities":"test"}]
            app.display_inventory(rows);item=app.inventory.get_children()[0];app.inventory.selection_set(item)
            app.display_inventory([{**rows[0],"version":"2.0"}])
            assert app.inventory.get_children()==(item,) and app.inventory.selection()==(item,)
            app.window.geometry("1120x780");app.window.update()
            assert all(page.winfo_width()==app.tabs.winfo_width() for page in app.tabs.pages)
            app.window.withdraw();app.window.update();app.window.deiconify();app.window.update()
            assert not errors,errors
            report={"page_animation_removed":True,"full_page_textures_removed":True,"rapid_switches":120,
                    "no_navigation_layout_or_translation":True,"controls_and_images_reused":True,
                    "mouse_and_keyboard_focus_distinguished":True,"native_immediate_input":physical,
                    "physical_input_limit":None if physical else "Windows desktop locked; Tk input checked; no screen-pixel claim",
                    "incremental_inventory_preserves_selection":True,"screen_black_fraction":black,
                    "switch_update_samples_ms":samples,"resize_and_hide_cleanup":True}
        finally:
            user.SetCursorPos(cursor.x,cursor.y)
            app.window.destroy()
        assert not errors,errors
        (ROOT/".tooling/desktop-transitions-smoke.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        print(json.dumps({key:value for key,value in report.items() if key!="switch_update_samples_ms"}),flush=True)

if __name__=="__main__":main()
