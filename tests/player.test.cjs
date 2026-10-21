const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createPlayerController } = require('../desktop/assets/player.js');

function setup() {
  let time = 0;
  const video = { paused: true, playbackRate: 1.5, currentTime: 50, duration: 100, volume: 0.9, muted: true, seekable: { length: 0 }, async play() { this.paused = false; }, pause() { this.paused = true; } };
  const player = createPlayerController(() => video, { now: () => time });
  return { video, player, advance: ms => time += ms };
}
test('toggle, seek and volume stay within player bounds', async () => {
  const { player, video } = setup();
  await player.execute({ cmd: 'toggle' }); assert.equal(video.paused, false);
  await player.execute({ cmd: 'toggle' }); assert.equal(video.paused, true);
  await player.execute({ cmd: 'seek', delta: 90 }); assert.equal(video.currentTime, 100);
  await player.execute({ cmd: 'seek', delta: -120 }); assert.equal(video.currentTime, 0);
  await player.execute({ cmd: 'volume', delta: .2 }); assert.equal(video.volume, 1); assert.equal(video.muted, false);
});
test('hold restores original rate even when another hold supersedes it', async () => {
  const { player, video } = setup();
  await player.execute({ cmd: 'speed_start', rate: 2, owner: 'a' });
  await player.execute({ cmd: 'speed_start', rate: 3, owner: 'b' });
  await player.execute({ cmd: 'speed_end', owner: 'a' }); assert.equal(video.playbackRate, 3);
  await player.execute({ cmd: 'speed_end', owner: 'b' }); assert.equal(video.playbackRate, 1.5);
});
test('watchdog restores rate when connection disappears', async () => {
  const { player, video, advance } = setup();
  await player.execute({ cmd: 'speed_start', rate: 2, owner: 'a' });
  advance(1500); await player.execute({ cmd: 'speed_keep', owner: 'a' });
  advance(1500); player.expire(); assert.equal(video.playbackRate, 2);
  advance(1000); player.expire(); assert.equal(video.playbackRate, 1.5);
});
test('seek honors seekable range', async () => {
  const { player, video } = setup();
  video.seekable = { length: 1, start: () => 20, end: () => 80 };
  await player.execute({ cmd: 'seek', delta: -120 }); assert.equal(video.currentTime, 20);
});

test('absolute scrubbing preserves fractions, respects ranges and rejects a changed video source', async () => {
  const {player, video} = setup();
  const state = await player.execute({cmd:'status'});
  await player.execute({cmd:'seek_to', position:63.375, media_key:state.media_key});
  assert.equal(video.currentTime, 63.375);
  video.seekable = {length:1, start:() => 20, end:() => 80};
  await player.execute({cmd:'seek_to', position:200, media_key:state.media_key});
  assert.equal(video.currentTime, 80);
  video.src = 'another-video';
  await assert.rejects(player.execute({cmd:'seek_to', position:40, media_key:state.media_key}), /已变化/);
  assert.equal(video.currentTime, 80);
});

test('slow motion holds restore the speed present before the hold', async () => {
  const {player, video} = setup();
  await player.execute({cmd:'speed_start', rate:.5, owner:'a'});
  assert.equal(video.playbackRate,.5);
  await player.execute({cmd:'speed_change', rate:.75, owner:'a'});
  await player.execute({cmd:'speed_end', owner:'a'});
  assert.equal(video.playbackRate,1.5);
});

test('changing gears retains the original rate and never changes owner', async () => {
  const { player, video } = setup();
  await player.execute({ cmd: 'speed_start', rate: 2, owner: 'a' });
  await player.execute({ cmd: 'speed_change', rate: 3, owner: 'a' }); assert.equal(video.playbackRate, 3);
  await assert.rejects(player.execute({ cmd: 'speed_change', rate: 2, owner: 'b' }), /重新长按/);
  assert.equal(video.playbackRate, 3);
  await player.execute({ cmd: 'speed_change', rate: 2, owner: 'a' });
  await player.execute({ cmd: 'speed_end', owner: 'a' }); assert.equal(video.playbackRate, 1.5);
  await assert.rejects(player.execute({ cmd: 'speed_change', rate: 3, owner: 'a' }), /重新长按/);
});

test('watchdog after gear changes still restores the initial rate', async () => {
  const { player, video, advance } = setup();
  await player.execute({ cmd: 'speed_start', rate: 2, owner: 'a' });
  await player.execute({ cmd: 'speed_change', rate: 3, owner: 'a' });
  advance(2500); player.expire(); assert.equal(video.playbackRate, 1.5);
});
