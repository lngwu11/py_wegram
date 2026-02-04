import asyncio
import json

from loguru import logger

import config
from utils import call_wechat_api

# {
#   "Code": 0,
#   "Success": true,
#   "Message": "获取成功, 只保留最新的 100 条心跳、二次登录日志",
#   "Data": [
#     "[lnw1],[星空ت] 发送心跳成功，下次刷新时间：2026-02-04 10:31:44",
#     "[ln11],[星空ت] 发送心跳成功，下次刷新时间：2026-02-04 10:29:14",
#   ],
#   "Data62": "",
#   "Debug": ""
# }

help_text = '''--------------------
/check: 检查状态(待支持)
/status: 获取最后一条心跳日志
/auto_heart_beat: 开启自动心跳
/help: 使用帮助
--------------------'''


async def handle_cmd(content, to_wxid):
    if content == "/check":
        logger.info(" --- 检查状态 ---")

    elif content == "/auto_heart_beat":
        logger.info(" --- 开启自动心跳 ---")
        await call_wechat_api.auto_heart_beat(config.cfg.service.wxid)

    elif content == "/status":
        logger.info(" --- 查询状态 ---")
        response = await call_wechat_api.auto_heart_beat_log(config.cfg.service.wxid)
        # logger.info(response)
        data = response.get("Data", [])
        if len(data) == 0:
            await call_wechat_api.send_text(to_wxid, "没有数据")
        else:
            await call_wechat_api.send_text(to_wxid, data[0])

    elif content == "/help":
        logger.info(" --- 获取帮助 ---")
        await call_wechat_api.send_text(to_wxid, help_text)


import re
from datetime import datetime


def check_content(text):
    pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})'
    match = re.search(pattern, text)
    if match:
        time_str = match.group(1)
        # 将匹配到的时间字符串转换为datetime对象
        try:
            target_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            print(f"错误：时间格式解析失败 - {time_str}")
            return

        if target_time <= datetime.now():
            pass

    else:
        print("未找到时间字符串")
        return None


if __name__ == '__main__':
    # asyncio.run(handle_cmd("/check", "filehelper"))

    # 测试用例
    # test_text = "[lnw1],[星空ت] 发送心跳成功，下次刷新时间：2026-02-04 10:31:44"
    # check_content(test_text)
    pass
