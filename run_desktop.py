from desktop.gui import main
import sys

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        import asyncio
        import json
        from pathlib import Path
        from desktop.native import NativeController
        from pycaw.pycaw import AudioUtilities
        from winrt.windows.storage import streams
        from desktop.server import ASSETS
        import tkinter as tk
        from tkinter import ttk
        from desktop.layout import CachedPages, ScrollablePage
        async def check():
            result = await NativeController().discover()
            result["audio_count"] = len(AudioUtilities.GetAllSessions())
            result["assets"] = (ASSETS / "index.html").is_file()
            window = tk.Tk()
            window.withdraw()
            pages = CachedPages(window)
            pages.pack(fill="both", expand=True)
            frames = [ttk.Frame(pages) for _ in range(2)]
            for frame in frames:
                pages.add(frame)
            scroller = ScrollablePage(frames[1])
            ttk.Frame(scroller.content, height=1200).pack()
            pages.prepare()
            pages.select(1)
            window.update_idletasks()
            scroller.viewport.yview_moveto(.2)
            result["page_composition"] = len(pages.compositor.surfaces) == 2
            result["scroll_composition"] = bool(scroller.viewport.compositor.retained)
            result["scroll_runtime"] = scroller.viewport.yview()[0] > 0
            window.destroy()
            result["gui_runtime"] = True
            return result
        Path(sys.argv[-1]).write_text(json.dumps(asyncio.run(check()), ensure_ascii=False), encoding="utf-8")
    else:
        main()
