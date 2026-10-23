const {test} = require('node:test');
const assert = require('node:assert/strict');
const {PointerAcceleration, MouseTransport, TouchpadController} = require('../android/app/src/main/assets/mouse.js');
const {GestureEngine} = require('../android/app/src/main/assets/gestures.js');
const flush = () => new Promise(resolve => setImmediate(resolve));
const session = 'a'.repeat(24);

function setup(respond = () => ({})) {
  let time = 0, id = 0;
  const callbacks = new Map(), commands = [], errors = [], phases = [];
  const timers = {setInterval(fn) {callbacks.set(++id, fn); return id;}, clearInterval(id) {callbacks.delete(id);}};
  const frames = {requestAnimationFrame(fn) {callbacks.set(++id, fn); return id;}, cancelAnimationFrame(id) {callbacks.delete(id);}};
  const transport = new MouseTransport({
    send: (cmd, fields) => {commands.push({cmd, ...fields}); return Promise.resolve(cmd === 'mouse_start' ? {mouse_session:session} : respond(cmd, fields));},
    error: e => errors.push(e.message), changed: value => phases.push(value), timers, frames, now: () => time
  });
  const frame = async () => {if (transport.frame !== null) {const fn = callbacks.get(transport.frame); callbacks.delete(transport.frame); fn?.();} await flush();};
  return {transport, commands, errors, phases, frame, advance: dt => time += dt};
}

test('linear gain is continuous, precise at low speed and capped at fast speed', () => {
  const gain = speed => {const a = new PointerAcceleration(); a.reset(0,0,0); return a.sample(speed/100,0,10).dx/(speed/100);};
  assert.ok(gain(1) < .66);
  assert.ok(gain(899) < gain(900));
  assert.ok(Math.abs(gain(899)-gain(900)) < .004);
  assert.equal(gain(1800), 3.5);
  for(let speed=20;speed<=1000;speed+=20) assert.ok(gain(speed)+1e-12>=gain(speed-1));
});

test('equal finger motion at 60/120/240 Hz yields equal cursor travel', () => {
  const distances = [60,120,240].map(hz => {
    const a = new PointerAcceleration(); a.reset(0,0,0); let dx=0,dy=0;
    for(let i=1;i<=hz;i++) {const p=a.sample(i*400/hz,i*100/hz,i*1000/hz); dx+=p.dx;dy+=p.dy;}
    return [dx,dy];
  });
  for(const d of distances) {assert.ok(Math.abs(d[0]-distances[0][0])<.0001);assert.ok(Math.abs(d[1]-distances[0][1])<.0001);}
});

test('direction reversal and pauses discard old high speed; duplicate timestamps are ignored', () => {
  const a = new PointerAcceleration(); a.reset(0,0,0); a.sample(20,0,10);
  const reverse=a.sample(19,0,20);
  assert.ok(reverse.dx < 0 && reverse.dx > -1);
  assert.deepEqual(a.sample(500,0,20),{dx:0,dy:0});
  assert.ok(a.sample(20,0,220).dx<.7);
  a.reset(50,50,230); assert.ok(a.sample(51,50,250).dx<1);
});

test('subpixel fractions survive frames and lift/reposition without artificial motion', async () => {
  const {transport:t,commands,frame}=setup(); await t.start();
  for(let i=0;i<10;i++) {t.move(.26,-.26);await frame();}
  assert.equal(commands.filter(c=>c.cmd==='mouse_move').reduce((s,c)=>s+c.dx,0),2);
  assert.equal(commands.filter(c=>c.cmd==='mouse_move').reduce((s,c)=>s+c.dy,0),-2);
  t.stop();
});

test('merges samples per frame with one command in flight and click follows final motion', async () => {
  let resolve;
  const {transport:t,commands,frame}=setup((cmd)=> cmd==='mouse_move' ? new Promise(r=>resolve=r) : {});
  await t.start(); t.move(1,2);t.move(3,4);await frame();
  assert.deepEqual(commands.at(-1),{cmd:'mouse_move',dx:4,dy:6,mouse_session:session});
  t.move(10,20);t.move(20,30);await frame(); t.click('right');t.move(7,8); await flush();
  assert.equal(commands.length,2);
  resolve({}); await flush(); await frame();
  assert.equal(commands.at(-1).dx,30);
  resolve({}); await flush(); await frame();
  assert.equal(commands.at(-1).cmd,'mouse_click');
  await frame(); assert.equal(commands.at(-1).dx,7); t.stop();
});

test('network backlog drops stale unsent motion and failure exits without replay on reconnect', async () => {
  let reject;
  const {transport:t,commands,frame,advance,errors}=setup(()=>new Promise((_,r)=>reject=r));
  await t.start();t.move(1,1);await frame();t.move(100,100);advance(200);t.move(2,2);
  assert.equal(t.queue.length,1);assert.equal(t.queue[0].dx,2);
  reject(new Error('network'));await flush();
  assert.equal(t.session,null);assert.deepEqual(t.queue,[]);assert.deepEqual(errors,['network']);
  await t.start();await frame();assert.equal(commands.filter(c=>c.cmd==='mouse_move').length,1);t.stop();
});

test('late start response after cancel releases its session and never reenters mouse mode', async () => {
  const sent=[],phases=[];let resolve;
  const t = new MouseTransport({send:(cmd,fields)=>{sent.push({cmd,...fields});return cmd==='mouse_start'?new Promise(r=>resolve=r):Promise.resolve({});},changed:v=>phases.push(v)});
  const opening=t.start();t.stop();resolve({mouse_session:session});await opening;
  assert.equal(t.session,null);assert.equal(phases.includes('mouse'),false);
  assert.equal(sent.at(-1).cmd,'mouse_end');
});

function padSetup(options={}) {
  let clock=0,id=0; const jobs=new Map(),commands=[],pulses=[];
  const timers={setTimeout(fn,delay){jobs.set(++id,{fn,at:clock+delay});return id;},clearTimeout(id){jobs.delete(id);},setInterval(){return ++id;},clearInterval(){}};
  const frames={requestAnimationFrame(fn){return timers.setTimeout(fn,16);},cancelAnimationFrame(id){timers.clearTimeout(id);}};
  const send=async(cmd,fields)=>{commands.push({cmd,...fields});return cmd==='mouse_start'?{mouse_session:session}:{};};
  let pad;
  const video=new GestureEngine({send,timers,now:()=>clock,tap:(...args)=>pad.videoTap(...args)});
  pad=new TouchpadController({video,send,timers,frames,now:()=>clock,haptic:()=>pulses.push(clock),...options});
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
  assert.ok(a.commands.every(c=>['mouse_start','mouse_move'].includes(c.cmd)));
  assert.ok(a.commands.filter(c=>c.cmd==='mouse_move').at(-1).dx<10);a.pad.cancel();
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
