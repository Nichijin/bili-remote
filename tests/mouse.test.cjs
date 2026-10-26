const {test} = require('node:test');
const assert = require('node:assert/strict');
const {PointerAcceleration, MouseTransport, TouchpadController} = require('../android/app/src/main/assets/mouse.js');
const {GestureEngine} = require('../android/app/src/main/assets/gestures.js');
const flush = () => new Promise(resolve => setImmediate(resolve));
const session = 'a'.repeat(24);

function setup(options={}) {
  let time = 0, id = 0;
  const callbacks = new Map(), commands = [], errors = [], phases = [];
  const timers = {setInterval(fn) {callbacks.set(++id, fn); return id;}, clearInterval(id) {callbacks.delete(id);},setTimeout(fn) {callbacks.set(++id,fn);return id;},clearTimeout(id){callbacks.delete(id);}};
  const frames = {requestAnimationFrame(fn) {callbacks.set(++id, fn); return id;}, cancelAnimationFrame(id) {callbacks.delete(id);}};
  const transport = new MouseTransport({
    send: (cmd, fields) => {commands.push({cmd, ...fields}); return Promise.resolve(cmd === 'mouse_start' ? {mouse_session:session,mouse_stream:2,mouse_output_hz:1000} : options.respond?.(cmd, fields)||{});},
    stream: fields=> {if(options.stream && !options.stream(fields))return false; commands.push({cmd:'mouse_frame',...fields});return true;},
    error: e => errors.push(e.message), changed: value => phases.push(value), timers, frames, now: () => time
  });
  const frame = async () => {if (transport.frame !== null) {const fn = callbacks.get(transport.frame); callbacks.delete(transport.frame); fn?.();} await flush();};
  const ack=()=>transport.acknowledge({ok:true,mouse_session:session,seq:transport.seq});
  return {transport, commands, errors, phases, frame, ack, advance: dt => time += dt};
}

test('gain has continuous slope at both ends and increases monotonically without sharp knees', () => {
  const gain=PointerAcceleration.gain;
  assert.equal(gain(0),.85);assert.equal(gain(2000),4);
  for(let speed=1;speed<=1500;speed++)assert.ok(gain(speed)+1e-12>=gain(speed-1));
  assert.ok(Math.abs(gain(40.01)-gain(40))<1e-8);
  assert.ok(Math.abs(gain(1400)-gain(1399.99))<1e-8);
});

test('equal finger motion at 60/120/240 Hz keeps travel within one percent', () => {
  const distances = [60,120,240].map(hz => {
    const a = new PointerAcceleration(); a.reset(0,0,0); let dx=0,dy=0;
    for(let i=1;i<=hz;i++) {const p=a.sample(i*400/hz,i*100/hz,i*1000/hz); dx+=p.dx;dy+=p.dy;}
    return [dx,dy];
  });
  for(const d of distances)assert.ok(Math.abs(d[0]/distances[0][0]-1)<.01,JSON.stringify(distances));
});

test('short timestamp history suppresses coordinate quantization and gain ramps gradually', () => {
  const a=new PointerAcceleration();a.reset(0,0,0);let x=0;
  const gain=[];
  for(let i=1;i<=150;i++) {x=Math.round(i*1.7);a.sample(x,0,i*8);if(i>10)gain.push(a.gain);}
  assert.ok(Math.max(...gain)-Math.min(...gain)<.035);
  const b=new PointerAcceleration();b.reset(0,0,0);const first=b.sample(16,0,8);
  assert.ok(first.dx>16*.85 && first.dx<16*4);b.sample(0,0,16);assert.ok(b.x===0);
  assert.deepEqual(b.sample(500,0,16),{dx:0,dy:0});
  assert.ok(b.sample(1,0,216).dx<1);
});

function swipe(distance,duration,hz=120,profile='standard') {
  const a=new PointerAcceleration(()=>profile);a.reset(0,0,0);let travel=0;
  const count=Math.max(1,Math.round(duration*hz/1000));
  for(let i=1;i<=count;i++)travel+=a.sample(distance*i/count,0,duration*i/count).dx;
  return travel;
}

