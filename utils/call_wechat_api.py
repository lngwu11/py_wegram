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


async def auto_heart_beat_log(wxid: str) -> any:
    params = {
        "wxid": wxid,
    }
    return await wechat_api("AUTO_HEART_BEAT_LOG", query_params=params)
