"""Validate all remote commands before sending them to a player."""
import math

MOUSE_COMMANDS = {"mouse_start", "mouse_move", "mouse_frame", "mouse_click", "mouse_keep", "mouse_end"}
COMMANDS = {"toggle", "seek", "seek_to", "volume", "speed_start", "speed_change", "speed_keep", "speed_end", "discover", "open_browser", "status"} | MOUSE_COMMANDS
SPEED_VALUES = {.5, .75, 1, 1.25, 1.5, 2, 2.25, 2.5, 2.75, 3}


def validate(message):
    if not isinstance(message, dict):
        raise ValueError("指令必须是 JSON 对象")
    command = message.get("cmd")
    if not isinstance(command, str) or command not in COMMANDS:
        raise ValueError("未知指令")
    if command in MOUSE_COMMANDS:
        result = {"cmd": command}
        if command == "mouse_start" and "stream" in message:
            if type(message["stream"]) is not int or message["stream"] != 2:
                raise ValueError("不支持的鼠标流版本")
            result["stream"] = 2
        if command == "mouse_start" and "output_hz" in message:
            value = message["output_hz"]
            if type(value) is not int or value not in {125, 250, 500, 1000}:
                raise ValueError("鼠标输出频率必须是 125、250、500 或 1000 Hz")
            result["output_hz"] = value
        if command != "mouse_start":
            session = message.get("mouse_session")
            if not isinstance(session, str) or len(session) != 24 or any(c not in "0123456789abcdef" for c in session):
                raise ValueError("无效的鼠标模式标识")
            result["mouse_session"] = session
        if command == "mouse_move":
            for field in ("dx", "dy"):
                value = message.get(field)
                if isinstance(value, bool) or not isinstance(value, int) or not -8192 <= value <= 8192:
                    raise ValueError("鼠标位移必须是 -8192 到 8192 的整数")
                result[field] = value
        elif command == "mouse_frame":
            for field in ("x", "y", "t"):
                value = message.get(field)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1_000_000_000 or (field == "t" and value < 0):
                    raise ValueError("鼠标轨迹数值不正确")
                result[field] = float(value)
            seq = message.get("seq")
            if type(seq) is not int or not 1 <= seq <= 1_000_000_000:
                raise ValueError("鼠标轨迹序号不正确")
            result["seq"] = seq
        elif command == "mouse_click":
            button = message.get("button")
            if not isinstance(button, str) or button not in {"left", "right"}:
                raise ValueError("未知鼠标按键")
            result["button"] = button
        return result
    target = message.get("target", "browser")
    if not isinstance(target, str) or target not in {"auto", "browser", "native"}:
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