test('equal-distance short flicks never travel less than slower swipes, at all input rates',()=>{
  for(const hz of [60,120,240,1000]) for(const profile of ['gentle','standard','strong']) {
    for(const distance of [50,100,200]) {
      let previous=0;
      for(const duration of [1000,500,250,160,100,60,40]) {
        const travel=swipe(distance,duration,hz,profile);
        assert.ok(travel+1e-8>=previous,JSON.stringify({hz,profile,distance,duration,travel,previous}));
        previous=travel;
      }
    }
  }
});

test('acceleration profiles separate slow precision from fast crossing and off preserves raw travel',()=>{
  for(const duration of [1000,160,60])assert.ok(Math.abs(swipe(100,duration,120,'off')-100)<1e-9);
  const slow=swipe(100,1000),fast=swipe(100,60);
  assert.ok(slow<100 && fast>slow*3.5);
  assert.ok(swipe(100,60,120,'gentle')<fast && swipe(100,60,120,'strong')>fast);
  for(const hz of [60,120,240,1000])assert.ok(Math.abs(swipe(100,60,hz)/fast-1)<.001);
});

test('fractional cumulative endpoints survive frames without per-frame rounding loss', async () => {
  const {transport:t,commands,frame,ack}=setup(); await t.start();
  for(let i=0;i<10;i++) {t.move(.26,-.26);await frame();ack();}
  const packet=commands.filter(c=>c.cmd==='mouse_frame').at(-1);
  assert.equal(packet.x,2.6);assert.equal(packet.y,-2.6);t.stop();
});

test('motion does not wait for return packets, clicks flush final position and preserve socket order', async () => {
  let resolve;
  const {transport:t,commands,frame}=setup({respond:cmd=>cmd==='mouse_click'?new Promise(r=>resolve=r):{}});
  await t.start();t.move(1,2);t.move(3,4);await frame();
  t.move(10,20);await frame(); // first frame has still not been acknowledged
  assert.equal(commands.filter(c=>c.cmd==='mouse_frame').length,2);
  t.move(20,30);t.click('right');t.move(7,8);await frame();
  assert.deepEqual(commands.map(c=>c.cmd),['mouse_start','mouse_frame','mouse_frame','mouse_frame','mouse_click','mouse_frame']);
  assert.equal(commands.at(-1).x,41);resolve({});t.stop();
});

test('bounded outstanding frames coalesce to newest cumulative point and recover without replay', async () => {
  const {transport:t,commands,frame,ack,advance}=setup();await t.start();
  for(let i=0;i<60;i++){t.move(1,0);await frame();advance(8);}
  assert.ok(t.outstanding.size<=24);
  assert.ok(commands.filter(c=>c.cmd==='mouse_frame').length<60);
  ack();await frame();assert.equal(commands.at(-1).x,60);
  assert.equal(t.outstanding.size,1);t.stop();
});

test('browser backpressure retains one latest endpoint and refuses clicks at stale positions', async()=>{
  let blocked=true;const a=setup({stream:()=>!blocked});await a.transport.start();
  a.transport.move(20,0);await a.frame();assert.equal(a.commands.length,1);
  a.transport.move(10,0);blocked=false;await a.frame();assert.equal(a.commands.at(-1).x,30);
  blocked=true;a.transport.move(10,0);a.transport.click('left');
  assert.equal(a.transport.session,null);assert.ok(!a.commands.some(c=>c.cmd==='mouse_click'));assert.equal(a.errors.length,1);
});

test('click refuses an expired acknowledgement window even with no new motion pending',async()=>{
  const a=setup();await a.transport.start();a.transport.move(1,0);await a.frame();
  a.advance(200);a.transport.click('left');
  assert.equal(a.transport.session,null);assert.ok(!a.commands.some(c=>c.cmd==='mouse_click'));
});

