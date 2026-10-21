const { test } = require('node:test');
const assert = require('node:assert/strict');
const { HoldControl } = require('../android/app/src/main/assets/remote.js');
const flush = () => new Promise(resolve => setImmediate(resolve));
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
