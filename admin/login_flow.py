from typing import Any, Optional

import config
from utils import call_wechat_api


_WXID_KEYS = ("wxid", "Wxid", "userName", "UserName")

state = {
    "phase": "idle",
    "message": "",
    "uuid": "",
    "qrBase64": "",
    "needCode": False,
    "ticket": "",
}


def _find_wxid(obj: Any) -> str:
    if isinstance(obj, dict):
        for key in _WXID_KEYS:
            value = obj.get(key)
            if isinstance(value, str) and value.startswith("wxid_"):
                return value
        for value in obj.values():
            found = _find_wxid(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_wxid(value)
            if found:
                return found
    return ""


def _scan_status(result: dict) -> Optional[int]:
    data = result.get("Data")
    if not isinstance(data, dict):
        return None
    status = data.get("status", data.get("Status"))
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


def apply_wxid(wxid: str) -> None:
    raw = config.load_raw_config()
    raw.setdefault("service", {})["wxid"] = wxid
    config.save_raw_config(raw)


async def _open_heartbeat(wxid: str) -> str:
    beat = await call_wechat_api.auto_heart_beat(wxid)
    if isinstance(beat, dict) and beat.get("Success"):
        state["phase"] = "online"
        state["message"] = "登录成功，已开启自动心跳"
        state["qrBase64"] = ""
        state["needCode"] = False
        return state["message"]
    message = beat.get("Message") if isinstance(beat, dict) else "开启自动心跳失败"
    state["phase"] = "heartbeat_failed"
    state["message"] = message or "开启自动心跳失败"
    return state["message"]


async def relogin() -> dict:
    """二次登录。成功后立刻开启自动心跳。"""
    wxid = config.cfg.service.wxid
    state["phase"] = "twice"
    state["message"] = "正在二次登录"
    state["needCode"] = False
    result = await call_wechat_api.twice_login(wxid)
    if isinstance(result, dict) and result.get("Success"):
        found = _find_wxid(result.get("Data"))
        if found and found != wxid:
            apply_wxid(found)
            wxid = found
        await _open_heartbeat(wxid)
        return public_state()
    message = result.get("Message") if isinstance(result, dict) else "wechat861 无响应"
    state["phase"] = "need_qr"
    state["message"] = message or "二次登录失败，需要扫码"
    return public_state()


async def start_qr(device_id: str = "") -> dict:
    device_id = (device_id or config.cfg.service.device_id or "").strip()
    if not device_id:
        state["phase"] = "need_device"
        state["message"] = "请先填写固定设备 ID"
        return public_state()
    if device_id != config.cfg.service.device_id:
        save_device_id(device_id)
    state["phase"] = "qr"
    state["message"] = "正在获取二维码"
    state["needCode"] = False
    state["ticket"] = ""
    result = await call_wechat_api.login_get_qr(device_id)
    data = result.get("Data") if isinstance(result, dict) else None
    if not isinstance(data, dict) or not data.get("Uuid"):
        message = result.get("Message") if isinstance(result, dict) else "获取二维码失败"
        state["phase"] = "failed"
        state["message"] = message or "获取二维码失败"
        return public_state()
    state["uuid"] = data.get("Uuid") or ""
    state["qrBase64"] = data.get("QrBase64") or ""
    state["phase"] = "scan"
    state["message"] = "请使用微信扫码"
    return public_state()


async def check_qr() -> dict:
    uuid = state.get("uuid") or ""
    if not uuid:
        state["message"] = "还没有二维码"
        return public_state()
    result = await call_wechat_api.login_check_qr(uuid)
    if not isinstance(result, dict):
        state["message"] = "检测二维码失败"
        return public_state()
    if result.get("Code") == -3:
        ticket = result.get("Data")
        state["needCode"] = True
        state["ticket"] = ticket if isinstance(ticket, str) else ""
        state["phase"] = "need_code"
        state["message"] = result.get("Message") or "请提交验证码"
        return public_state()
    if result.get("Success") and "登录成功" in (result.get("Message") or ""):
        wxid = _find_wxid(result.get("Data")) or config.cfg.service.wxid
        if wxid:
            apply_wxid(wxid)
        await _open_heartbeat(wxid)
        return public_state()
    status = _scan_status(result)
    if status == 1:
        state["message"] = "已扫码，等待手机确认"
    elif status == 0:
        state["message"] = "等待扫码"
    else:
        state["message"] = result.get("Message") or "等待扫码"
    return public_state()


async def submit_code(code: str) -> dict:
    code = (code or "").strip()
    if not code:
        state["message"] = "验证码为空"
        return public_state()
    result = await call_wechat_api.login_verify_code(
        state.get("uuid") or "", code, state.get("ticket") or ""
    )
    if isinstance(result, dict) and result.get("Success"):
        wxid = _find_wxid(result.get("Data")) or config.cfg.service.wxid
        if wxid:
            apply_wxid(wxid)
        await _open_heartbeat(wxid)
        return public_state()
    message = result.get("Message") if isinstance(result, dict) else "验证码提交失败"
    state["message"] = message or "验证码提交失败"
    return public_state()


async def open_heartbeat() -> dict:
    wxid = config.cfg.service.wxid
    await _open_heartbeat(wxid)
    return public_state()


def save_device_id(device_id: str) -> None:
    raw = config.load_raw_config()
    raw.setdefault("service", {})["device_id"] = device_id
    config.save_raw_config(raw)


def public_state() -> dict:
    qr = state.get("qrBase64") or ""
    if qr and not qr.startswith("data:"):
        qr = "data:image/jpg;base64," + qr
    return {
        "phase": state.get("phase"),
        "message": state.get("message"),
        "uuid": state.get("uuid"),
        "qrBase64": qr,
        "needCode": bool(state.get("needCode")),
        "wxid": config.cfg.service.wxid,
        "deviceId": config.cfg.service.device_id,
    }
