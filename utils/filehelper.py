from loguru import logger

from utils import call_wechat_api


async def handle_cmd(content, to_wxid):
    if content == "/check":
        logger.info(" --- 检查状态 ---")
        await call_wechat_api.send_text(to_wxid, "ok")
