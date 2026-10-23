(function (root) {
  // Velocity controls gain, not pointer interpolation: position never glides on
  // after the finger stops. CSS pixels make the curve independent of WebView DPR.
  class PointerAcceleration {
    reset(x, y, time) {
      Object.assign(this, { x, y, time, speed: null, lastDX: 0, lastDY: 0 });
    }
    sample(x, y, time) {
      if (![x, y, time].every(Number.isFinite) || time <= this.time) return { dx: 0, dy: 0 };
      const dx = x - this.x, dy = y - this.y, dt = time - this.time;
      this.x = x; this.y = y; this.time = time;
      const speed = Math.hypot(dx, dy) * 1000 / dt;
      const reversed = dx * this.lastDX + dy * this.lastDY < 0;
      if (this.speed === null || dt > 80 || reversed) this.speed = speed;
      else this.speed += (speed - this.speed) * (1 - Math.exp(-dt / 24));
      this.lastDX = dx; this.lastDY = dy;
      // Continuous linear gain: precise at low speed, capped at 3.5x at 900px/s.
      const gain = .65 + Math.min(1, Math.max(0, this.speed / 900)) * 2.85;
      return { dx: dx * gain, dy: dy * gain };
    }
  }

  class MouseTransport {
    constructor({ send, error = () => {}, changed = () => {}, timers = root,
                  frames = root, now = () => performance.now() }) {
      Object.assign(this, { send, error, changed, timers, frames, now });
      this.generation = 0; this.session = null; this.opening = false;
      this.inflight = false; this.queue = []; this.frame = null;
      this.fractionX = this.fractionY = 0;
    }
    async start() {
      this.stop();
      const generation = ++this.generation;
      this.opening = true; this.changed("connecting");
      try {
        const result = await this.send("mouse_start");
        if (!/^[0-9a-f]{24}$/.test(result.mouse_session || "")) throw new Error("电脑端未提供鼠标模式，请将两端升级至 0.5.11 或更新版本");
        if (generation !== this.generation) {
          this.send("mouse_end", { mouse_session: result.mouse_session }).catch(() => {});
          return false;
        }
        this.session = result.mouse_session; this.opening = false;
        this.keep = this.timers.setInterval(() => {
          if (!this.inflight && !this.queue.length) this.command("mouse_keep");
        }, 1000);
        this.changed("mouse"); return true;
      } catch (failure) {
        if (generation === this.generation) { this.stop(); this.error(failure); }
        return false;
      }
    }
    stop() {
      const session = this.session;
      ++this.generation; this.session = null; this.opening = false;
      this.inflight = false; this.queue = [];
      this.fractionX = this.fractionY = 0;
      if (this.frame !== null) this.frames.cancelAnimationFrame(this.frame);
      this.frame = null; this.timers.clearInterval(this.keep); this.keep = null;
      if (session) this.send("mouse_end", { mouse_session: session }).catch(() => {});
      this.changed("video");
    }
    move(dx, dy) {
      if (!this.session || ![dx, dy].every(Number.isFinite)) return;
      this.fractionX += dx; this.fractionY += dy;
      const x = Math.trunc(this.fractionX), y = Math.trunc(this.fractionY);
      this.fractionX -= x; this.fractionY -= y;
      if (!x && !y) return;
      const tail = this.queue.at(-1), time = this.now();
      if (tail?.cmd === "mouse_move" && time - tail.time <= 100) {
        tail.dx = Math.max(-8192, Math.min(8192, tail.dx + x));
        tail.dy = Math.max(-8192, Math.min(8192, tail.dy + y));
      } else {
        // Discard expired unsent motion, never replay an old travel path.
        if (tail?.cmd === "mouse_move") this.queue.pop();
        this.queue.push({ cmd: "mouse_move", dx: Math.max(-8192, Math.min(8192, x)), dy: Math.max(-8192, Math.min(8192, y)), time });
      }
      this.schedule();
    }
    click(button) {
      if (!this.session || !["left", "right"].includes(button)) return;
      if (this.queue.filter(item => item.cmd === "mouse_click").length >= 4) return;
      this.queue.push({ cmd: "mouse_click", button, time: this.now() });
      this.flush();
    }
    schedule() {
      if (this.frame !== null || this.inflight || !this.session || !this.queue.length) return;
      this.frame = this.frames.requestAnimationFrame(() => { this.frame = null; this.flush(); });
    }
    flush() {
      if (this.inflight || !this.session) return;
      let item;
      while ((item = this.queue.shift())) {
        if (this.now() - item.time <= 150) break;
        item = null;
      }
      if (!item) return;
      const {cmd, time, ...fields} = item;
      this.command(cmd, fields);
    }
    command(cmd, fields = {}) {
      if (!this.session || this.inflight) return;
      const generation = this.generation;
      this.inflight = true;
      Promise.resolve().then(() => {
        if (generation === this.generation) return this.send(cmd, { ...fields, mouse_session: this.session });
      }).catch(failure => {
        if (generation === this.generation) { this.stop(); this.error(failure); }
      }).finally(() => {
        if (generation === this.generation) { this.inflight = false; this.schedule(); }
      });
    }
  }
  class TouchpadController {
    constructor({ video, send, hint = () => {}, error = () => {}, haptic = () => {}, changed = () => {},
                  tapButton = () => "left", timers = root, frames = root,
                  now = () => performance.now() }) {
      Object.assign(this, { video, send, hint, error, haptic, changed, tapButton, timers, now });
      this.phase = "video"; this.current = null; this.pendingTap = null;
      this.acceleration = new PointerAcceleration();
      this.mouse = new MouseTransport({ send, error, timers, frames, now, changed: phase => {
        const previous = this.phase; this.phase = phase;
        if (phase !== "mouse") this.cancelTouch();
        this.changed(phase);
        if (phase === "mouse") { this.haptic(); this.hint("鼠标模式 · 滑动移动光标"); }
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
      this.move(x, y, time); this.cancelTouch();
      if (g.mode !== "pending") return;
      this.mouse.click(this.tapButton());
    }
  }
  root.PointerAcceleration = PointerAcceleration;
  root.MouseTransport = MouseTransport;
  root.TouchpadController = TouchpadController;
  if (typeof module !== "undefined") module.exports = { PointerAcceleration, MouseTransport, TouchpadController };
})(globalThis);
