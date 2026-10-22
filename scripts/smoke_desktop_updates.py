"""Exercise actual GUI update states with bounded/offline dependency substitutes."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.gui import Companion
from desktop.version import APP_VERSION
from desktop.updates import check_latest


class Preview(Companion):
    def start(self):
        pass


def main():
    with tempfile.TemporaryDirectory(prefix="bili-update-ui-") as directory:
        with patch.dict(os.environ, {"BILI_REMOTE_DATA_DIR": directory}), patch("desktop.gui.startup_enabled", return_value=False):
            app = Preview(hidden=True)
        errors = []
        app.window.report_callback_exception = lambda *error: errors.append(str(error[1]))
        try:
            app.window.deiconify(); app.window.update()
            assert not app.update_started, "Cold startup started update I/O"
            app.tabs.select(1); app.window.update()
            assert not app.update_started, "Isolated previews unexpectedly used the network"
            started, release = threading.Event(), threading.Event()
            calls = []
            def delayed(cache, force):
                calls.append(force); started.set()
                assert release.wait(3), "Test did not release simulated network"
                return {"version": "9.0.0", "download_url": "https://github.com/Nichijin/bili-remote/releases/download/v9.0.0/BiliRemote-Setup-9.0.0.exe",
                        "page_url": "https://github.com/Nichijin/bili-remote/releases/tag/v9.0.0", "cache": {}, "cached": False}
            with patch("desktop.updates.check_latest", delayed):
                app.check_updates(manual=True)
                assert started.wait(1)
                app.check_updates(manual=True)
                # A blocked network worker must not block menu input/settings.
                app.tabs.select(3); app.window.update()
                assert app.tabs.selected == 3 and app.update_busy and len(calls) == 1
                release.set()
                deadline = time.monotonic()+2
                while app.update_busy and time.monotonic() < deadline:
                    app.window.update(); time.sleep(.002)
            assert not app.update_busy and "9.0.0" in app.update_status.get()
            assert "disabled" not in app.update_download_button.state()
            with patch("webbrowser.open", return_value=True) as open_browser:
                app.download_update()
                open_browser.assert_called_once_with(app.update_download)
            with patch("desktop.updates.check_latest", side_effect=RuntimeError("无法连接 GitHub")):
                app.check_updates(manual=True)
                deadline = time.monotonic()+2
                while app.update_busy and time.monotonic() < deadline:
                    app.window.update(); time.sleep(.002)
            assert "检查更新失败" in app.update_status.get() and "disabled" not in app.update_button.state()
            app.show_update_result({"version": APP_VERSION, "download_url": "unused", "cache": {}, "cached": False})
            assert "已是最新正式版" in app.update_status.get() and not app.update_download
            assert not errors, errors
            report = {"current_version": APP_VERSION, "no_network_during_cold_start": True,
                      "network_worker_does_not_block_navigation": True, "duplicate_requests_coalesced": True,
                      "newer_version_download_link": True, "offline_retry_and_latest_states": True}
        finally:
            app.window.destroy()
        assert not errors, errors
        (ROOT/".tooling/desktop-updates-smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)
    # Public production endpoint, without gh credentials or embedded tokens.
    actual = check_latest(force=True)
    print(json.dumps({"public_api_latest": actual["version"], "official_installer_url": actual["download_url"]}), flush=True)


if __name__ == "__main__":
    main()
