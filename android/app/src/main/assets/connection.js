(function (root) {
  function normalizeHost(value) {
    value = String(value || "").trim().replace(/^(?:https?|wss?):\/\//, "").replace(/\/$/, "");
    if (!/^[a-zA-Z0-9.-]+(?::\d{1,5})?$/.test(value)) throw new Error("请填写电脑 IP 或主机名，例如 192.168.1.10");
    const pieces = value.split(":");
    const port = pieces.length === 2 ? Number(pieces[1]) : 8765;
    if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("端口必须在 1 到 65535 之间");
    return `${pieces[0]}:${port}`;
  }

  class RemoteConnection {
    constructor({ config, persist, state = () => {}, discovery = () => {}, WebSocketClass = root.WebSocket, timers = root }) {
      Object.assign(this, { config, persist, stateChanged: state, discoveryChanged: discovery, WebSocketClass, timers });
      config.credentials ||= {};
      config.hostIds ||= {};
      config.history = Array.isArray(config.history) ? config.history.slice(0, 10) : [];
      this.socket = null;
      this.pending = new Map();
      this.connected = false;
      this.connecting = false;
      this.needsPin = false;
      this.active = true;
      this.generation = 0;
      this.nextId = 1;
      this.failures = 0;
      this.computers = [];
    }
    state(phase, text, fields = {}) { this.stateChanged({ phase, text, ...fields }); }
    record(host, computerId = "", name = "", manual = false) {
      const previous = this.config.history.find(item => item.host === host) || {};
      const entry = { host, computer_id: computerId || previous.computer_id || "", name: name || previous.name || host, manual: manual || Boolean(previous.manual), lastUsed: Date.now() };
      this.config.history = [entry, ...this.config.history.filter(item => item.host !== host)].slice(0, 10);
      this.persist();
    }
    clearPending(reason) {
      for (const item of this.pending.values()) { this.timers.clearTimeout(item.timer); item.reject(new Error(reason)); }
      this.pending.clear();
    }
    connect(host, computerId = "", { pin = "", manual = false } = {}) {
      host = normalizeHost(host);
      if (this.connecting && this.host === host && !pin && !manual) return;
      const generation = ++this.generation;
      this.timers.clearTimeout(this.retry);
      this.timers.clearTimeout(this.deadline);
      if (this.socket) this.socket.close();
      this.clearPending("连接正在切换");
      this.host = host;
      this.connected = false;
      this.connecting = true;
      this.needsPin = false;
      this.config.host = host;
      this.config.computer_id = computerId || this.config.hostIds[host] || "";
      if (manual) this.record(host, this.config.computer_id, "", true);
      this.persist();
      if (!this.active) { this.connecting = false; return; }
      this.state("connecting", "正在连接电脑…", { host });
      const ws = new this.WebSocketClass(`ws://${host}`);
      this.socket = ws;
      this.deadline = this.timers.setTimeout(() => {
        if (this.generation === generation && !this.connected) ws.close();
      }, 3500);
      ws.onopen = () => {
        if (generation !== this.generation) return;
        ws.send(JSON.stringify({ role: "remote", device_id: this.config.device_id, device_name: this.config.device_name, token: this.config.credentials[this.config.computer_id] || "", pairing_code: pin }));
      };
      ws.onmessage = event => {
        if (generation !== this.generation) return;
        let message;
        try { message = JSON.parse(event.data); } catch { return; }
        if (message.type === "auth") {
          this.timers.clearTimeout(this.deadline);
          this.connecting = false;
          if (message.ok) {
            if (typeof message.computer_id !== "string" || typeof message.token !== "string") { ws.close(); return; }
            this.connected = true;
            this.failures = 0;
            this.config.computer_id = message.computer_id;
            this.config.computer_name = message.computer_name || host;
            this.config.hostIds[host] = message.computer_id;
            this.config.credentials[message.computer_id] = message.token;
            this.record(host, message.computer_id, this.config.computer_name, manual);
            this.state("connected", "已连接 · 下次自动重连", { host, name: this.config.computer_name });
          } else {
            this.needsPin = true;
            this.state(message.code === "rate_limited" ? "error" : "pair", message.error || "请输入电脑配对码", { host, computer_id: message.computer_id || this.config.computer_id, code: message.code });
          }
          return;
        }
        const item = this.pending.get(message.id);
        if (!item) return;
        this.timers.clearTimeout(item.timer);
        this.pending.delete(message.id);
        if (message.ok) item.resolve(message.result || {}); else item.reject(new Error(message.error || "操作失败"));
      };
      ws.onclose = () => {
        if (generation !== this.generation) return;
        this.timers.clearTimeout(this.deadline);
        this.connected = this.connecting = false;
        this.clearPending("连接已断开");
        if (!this.active || this.needsPin) return;
        this.state("disconnected", "正在等待电脑上线…", { host });
        const delay = Math.min(8000, 1000 * 2 ** Math.min(this.failures++, 3));
        this.retry = this.timers.setTimeout(() => this.reconnect(), delay);
      };
      ws.onerror = () => {};
    }
    reconnect() {
      if (!this.active || this.connected || this.connecting || this.needsPin) return;
      const remembered = this.computers.find(item => item.computer_id === this.config.computer_id) || (!this.config.computer_id && this.computers.find(item => this.config.credentials[item.computer_id]));
      if (remembered) this.connect(remembered.host, remembered.computer_id);
      else if (this.config.host) this.connect(this.config.host, this.config.computer_id);
    }
    discovered(computers) {
      this.computers = computers.filter(item => typeof item.computer_id === "string" && typeof item.host === "string");
      this.discoveryChanged(this.computers);
      if (!this.active || this.connected || this.needsPin) return;
      const remembered = this.computers.find(item => item.computer_id === this.config.computer_id);
      if (remembered && remembered.host !== this.host) { this.connect(remembered.host, remembered.computer_id); return; }
      if (this.connecting) return;
      const known = remembered || this.computers.find(item => this.config.credentials[item.computer_id]);
      if (known) this.connect(known.host, known.computer_id);
      else if (!this.config.computer_id && this.computers.length === 1) this.connect(this.computers[0].host, this.computers[0].computer_id);
    }
    send(cmd, fields = {}) {
      if (!this.connected || this.socket?.readyState !== 1) return Promise.reject(new Error("电脑尚未连接，请打开连接设置"));
      const id = this.nextId++;
      return new Promise((resolve, reject) => {
        const timer = this.timers.setTimeout(() => { this.pending.delete(id); reject(new Error("电脑未及时回应，请查看电脑端状态")); }, cmd === "open_browser" ? 15000 : 8000);
        this.pending.set(id, { resolve, reject, timer });
        try { this.socket.send(JSON.stringify({ id, cmd, target: this.config.target || "auto", session_id: this.config.session_id || "", ...fields })); }
        catch (error) { this.timers.clearTimeout(timer); this.pending.delete(id); reject(error); }
      });
    }
    suspend() {
      this.active = false;
      ++this.generation;
      this.timers.clearTimeout(this.retry);
      this.timers.clearTimeout(this.deadline);
      this.socket?.close();
      this.connected = this.connecting = false;
      this.clearPending("遥控器已进入后台");
    }
    resume() {
      this.active = true;
      if (!this.connected && !this.connecting && !this.needsPin) this.reconnect();
    }
  }
  root.RemoteConnection = RemoteConnection;
  root.normalizeRemoteHost = normalizeHost;
  if (typeof module !== "undefined") module.exports = { RemoteConnection, normalizeHost };
})(globalThis);
