const { test } = require('node:test');
const assert = require('node:assert/strict');
const { HoldControl } = require('../android/app/src/main/assets/remote.js');
const flush = () => new Promise(resolve => setImmediate(resolve));

test('default three gears include slow motion and can return to the original starting gear', async () => {
  const commands = []; let pulses = 0;
  const control = new HoldControl({send: async (cmd, fields) => commands.push({cmd, ...fields}), haptic: () => pulses++, timers: {setInterval: () => 1, clearInterval() {}}});
  control.start(200); control.move(151); control.move(150); control.move(199); control.move(248); control.move(1000); control.stop();
  await flush();
  assert.deepEqual(commands.filter(m => m.rate).map(m => m.rate), [2, .5, 2, 3]);
  assert.equal(pulses, 4);
});

test('five custom gears move in order, stop at the ends, and a single gear never switches', async () => {
  const changes = [];
  const control = new HoldControl({send: async () => {}, rate: () => .75, gears: () => [.5, .75, 1.25, 2.25, 2.75], changed: value => changes.push(value), timers: {setInterval: () => 1, clearInterval() {}}});
  control.start(100); control.move(148); control.move(196); control.move(244); control.move(500); control.move(452); control.stop(); await flush();
  assert.deepEqual(changes, [.75, 1.25, 2.25, 2.75, 2.25, null]);
  changes.length = 0; control.gears = () => [1.5]; control.rate = () => 1.5;
  control.start(100); control.move(900); control.move(0); control.stop(); await flush();
  assert.deepEqual(changes, [1.5, null]);
});
test('traditional speed button always releases exactly once on cancel or repeated release', async () => {
  const commands = [], intervals = new Set();
  const control = new HoldControl({ send: async cmd => commands.push(cmd), rate: () => 2, hint() {}, error(e) { throw e; }, timers: { setInterval(fn) { intervals.add(fn); return fn; }, clearInterval(fn) { intervals.delete(fn); } } });
  control.start(); await flush();
  control.stop(); control.stop(); await flush();
  assert.deepEqual(commands, ['speed_start', 'speed_end']);
  assert.equal(intervals.size, 0);
});
test('rejected speed request stops heartbeats and attempts restore', async () => {
  const commands = [], errors = [], intervals = new Set();
  const control = new HoldControl({ send: async cmd => { commands.push(cmd); if (cmd === 'speed_start') throw new Error('unsupported'); }, rate: () => 2, hint() {}, error: e => errors.push(e.message), timers: { setInterval(fn) { intervals.add(fn); return fn; }, clearInterval(fn) { intervals.delete(fn); } } });
  control.start(); await flush(); await flush();
  assert.deepEqual(commands, ['speed_start', 'speed_end']);
  assert.equal(intervals.size, 0);
  assert.ok(errors.includes('unsupported'));
});

test('gear detents vibrate only on start and actual transitions, with hysteresis', async () => {
  const commands = [], pulses = [], changes = [];
  const control = new HoldControl({ send: async (cmd, fields) => commands.push({ cmd, ...fields }), gears: () => [2, 3], haptic: () => pulses.push('pulse'), changed: value => changes.push(value), timers: { setInterval: () => 1, clearInterval() {} } });
  control.start(100);
  for (const x of [110, 135, 147]) control.move(x);
  assert.equal(pulses.length, 1);
  control.move(148); // 2 -> 3.
  for (const x of [149, 150, 147, 149, 140, 120, 103]) control.move(x);
  assert.equal(pulses.length, 2);
  control.move(102); // 3 -> 2, 48 pixels back from the farthest point.
  for (const x of [99, 50, 20]) control.move(x);
  assert.equal(pulses.length, 3);
  control.stop(); control.stop(); await flush();
  assert.deepEqual(commands, [{ cmd: 'speed_start', rate: 2 }, { cmd: 'speed_change', rate: 3 }, { cmd: 'speed_change', rate: 2 }, { cmd: 'speed_end' }]);
  assert.deepEqual(changes, [2, 3, 2, null]);
});

test('long travel within a gear requires only 48px in reverse to switch back', async () => {
  let pulses = 0;
  const commands = [];
  const control = new HoldControl({ send: async (cmd, fields) => commands.push({ cmd, ...fields }), gears: () => [2, 3], haptic: () => pulses++, timers: { setInterval: () => 1, clearInterval() {} } });
  control.start(60); control.move(120); control.move(300); control.move(253);
  assert.equal(pulses, 2);
  control.move(252); control.move(150); control.move(197);
  assert.equal(pulses, 3);
  control.move(198); control.stop(); await flush();
  assert.equal(pulses, 4);
  assert.deepEqual(commands.filter(m => m.cmd === 'speed_change').map(m => m.rate), [3, 2, 3]);
});

test('release is sent after all gear commands even before acknowledgements', async () => {
  const commands = [];
  const control = new HoldControl({ send: (cmd, fields) => { commands.push({ cmd, ...fields }); return new Promise(() => {}); }, timers: { setInterval: () => 1, clearInterval() {} } });
  control.start(50); control.move(110); control.move(50); control.stop();
  await flush();
  assert.deepEqual(commands.map(m => m.cmd), ['speed_start', 'speed_change', 'speed_change', 'speed_end']);
});

test('stale failed request cannot stop a newer hold or reset its UI', async () => {
  let rejectFirst;
  const changes = [], errors = [];
  const control = new HoldControl({ send: cmd => cmd === 'speed_start' && !rejectFirst ? new Promise((_, reject) => { rejectFirst = reject; }) : Promise.resolve({}), changed: rate => changes.push(rate), error: e => errors.push(e), timers: { setInterval: () => 1, clearInterval() {} } });
  control.start(); await flush(); control.stop(); control.start(); await flush();
  rejectFirst(new Error('old failure')); await flush();
  assert.ok(control.current);
  assert.equal(changes.at(-1), 2);
  assert.equal(errors.length, 0);
  control.stop(); await flush();
});

test('heartbeat failure stops the hold and release never vibrates', async () => {
  let heartbeat; let pulses = 0;
  const errors = [], commands = [];
  const control = new HoldControl({ send: async cmd => { commands.push(cmd); if (cmd === 'speed_keep') throw new Error('offline'); }, haptic: () => pulses++, error: e => errors.push(e.message), timers: { setInterval: fn => { heartbeat = fn; return fn; }, clearInterval() {} } });
  control.start(); await flush(); heartbeat(); await flush(); await flush();
  assert.equal(control.current, null);
  assert.deepEqual(commands, ['speed_start', 'speed_keep', 'speed_end']);
  assert.equal(pulses, 1); assert.deepEqual(errors, ['offline']);
});
