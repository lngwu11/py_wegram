import config
from api.wechat_api import wechat_api


async def send_text(to_wxid: str, text: str) -> bool:
    """发送文本消息到微信"""
    payload = {
        "At": "",
        "Content": text,
        "ToWxid": to_wxid,
        "Type": 1,
        "Wxid": config.WXID
    }
    return await wechat_api("SEND_TEXT", payload)
