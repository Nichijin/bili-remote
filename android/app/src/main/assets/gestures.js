(function (root) {
  class GestureEngine {
    constructor({ send, hint = () => {}, error = () => {}, rate = () => 2, timers = globalThis }) {
      Object.assign(this, { send, hint, error, rate, timers });
      this.current = null;
    }
    emit(cmd, fields = {}) {
      return Promise.resolve().then(() => this.send(cmd, fields)).catch(this.error);
    }
    down(x, y, width, height) {
      this.cancel();
      const g = { x, y, lastY: y, width, height, mode: "pending", volume: 0 };
      this.current = g;
      g.timer = this.timers.setTimeout(() => {
        if (this.current !== g || g.mode !== "pending") return;
        g.mode = "hold";
        this.hint(`临时 ${this.rate()} 倍速`);
        Promise.resolve().then(() => this.send("speed_start", { rate: this.rate() })).catch(error => {
          if (this.current === g && g.mode === "hold") {
            this.stopHold(g); g.mode = "failed";
            this.emit("speed_end");
          }
          this.error(error);
        });
        g.keep = this.timers.setInterval(() => this.emit("speed_keep"), 400);
      }, 500);
    }
    move(x, y) {
      const g = this.current;
      if (!g || g.mode === "hold" || g.mode === "failed") return;
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
      if (g.keep != null) this.timers.clearInterval(g.keep);
    }
    up(x, y) {
      const g = this.current;
      if (!g) return;
      this.move(x, y);
      this.stopHold(g);
      this.current = null;
      if (g.mode === "pending") this.emit("toggle");
      else if (g.mode === "hold") { this.emit("speed_end"); this.hint("恢复原播放速度"); }
      else if (g.mode === "seek" && g.seek) this.emit("seek", { delta: Math.round(g.seek) });
      else if (g.mode === "volume" && Math.abs(g.volume) > 0.001) this.emit("volume", { delta: g.volume });
    }
    cancel() {
      const g = this.current;
      if (!g) return;
      this.stopHold(g);
      this.current = null;
      if (g.mode === "hold") this.emit("speed_end");
    }
  }
  root.GestureEngine = GestureEngine;
  if (typeof module !== "undefined") module.exports = { GestureEngine };
})(globalThis);
