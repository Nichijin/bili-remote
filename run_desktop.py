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
        async def check():
            result = await NativeController().discover()
            result["audio_count"] = len(AudioUtilities.GetAllSessions())
            result["assets"] = (ASSETS / "index.html").is_file()
            window = tk.Tk()
            window.withdraw()
            window.destroy()
            result["gui_runtime"] = True
            return result
        Path(sys.argv[-1]).write_text(json.dumps(asyncio.run(check()), ensure_ascii=False), encoding="utf-8")
    else:
        main()
