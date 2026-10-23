"""Check full-width layouts, wrapping and reachable actions at multiple DPI scales."""
import argparse,json,os,subprocess,sys,tempfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--scale',type=float);args=parser.parse_args()
 if args.scale is None:
  report=[]
  for scale in (1,1.25,1.5,2):
   env={**os.environ,'QT_SCALE_FACTOR':str(scale)}
   result=subprocess.run([sys.executable,__file__,'--scale',str(scale)],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
   if result.returncode:raise RuntimeError(result.stdout+result.stderr)
   report.extend(json.loads(result.stdout))
  (ROOT/'.tooling/desktop-layout-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
  print(json.dumps({'cases':len(report),'scales':[1,1.25,1.5,2],'full_width_and_bottom_reachable':True}));return
 from PySide6.QtCore import QPoint
 from PySide6.QtTest import QTest
 from desktop.gui import Companion
 from desktop.qt_widgets import FlowLayout
 class Preview(Companion):
  def start(self):pass
 report=[]
 with tempfile.TemporaryDirectory(prefix='bili-layout-') as directory:
  with patch.dict(os.environ,{'BILI_REMOTE_DATA_DIR':directory}),patch('desktop.gui.startup_enabled',return_value=False):app=Preview(hidden=True)
  try:
   app.window.show()
   for width,height in ((440,300),(480,360),(640,480),(800,550),(1040,780),(1200,780),(1366,900),(1920,1080)):
    app.window.resize(width,height);QTest.qWait(20)
    for index in range(4):
     app.select_page(index);QTest.qWait(15)
     scroll=app.tabs.widget(index);page=app.pages[index]
     assert scroll.width()==app.tabs.width(),'Unused side columns'
     assert page.width()==scroll.viewport().width(),'Scrollable content not full width'
     assert app.navigation[index].isVisible()
     assert app.navigation[index].geometry().bottom()<=app.sidebar.height(),'Sidebar overflow'
     for flow in page.findChildren(FlowLayout):
      for n in range(flow.count()):
       item=flow.itemAt(n)
       assert item.geometry().right()<=flow.geometry().right()+1,'Action row overflow'
     bar=scroll.verticalScrollBar();bar.setValue(bar.maximum());app.app.processEvents()
     assert page.mapTo(scroll.viewport(),QPoint(0,page.height())).y()<=scroll.viewport().height()+1,'Bottom unreachable'
    report.append({'logical_window':[width,height],'requested_qt_scale':args.scale,'actual_dpr':app.window.devicePixelRatioF(),'full_width':True,'bottom_reachable':True})
  finally:app.dispose()
 print(json.dumps(report))
if __name__=='__main__':main()
