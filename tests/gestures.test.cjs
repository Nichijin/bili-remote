const { test } = require('node:test');
const assert = require('node:assert/strict');
const { GestureEngine } = require('../android/app/src/main/assets/gestures.js');
const flush = () => new Promise(resolve => setImmediate(resolve));
function setup() {
  const commands = [], callbacks = new Map(); let id = 0;
  const timers = { setTimeout(fn) { callbacks.set(++id, fn); return id; }, clearTimeout(i) { callbacks.delete(i); }, setInterval(fn) { callbacks.set(++id, fn); return id; }, clearInterval(i) { callbacks.delete(i); } };
  const engine = new GestureEngine({ send: (cmd, fields) => { commands.push({ cmd, ...fields }); return Promise.resolve({}); }, timers });
  return { engine, commands, fireHold: () => [...callbacks.values()][0]() };
}
test('tap emits only toggle', async () => {
  const { engine, commands } = setup(); engine.down(50, 50, 400, 800); engine.up(50, 50); await flush();
  assert.deepEqual(commands, [{ cmd: 'toggle' }]);
});
test('horizontal swipe never pauses and seeks only on release', async () => {
  const { engine, commands } = setup(); engine.down(50, 50, 400, 800); engine.move(150, 55); await flush();
  assert.equal(commands.length, 0); engine.up(250, 55); await flush();
  assert.deepEqual(commands, [{ cmd: 'seek', delta: 60 }]);
});
test('up swipe increases volume without triggering seek', async () => {
  const { engine, commands } = setup(); engine.down(50, 400, 400, 800); engine.move(52, 200); engine.up(52, 200); await flush();
  assert.ok(commands.every(c => c.cmd === 'volume' && c.delta > 0));
  assert.equal(commands.reduce((s, c) => s + c.delta, 0), .25);
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
