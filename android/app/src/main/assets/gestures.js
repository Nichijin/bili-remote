(function (root) {
  const HoldControl = root.HoldControl || (typeof require !== "undefined" ? require("./remote.js").HoldControl : null);
  class GestureEngine {
    constructor({ send, hint = () => {}, preview, error = () => {}, rate = () => 2, gears = () => [.5, 2, 3], haptic = () => {}, changed = () => {}, timers = globalThis, now = () => Date.now() }) {
      Object.assign(this, { send, hint, error, rate, timers, now });
      this.preview = preview || (value => hint(`进度 ${value.position.toFixed(1)} / ${value.end.toFixed(1)} 秒`));
      this.hold = new HoldControl({ send, hint, error, rate, gears, haptic, changed, timers });
      this.current = null;
      this.scrubs = new Set();
      this.scrubTail = Promise.resolve();
    }
    emit(cmd, fields = {}) {
      return Promise.resolve().then(() => this.send(cmd, fields)).catch(this.error);
    }
    down(x, y, width, height) {
      this.cancel(false);
      const g = { x, y, lastX: x, lastY: y, width, height, mode: "pending", volume: 0 };
      this.current = g;
      g.timer = this.timers.setTimeout(() => {
        if (this.current !== g || g.mode !== "pending") return;
        g.mode = "hold";
        this.hold.start(g.lastX);
      }, 500);
    }
    beginSeek(g) {
      g.loading = true;
      const previous = this.scrubTail;
      this.scrubTail = new Promise(resolve => { g.resolveSeek = resolve; });
      this.scrubs.add(g);
      // A new drag snapshots its position only after the previous drag's final seek.
      previous.then(async () => {
        if (g.canceled) return;
        const state = await this.send("status");
        if (g.canceled) return;
        const { time, seek_start: start, seek_end: end, media_key: key } = state;
        if (![time, start, end].every(value => typeof value === "number" && Number.isFinite(value)) || end <= start || !key) throw new Error("当前视频未提供可拖动的进度，请先播放视频");
        g.range = { time, start, end, key };
        this.updateSeek(g);
      }).catch(error => this.seekError(g, error)).finally(() => {
        g.loading = false;
        this.scheduleSeek(g);
        this.finishSeek(g);
      });
    }
    updateSeek(g) {
      if (!g.range || g.canceled || g.failed) return;
      const { time, start, end, key } = g.range;
      const position = Math.max(start, Math.min(end, time + (g.lastX - g.x) / Math.max(1, g.width) * 120));
      if (position !== g.requested || g.forceFinal) g.pending = { position, media_key: key };
      else g.pending = null;
      g.forceFinal = false;
      if (this.current === g || (!this.current && g.released)) this.preview({ position, start, end });
      this.scheduleSeek(g);
    }
    scheduleSeek(g) {
      if (g.canceled || g.failed || g.loading || g.inflight || !g.pending || g.seekTimer) return;
      const delay = g.released ? 0 : Math.max(0, (g.nextSend || 0) - this.now());
      if (delay) {
        g.seekTimer = this.timers.setTimeout(() => { g.seekTimer = null; this.scheduleSeek(g); }, delay);
        return;
      }
      const fields = g.pending;
      g.pending = null; g.requested = fields.position; g.inflight = true;
      g.nextSend = this.now() + 80;
      Promise.resolve().then(() => {
        if (!g.canceled) return this.send("seek_to", fields);
      }).catch(error => this.seekError(g, error)).finally(() => {
        g.inflight = false;
        this.scheduleSeek(g);
        this.finishSeek(g);
      });
    }
    seekError(g, error) {
      g.failed = true; g.pending = null;
      this.timers.clearTimeout(g.seekTimer); g.seekTimer = null;
      if (!g.canceled) this.error(error);
    }
    finishSeek(g) {
      if (!g.resolveSeek || g.loading || g.inflight) return;
      if (!g.canceled && !g.failed && (!g.released || g.pending)) return;
      this.timers.clearTimeout(g.seekTimer); g.seekTimer = null;
      this.scrubs.delete(g);
      g.resolveSeek(); g.resolveSeek = null;
    }
    move(x, y) {
      const g = this.current;
      if (!g) return;
      g.lastX = x;
      if (g.mode === "hold") { this.hold.move(x); return; }
      const dx = x - g.x, dy = y - g.y;
      if (g.mode === "pending") {
        if (Math.max(Math.abs(dx), Math.abs(dy)) < 12) return;
        this.timers.clearTimeout(g.timer);
        g.mode = Math.abs(dx) >= Math.abs(dy) ? "seek" : "volume";
        if (g.mode === "seek") this.beginSeek(g);
      }
      if (g.mode === "seek") {
        this.updateSeek(g);
      } else if (g.mode === "volume") {
        g.volume += (g.lastY - y) / g.height;
        g.lastY = y;
        while (Math.abs(g.volume) >= 0.03) {
          const delta = Math.sign(g.volume) * Math.min(0.25, Math.abs(g.volume));
          this.emit("volume", { delta });
          g.volume -= delta;
        }
        this.hint(dy < 0 ? "音量增大" : "音量减小");
      }
    }
    stopHold(g) {
      this.timers.clearTimeout(g.timer);
    }
    up(x, y) {
      const g = this.current;
      if (!g) return;
      if (g.mode !== "hold") this.move(x, y);
      this.stopHold(g);
      this.current = null;
      if (g.mode === "pending") this.emit("toggle");
      else if (g.mode === "hold") this.hold.stop();
      else if (g.mode === "seek") {
        g.released = true; g.forceFinal = true;
        this.timers.clearTimeout(g.seekTimer); g.seekTimer = null;
        this.updateSeek(g);
        this.scheduleSeek(g); this.finishSeek(g);
      }
      else if (g.mode === "volume" && Math.abs(g.volume) > 0.001) this.emit("volume", { delta: g.volume });
    }
    cancel(all = true) {
      const g = this.current;
      if (g) {
        this.stopHold(g);
        this.current = null;
        if (g.mode === "hold") this.hold.stop(false);
      }
      for (const scrub of this.scrubs) {
        if (!all && scrub !== g) continue;
        scrub.canceled = true; scrub.pending = null;
        this.timers.clearTimeout(scrub.seekTimer); scrub.seekTimer = null;
        this.finishSeek(scrub);
      }
    }
  }
  root.GestureEngine = GestureEngine;
  if (typeof module !== "undefined") module.exports = { GestureEngine };
})(globalThis);