test('new touch samples can send immediately without a render frame, never repeat unchanged endpoints',async()=>{
  const a=setup();await a.transport.start();
  a.transport.move(1,0);a.transport.sampled();
  assert.equal(a.commands.at(-1).cmd,'mouse_frame');
  a.ack();a.advance(4);a.transport.move(1,0);a.transport.sampled();
  assert.equal(a.commands.filter(c=>c.cmd==='mouse_frame').length,2);
  a.transport.sampled();assert.equal(a.commands.filter(c=>c.cmd==='mouse_frame').length,2);
  a.transport.stop();
});

test('acknowledgement releases a coalesced endpoint immediately without waiting for the next render',async()=>{
  const a=setup();await a.transport.start();
  for(let i=0;i<24;i++){a.transport.move(1,0);a.transport.sampled();a.advance(2);}
  a.transport.move(7,0);a.transport.sampled();
  assert.equal(a.transport.outstanding.size,24);
  a.ack();
  assert.equal(a.commands.at(-1).x,31);
  assert.equal(a.transport.outstanding.size,1);a.transport.stop();
});

test('selected computer output rate is negotiated without claiming a new touch sample rate',async()=>{
  const sent=[];
  const t=new MouseTransport({send:async(cmd,fields)=>{sent.push({cmd,...fields});return cmd==='mouse_start'?{mouse_session:session,mouse_stream:2,mouse_output_hz:500}:{};},stream:()=>true,outputHz:()=>500});
  await t.start();assert.equal(sent[0].output_hz,500);assert.equal(t.actualOutputHz,500);t.stop();
});

test('PC without output-rate negotiation is rejected and released instead of falsely showing 1000 Hz',async()=>{
  const sent=[],errors=[];
  const t=new MouseTransport({send:async(cmd)=>{sent.push(cmd);return {mouse_session:session,mouse_stream:2};},stream:()=>true,error:e=>errors.push(e.message)});
  assert.equal(await t.start(),false);assert.equal(t.session,null);
  assert.ok(errors[0].includes('0.5.13'));assert.deepEqual(sent,['mouse_start','mouse_end']);
});

test('stream failure stops immediately; late error for an old mode cannot end a new one',async()=>{
  let fail=false;const a=setup({stream:()=>{if(fail)throw Error('closed');return true;}});await a.transport.start();
  a.transport.move(1,0);await a.frame();fail=true;a.transport.move(1,0);await a.frame();
  assert.equal(a.transport.session,null);assert.deepEqual(a.errors,['closed']);fail=false;await a.transport.start();
  a.transport.acknowledge({mouse_session:'b'.repeat(24),ok:false,error:'old'});assert.equal(a.transport.session,session);a.transport.stop();
});

test('late start response after cancel releases its session and never reenters mouse mode', async () => {
  const sent=[],phases=[];let resolve;
  const t = new MouseTransport({send:(cmd,fields)=>{sent.push({cmd,...fields});return cmd==='mouse_start'?new Promise(r=>resolve=r):Promise.resolve({});},changed:v=>phases.push(v)});
  const opening=t.start();t.stop();resolve({mouse_session:session,mouse_stream:2});await opening;
  assert.equal(t.session,null);assert.equal(phases.includes('mouse'),false);assert.equal(sent.at(-1).cmd,'mouse_end');
});

test('old PC is rejected clearly and its acquired mouse session is released',async()=>{
  const commands=[],errors=[];
  const t=new MouseTransport({send:async(cmd)=>{commands.push(cmd);return {mouse_session:session};},error:e=>errors.push(e.message)});
  assert.equal(await t.start(),false);assert.equal(t.session,null);assert.ok(errors[0].includes('0.5.12'));assert.deepEqual(commands,['mouse_start','mouse_end']);
});

test('40/80 ms RTT cannot reduce the movement stream below the display frame rate',async()=>{
  const {simulate}=require('../scripts/measure_mouse_motion.cjs');
  const module=require('../android/app/src/main/assets/mouse.js');
  for(const rtt of [40,80]){
    const report=await simulate(module,rtt,60);
    assert.ok(report.packets_per_second>=57,JSON.stringify(report));assert.equal(report.final_x,720);
  }
});

