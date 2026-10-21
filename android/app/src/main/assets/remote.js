(function (root) {
  const SPEED_VALUES = [.5, .75, 1, 1.25, 1.5, 2, 2.25, 2.5, 2.75, 3];
  function normalizeGears(values) {
    const gears = Array.isArray(values) ? [...new Set(values.filter(value => SPEED_VALUES.includes(value)))].sort((a, b) => a - b).slice(0, 5) : [];
    return gears.length ? gears : [.5, 2, 3];
  }
  // Shared by the dedicated speed button and the touchpad after long-press.
  class HoldControl {
    constructor({ send, rate = () => 2, gears = () => [.5, 2, 3], hint = () => {}, error = () => {}, haptic = () => {}, changed = () => {}, timers = root }) {
      Object.assign(this, { send, rate, gears, hint, error, haptic, changed, timers });
      this.current = null;
    }
    request(current, cmd, fields = {}) {
      // Dispatch in input order. Do not wait for a network acknowledgement to
      // send release or heartbeats; the computer serializes playback commands.
      Promise.resolve().then(() => this.send(cmd, fields)).catch(error => {
        if (this.current !== current) return;
        this.stop(false);
        this.error(error);
      });
    }
    start(x = 0) {
      this.stop(false);
      const gears = normalizeGears(this.gears());
      const index = Math.max(0, gears.indexOf(Number(this.rate())));
      const current = { gears, index, rate: gears[index], anchor: x };
      this.current = current;
      this.request(current, "speed_start", { rate: current.rate });
      this.feedback(current);
      current.timer = this.timers.setInterval(() => {
        if (this.current === current) this.request(current, "speed_keep");
      }, 400);
    }
    feedback(current) {
      this.hint(`临时 ${current.rate} 倍速 · 第 ${current.index + 1} / ${current.gears.length} 挡`);
      this.changed(current.rate);
      this.haptic();
    }
    move(x) {
      const current = this.current;
      if (!current || !Number.isFinite(x)) return;
      const dx = x - current.anchor;
      const index = Math.max(0, Math.min(current.gears.length - 1, current.index + Math.trunc(dx / 48)));
      if (index === current.index) {
        // Track travel farther into the current gear, so returning 48px from
        // the farthest point always changes gear even after a long swipe.
        if (index === current.gears.length - 1 && dx > 0) current.anchor = x;
        if (index === 0 && dx < 0) current.anchor = x;
        return;
      }
      current.index = index;
      current.rate = current.gears[index];
      // A fresh distance is required to switch back: jitter near a boundary
      // cannot repeatedly change gears or generate repeated vibration.
      current.anchor = x;
      this.request(current, "speed_change", { rate: current.rate });
      this.feedback(current);
    }
    stop(showHint = true) {
      if (!this.current) return;
      this.timers.clearInterval(this.current.timer);
      this.current = null;
      this.changed(null);
      Promise.resolve().then(() => this.send("speed_end")).catch(this.error);
      if (showHint) this.hint("恢复原播放速度");
    }
  }
  root.HoldControl = HoldControl;
  root.SPEED_VALUES = SPEED_VALUES;
  root.normalizeGears = normalizeGears;
  if (typeof module !== "undefined") module.exports = { HoldControl, SPEED_VALUES, normalizeGears };
})(globalThis);
