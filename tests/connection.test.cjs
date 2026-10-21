const { test } = require('node:test');
const assert = require('node:assert/strict');
const { RemoteConnection, normalizeHost } = require('../android/app/src/main/assets/connection.js');

class Socket {
  static instances = [];
  constructor(url) { this.url = url; this.readyState = 0; this.messages = []; Socket.instances.push(this); }
  open() { this.readyState = 1; this.onopen(); }
  receive(message) { this.onmessage({ data: JSON.stringify(message) }); }
  send(message) { this.messages.push(JSON.parse(message)); }
  close() { this.readyState = 3; this.onclose?.(); }
}
function setup() {
  const config = { device_id: 'phone-1234', device_name: 'test' }, states = [];
  const timers = { setTimeout() { return 1; }, clearTimeout() {} };
  const connection = new RemoteConnection({ config, persist() {}, state: state => states.push(state), WebSocketClass: Socket, timers });
  return { connection, config, states };
}
test('manual addresses are normalized, deduplicated and saved even when offline', () => {
  const { connection, config } = setup();
  connection.connect('192.168.1.5', '', { manual: true });
  connection.connect('192.168.1.5:8765', '', { manual: true });
  assert.equal(config.history.length, 1);
  assert.equal(config.history[0].host, '192.168.1.5:8765');
  assert.throws(() => normalizeHost('192.168.1.5:99999'));
  assert.throws(() => normalizeHost('example.com/anything'));
});
test('first connection asks for PIN and saved reconnect does not send it again', () => {
  const { connection, config, states } = setup();
  connection.connect('192.168.1.5', 'computer-1234');
  let socket = connection.socket; socket.open(); socket.receive({ type: 'auth', ok: false, code: 'pair_required', computer_id: 'computer-1234' });
  assert.equal(states.at(-1).phase, 'pair');
  assert.equal(connection.needsPin, true);
  connection.connect('192.168.1.5', 'computer-1234', { pin: '123456' });
  socket = connection.socket; socket.open();
  assert.equal(socket.messages[0].pairing_code, '123456');
  socket.receive({ type: 'auth', ok: true, computer_id: 'computer-1234', token: 'stored-secret', computer_name: 'PC' });
  connection.suspend(); connection.resume(); socket = connection.socket; socket.open();
  assert.equal(socket.messages[0].token, 'stored-secret');
  assert.equal(socket.messages[0].pairing_code, '');
  assert.equal(config.credentials['computer-1234'], 'stored-secret');
});
test('discovery finds changed IP of the remembered computer and does not switch while connected', () => {
  const { connection, config } = setup();
  config.computer_id = 'computer-1234'; config.host = '192.168.1.5:8765';
  connection.connect(config.host, config.computer_id);
  connection.discovered([{ computer_id: 'computer-1234', host: '192.168.1.20:8765' }]);
  assert.equal(connection.socket.url, 'ws://192.168.1.20:8765');
  const socket = connection.socket; socket.open(); socket.receive({ type: 'auth', ok: true, computer_id: 'computer-1234', token: 'secret' });
  connection.discovered([{ computer_id: 'computer-5678', host: '192.168.1.30:8765' }]);
  assert.equal(connection.socket, socket);
});
test('a rejected PIN does not cause automatic retry loops', () => {
  const { connection } = setup();
  connection.connect('192.168.1.5', 'computer-1234');
  const socket = connection.socket; socket.open(); socket.receive({ type: 'auth', ok: false, code: 'pair_invalid' }); socket.close();
  connection.discovered([{ computer_id: 'computer-1234', host: '192.168.1.20:8765' }]);
  connection.reconnect();
  assert.equal(connection.socket, socket);
});
test('stale responses from a previous computer cannot overwrite the active connection', () => {
  const { connection, config } = setup();
  connection.connect('192.168.1.5', 'computer-1234'); const old = connection.socket;
  connection.connect('192.168.1.6', 'computer-5678');
  old.receive({ type: 'auth', ok: true, computer_id: 'computer-1234', token: 'wrong' });
  assert.equal(config.computer_id, 'computer-5678');
  assert.equal(connection.connected, false);
});
test('offline manual address remains saved while reconnect can recover a known online computer', () => {
  const { connection, config } = setup();
  config.credentials['known-computer'] = 'secret';
  connection.connect('192.168.1.99', '', { manual: true });
  connection.discovered([{ computer_id: 'known-computer', host: '192.168.1.10:8765' }]);
  connection.socket.close();
  connection.reconnect();
  assert.equal(connection.socket.url, 'ws://192.168.1.10:8765');
  assert.ok(config.history.some(item => item.host === '192.168.1.99:8765'));
});
