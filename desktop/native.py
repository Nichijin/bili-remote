"""Windows GSMTC adapter. Unsupported capabilities are explicitly reported."""
import asyncio
import time
from datetime import timedelta
from .detection import is_client


class NativeController:
    def __init__(self, audio_processes=()):
        self.audio_processes = {name.lower() for name in audio_processes}
        self.manager = None
        self.boost = None
        self.lock = asyncio.Lock()

    async def _manager(self):
        if self.manager is None:
            try:
                from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
            except ImportError as exc:
                raise RuntimeError("Windows 客户端控制依赖未安装；请安装 requirements.txt") from exc
            self.manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        return self.manager

    async def discover(self):
        manager = await self._manager()
        sessions = []
        for session in manager.get_sessions():
            info = session.get_playback_info()
            controls = info.controls
            sessions.append({
                "id": session.source_app_user_model_id,
                "toggle": bool(controls.is_play_pause_toggle_enabled or controls.is_pause_enabled or controls.is_play_enabled),
                "seek": bool(controls.is_playback_position_enabled),
                "speed": bool(controls.is_playback_rate_enabled),
            })
        return {"sessions": sessions}

    async def _session(self, session_id):
        sessions = list((await self._manager()).get_sessions())
        if session_id:
            match = next((s for s in sessions if s.source_app_user_model_id == session_id), None)
            if match is None:
                raise RuntimeError("所选客户端未提供媒体会话；请先播放视频并重新检测")
            return match
        matches = [s for s in sessions if is_client(s.source_app_user_model_id)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise RuntimeError("检测到多个哔哩哔哩会话，请在设置中选择")
        raise RuntimeError("未发现哔哩哔哩媒体会话；客户端可能未开放接口，请检测并手动选择")

    @staticmethod
    async def _checked(operation, label):
        try:
            succeeded = await asyncio.wait_for(operation, timeout=3)
        except asyncio.TimeoutError as exc:
            raise RuntimeError(f"客户端{label}操作超时") from exc
        if not succeeded:
            raise RuntimeError(f"客户端拒绝了{label}操作")

    async def _restore(self):
        if self.boost:
            boost = self.boost
            await self._checked(boost["session"].try_change_playback_rate_async(boost["rate"]), "恢复速度")
            self.boost = None

    async def expire(self):
        async with self.lock:
            if self.boost and time.monotonic() > self.boost["deadline"]:
                await self._restore()
                return True
        return False

    async def _volume(self, session_id, delta):
        # The companion can stop and restart its worker thread; COM must be
        # initialized in whichever thread currently owns the media adapter.
        from comtypes import CoInitialize, CoUninitialize
        CoInitialize()
        try:
            return self._volume_sync(session_id, delta)
        finally:
            CoUninitialize()

    def _volume_sync(self, session_id, delta):
        try:
            from pycaw.pycaw import AudioUtilities
        except ImportError as exc:
            raise RuntimeError("缺少 pycaw，无法调节客户端音量") from exc
        app_id = session_id.lower()
        matches = []
        for audio in AudioUtilities.GetAllSessions():
            if not audio.Process:
                continue
            try:
                name = audio.Process.name().lower()
            except Exception:
                continue
            # Exact executable IDs work for Win32. Packaged clients may need --audio-process.
            direct = name == app_id or name.removesuffix(".exe") == app_id
            configured = name in self.audio_processes
            bilibili = "bili" in app_id and "bili" in name
            if direct or configured or bilibili:
                matches.append(audio.SimpleAudioVolume)
        if not matches:
            raise RuntimeError("未找到客户端音频会话；可用 --audio-process 指定进程名")
        for volume in matches:
            volume.SetMasterVolume(max(0.0, min(1.0, volume.GetMasterVolume() + delta)), None)
            if delta > 0:
                volume.SetMute(False, None)
        return {"audio_sessions": len(matches), "volume": matches[0].GetMasterVolume()}

    async def execute(self, message, owner):
        async with self.lock:
            command = message["cmd"]
            if command == "discover":
                return await self.discover()
            if command in {"speed_keep", "speed_end", "speed_change"}:
                if self.boost and self.boost["owner"] == owner:
                    if command == "speed_change":
                        await self._checked(self.boost["session"].try_change_playback_rate_async(message["rate"]), "倍速切换")
                        self.boost["deadline"] = time.monotonic() + 1.8
                        return {"rate": message["rate"]}
                    elif command == "speed_keep":
                        self.boost["deadline"] = time.monotonic() + 1.8
                    else:
                        await self._restore()
                elif command == "speed_change":
                    raise RuntimeError("临时倍速已结束，请重新长按")
                return {}
            session = await self._session(message["session_id"])
            info = session.get_playback_info()
            controls = info.controls
            if command == "toggle":
                if controls.is_play_pause_toggle_enabled:
                    await self._checked(session.try_toggle_play_pause_async(), "播放/暂停")
                elif getattr(info.playback_status, "name", "") == "PLAYING" and controls.is_pause_enabled:
                    await self._checked(session.try_pause_async(), "暂停")
                elif getattr(info.playback_status, "name", "") != "PLAYING" and controls.is_play_enabled:
                    await self._checked(session.try_play_async(), "播放")
                else:
                    raise RuntimeError("该客户端未开放播放/暂停接口")
            elif command == "seek":
                if not controls.is_playback_position_enabled:
                    raise RuntimeError("该客户端未开放进度控制接口")
                timeline = session.get_timeline_properties()
                position = timeline.position + timedelta(seconds=message["delta"])
                position = max(timeline.min_seek_time, min(timeline.max_seek_time, position))
                # GSMTC expects 100-nanosecond ticks, not seconds or a TimeSpan.
                await self._checked(session.try_change_playback_position_async(int(position.total_seconds() * 10_000_000)), "进度调整")
                return {"time": position.total_seconds()}
            elif command == "volume":
                return await self._volume(session.source_app_user_model_id, message["delta"])
            elif command == "speed_start":
                if not controls.is_playback_rate_enabled:
                    raise RuntimeError("该客户端未开放倍速接口，需要为该版本另写适配器")
                await self._restore()
                info = session.get_playback_info()
                original = info.playback_rate
                if original is None:
                    raise RuntimeError("客户端未报告原始速度，无法安全恢复临时倍速")
                await self._checked(session.try_change_playback_rate_async(message["rate"]), "临时倍速")
                self.boost = {"session": session, "rate": original, "owner": owner, "deadline": time.monotonic() + 1.8}
            return {}
