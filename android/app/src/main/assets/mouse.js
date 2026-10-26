(function (root) {
  // Smooth gain, never filter the finger's direction or invent inertial motion.
  class PointerAcceleration {
    static gain(speed) {
      const u = Math.max(0, Math.min(1, (speed - 40) / 1000));
      return .85 + 2.15 * u * u * (3 - 2 * u);
    }
    reset(x, y, time) {
      Object.assign(this, { x, y, time, gain: .85, lastDX: 0, lastDY: 0 });
      this.history = [{ x, y, time }];
    }
    sample(x, y, time) {
      if (![x, y, time].every(Number.isFinite) || time <= this.time) return { dx: 0, dy: 0 };
      const dx = x - this.x, dy = y - this.y, dt = time - this.time;
      const reversed = dx * this.lastDX + dy * this.lastDY < 0 && Math.hypot(dx, dy) >= 1.5;
      if (dt > 80 || reversed) {
        this.history = [{ x: this.x, y: this.y, time: this.time }];
        if (dt > 80) this.gain = .85;
      }
      this.x = x; this.y = y; this.time = time;
      this.history.push({ x, y, time });
      while (this.history.length > 2 && this.history[1].time <= time - 32) this.history.shift();
      const first = this.history[0];
      const speed = Math.hypot(x - first.x, y - first.y) * 1000 / Math.max(1, time - first.time);
      const target = PointerAcceleration.gain(speed), previous = this.gain;
      this.gain += (target - this.gain) * (1 - Math.exp(-dt / (target < this.gain ? 12 : 32)));
      if (Math.hypot(dx, dy) >= .5) { this.lastDX = dx; this.lastDY = dy; }
      const gain = (previous + this.gain) / 2;
      return { dx: dx * gain, dy: dy * gain };
    }
  }

  class MouseTransport {
    constructor({ send, stream, outputHz = () => 1000, error = () => {}, changed = () => {}, timers = root,
                  frames = root, now = () => performance.now() }) {
      Object.assign(this, { send, stream, outputHz, error, changed, timers, frames, now });
      this.generation = 0; this.session = null; this.opening = false; this.frame = null;
      this.outstanding = new Map(); this.controls = new Set();
      this.x = this.y = this.seq = 0; this.dirty = false;
      this.activeUntil = -Infinity;
      this.sampleTimer = null; this.lastSentAt = -Infinity;
    }
    async start() {
      this.stop();
      const generation = ++this.generation;
      this.opening = true; this.changed("connecting");
      try {
        const result = await this.send("mouse_start", { stream: 2, output_hz: this.outputHz() });
        if (!/^[0-9a-f]{24}$/.test(result.mouse_session || "")) throw new Error("电脑端未提供鼠标模式，请同时更新两端");
        if (generation !== this.generation) {
          this.send("mouse_end", { mouse_session: result.mouse_session }).catch(() => {});
          return false;
        }
        this.session = result.mouse_session;
        if (result.mouse_stream !== 2 || !this.stream) throw new Error("流畅鼠标模式需要电脑端与安卓端都升级到 0.5.12 或更新版本");
        if (result.mouse_output_hz !== this.outputHz()) throw new Error("所选输出频率需要电脑端与安卓端都升级到 0.5.13 或更新版本");
        this.actualOutputHz = result.mouse_output_hz;
        this.opening = false; this.started = this.now(); this.lastTime = 0;
        this.keep = this.timers.setInterval(() => {
          if (!this.keeping) {
            this.keeping = true;
            this.command("mouse_keep").finally(() => { if (generation === this.generation) this.keeping = false; });
          }
        }, 1000);
        this.changed("mouse"); return true;
      } catch (failure) {
        if (generation === this.generation) this.fail(failure);
        return false;
      }
    }
    stop() {
      const session = this.session;
      ++this.generation; this.session = null; this.opening = this.keeping = false;
      this.outstanding.clear(); this.controls.clear(); this.dirty = false;
      this.x = this.y = this.seq = 0;
      this.activeUntil = -Infinity;
      this.lastSentAt = -Infinity;
      this.timers.clearTimeout(this.sampleTimer); this.sampleTimer = null;
      if (this.frame !== null) this.frames.cancelAnimationFrame(this.frame);
      this.frame = null; this.timers.clearInterval(this.keep); this.keep = null;
      if (session) this.send("mouse_end", { mouse_session: session }).catch(() => {});
      this.changed("video");
    }
    fail(failure) { this.stop(); this.error(failure); }
    move(dx, dy) {
      if (!this.session || ![dx, dy].every(Number.isFinite)) return;
      this.x += Math.max(-8192, Math.min(8192, dx));
      this.y += Math.max(-8192, Math.min(8192, dy));
      if (!dx && !dy) return;
      this.dirty = true; this.activeUntil = this.now()+32; this.schedule();
    }
    click(button) {
      if (!this.session || !["left", "right"].includes(button)) return;
      // The stream and click share one ordered socket. The PC flushes the last
      // position before clicking; a congested socket must never click elsewhere.
      if (!this.flush() || this.controls.size >= 4) {
        this.fail(new Error("鼠标连接拥塞，已停止点击；请重新进入鼠标模式")); return;
      }
      this.command("mouse_click", { button });
    }
    sampled() {
      if (!this.session || !this.dirty) return;
      const delay = 1-(this.now()-this.lastSentAt);
      if (delay <= 0) { this.flush(); return; }
      if (this.sampleTimer === null) this.sampleTimer = this.timers.setTimeout(() => {
        this.sampleTimer = null;
        if (this.session) this.flush();
      }, delay);
    }
    schedule() {
      if (this.frame !== null || !this.session || (!this.dirty && this.now() >= this.activeUntil)) return;
      this.frame = this.frames.requestAnimationFrame(() => {
        this.frame = null; this.flush(); this.schedule();
      });
    }
    flush() {
      if (!this.session) return false;
      const time = this.now();
      const oldest = this.outstanding.values().next().value;
      if (this.outstanding.size >= 24 || (oldest !== undefined && time - oldest > 180)) return false;
      if (!this.dirty) return true;
      const fields = { mouse_session: this.session, seq: this.seq + 1,
        t: Math.max(this.lastTime, time - this.started),
        x: Number(this.x.toFixed(4)), y: Number(this.y.toFixed(4)) };
      try {
        if (!this.stream(fields)) return false;
        this.seq = fields.seq; this.lastTime = fields.t;
        this.lastSentAt = time;
        this.outstanding.set(this.seq, time); this.dirty = false;
        return true;
      } catch (failure) { this.fail(failure); return false; }
    }
    acknowledge(message) {
      if (!this.session || message.mouse_session !== this.session) return;
      if (!message.ok) { this.fail(new Error(message.error || "鼠标输入失败")); return; }
      if (!Number.isInteger(message.seq) || message.seq < 1 || message.seq > this.seq) return;
      for (const seq of this.outstanding.keys()) if (seq <= message.seq) this.outstanding.delete(seq);
      this.sampled(); this.schedule();
    }
    command(cmd, fields = {}) {
      if (!this.session) return Promise.resolve();
      const generation = this.generation;
      const task = this.send(cmd, { ...fields, mouse_session: this.session });
      this.controls.add(task);
      return task.catch(failure => {
        if (generation === this.generation) this.fail(failure);
      }).finally(() => this.controls.delete(task));
    }
  }
  class TouchpadController {
    constructor({ video, send, stream, outputHz = () => 1000, hint = () => {}, error = () => {}, haptic = () => {}, changed = () => {},
                  tapButton = () => "left", timers = root, frames = root,
                  now = () => performance.now() }) {
      Object.assign(this, { video, send, hint, error, haptic, changed, tapButton, timers, now });
      this.phase = "video"; this.current = null; this.pendingTap = null;
      this.acceleration = new PointerAcceleration();
      this.mouse = new MouseTransport({ send, stream, outputHz, error, timers, frames, now, changed: phase => {
        const previous = this.phase; this.phase = phase;
        if (phase !== "mouse") this.cancelTouch();
        this.changed(phase);
        if (phase === "mouse") { this.haptic(); this.hint(`鼠标模式 · 电脑输出目标 ${this.mouse.actualOutputHz} Hz`); }
        else if (phase === "connecting") this.hint("正在连接鼠标模式…");
        else if (previous !== "video") this.hint("已返回视频触摸板");
      } });
    }
    clearTap() {
      if (this.pendingTap) this.timers.clearTimeout(this.pendingTap.timer);
      this.pendingTap = null;
    }
    tap(x, y, duration, action) {
      const previous = this.pendingTap, time = this.now();
      if (duration <= 250 && previous && previous.phase === this.phase &&
          time - previous.time <= 280 && Math.hypot(x - previous.x, y - previous.y) <= 28) {
        this.clearTap();
        this.enter();
        return;
      }
      if (previous) { this.clearTap(); previous.action(); }
      if (duration > 250) { action(); return; }
      const pending = { x, y, time, action, phase: this.phase };
      pending.timer = this.timers.setTimeout(() => {
        if (this.pendingTap !== pending) return;
        this.pendingTap = null;
        if (pending.phase === this.phase) action();
      }, 280);
      this.pendingTap = pending;
    }
    videoTap(x, y, duration) {
      if (this.phase === "video") this.tap(x, y, duration, () => this.video.emit("toggle"));
    }
    enter() {
      this.clearTap(); this.cancelTouch(); this.video.cancel();
      return this.mouse.start();
    }
    exit() { this.clearTap(); this.cancelTouch(); this.mouse.stop(); }
    cancelTouch() {
      if (this.current) this.timers.clearTimeout(this.current.timer);
      this.current = null;
    }
    cancel() { this.clearTap(); this.cancelTouch(); this.video.cancel(); this.mouse.stop(); }
    down(x, y, width, height, time = this.now()) {
      if (this.phase === "video") { this.video.down(x, y, width, height); return; }
      if (this.phase !== "mouse") return;
      this.cancelTouch();
      const g = { x, y, time, mode: "pending" };
      this.current = g; this.acceleration.reset(x, y, time);
      g.timer = this.timers.setTimeout(() => {
        if (this.current !== g || g.mode !== "pending") return;
        g.mode = "hold"; this.clearTap();
        this.mouse.click("right"); this.haptic(); this.hint("鼠标右键");
      }, 500);
    }
    move(x, y, time = this.now()) {
      if (this.phase === "video") { this.video.move(x, y); return; }
      const g = this.current;
      if (this.phase !== "mouse" || !g) return;
      const motion = this.acceleration.sample(x, y, time);
      if (g.mode === "pending" && Math.hypot(x - g.x, y - g.y) > 3) {
        g.mode = "move"; this.timers.clearTimeout(g.timer);
      }
      this.mouse.move(motion.dx, motion.dy);
    }
    up(x, y, time = this.now()) {
      if (this.phase === "video") { this.video.up(x, y); return; }
      const g = this.current;
      if (this.phase !== "mouse" || !g) return;
      this.move(x, y, time); this.cancelTouch(); this.mouse.flush();
      if (g.mode !== "pending") return;
      this.mouse.click(this.tapButton());
    }
  }
  root.PointerAcceleration = PointerAcceleration;
  root.MouseTransport = MouseTransport;
  root.TouchpadController = TouchpadController;
  if (typeof module !== "undefined") module.exports = { PointerAcceleration, MouseTransport, TouchpadController };
})(globalThis);
