"""Validate all remote commands before sending them to a player."""
import math

COMMANDS = {"toggle", "seek", "seek_to", "volume", "speed_start", "speed_change", "speed_keep", "speed_end", "discover", "open_browser", "status"}
SPEED_VALUES = {.5, .75, 1, 1.25, 1.5, 2, 2.25, 2.5, 2.75, 3}


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
    if command == "open_browser":
        browser = message.get("browser", "auto")
        if not isinstance(browser, str) or browser not in {"auto", "edge", "chrome"}:
            raise ValueError("未知浏览器选择")
        result["browser"] = browser
    session_id = message.get("session_id", "")
    if not isinstance(session_id, str) or len(session_id) > 512:
        raise ValueError("客户端标识不正确")
    result["session_id"] = session_id
    if command in {"seek", "seek_to", "volume", "speed_start", "speed_change"}:
        field = "rate" if command in {"speed_start", "speed_change"} else "position" if command == "seek_to" else "delta"
        value = message.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("数值不正确")
        lower, upper = {"seek": (-120, 120), "seek_to": (0, 1_000_000_000), "volume": (-0.25, 0.25), "speed_start": (.5, 4), "speed_change": (.5, 4)}[command]
        if not lower <= value <= upper:
            raise ValueError("数值超出允许范围")
        result[field] = float(value)
        if field == "rate" and value not in SPEED_VALUES:
            raise ValueError("倍速不在允许的挡位范围内")
    if command == "seek_to":
        key = message.get("media_key")
        if not isinstance(key, str) or not 1 <= len(key) <= 256:
            raise ValueError("缺少有效的视频标识，请重新拖动")
        result["media_key"] = key
    return result
