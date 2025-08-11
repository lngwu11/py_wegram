import asyncio
import random
import threading
import time
import traceback
from asyncio import Queue
from typing import Dict, Any, Optional

from loguru import logger

import config
import httpapi
from api import wechat_contacts, wechat_tenpay
from config import LOCALE as locale
from utils import message_formatter, caichengyu
from utils.contact_manager import contact_manager
from utils.group_manager import group_manager

black_list = ['open_chat', 'bizlivenotify', 'qy_chat_update', 74, 'paymsg']


# 提取回调信息 - 保持同步，纯数据处理
def extract_message(data):
    try:
        # 提取所需字段
        message_info = {
            'MsgId': data.get('MsgId'),
            'NewMsgId': data.get('NewMsgId'),
            'FromUserName': data.get('FromUserName', {}).get('string', ''),
            'ToUserName': data.get('ToUserName', {}).get('string', ''),
            'MsgType': data.get('MsgType'),
            'Content': data.get('Content', {}).get('string', ''),
            'PushContent': data.get('PushContent', ''),
            'CreateTime': data.get('CreateTime'),
        }

        return message_info

    except Exception as e:
        logger.error(f"提取消息信息失败: {e}")
        return None


async def _get_contact_info(wxid: str, content: dict, push_content: str) -> tuple:
    """获取联系人显示信息，处理特殊情况"""
    # 先读取已保存的联系人
    contact_saved = await contact_manager.get_contact(wxid)
    if contact_saved:
        contact_name = contact_saved["name"]
        avatar_url = contact_saved["avatarLink"]
    else:
        # 异步获取联系人信息
        user_info = await wechat_contacts.get_user_info(wxid)
        contact_name = user_info.name
        avatar_url = user_info.avatar_url

    # 从推送内容获取用户名称
    if (contact_name.startswith('微信_') or contact_name.startswith('企微_')) and push_content:
        contact_name = push_content.split(" : ")[0].split("さん")[0]

    # 服务通知
    if wxid == "service_notification":
        contact_name = (
                content.get('msg', {}).get('appinfo', {}).get('appname') or
                content.get('msg', {}).get('appmsg', {}).get('mmreader', {}).get('publisher', {}).get('nickname') or
                content.get('msg', {}).get('appmsg', {}).get('mmreader', {}).get('category', {}).get('name') or
                content.get('msg', {}).get('appmsg', {}).get('mmreader', {}).get('category', {}).get('item', {}).get('sources', {}).get('source', {}).get('name') or
                ''
        )

    return contact_name, avatar_url


async def _get_sender_info(from_wxid: str, sender_wxid: str, contact_name: str = "") -> str:
    if sender_wxid == from_wxid:  # 私聊
        sender_name = contact_name
    else:  # 群聊
        contact_saved = await contact_manager.get_contact(sender_wxid)
        if contact_saved:
            sender_name = contact_saved["name"]
        else:
            sender_name = await group_manager.get_display_name(from_wxid, sender_wxid)
            if not sender_name:
                sender_name = "未知用户"

    return sender_name


async def _get_chat(from_wxid: str) -> Optional[int]:
    """获取或创建聊天群组"""
    # 读取contact映射
    contact_dic = await contact_manager.get_contact(from_wxid)

    if contact_dic and not contact_dic["isReceive"]:
        return None

    # 检查是否已有有效的chatId
    if contact_dic and contact_dic["isReceive"] and contact_dic["chatId"] != -9999999999:
        return contact_dic["chatId"]

    return None


async def process_callback_message(message_data: Dict[str, Any]) -> None:
    """处理微信回调消息"""
    try:
        message_info = extract_message(message_data)
        if not message_info:
            logger.error("提取消息信息失败")
            return

        # 忽略微信官方信息
        if message_info["FromUserName"] == "weixin":
            return

        await message_processor.add_message_async(message_info)

    except Exception as e:
        logger.error(f"消息处理失败: {e}", exc_info=True)