function padSetup(options={}) {
  let clock=0,id=0; const jobs=new Map(),commands=[],pulses=[];
  const timers={setTimeout(fn,delay){jobs.set(++id,{fn,at:clock+delay});return id;},clearTimeout(id){jobs.delete(id);},setInterval(){return ++id;},clearInterval(){}};
  const frames={requestAnimationFrame(fn){return timers.setTimeout(fn,16);},cancelAnimationFrame(id){timers.clearTimeout(id);}};
  const send=async(cmd,fields)=>{commands.push({cmd,...fields});return cmd==='mouse_start'?{mouse_session:session,mouse_stream:2,mouse_output_hz:1000}:{};};
  let pad;
  const video=new GestureEngine({send,timers,now:()=>clock,tap:(...args)=>pad.videoTap(...args)});
  const stream=fields=>{commands.push({cmd:'mouse_frame',...fields});return true;};
  pad=new TouchpadController({video,send,stream,timers,frames,now:()=>clock,haptic:()=>pulses.push(clock),...options});
  const advance=async(ms)=>{clock+=ms;for(const [key,job] of [...jobs])if(job.at<=clock){jobs.delete(key);job.fn();}await flush();};
  const tap=async(x=50,y=50)=>{pad.down(x,y,400,800,clock);await advance(30);pad.up(x,y,clock);await flush();};
  return {pad,commands,pulses,advance,tap};
}

test('video single tap waits; double tap enters mouse without toggling video', async()=>{
  const a=padSetup();await a.tap();assert.deepEqual(a.commands,[]);await a.advance(280);assert.equal(a.commands[0].cmd,'toggle');
  const b=padSetup();await b.tap();await b.advance(80);await b.tap();await b.advance(500);
  assert.equal(b.pad.phase,'mouse');assert.deepEqual(b.commands.map(c=>c.cmd),['mouse_start']);b.pad.cancel();
});

test('mouse default left tap, configurable right tap and long right press never control video', async()=>{
  let button='left';const a=padSetup({tapButton:()=>button});await a.pad.enter();
  await a.tap();button='right';await a.tap();
  a.pad.down(50,50,400,800,1000);await a.advance(500);await a.advance(16);a.pad.up(50,50,1600);await a.advance(16);
  assert.deepEqual(a.commands.map(c=>c.cmd),['mouse_start','mouse_click','mouse_click','mouse_click']);
  assert.deepEqual(a.commands.filter(c=>c.cmd==='mouse_click').map(c=>c.button),['left','right','right']);
  assert.equal(a.pulses.length,2);a.pad.cancel();
});

test('mouse movement and finger reposition never seek/boost/click or jump to touch coordinates',async()=>{
  const a=padSetup();await a.pad.enter();a.pad.down(20,20,400,800,0);a.pad.move(120,220,100);await a.advance(16);a.pad.up(120,220,110);
  a.pad.down(300,500,400,800,200);a.pad.move(301,500,220);await a.advance(16);a.pad.up(305,500,240);await a.advance(16);
  assert.ok(a.commands.every(c=>['mouse_start','mouse_frame'].includes(c.cmd)));
  assert.ok(a.commands.filter(c=>c.cmd==='mouse_frame').at(-1).x-a.commands.filter(c=>c.cmd==='mouse_frame')[0].x<10);a.pad.cancel();
});

test('mouse double click sends two default left clicks and keeps mouse mode until explicit exit',async()=>{
  const b=padSetup();await b.pad.enter();await b.tap();await b.advance(80);await b.tap();await b.advance(300);
  assert.equal(b.pad.phase,'mouse');assert.equal(b.commands.filter(c=>c.cmd==='mouse_click').length,2);b.pad.cancel();
  assert.ok(b.commands.filter(c=>c.cmd==='mouse_click').every(c=>c.button==='left'));
  assert.equal(b.pad.phase,'video');
});

test('cancel/background clears delayed video taps and held mouse right-click timer',async()=>{
  const a=padSetup();await a.tap();a.pad.cancel();await a.advance(1000);assert.deepEqual(a.commands,[]);
  await a.pad.enter();a.pad.down(50,50,400,800,0);a.pad.cancel();await a.advance(1000);
  assert.deepEqual(a.commands.map(c=>c.cmd),['mouse_start','mouse_end']);
});
