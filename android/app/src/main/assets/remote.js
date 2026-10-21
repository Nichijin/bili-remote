(function (root) {
  // Shared by the dedicated speed button and the touchpad after long-press.
  class HoldControl {
    constructor({ send, rate = () => 2, hint = () => {}, error = () => {}, haptic = () => {}, changed = () => {}, timers = root }) {
      Object.assign(this, { send, rate, hint, error, haptic, changed, timers });
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
      const current = { rate: Number(this.rate()) === 3 ? 3 : 2, anchor: x };
      this.current = current;
      this.request(current, "speed_start", { rate: current.rate });
      this.feedback(current);
      current.timer = this.timers.setInterval(() => {
        if (this.current === current) this.request(current, "speed_keep");
      }, 400);
    }
    feedback(current) {
      this.hint(`临时 ${current.rate} 倍速 · 左滑 2× / 右滑 3×`);
      this.changed(current.rate);
      this.haptic();
    }
    move(x) {
      const current = this.current;
      if (!current || !Number.isFinite(x)) return;
      const dx = x - current.anchor;
      const next = dx >= 48 ? 3 : dx <= -48 ? 2 : current.rate;
      if (next === current.rate) {
        // Track travel farther into the current gear, so returning 48px from
        // the farthest point always changes gear even after a long swipe.
        current.anchor = current.rate === 3 ? Math.max(current.anchor, x) : Math.min(current.anchor, x);
        return;
      }
      current.rate = next;
      // A fresh distance is required to switch back: jitter near a boundary
      // cannot repeatedly change gears or generate repeated vibration.
      current.anchor = x;
      this.request(current, "speed_change", { rate: next });
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
  if (typeof module !== "undefined") module.exports = { HoldControl };
})(globalThis);
