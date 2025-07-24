from loguru import logger

import config
from api.wechat_api import wechat_api


async def auto_hong_bao(send_username, xml):
    # 构建请求体
    body = {
        "Wxid": config.WXID,
        "Xml": xml,
        "SendUserName": send_username
    }

    logger.debug(f"QHB ==> 请求: {body}")

    # 发送请求
    result = await wechat_api("AUTO_HONGBAO", body)

    logger.debug(f"QHB ==> 结果: {result}")
