import datetime
import hashlib
import os
import random
import re
import time
from typing import Dict

from loguru import logger

import config
from api import wechat_download
from utils import call_wechat_api
from config import cfg

save_file = ''


def get_file_md5(file_path: str, chunk_size: int = 4096) -> str:
    """计算文件的MD5值"""
    md5_hash = hashlib.md5()
    with open(file_path, "rb") as f:
        # 分块读取文件以处理大文件
        for chunk in iter(lambda: f.read(chunk_size), b""):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()


def extract_chinese_filename(filename: str) -> str:
    """
    去掉文件名后缀，并提取其中的中文字符
    """
    # 去掉文件后缀
    name_without_ext = os.path.splitext(filename)[0]

    # 提取中文字符（包括中文标点）
    chinese_chars = re.findall(r'[\u4e00-\u9fff\u3000-\u303f]', name_without_ext)

    # 拼接成字符串返回
    return ''.join(chinese_chars)


def collect_image_md5s(directory: str, image_extensions: tuple = ('.jpg', '.jpeg', '.png')) -> Dict[str, str]:
    """
    收集指定目录中所有图片文件的MD5值和处理后的文件名，以字典形式存储

    参数:
        directory: 要扫描的目录路径
        image_extensions: 被视为图片的文件扩展名

    返回:
        字典，key为MD5值，value为处理后的中文文件名
    """
    md5_dict = {}

    # 遍历目录中的所有文件和子目录
    for root, dirs, files in os.walk(directory):
        for file in files:
            # 检查文件扩展名是否为图片格式
            if file.lower().endswith(image_extensions):
                file_path = os.path.join(root, file)

                try:
                    # 计算文件MD5值
                    file_md5 = get_file_md5(file_path)

                    # 处理文件名：提取中文部分
                    chinese_name = extract_chinese_filename(file)

                    # 检查是否已存在该MD5值
                    if file_md5 not in md5_dict:
                        md5_dict[file_md5] = chinese_name
                        logger.info(f"已处理 {file_path}: {file_md5} -> {chinese_name}")
                    else:
                        logger.warning(f"跳过重复文件: {file_path}")

                except Exception as e:
                    logger.error(f"处理文件 {file_path} 时出错: {str(e)}")

    return md5_dict


def in_time_range(start: str, end: str):
    return start <= time.strftime("%H:%M:%S", time.localtime()) <= end


def get_answer(content: str) -> str:
    # 匹配【答案】后的内容（非贪婪模式）
    match = re.search(r'【答案】(.*?)\n', content)
    if match:
        answer = match.group(1).strip()
        return answer

    return ''


def handle_text(content: str):
    global save_file

    if not save_file or not in_time_range(cfg.ccy.text_time_range[0], cfg.ccy.text_time_range[1]):
        return

    answer = get_answer(content)
    logger.debug(f"过滤答案：{answer}")
    if answer:
        parent_path = os.path.dirname(save_file)
        save_path = os.path.join(parent_path, answer + ".png")
        if os.path.exists(save_path):
            save_path = os.path.join(parent_path, answer + str(random.randint(1, 100)) + ".png")

        logger.debug(f"重命名文件：{save_path}")
        os.rename(save_file, save_path)
        save_file = None
        image_md5s[get_file_md5(save_path)] = answer
        logger.debug(f"成语总数：{len(image_md5s)}")


async def handle_image(msg_id, from_wxid, content):
    global save_file

    if not in_time_range(cfg.ccy.img_time_range[0], cfg.ccy.img_time_range[1]):
        return

    msg_img_md5 = content['msg']['img']['md5']
    logger.debug(f"获取到md5值：{msg_img_md5}")
    if msg_img_md5 in image_md5s:
        value = image_md5s[msg_img_md5]
        logger.debug(f"获取到值：{value}")

        if not value:
            # 删除key
            del image_md5s[msg_img_md5]
            return

        # Monday is 0 and Friday is 4
        weekday = datetime.datetime.today().weekday()
        logger.debug(f"weekday={weekday} weekdays={cfg.ccy.weekdays}")
        if weekday in cfg.ccy.weekdays:
            # 延时3秒发送文本消息
            time.sleep(3)
            logger.info(f"发送文本：{value}")
            await call_wechat_api.send_text(from_wxid, value)

    else:
        # 异步下载图片
        logger.info(f"下载图片开始")
        success, file, _ = await wechat_download.get_image(msg_id, from_wxid, content)
        logger.info(f"下载图片结束：{success} 路径：{file}")
        save_file = file


image_md5s = {}


def init(images_path: str):
    if not config.cfg.ccy.enable:
        return

    global image_md5s
    image_md5s = collect_image_md5s(images_path)
    logger.debug(f"成语总数：{len(image_md5s)}")


if __name__ == '__main__':
    aaa = '''恭喜 @雄雄的小课堂 答对！

【答案】度日如年
【发音】dù rì rú nián
'''
    print(get_answer(aaa))
    print(get_answer(aaa) is None)

    if save_file:
        print(1)
    else:
        print(0)
