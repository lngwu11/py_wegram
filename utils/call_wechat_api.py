import config
from api.wechat_api import wechat_api


async def send_text(to_wxid: str, text: str) -> any:
    """发送文本消息到微信"""
    payload = {
        "At": "",
        "Content": text,
        "ToWxid": to_wxid,
        "Type": 1,
        "Wxid": config.WXID
    }
    return await wechat_api("SEND_TEXT", payload)


async def auto_heart_beat(wxid: str) -> any:
    payload = {
        "wxid": wxid,
    }
    return await wechat_api("AUTO_HEART_BEAT", payload)


async def auto_heart_beat_log(wxid: str, timeout: int = 5) -> any:
    params = {
        "wxid": wxid,
    }
    return await wechat_api("AUTO_HEART_BEAT_LOG", query_params=params, timeout=timeout)


async def twice_login(wxid: str) -> any:
    return await wechat_api("TWICE_LOGIN", query_params={"wxid": wxid})


async def login_get_qr(device_id: str, device_name: str = "") -> any:
    body = {
        "Proxy": {"ProxyIp": "", "ProxyUser": "", "ProxyPassword": ""},
        "DeviceID": device_id,
        "DeviceName": device_name,
        "LoginType": "",
    }
    return await wechat_api("LOGIN_GET_QR", body)


async def login_check_qr(uuid: str) -> any:
    return await wechat_api("LOGIN_CHECK_QR", query_params={"uuid": uuid})


async def login_verify_code(uuid: str, code: str, ticket: str, data62: str = "") -> any:
    body = {
        "Uuid": uuid,
        "Data62": data62,
        "Code": code,
        "Ticket": ticket,
    }
    return await wechat_api("LOGIN_VERIFY_CODE", body)
