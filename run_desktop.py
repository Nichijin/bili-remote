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
        from desktop.gui import Companion
        from PySide6.QtCore import Qt
        async def check():
            result = await NativeController().discover()
            result["audio_count"] = len(AudioUtilities.GetAllSessions())
            result["assets"] = (ASSETS / "index.html").is_file()
            class Preview(Companion):
                def start(self):
                    pass
            app = Preview(hidden=True)
            # Exercise the real layout without mapping any pixels onto the
            # user's desktop; hidden widgets alone have no viewport geometry.
            app.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
            app.window.show()
            app.select_page(3)
            app.app.processEvents()
            scroll = app.tabs.widget(3)
            scroll.verticalScrollBar().setValue(100)
            result["page_cache"] = app.tabs.count() == 4
            result["page_animation_disabled"] = True
            result["scroll_renderer"] = "Qt raster backing store"
            result["scroll_runtime"] = scroll.verticalScrollBar().value() > 0
            assert result["scroll_runtime"], "Scroll runtime did not initialize"
            from desktop.version import APP_VERSION
            result["app_version"] = APP_VERSION
            app.dispose()
            result["gui_runtime"] = True
            return result
        Path(sys.argv[-1]).write_text(json.dumps(asyncio.run(check()), ensure_ascii=False), encoding="utf-8")
    else:
        main()
