import os
import sys
from typing import List

import requests
import yaml
from loguru import logger
from pydantic import BaseModel
from requests import RequestException

from utils.locales import Locale
import time
import threading
from typing import Callable


class Service(BaseModel):
    port: int
    wxid: str
    baseurl: str
    saveimg_wxids: List[str]
    ccy_weekdays: List[int]


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


def reload_config():
    global cfg
    cfg = load_config('config.yaml')
    logger.info(f"Reload config: {cfg}")


class ConfigWatcher:
    def __init__(self, config_path: str, reload_callback: Callable, interval: float = 3.0):
        self.config_path = os.path.abspath(config_path)  # 配置文件绝对路径
        self.reload_callback = reload_callback  # 配置文件更新后的回调函数
        self.interval = interval  # 检查间隔（秒）
        self.last_mtime = self._get_mtime()  # 初始修改时间
        self._stop_event = threading.Event()  # 停止信号
        self._thread = threading.Thread(target=self._watch, daemon=True)  # 后台线程

    def _get_mtime(self) -> float:
        """获取文件的最后修改时间"""
        return os.path.getmtime(self.config_path)

    def _watch(self):
        """后台线程：持续检查文件是否被修改"""
        while not self._stop_event.is_set():
            try:
                current_mtime = self._get_mtime()
                if current_mtime != self.last_mtime:  # 文件被修改
                    logger.info(f"[ConfigWatcher] 检测到配置文件修改: {self.config_path}")
                    self.last_mtime = current_mtime
                    self.reload_callback()  # 调用回调函数重新加载配置
            except Exception as e:
                logger.error(f"[ConfigWatcher] 错误: {e}")
            time.sleep(self.interval)

    def start(self):
        """启动监听线程"""
        self._thread.start()
        logger.info(f"[ConfigWatcher] 开始监听配置文件: {self.config_path}")

    def stop(self):
        """停止监听线程"""
        self._stop_event.set()
        self._thread.join()
        logger.info("[ConfigWatcher] 已停止监听")


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

# 创建并启动监听器
watcher = ConfigWatcher("config.yaml", reload_callback=reload_config)
watcher.start()

# 配置
PORT = cfg.service.port
WXID = cfg.service.wxid
BASE_URL = cfg.service.baseurl

# 语言
# LANG = os.getenv("LANG", "zh")
LOCALE = Locale("zh")
