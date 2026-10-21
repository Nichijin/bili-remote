(function (root) {
  class HoldControl {
    constructor({ send, rate, hint, error, timers = root }) { Object.assign(this, { send, rate, hint, error, timers }); this.current = null; }
    start() {
      this.stop();
      const current = {};
      this.current = current;
      this.hint(`临时 ${this.rate()} 倍速`);
      Promise.resolve().then(() => this.send("speed_start", { rate: this.rate() })).catch(error => {
        if (this.current === current) this.stop();
        this.error(error);
      });
      current.timer = this.timers.setInterval(() => this.send("speed_keep").catch(this.error), 400);
    }
    stop() {
      if (!this.current) return;
      this.timers.clearInterval(this.current.timer);
      this.current = null;
      Promise.resolve().then(() => this.send("speed_end")).then(() => this.hint("恢复原播放速度")).catch(this.error);
    }
  }
  root.HoldControl = HoldControl;
  if (typeof module !== "undefined") module.exports = { HoldControl };
})(globalThis);
