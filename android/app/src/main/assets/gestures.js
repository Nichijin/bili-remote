(function (root) {
  const HoldControl = root.HoldControl || (typeof require !== "undefined" ? require("./remote.js").HoldControl : null);
  class GestureEngine {
    constructor({ send, hint = () => {}, error = () => {}, rate = () => 2, haptic = () => {}, changed = () => {}, timers = globalThis }) {
      Object.assign(this, { send, hint, error, rate, timers });
      this.hold = new HoldControl({ send, hint, error, rate, haptic, changed, timers });
      this.current = null;
    }
    emit(cmd, fields = {}) {
      return Promise.resolve().then(() => this.send(cmd, fields)).catch(this.error);
    }
    down(x, y, width, height) {
      this.cancel();
      const g = { x, y, lastX: x, lastY: y, width, height, mode: "pending", volume: 0 };
      this.current = g;
      g.timer = this.timers.setTimeout(() => {
        if (this.current !== g || g.mode !== "pending") return;
        g.mode = "hold";
        this.hold.start(g.lastX);
      }, 500);
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
      }
      if (g.mode === "seek") {
        g.seek = Math.max(-120, Math.min(120, dx / g.width * 120));
        this.hint(`${g.seek >= 0 ? "快进" : "快退"} ${Math.round(Math.abs(g.seek))} 秒`);
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
      else if (g.mode === "seek" && g.seek) this.emit("seek", { delta: Math.round(g.seek) });
      else if (g.mode === "volume" && Math.abs(g.volume) > 0.001) this.emit("volume", { delta: g.volume });
    }
    cancel() {
      const g = this.current;
      if (!g) return;
      this.stopHold(g);
      this.current = null;
      if (g.mode === "hold") this.hold.stop(false);
    }
  }
  root.GestureEngine = GestureEngine;
  if (typeof module !== "undefined") module.exports = { GestureEngine };
})(globalThis);
