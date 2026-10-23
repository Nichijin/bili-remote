"""Actual passive overlay lifecycle, input policy and settings persistence."""
import ctypes,json,os,sys,tempfile
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from desktop.gui import Companion
from desktop.feedback import DEFAULT_STYLE
class Preview(Companion):
 def start(self):pass

def main():
 user=ctypes.WinDLL('user32');user.GetForegroundWindow.restype=wintypes.HWND
 with tempfile.TemporaryDirectory(prefix='bili-feedback-') as directory:
  with patch.dict(os.environ,{'BILI_REMOTE_DATA_DIR':directory}),patch('desktop.gui.startup_enabled',return_value=False):app=Preview(hidden=True)
  try:
   assert app.overlay is None
   app.window.show();QTest.qWait(30);foreground=user.GetForegroundWindow()
   app.feedback_vars['font_size'].setValue(32);app.feedback_vars['color'].setText('#75e1eb');app.feedback_vars['opacity'].setValue(65)
   app.feedback_position.setCurrentText('右上');app.choose_feedback_position();app.finish_feedback_edit()
   app.show_overlay('样式检查 · 临时 2 倍速');QTest.qWait(30);overlay=app.overlay
   assert overlay.style=={'font_size':32,'color':'#75E1EB','opacity':65,'x':95,'y':5}
   assert abs(overlay.windowOpacity()-.65)<.01
   assert overlay.windowFlags()&Qt.WindowType.WindowTransparentForInput
   assert user.GetForegroundWindow()==foreground,'Overlay took foreground focus'
   area=overlay.work_area();rect=overlay.geometry()
   assert area[0]<=rect.left()<=rect.right()<area[2] and area[1]<=rect.top()<=rect.bottom()<area[3]
   assert json.loads(app.preferences.path.read_text(encoding='utf-8'))['feedback_style']==overlay.style
   timer=overlay.timer;native=int(overlay.winId())
   for n in range(300):app.show_overlay(f'连续操作 {n} · 音量 50%')
   assert overlay.timer is timer and int(overlay.winId())==native
   app.show_feedback.click();assert app.overlay is None
   app.show_overlay('disabled');assert app.overlay is None
   app.show_feedback.click();app.show_overlay('重新开启');app.reset_feedback_style();assert app.overlay.style==DEFAULT_STYLE
   QTest.qWait(1600);assert not app.overlay.isVisible()
   assert user.GetForegroundWindow()==foreground
   report={'focus_preserved':True,'mouse_passthrough':True,'style_and_position':True,'settings_saved':True,'repeated_updates_reuse_window_and_timer':True,'auto_hide':True}
   (ROOT/'.tooling/feedback-test-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
  finally:app.dispose()
if __name__=='__main__':main()
