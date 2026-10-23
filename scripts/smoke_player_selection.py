"""Verify the mobile target picker with isolated WebSocket replies; no real player control."""
import json,sys
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from desktop.browser import find_browser
with sync_playwright() as playwright:
 browser=playwright.chromium.launch(executable_path=str(find_browser()),headless=True)
 try:
  page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
  page.add_init_script("""
   const settings={schema:2,target:'auto',ui_style:'remote',device_id:'test-phone-0001',host:'127.0.0.1:19999',computer_id:'test-computer',credentials:{'test-computer':'test-key'}};
   window.Android={loadSettings:()=>JSON.stringify(settings),saveSettings:v=>window.saved=JSON.parse(v),deviceId:()=>settings.device_id,deviceName:()=> 'test',startDiscovery:()=>{},stopDiscovery:()=>{}};
   window.sent=[];
   window.WebSocket=class {
    constructor(){this.readyState=0;setTimeout(()=>{this.readyState=1;this.onopen?.()},10)}
    send(text){const q=JSON.parse(text);window.sent.push(q);let result={};
     if(q.role==='remote'){setTimeout(()=>this.onmessage?.({data:JSON.stringify({type:'auth',ok:true,computer_id:'test-computer',token:'test-key',computer_name:'test'})}),5);return}
     if(q.cmd==='discover')result={sessions:[{id:'msedge.exe',name:'Edge · 系统媒体',toggle:true,seek:true,speed:false}]};
     else if(q.cmd==='open_browser')result={opened:true,browser:'chrome.exe',control_target:{name:'Chrome · 专用网页',channel:'web'}};
     else result={control_target:{name:'Edge · 系统媒体',channel:'system'},paused:true};
     setTimeout(()=>this.onmessage?.({data:JSON.stringify({id:q.id,ok:true,result})}),5)
    }
    close(){this.readyState=3}
   }
  """)
  page.goto((root/'android/app/src/main/assets/index.html').as_uri());page.locator('body.connected').wait_for()
  page.evaluate('window.openSettings()')
  page.select_option('#target','native');page.click('#discover');page.locator('#session option[value="msedge.exe"]').wait_for(state='attached')
  page.select_option('#session','msedge.exe')
  assert page.evaluate('saved.session_id')=='msedge.exe'
  page.click('#discover');page.wait_for_timeout(50)
  assert page.locator('#session').input_value()=='msedge.exe'
  page.select_option('#browserChoice','chrome');page.click('#launchBrowser')
  page.wait_for_function("window.saved?.target==='browser'")
  assert page.locator('#target').input_value()=='browser'
  assert page.locator('#activeTarget').inner_text()=='最近确认目标：Chrome · 专用网页'
  assert page.evaluate("sent.findLast(q=>q.cmd==='open_browser').browser")=='chrome'
  assert page.evaluate("saved.browser_choice")=='chrome'
  assert page.evaluate("document.querySelector('#settings').scrollWidth<=innerWidth")
  print(json.dumps({'system_media_picker':True,'selected_session_preserved_after_refresh':True,'explicit_chrome_launch_command':True,'actual_target_label':True,'explicit_launch_selects_web_target':True,'mobile_no_horizontal_overflow':True}))
 finally:browser.close()