async def _process_message_async(message_info: Dict[str, Any]) -> None:
    """异步处理单条消息"""
    try:
        # ========== 消息基础信息解析 ==========
        msg_type = int(message_info['MsgType'])
        msg_id = message_info['MsgId']
        new_msg_id = message_info['NewMsgId']
        from_wxid = message_info['FromUserName']
        to_wxid = message_info['ToUserName']
        content = message_info['Content']
        push_content = message_info['PushContent']
        create_time = message_info['CreateTime']

        # 处理服务通知
        if from_wxid.endswith('@app'):
            from_wxid = "service_notification"

        # 处理群聊消息格式
        if from_wxid.endswith('@chatroom'):
            if ':\n' in content:
                sender_part, content_part = content.split('\n', 1)
                sender_wxid = sender_part.rstrip(':')
                content = content_part
            else:
                sender_wxid = message_info['FromUserName'] if message_info['FromUserName'] == config.WXID else ""
        else:
            sender_wxid = from_wxid

        # logger.info(f"from_wxid: {from_wxid} to_wxid: {to_wxid}")

        # 转发自己的消息
        # if from_wxid == config.WXID:
        #     from_wxid = to_wxid

        # ========== 特殊消息类型处理 ==========
        # 微信上打开联系人对话
        if msg_type == 51:
            msg_type = "open_chat"

        # 处理非文本消息
        if msg_type != 1 and msg_type != 10000:
            content = message_formatter.xml_to_json(content)
            if msg_type == 49:  # App消息
                msg_type = int(content['msg']['appmsg']['type'])
            elif msg_type == 50:  # 通话信息
                msg_type = content['voipmsg']['type']
            elif msg_type == 10002:  # 系统信息
                msg_type = content['sysmsg']['type']

        # ========== 早期过滤不需要处理的消息 ==========
        if (from_wxid.endswith('@placeholder_foldgroup') or  # 激活折叠聊天
                from_wxid == 'notification_messages' or  # 系统通知
                msg_type in black_list or  # 黑名单类型
                (sender_wxid == config.WXID and msg_type == "revokemsg")):  # 自己撤回的消息
            return

        # ========== 获取联系人和发送者信息 ==========
        # 获取联系人信息
        contact_name, avatar_url = await _get_contact_info(from_wxid, content, push_content)
        # 获取发送者信息
        sender_name = await _get_sender_info(from_wxid, sender_wxid, contact_name)

        logger.info(f"💬 类型:{locale.type(msg_type)} 来自:{contact_name}[{from_wxid}] 发送者:{sender_name}[{sender_wxid}] 内容:{content}")

        if msg_type == 2001 and from_wxid.endswith('@chatroom'):
            notify_msg = f"收到来自群[{contact_name}]-[{sender_name}]的红包".encode('utf-8')
            httpapi.do_post(config.cfg.ntfy_url, notify_msg)
            # 自动抢红包
            time.sleep(random.randint(3, 5))
            logger.warning("~~~~~抢hb~~~~~~~")
            await wechat_tenpay.auto_hong_bao(from_wxid, message_info['Content'])

        elif msg_type == 1:
            """处理文本消息"""

            # 处理成语
            if sender_wxid in config.cfg.ccy.saveimg_wxids:
                caichengyu.handle_text(content)

        elif msg_type == 3:
            """处理图片消息"""

            # 处理成语
            if sender_wxid in config.cfg.ccy.saveimg_wxids:
                await caichengyu.handle_image(msg_id, from_wxid, content)

        # 获取群组
        chat_id = await _get_chat(from_wxid)
        if not chat_id:
            return

        # ========== 设置发送者显示格式 ==========
        # 获取联系人信息用于显示
        contact_dic = await contact_manager.get_contact(from_wxid)

        # 设置发送者显示名称
        if "chatroom" in from_wxid or contact_dic["isGroup"]:
            sender_name = f"<blockquote expandable>{sender_name}: </blockquote>"
        else:
            sender_name = ""

        # 调试输出未知类型消息
        types_keys = [k for k in locale.type_map.keys()]
        if msg_type not in types_keys:
            logger.warning(f"💬 类型:{msg_type} 来自:{from_wxid} 发送者:{sender_wxid} 内容:{content}")

    except Exception as e:
        logger.error(f"异步消息处理失败: {e}", exc_info=True)
        traceback.print_exc()  # 打印完整堆栈信息


class MessageProcessor:
    def __init__(self):
        self.queue = None
        self.loop = None
        self._shutdown = False
        self._task = None
        self._init_complete = asyncio.Event()
        self._init_async_env()

    def _init_async_env(self):
        """在后台线程中初始化异步环境"""

        def run_async():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.queue = Queue(maxsize=1000)

            # 启动队列处理器
            self._task = self.loop.create_task(self._process_queue())
            logger.info("消息处理器已启动")

            # 标记初始化完成
            self.loop.call_soon_threadsafe(self._init_complete.set)

            # 运行事件循环
            try:
                self.loop.run_forever()
            except Exception as e:
                logger.error(f"消息处理器事件循环异常: {e}")

        thread = threading.Thread(target=run_async, daemon=True)
        thread.start()

    async def _process_queue(self):
        """处理队列中的消息"""
        while not self._shutdown:
            try:
                # 等待消息
                message = await asyncio.wait_for(self.queue.get(), timeout=1.0)

                # 处理消息
                await _process_message_async(message)
                self.queue.task_done()

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"处理消息失败: {e}", exc_info=True)

    def add_message(self, message_info: Dict[str, Any]):
        """添加消息到队列 - 同步版本（兼容性）"""
        if not self.loop or not self.queue:
            logger.error("处理器未就绪")
            return

        # 线程安全地添加消息
        try:
            self.loop.call_soon_threadsafe(
                self.queue.put_nowait, message_info
            )
        except Exception as e:
            logger.error(f"添加消息到队列失败: {e}")

    async def add_message_async(self, message_info: Dict[str, Any]):
        """添加消息到队列"""
        # 等待初始化完成
        if not self._init_complete.is_set():
            await asyncio.wait_for(self._init_complete.wait(), timeout=5.0)

        if not self.queue:
            logger.error("处理器未就绪")
            return

        try:
            # 如果在同一个事件循环中，直接添加
            if asyncio.get_event_loop() == self.loop:
                await self.queue.put(message_info)
            else:
                # 跨线程调用
                future = asyncio.run_coroutine_threadsafe(
                    self.queue.put(message_info), self.loop
                )
                await asyncio.wrap_future(future)
        except Exception as e:
            logger.error(f"异步添加消息到队列失败: {e}")

    async def shutdown(self):
        """优雅关闭处理器"""
        logger.info("正在关闭消息处理器...")
        self._shutdown = True

        if self.queue:
            # 等待队列处理完成
            try:
                await asyncio.wait_for(self.queue.join(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("等待队列处理完成超时")

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)

        logger.info("消息处理器已关闭")

    def get_queue_size(self) -> int:
        """获取队列大小"""
        if self.queue:
            return self.queue.qsize()
        return 0


# 全局实例
message_processor = MessageProcessor()
