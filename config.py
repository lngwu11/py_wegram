import os
import sys

import requests
import yaml
from loguru import logger
from pydantic import BaseModel
from requests import RequestException

from utils.locales import Locale


class Service(BaseModel):
    port: int
    wxid: str
    baseurl: str


class Config(BaseModel):
    logfile: str
    loglevel: str
    ntfy_url: str

    service: Service


def load_config(file_path: str) -> Config:
    with open(file_path, 'r') as f:
        data = yaml.safe_load(f)
    return Config(**data)


# 加载配置文件
cfg = load_config('config.yaml')


class Notifier:
    LEVEL = "NOTIFY"

    def __init__(self, url=""):
        self.url = url

        # 自定义日志级别
        logger.level(Notifier.LEVEL, no=35, color="<magenta><bold>")

    def write(self, message):
        # print(message.encode(encoding='utf-8'))

        level = message.record['level'].name
        if not self.url or level != "NOTIFY":
            return

        time_str = message.record['time'].strftime("%Y-%m-%d %H:%M:%S")
        msg = message.record['message']
        data = f"{time_str} | {level}\n{msg}"

        try:
            requests.post(self.url, data=data.encode(encoding='utf-8'))
        except RequestException as e:
            err = e if e.response is None else e.response.content.decode()
            logger.error(f"Failed to post log to: {self.url}, err: {err}")


def init_logger(logfile=cfg.logfile, level=cfg.loglevel.upper(), ntfy_url=cfg.ntfy_url):
    path, filename = os.path.split(logfile)
    name, suffix = os.path.splitext(filename)
    log_file_path = f"{path}/{name}.{{time:YYYY-MM-DD}}{suffix}"

    # 去除默认控制台输出
    logger.remove()

    # 自定义日志格式，输出到控制台和文件
    # logger_format = "{time:YYYY-MM-DD HH:mm:ss.SSS} {level} {file}:{line} {message}"
    # logger.add(sys.stdout, format=logger_format, level=level)
    # logger.add(log_file_path, format=logger_format, level=level, rotation="00:00", compression="zip", retention="1 month")
    logger.add(sys.stdout, level=level, enqueue=True)
    logger.add(log_file_path, level=level, enqueue=True, rotation="00:00", retention="10 days", encoding='utf8')

    # 输出到 ntfy
    logger.add(Notifier(ntfy_url), enqueue=True)


init_logger()
logger.info(f"Config: {cfg}")

# 配置
PORT = cfg.service.port
WXID = cfg.service.wxid
BASE_URL = cfg.service.baseurl

# 语言
LANG = os.getenv("LANG", "zh")
LOCALE = Locale(LANG)
