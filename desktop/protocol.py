"""Validate all remote commands before sending them to a player."""
import math

COMMANDS = {"toggle", "seek", "volume", "speed_start", "speed_keep", "speed_end", "discover", "open_browser", "status"}


def validate(message):
    if not isinstance(message, dict):
        raise ValueError("指令必须是 JSON 对象")
    command = message.get("cmd")
    if command not in COMMANDS:
        raise ValueError("未知指令")
    target = message.get("target", "browser")
    if target not in {"auto", "browser", "native"}:
        raise ValueError("未知播放目标")
    result = {"cmd": command, "target": target}
    session_id = message.get("session_id", "")
    if not isinstance(session_id, str) or len(session_id) > 512:
        raise ValueError("客户端标识不正确")
    result["session_id"] = session_id
    if command in {"seek", "volume", "speed_start"}:
        field = "rate" if command == "speed_start" else "delta"
        value = message.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("数值不正确")
        lower, upper = {"seek": (-120, 120), "volume": (-0.25, 0.25), "speed_start": (1, 4)}[command]
        if not lower <= value <= upper:
            raise ValueError("数值超出允许范围")
        result[field] = float(value)
    return result
