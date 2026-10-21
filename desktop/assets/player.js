(function (root) {
  function createPlayerController(findVideo, options = {}) {
    const now = options.now || Date.now;
    let boost = null;
    const mediaKeys = new WeakMap();
    const prefix = Math.random().toString(36).slice(2);
    let nextKey = 0;
    function mediaKey(video) {
      const source = video.currentSrc || video.src || "";
      let record = mediaKeys.get(video);
      if (!record || record.source !== source || record.duration !== video.duration) {
        record = { source, duration: video.duration, key: `${prefix}:${++nextKey}` };
        mediaKeys.set(video, record);
      }
      return record.key;
    }
    function restore() {
      if (!boost) return;
      boost.video.playbackRate = boost.originalRate;
      boost = null;
    }
    async function execute(message) {
      if (message.cmd === "speed_change") {
        if (!boost || boost.owner !== message.owner) throw new Error("临时倍速已结束，请重新长按");
        try {
          boost.video.playbackRate = message.rate;
          if (Math.abs(boost.video.playbackRate - message.rate) > .01) throw new Error("播放器拒绝了倍速操作");
          boost.deadline = now() + 2200;
          return { rate: boost.video.playbackRate };
        } catch (error) { restore(); throw error; }
      }
      if (message.cmd === "speed_end" || message.cmd === "speed_keep") {
        if (boost && boost.owner === message.owner) {
          if (message.cmd === "speed_end") restore();
          else boost.deadline = now() + 2200;
        }
        return {};
      }
      const player = findVideo();
      if (!player) throw new Error("请先在遥控播放窗口中打开并播放一个视频");
      switch (message.cmd) {
        case "toggle":
          if (player.paused) await player.play(); else player.pause();
          break;
        case "seek":
        case "seek_to": {
          const start = player.seekable.length ? player.seekable.start(0) : 0;
          const end = player.seekable.length ? player.seekable.end(player.seekable.length - 1) : player.duration;
          if (!Number.isFinite(end)) throw new Error("当前视频不支持跳转进度");
          if (message.cmd === "seek_to" && message.media_key !== mediaKey(player)) throw new Error("播放视频已变化，请重新拖动");
          player.currentTime = Math.max(start, Math.min(end, message.cmd === "seek_to" ? message.position : player.currentTime + message.delta));
          break;
        }
        case "volume":
          player.volume = Math.max(0, Math.min(1, player.volume + message.delta));
          if (message.delta > 0) player.muted = false;
          break;
        case "speed_start":
          restore();
          boost = { video: player, originalRate: player.playbackRate, owner: message.owner, deadline: now() + 2200 };
          try {
            player.playbackRate = message.rate;
            if (Math.abs(player.playbackRate - message.rate) > .01) throw new Error("播放器拒绝了倍速操作");
          } catch (error) { restore(); throw error; }
          break;
        case "status": break;
        default: throw new Error("未知视频操作");
      }
      const start = player.seekable.length ? player.seekable.start(0) : 0;
      const end = player.seekable.length ? player.seekable.end(player.seekable.length - 1) : player.duration;
      return { paused: player.paused, time: player.currentTime, duration: Number.isFinite(player.duration) ? player.duration : null, seek_start: start, seek_end: Number.isFinite(end) ? end : null, media_key: mediaKey(player), volume: player.volume, rate: player.playbackRate };
    }
    return { execute, restore, expire() { if (boost && now() > boost.deadline) restore(); } };
  }
  root.createPlayerController = createPlayerController;
  if (typeof module !== "undefined") module.exports = { createPlayerController };
})(globalThis);
