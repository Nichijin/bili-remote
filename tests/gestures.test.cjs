const { test } = require('node:test');
const assert = require('node:assert/strict');
const { GestureEngine } = require('../android/app/src/main/assets/gestures.js');
const flush = () => new Promise(resolve => setImmediate(resolve));
function setup(options = {}) {
  const commands = [], callbacks = new Map(); let id = 0, clock = 0;
  const timers = { setTimeout(fn, delay = 0) { callbacks.set(++id, {fn, at: clock + delay}); return id; }, clearTimeout(i) { callbacks.delete(i); }, setInterval() { return ++id; }, clearInterval() {} };
  const state = {time: 50, seek_start: 0, seek_end: 1000, media_key: 'video-a'};
  const engine = new GestureEngine({ send: (cmd, fields) => { commands.push({ cmd, ...fields }); return Promise.resolve(options.respond ? options.respond(cmd, fields) : state); }, timers, now: () => clock, ...options });
  const advance = ms => { clock += ms; for (const [key, task] of [...callbacks]) if (task.at <= clock) { callbacks.delete(key); task.fn(); } };
  return { engine, commands, advance, fireHold: () => { const [key, task] = [...callbacks][0]; callbacks.delete(key); task.fn(); } };
}

test('tap emits only toggle', async () => {
  const { engine, commands } = setup(); engine.down(50, 50, 400, 800); engine.up(50, 50); await flush();
  assert.deepEqual(commands, [{ cmd: 'toggle' }]);
});

test('horizontal drag updates continuously, coalesces movement and flushes fractional final position', async () => {
  const { engine, commands, advance } = setup();
  engine.down(0, 50, 400, 800); engine.move(100, 55); await flush();
  assert.deepEqual(commands, [{cmd:'status'}, {cmd:'seek_to', position:80, media_key:'video-a'}]);
  engine.move(200, 55); engine.move(210, 55); engine.move(220, 55); await flush();
  assert.equal(commands.length, 2);
  advance(80); await flush();
  assert.equal(commands.at(-1).position, 116);
  engine.up(251.25, 55); await flush();
  assert.equal(commands.at(-1).position, 125.375);
  assert.ok(commands.every(m => ['status', 'seek_to'].includes(m.cmd)));
});

test('up swipe increases volume without triggering seek', async () => {
  const { engine, commands } = setup(); engine.down(50, 400, 400, 800); engine.move(52, 200); engine.up(52, 200); await flush();
  assert.ok(commands.every(c => c.cmd === 'volume' && c.delta > 0));
  assert.equal(commands.reduce((s, c) => s + c.delta, 0), .25);
});

test('cancel before status arrives discards a drag without seeking or showing a stale error', async () => {
  let respond; const errors = [];
  const {engine, commands} = setup({respond: () => new Promise(resolve => respond = resolve), error: e => errors.push(e)});
  engine.down(0, 0, 400, 800); engine.move(100, 0); await flush(); engine.cancel();
  respond({time:50, seek_start:0, seek_end:100, media_key:'old'}); await flush();
  assert.deepEqual(commands, [{cmd:'status'}]); assert.deepEqual(errors, []);
});

test('release reapplies the final position even when playback advanced while the finger was stationary', async () => {
  const {engine, commands} = setup();
  engine.down(0, 0, 400, 800); engine.move(100, 0); await flush();
  engine.up(100, 0); await flush();
  assert.deepEqual(commands.filter(m => m.cmd === 'seek_to').map(m => m.position), [80,80]);
});

test('only one seek is in flight, next drag waits for the final previous position', async () => {
  let unblock, position = 50, first = true;
  const {engine, commands} = setup({respond: (cmd, fields) => {
    if (cmd === 'status') return {time:position, seek_start:0, seek_end:1000, media_key:'same'};
    if (first) { first = false; return new Promise(resolve => unblock = () => { position = fields.position; resolve({}); }); }
    position = fields.position; return {};
  }});
  engine.down(0, 0, 400, 800); engine.move(100, 0); await flush();
  engine.move(200, 0); engine.up(250, 0);
  engine.down(0, 0, 400, 800); engine.move(100, 0); engine.up(100, 0); await flush();
  assert.equal(commands.filter(m => m.cmd === 'status').length, 1);
  unblock(); await flush(); await flush();
  assert.deepEqual(commands.filter(m => m.cmd === 'seek_to').map(m => m.position), [80, 125, 155]);
});

test('drag clamps to actual seekable range and invalid timelines never seek', async () => {
  const {engine, commands} = setup({respond: () => ({time:50, seek_start:20, seek_end:80, media_key:'range'})});
  engine.down(0, 0, 400, 800); engine.move(900, 0); await flush(); engine.up(-900, 0); await flush();
  assert.deepEqual(commands.filter(m => m.cmd === 'seek_to').map(m => m.position), [80,20]);
  const errors = [], unsupported = setup({respond: () => ({}), error: e => errors.push(e.message)});
  unsupported.engine.down(0, 0, 400, 800); unsupported.engine.up(100, 0); await flush();
  assert.deepEqual(unsupported.commands, [{cmd:'status'}]); assert.equal(errors.length, 1);
});
test('cancelled hold restores rate and never pauses', async () => {
  const { engine, commands, fireHold } = setup(); engine.down(50, 50, 400, 800); fireHold(); await flush();
  engine.cancel(); engine.up(50, 50); await flush();
  assert.deepEqual(commands.map(c => c.cmd), ['speed_start', 'speed_end']);
});
test('cancelled pending touch does nothing', async () => {
  const { engine, commands } = setup(); engine.down(50, 50, 400, 800); engine.cancel(); await flush();
  assert.deepEqual(commands, []);
});

test('touchpad long press shares gear switching and haptics without seeking', async () => {
  let pulses = 0;
  const { engine, commands, fireHold } = setup({ haptic: () => pulses++ });
  engine.down(120, 300, 400, 800);
  assert.equal(pulses, 0);
  fireHold(); engine.move(180, 310); engine.move(190, 250); engine.move(120, 200);
  engine.up(120, 200); await flush();
  assert.deepEqual(commands, [{ cmd: 'speed_start', rate: 2 }, { cmd: 'speed_change', rate: 3 }, { cmd: 'speed_change', rate: 2 }, { cmd: 'speed_end' }]);
  assert.equal(pulses, 3);
});

test('normal taps, swipes and cancelled pending holds do not vibrate', async () => {
  let pulses = 0;
  const { engine } = setup({ haptic: () => pulses++ });
  engine.down(20, 30, 400, 800); engine.up(20, 30);
  engine.down(20, 30, 400, 800); engine.move(130, 30); engine.up(130, 30);
  engine.down(20, 300, 400, 800); engine.move(20, 100); engine.up(20, 100);
  engine.down(20, 30, 400, 800); engine.cancel(); await flush();
  assert.equal(pulses, 0);
});

test('releasing at a new coordinate does not vibrate or change hold gear', async () => {
  let pulses = 0;
  const { engine, commands, fireHold } = setup({ haptic: () => pulses++ });
  engine.down(120, 300, 400, 800); fireHold(); engine.up(240, 300); await flush();
  assert.equal(pulses, 1);
  assert.deepEqual(commands.map(m => m.cmd), ['speed_start', 'speed_end']);
});
