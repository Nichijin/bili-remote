"""Mobile pointer gestures in an isolated browser with mock computer replies."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.browser import find_browser
from desktop.version import APP_VERSION

FIXTURE = """
const sample={schema:2,target:'auto',ui_style:'touchpad',device_id:'test-mouse-phone',host:'127.0.0.1:19999',computer_id:'test-computer',credentials:{'test-computer':'test-key'}};
window.saved=JSON.parse(localStorage.getItem('mouse-test')||'null')||sample;
window.Android={loadSettings:()=>JSON.stringify(window.saved),saveSettings:v=>{window.saved=JSON.parse(v);localStorage.setItem('mouse-test',v)},deviceId:()=>sample.device_id,deviceName:()=> 'test',startDiscovery:()=>{},stopDiscovery:()=>{},haptic:()=>window.pulses++};
window.sent=[];window.pulses=0;
window.WebSocket=class {
 constructor(){this.readyState=0;setTimeout(()=>{this.readyState=1;this.onopen?.()},10)}
 send(text){const q=JSON.parse(text);window.sent.push(q);
  const result=q.cmd==='mouse_start'?{mouse_session:'aaaaaaaaaaaaaaaaaaaaaaaa',mouse_stream:2,mouse_output_hz:q.output_hz||1000}:{time:120,seek_start:0,seek_end:3600,media_key:'fixture-video'};
  const reply=q.role==='remote'?{type:'auth',ok:true,computer_id:'test-computer',token:'test-key',computer_name:'示例电脑'}:q.cmd==='mouse_frame'?{type:'mouse_ack',ok:true,mouse_session:q.mouse_session,seq:q.seq}:{id:q.id,ok:true,result};
  setTimeout(()=>this.onmessage?.({data:JSON.stringify(reply)}),5)
 }
 close(){this.readyState=3}
};
"""


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(find_browser()), headless=True)
        try:
            page = browser.new_page(viewport={"width":390,"height":844}, is_mobile=True, has_touch=True)
            page.add_init_script(FIXTURE)
            page.goto((ROOT / "android/app/src/main/assets/index.html").as_uri())
            page.locator("body.connected").wait_for()
            page.mouse.click(180,400)
            page.wait_for_function("sent.some(q=>q.cmd==='toggle')")
            page.evaluate("sent=[]")
            page.mouse.dblclick(180,400,delay=80)
            page.wait_for_function("touchpad.phase==='mouse'")
            assert page.evaluate("sent.every(q=>q.cmd!=='toggle')")
            page.mouse.move(100,300)
            page.mouse.down()
            page.mouse.move(250,470,steps=12)
            page.mouse.up()
            page.wait_for_function("sent.some(q=>q.cmd==='mouse_frame' && q.x>0 && q.y>0)")
            assert page.evaluate("sent.every(q=>!['toggle','seek','seek_to','volume','speed_start'].includes(q.cmd))")
            page.mouse.click(180,400)
            page.wait_for_function("sent.some(q=>q.cmd==='mouse_click' && q.button==='left')")
            before = page.evaluate("sent.filter(q=>q.cmd==='mouse_click').length")
            page.mouse.down()
            page.wait_for_timeout(550)
            page.mouse.up()
            page.wait_for_function(f"sent.filter(q=>q.cmd==='mouse_click').length==={before+1}")
            assert page.evaluate("pulses") == 2
            page.screenshot(path=str(ROOT / ".tooling/mouse-touchpad0511.png"))
            page.click("#mouseExit")
            page.wait_for_function("touchpad.phase==='video'")
            page.evaluate("window.openSettings()")
            assert page.locator("#mouseOutputHz").input_value()=="1000"
            assert page.locator("#mouseAcceleration").input_value()=="standard"
            page.select_option("#mouseOutputHz", "500")
            page.select_option("#mouseTapButton", "right")
            page.check("#showHints", force=True) if not page.locator("#showHints").is_checked() else None
            page.uncheck("#showHints")
            page.click("#enterMouse")
            page.wait_for_function("touchpad.phase==='mouse'")
            assert page.evaluate("sent.filter(q=>q.cmd==='mouse_start').at(-1).output_hz") == 500
            assert page.locator("#mouseExit").is_visible()
            page.mouse.click(180,400)
            page.wait_for_function("sent.filter(q=>q.cmd==='mouse_click' && q.button==='right').length===2")
            page.evaluate("window.openSettings()")
            page.select_option("#mouseTapButton", "left")
            page.click("#enterMouse")
            page.wait_for_function("touchpad.phase==='mouse'")
            page.evaluate("sent=[]")
            page.mouse.dblclick(180,400,delay=80)
            page.wait_for_function("sent.filter(q=>q.cmd==='mouse_click').length===2")
            assert page.evaluate("touchpad.phase==='mouse' && sent.filter(q=>q.cmd==='mouse_click').every(q=>q.button==='left')")
            page.click("#mouseExit")
            page.wait_for_function("touchpad.phase==='video'")
            page.reload()
            page.locator("body.connected").wait_for()
            assert page.evaluate("saved.mouse_tap_button==='left' && saved.mouse_output_hz===500 && !saved.show_hints")
            profile_travel={}
            for profile in ("off","gentle","standard","strong"):
                page.evaluate("window.openSettings()")
                page.select_option("#mouseAcceleration",profile)
                page.click("#enterMouse")
                page.wait_for_function("touchpad.phase==='mouse'")
                profile_travel[profile]=page.evaluate("""() => {
                  const before=touchpad.mouse.x, time=performance.now();
                  touchpad.down(50,300,innerWidth,innerHeight,time);
                  for(let i=1;i<=12;i++)touchpad.move(50+100*i/12,300,time+60*i/12);
                  touchpad.up(150,300,time+60);
                  return touchpad.mouse.x-before;
                }""")
            assert abs(profile_travel["off"]-100)<1e-7
            assert 100<profile_travel["gentle"]<profile_travel["standard"]<profile_travel["strong"]
            page.click("#mouseExit")
            page.reload()
            page.locator("body.connected").wait_for()
            assert page.evaluate("saved.mouse_acceleration==='strong'")
            page.evaluate("window.openSettings()")
            assert page.locator("#mouseAcceleration").input_value()=="strong"
            page.click("#enterMouse")
            page.wait_for_function("touchpad.phase==='mouse'")
            for width,height in [(320,568),(360,640),(390,844),(412,915),(568,320),(844,390),(768,1024)]:
                page.set_viewport_size({"width":width,"height":height})
                bounds=page.locator("#mouseExit").bounding_box()
                assert bounds["height"]>=44 and bounds["x"]>=0 and bounds["y"]>=0
                assert bounds["x"]+bounds["width"]<=width and bounds["y"]+bounds["height"]<=height
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            page.set_viewport_size({"width":390,"height":844})
            page.mouse.down()
            page.evaluate("window.setAppActive(false)")
            page.mouse.up()
            page.wait_for_function("touchpad.phase==='video' && !connection.connected")
            page.wait_for_timeout(550)
            assert page.evaluate("sent.every(q=>q.cmd!=='mouse_click')")
            report={"version":APP_VERSION,"single_video_tap":True,"double_tap_enters_without_pause":True,"real_pointer_movement":True,
                    "default_left_click":True,"long_right_once_with_haptic":True,"configurable_right_click":True,
                    "normal_double_click_stays_in_mouse_mode":True,"preferences_survive_reload":True,
                    "exit_accessible_with_hints_hidden":True,"mouse_layout_viewports":7,"output_1000_default_and_500_persisted":True,"background_clears_hold_and_session":True,
                    "acceleration_profiles_applied_and_persisted":True,"synthetic_100px_60ms_profile_travel":profile_travel}
            (ROOT / ".tooling/mouse-touchpad-report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
            print(json.dumps(report))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
