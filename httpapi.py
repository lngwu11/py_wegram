import json

import requests
from loguru import logger
from requests import RequestException


# 返回结果状态码
class Status:
    # 成功
    OK = 0
    # 失败
    Fail = 1


# 封装返回结果，格式如下，其中data为字典类型或者字符串类型
# {'status': 0, 'data': {}}
class Result:
    def __init__(self):
        self.__result = {}

    def set_status(self, s=Status.Fail):
        self.__result["status"] = s

    def set_data(self, r=None):
        self.__result["data"] = r

    def is_ok(self):
        return self.__result["status"] == Status.OK

    def is_fail(self):
        return self.__result["status"] != Status.OK

    def get_data(self):
        return self.__result["data"]

    def get_result(self):
        return self.__result


def do_get(url, params=None, headers=None, cookies=None):
    r = Result()

    logger.info("[GET请求]：{}", url)

    try:
        # 发送GET请求
        response = requests.get(url, params=params, headers=headers, cookies=cookies)
        response.raise_for_status()

        # logger.info("code={}, headers encoding={}", response.status_code, response.headers.get('Content-Encoding'))
        if response.status_code == 200:
            logger.info("[GET响应]：{}", response.text)
            r.set_status(Status.OK)
            r.set_data(response.json())
        else:
            logger.error("[GET响应]失败：{}", response)
            r.set_status(Status.Fail)
            r.set_data(response)

        return r

    except RequestException as e:
        # 请求发生异常，打印异常信息和响应内容（如果有）
        err = e if e.response is None else e.response.text
        logger.error("[GET请求]异常: {}", err)
        r.set_status(Status.Fail)
        r.set_data(err)
        return r


def do_post(url, data=None, json=None, headers=None, params=None, cookies=None):
    r = Result()

    logger.info("[POST请求]：{}", url)

    try:
        # 发送POST请求，将JSON数据作为请求体
        response = requests.post(url, data=data, json=json, headers=headers, params=params, cookies=cookies)
        response.raise_for_status()

        # logger.info("code={}, headers encoding={}", response.status_code, response.headers.get('Content-Encoding'))
        if response.status_code == 200 or response.status_code == 201:
            logger.info("[POST响应]：{}", response.text)
            r.set_status(Status.OK)
            r.set_data(response.json())
        else:
            logger.error("[POST响应]失败：{}", response)
            r.set_status(Status.Fail)
            r.set_data(response)

        return r

    except RequestException as e:
        # 请求发生异常，打印异常信息和响应内容（如果有）
        err = e if e.response is None else e.response.text
        logger.error("[POST请求]异常: {}", err)
        r.set_status(Status.Fail)
        r.set_data(err)
        return r


def do_put(url, data=None, json=None, headers=None, params=None):
    r = Result()

    logger.info("[PUT请求]：{}", url)

    try:
        # 发送PUT请求，将JSON数据作为请求体
        response = requests.put(url, data=data, json=json, headers=headers, params=params)
        response.raise_for_status()

        # logger.info("code={}, headers encoding={}", response.status_code, response.headers.get('Content-Encoding'))
        if response.status_code == 200 or response.status_code == 201:
            logger.info("[PUT响应]：{}", response.text)
            r.set_status(Status.OK)
            r.set_data(response.json())
        else:
            logger.error("[PUT响应]失败：{}", response)
            r.set_status(Status.Fail)
            r.set_data(response)

        return r

    except RequestException as e:
        # 请求发生异常，打印异常信息和响应内容（如果有）
        err = e if e.response is None else e.response.text
        logger.error("[PUT请求]异常: {}", err)
        r.set_status(Status.Fail)
        r.set_data(err)
        return r

# res = do_get("https://httpbin.org/get")
# logger.debug(res.get_result())
#
# res = do_post("https://httpbin.org/post")
# logger.debug(res.get_result())
#
# res = do_put("https://httpbin.org/put")
# logger.debug(res.get_result())

# contact_name="仅仅语音"
# notify_msg = f"收到群[{contact_name}]红包"
# do_post("https://ntfy.sh/lngwu00", data=notify_msg.encode('utf-8'))