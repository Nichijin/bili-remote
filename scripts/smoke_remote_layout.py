"""Check remote controls inside the circle on seven viewport sizes.

Uses installed Edge/Chrome with an isolated fixture; no phone or network service.
Optional dependency: pip install playwright
"""
import json
import math
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from desktop.browser import find_browser

config={'schema':2,'ui_style':'remote','device_id':'layout-test-phone','device_name':'布局测试','host':'127.0.0.1:19999','computer_id':'layout-test-computer','target':'auto','rate':2}
fixture='''
const sample=__CONFIG__;
window.sentCommands=[];
window.hapticPulses=0;
window.Android={loadSettings:()=>localStorage.getItem('smoke-settings')||JSON.stringify(sample),saveSettings:text=>localStorage.setItem('smoke-settings',text),haptic:()=>window.hapticPulses++,deviceId:()=>sample.device_id,deviceName:()=>sample.device_name,startDiscovery:()=>{},stopDiscovery:()=>{}};
window.WebSocket=class{
 static OPEN=1;
 constructor(){this.readyState=0;setTimeout(()=>{this.readyState=1;this.onopen?.()},10)}
 send(text){const m=JSON.parse(text);window.sentCommands.push(m);const reply=m.role==='remote'?{type:'auth',ok:true,token:'fixture',computer_id:sample.computer_id,computer_name:'DESKTOP-LONG-COMPUTER-NAME-FOR-LAYOUT'}:{id:m.id,ok:true,result:{volume:0.55,paused:true,time:120,seek_start:0,seek_end:3600,media_key:'layout-video'}};setTimeout(()=>this.onmessage?.({data:JSON.stringify(reply)}),5)}
 close(){this.readyState=3}
};
'''.replace('__CONFIG__',json.dumps(config))
(ROOT/'.tooling').mkdir(exist_ok=True)
report=[]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=str(find_browser()),headless=True)
    try:
        for width,height in [(320,568),(360,640),(390,844),(412,915),(568,320),(844,390),(768,1024)]:
            context=browser.new_context(viewport={'width':width,'height':height},is_mobile=True,has_touch=True,device_scale_factor=1)
            context.add_init_script(fixture)
            page=context.new_page();page.goto((ROOT/'android/app/src/main/assets/index.html').as_uri())
            page.locator('body.connected').wait_for()
            page.wait_for_function("getComputedStyle(document.querySelector('#hud')).opacity==='0' && !document.querySelector('#hud').classList.contains('visible')")
            result=page.evaluate('''() => {
              const rect=s=>{const r=document.querySelector(s).getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,cx:r.x+r.width/2,cy:r.y+r.height/2}};
              const selectors=['.play-button','.seek.left','.seek.right','.volume-up','.volume-down'];
              return {disc:rect('.playback-disc'),controls:Object.fromEntries(selectors.map(s=>[s,rect(s)])),overflow:document.querySelector('#remote').scrollWidth>innerWidth,oldVolumeBar:!!document.querySelector('.volume-control')};
            }''')
            disc=result['disc'];controls=result['controls'];center=controls['.play-button']
            assert abs(disc['w']-disc['h'])<1, result
            assert not result['overflow'] and not result['oldVolumeBar']
            for name,r in controls.items():
                assert r['w']>=44 and r['h']>=44,(width,height,name,r)
                # Every rectangular touch target, including seek labels, is inside the circle.
                assert max(math.hypot(x-disc['cx'],y-disc['cy']) for x in [r['x'],r['x']+r['w']] for y in [r['y'],r['y']+r['h']]) < disc['w']/2,(width,height,name,result)
            assert abs(center['cx']-disc['cx'])<1 and abs(center['cy']-disc['cy'])<1,result
            assert controls['.volume-up']['y']+controls['.volume-up']['h']<=center['y']
            assert controls['.volume-down']['y']>=center['y']+center['h']
            assert controls['.seek.left']['x']+controls['.seek.left']['w']<=center['x']
            assert controls['.seek.right']['x']>=center['x']+center['w']
            for name in ['音量增大','音量减小','快退 10 秒','快进 10 秒','播放或暂停']:
                page.get_by_role('button',name=name,exact=True).click()
            page.wait_for_function('window.sentCommands.filter(m=>m.cmd && m.cmd!=="ping").length===5')
            commands=page.evaluate('window.sentCommands.filter(m=>m.cmd && m.cmd!=="ping").map(({cmd,delta})=>({cmd,...(delta===undefined?{}:{delta})}))')
            assert commands==[{'cmd':'volume','delta':0.05},{'cmd':'volume','delta':-0.05},{'cmd':'seek','delta':-10},{'cmd':'seek','delta':10},{'cmd':'toggle'}],commands
            assert page.locator('#remote #launchBrowser').count()==0
            # The sheet header/actions remain reachable while its content scrolls.
            page.locator('#deviceStatus').click()
            page.locator('#settings[open]').wait_for()
            sheet=page.evaluate('''() => {
              const s=document.querySelector('#settings'),b=document.querySelector('.sheet-actions .primary').getBoundingClientRect(),c=document.querySelector('#closeSettings').getBoundingClientRect();
              return {overflow:s.scrollWidth>s.clientWidth,done:b.top>=0&&b.bottom<=innerHeight,close:c.top>=0&&c.bottom<=innerHeight};
            }''')
            assert sheet=={'overflow':False,'done':True,'close':True},(width,height,sheet)
            page.locator('#manualDetails summary').click()
            page.locator('#host').fill('192.168.1.10')
            page.locator('#target').select_option('native')
            assert page.locator('#nativeSettings').is_visible()
            page.locator('#discover').scroll_into_view_if_needed()
            assert page.evaluate('window.sentCommands.filter(m=>m.cmd==="open_browser").length')==0
            page.locator('#settings #launchBrowser').click()
            page.wait_for_function('window.sentCommands.filter(m=>m.cmd==="open_browser").length===1 && !document.querySelector("#launchBrowser").disabled')
            assert page.locator('#settings').evaluate('e=>e.open'), 'Opening a player must not submit the settings form'
            assert '已在电脑打开' in page.locator('#browserMessage').inner_text()
            page.locator('#target').select_option('auto')
            assert page.locator('#nativeSettings').is_hidden()
            page.locator('#rate').select_option('3')
            assert page.locator('#speedTrack .active').get_attribute('data-rate')=='3'
            page.locator('#style').select_option('touchpad')
            assert page.locator('[data-style="touchpad"]').get_attribute('aria-pressed')=='true'
            page.locator('#style').select_option('remote')
            assert page.locator('[data-style="remote"]').get_attribute('aria-pressed')=='true'
            page.locator('#rate').select_option('2')
            page.locator('.sheet-actions .primary').click()
            assert not page.locator('#settings').evaluate('e=>e.open')
            page.locator('#remote').evaluate('e=>e.scrollTop=0')
            if width == 390:
                page.evaluate('window.sentCommands=[];window.hapticPulses=0')
                button=page.locator('#holdSpeed')
                button.scroll_into_view_if_needed()
                rect=button.bounding_box(); x,y=rect['x']+rect['width']/2,rect['y']+rect['height']/2
                page.mouse.move(x,y);page.mouse.down()
                page.wait_for_function('window.hapticPulses===1')
                page.mouse.move(x+60,y)
                page.wait_for_function('window.hapticPulses===2')
                assert page.locator('#holdRate').inner_text()=='3×'
                for offset in [65,62,70,61]: page.mouse.move(x+offset,y)
                assert page.evaluate('window.hapticPulses')==2
                page.mouse.move(x,y);page.mouse.up()
                page.wait_for_function('window.sentCommands.some(m=>m.cmd==="speed_end")')
                assert page.evaluate('window.hapticPulses')==3
                assert page.evaluate('window.sentCommands.filter(m=>m.cmd?.startsWith("speed_") && m.cmd!=="speed_keep").map(m=>m.cmd)')==['speed_start','speed_change','speed_change','speed_end']
                page.get_by_role('button',name='震动反馈',exact=True).click()
                assert page.locator('#hapticToggle').get_attribute('aria-pressed')=='false'
                page.reload();page.locator('body.connected').wait_for()
                assert page.locator('#hapticToggle').get_attribute('aria-pressed')=='false'
                page.locator('[data-style="touchpad"]').click()
                page.evaluate('window.sentCommands=[];window.hapticPulses=0')
                page.mouse.move(150,300);page.mouse.down();page.wait_for_timeout(560)
                page.mouse.move(215,300);page.mouse.move(150,300);page.mouse.up()
                page.wait_for_function('window.sentCommands.some(m=>m.cmd==="speed_end")')
                assert page.evaluate('window.hapticPulses')==0
                assert page.evaluate('window.sentCommands.filter(m=>m.cmd && m.cmd!=="ping" && m.cmd!=="speed_keep").map(m=>m.cmd)')==['speed_start','speed_change','speed_change','speed_end']
                # Re-enable from settings in touchpad mode; both entry points sync.
                page.evaluate('window.openSettings()')
                page.locator('#haptics').check()
                assert page.locator('#hapticToggle').get_attribute('aria-pressed')=='true'
                page.locator('#closeSettings').click()
                page.evaluate('window.sentCommands=[];window.hapticPulses=0')
                page.mouse.move(150,300);page.mouse.down();page.wait_for_timeout(560)
                page.mouse.move(215,300);page.mouse.move(150,300);page.mouse.up()
                page.wait_for_function('window.sentCommands.some(m=>m.cmd==="speed_end")')
                assert page.evaluate('window.hapticPulses')==3
                assert page.evaluate('window.sentCommands.filter(m=>m.cmd && m.cmd!=="ping" && m.cmd!=="speed_keep").map(m=>m.cmd)')==['speed_start','speed_change','speed_change','speed_end']
                # Preferences persist and apply equally to both modes.
                page.evaluate('window.openSettings()')
                page.locator('#gearSettings summary').click()
                page.locator('#gearCount').select_option('5')
                assert page.locator('#gearEditor select').count()==5
                assert page.locator('#speedTrack .speed-detent').count()==5
                page.locator('#rate').select_option('0.5')
                page.locator('#showHints').uncheck()
                page.locator('#closeSettings').click()
                page.evaluate('window.sentCommands=[];window.hapticPulses=0')
                page.mouse.move(80,300);page.mouse.down();page.wait_for_timeout(560)
                page.mouse.move(140,300);page.mouse.up()
                page.wait_for_function('window.sentCommands.some(m=>m.cmd==="speed_end")')
                assert page.evaluate('window.sentCommands.filter(m=>m.rate).map(m=>m.rate)')==[0.5,0.75]
                assert not page.locator('#hud').is_visible()
                page.reload();page.locator('body.connected').wait_for()
                assert page.locator('#showHints').is_checked()==False
                assert page.locator('#gearEditor select').count()==5
                # Actual pointer input sends fractional positions before release.
                page.evaluate('window.sentCommands=[]')
                page.mouse.move(60,300);page.mouse.down();page.mouse.move(110,300)
                page.wait_for_function('window.sentCommands.some(m=>m.cmd==="seek_to")')
                page.mouse.move(177,300);page.wait_for_timeout(100);page.mouse.up()
                page.wait_for_function('window.sentCommands.filter(m=>m.cmd==="seek_to").at(-1).position===156')
                assert not page.locator('#hud').is_visible()
                print('Both modes: actual pointer input, detent haptics, persisted off switch and restored settings passed')
            report.append({'viewport':f'{width}x{height}','circle_diameter':round(disc['w'],1),'controls_inside_ring':True,'minimum_touch_target':44,'commands_correct':True})
            context.close()
    finally:browser.close()
(ROOT/'.tooling/remote-layout-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
