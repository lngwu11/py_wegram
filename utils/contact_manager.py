import asyncio
import json
import os
from typing import Dict, Optional

from loguru import logger

from admin.db import import_json_once, load_contacts, replace_contacts
from api import wechat_contacts


# 异步版本的ContactManager类
class ContactManager:
    def __init__(self):
        self.contacts = []
        self.wxid_to_contact = {}
        self.chatid_to_wxid = {}
        self.contact_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contact.json")
        self._loaded = False

        # 初始加载联系人（同步方式，用于初始化）
        self._load_contacts_sync()

    def _reindex(self):
        self.wxid_to_contact = {contact["wxId"]: contact for contact in self.contacts if contact.get("wxId")}
        self.chatid_to_wxid = {
            contact["chatId"]: contact["wxId"]
            for contact in self.contacts
            if contact.get("wxId") and "chatId" in contact
        }

    def _load_contacts_sync(self):
        """从数据库加载联系人。库为空时导入 contact.json。"""
        try:
            import_json_once(self.contact_file_path, None, replace_contacts, lambda: not load_contacts())
            self.contacts = load_contacts()
            self._reindex()
            self._loaded = True
            logger.info(f"联系人已从数据库加载，共 {len(self.contacts)} 个")
        except Exception as e:
            logger.error(f"读取联系人失败: {e}")
            self.contacts = []
            self.wxid_to_contact = {}
            self.chatid_to_wxid = {}
            self._loaded = True

    async def load_contacts(self):
        if self._loaded:
            return
        self._load_contacts_sync()

    async def _save_contacts(self):
        """保存联系人到数据库"""
        try:
            replace_contacts(self.contacts)
            self._reindex()
        except Exception as e:
            logger.error(f"保存联系人失败: {e}")
            raise

    async def delete_contact(self, wxid: str) -> bool:
        """删除联系人信息"""
        try:
            # 先加载最新的联系人信息
            await self.load_contacts()

            # 检查联系人是否存在
            if wxid not in self.wxid_to_contact:
                logger.warning(f"联系人不存在: {wxid}")
                return False

            # 获取要删除的联系人信息
            contact_to_delete = self.wxid_to_contact[wxid]
            chat_id = contact_to_delete.get("chatId")

            # 从内存中删除
            self.contacts = [contact for contact in self.contacts if contact["wxId"] != wxid]
            del self.wxid_to_contact[wxid]

            # 如果有chatId，也从映射中删除
            if chat_id and chat_id in self.chatid_to_wxid:
                del self.chatid_to_wxid[chat_id]

            # 保存到文件
            await self._save_contacts()

            return True

        except Exception as e:
            logger.error(f"删除联系人失败: {wxid}, 错误: {e}")
            return False

    async def delete_contact_by_chatid(self, chat_id: int) -> bool:
        """通过ChatID删除联系人信息"""
        try:
            # 先通过chatId获取wxId
            wxid = await self.get_wxid_by_chatid(chat_id)
            if not wxid:
                logger.warning(f"未找到ChatID对应的联系人: {chat_id}")
                return False

            # 调用删除方法
            return await self.delete_contact(wxid)

        except Exception as e:
            logger.error(f"通过ChatID删除联系人失败: {chat_id}, 错误: {e}")
            return False

    async def update_contact_by_chatid(self, chat_id: int, updates: dict) -> bool:
        """通过ChatID更新联系人的指定字段"""
        try:
            # 先加载最新的联系人信息
            await self.load_contacts()

            # 通过chatId获取wxId
            wxid = self.chatid_to_wxid.get(int(chat_id))
            if not wxid:
                return False

            # 找到联系人在列表中的索引
            contact_index = -1
            for i, contact in enumerate(self.contacts):
                if contact["wxId"] == wxid:
                    contact_index = i
                    break

            if contact_index == -1:
                return False

            # 批量更新字段
            for key, value in updates.items():
                # 特殊处理切换布尔值
                if value == "toggle" and key in ["isReceive", "isGroup"]:
                    current_value = self.contacts[contact_index].get(key, False)
                    value = not current_value
                elif key in ["isReceive", "isGroup"] and isinstance(value, str):
                    # 如果传入字符串，转换为布尔值
                    value = value.lower() in ['true', '1', 'yes', 'on']

                # 更新字段
                self.contacts[contact_index][key] = value
                self.wxid_to_contact[wxid][key] = value

            # 保存到文件
            await self._save_contacts()
            return True

        except Exception as e:
            logger.error(f"更新联系人字段失败 - ChatID: {chat_id}, 更新: {updates}, 错误: {e}")
            return False

    async def search_contacts_by_name(self, username: str = "") -> list:
        """根据用户名搜索联系人"""
        try:
            # 先加载最新的联系人信息
            await self.load_contacts()

            if not username or not username.strip():
                return self.contacts

            # 搜索name字段包含username的联系人（不区分大小写）
            username_lower = username.strip().lower()
            matching_contacts = []

            for contact in self.contacts:
                contact_name = contact.get("name", "")
                if contact_name and username_lower in contact_name.lower():
                    matching_contacts.append(contact)

            return matching_contacts

        except Exception as e:
            logger.error(f"搜索联系人失败 - 用户名: {username}, 错误: {e}")
            return []

    async def get_contact(self, wxid):
        """异步获取联系人信息"""
        await self.load_contacts()
        contact = self.wxid_to_contact.get(wxid)
        return contact

    async def get_wxid_by_chatid(self, chat_id):
        """异步通过chatId获取wxId"""
        await self.load_contacts()
        return self.chatid_to_wxid.get(int(chat_id))

    async def get_contact_by_chatid(self, chat_id):
        """异步通过chatId获取联系人完整信息"""
        wxid = await self.get_wxid_by_chatid(chat_id)
        return await self.get_contact(wxid) if wxid else None

    async def check_existing_mapping(self, wxid: str) -> Optional[Dict]:
        """检查是否已有映射"""
        await self.load_contacts()
        for contact in self.contacts:
            if contact.get('wxId') == wxid and contact.get('chatId'):
                return contact
        return None

    async def save_chat_wxid_mapping(self, wxid: str, name: str, chat_id: int, avatar_url: str = None):
        """保存群组ID和微信ID的映射关系"""
        await self.load_contacts()

        # 检查是否已存在
        for contact in self.contacts:
            if contact.get('wxId') == wxid and contact.get('chatId') == chat_id:
                return

        is_group = wxid.endswith('@chatroom')
        new_contact = {
            "name": name,
            "wxId": wxid,
            "chatId": chat_id,
            "isGroup": is_group,
            "isReceive": True,
            "alias": "",
            "avatarLink": avatar_url
        }

        self.contacts.append(new_contact)
        self.wxid_to_contact[wxid] = new_contact
        self.chatid_to_wxid[chat_id] = wxid

        await self._save_contacts()

    async def update_contacts_and_sync_to_json(self, chat_id: int):
        """获取联系人列表并同步到contact.json"""
        try:
            # 发送开始处理的消息
            logger.info("🔄 正在获取联系人列表...")

            # 获取联系人列表
            friend_contacts, chatroom_contacts, gh_contacts = await wechat_contacts.get_friends()
            all_contacts = friend_contacts + chatroom_contacts
            if not all_contacts:
                # await telegram_sender.send_text(chat_id, "❌ 未获取到好友联系人")
                return

            logger.info(f"📋 获取到 {len(all_contacts)} 个好友，正在同步信息...")

            # 将all_contacts按每组20个分割
            batch_size = 20
            batches = [all_contacts[i:i + batch_size] for i in range(0, len(all_contacts), batch_size)]

            new_contacts_count = 0
            total_batches = len(batches)

            # 处理每个批次
            for batch_index, batch in enumerate(batches):
                try:
                    # 发送进度更新
                    if batch_index % 5 == 0 or batch_index == total_batches - 1:  # 每5个批次或最后一个批次更新进度
                        progress = f"⏳ 处理进度: {batch_index + 1}/{total_batches} 批次"
                        logger.info(progress)

                    # 调用get_user_info获取用户信息
                    user_info_dict = await wechat_contacts.get_user_info(batch)

                    if not user_info_dict:
                        logger.warning(f"批次 {batch_index + 1} 未获取到用户信息")
                        continue

                    # 遍历用户信息
                    for wxid, user_info in user_info_dict.items():
                        if user_info is None:
                            logger.warning(f"用户 {wxid} 信息获取失败")
                            continue

                        # 检查wxId是否已存在于contact.json中
                        existing_contact = await self.get_contact(wxid)

                        if existing_contact is None:
                            # 不存在则创建新联系人
                            new_contact = {
                                "name": user_info.name,
                                "wxId": wxid,
                                "chatId": -9999999999,
                                "isGroup": False,
                                "isReceive": True,
                                "alias": "",
                                "avatarLink": user_info.avatar_url if user_info.avatar_url else ""
                            }

                            # 添加到联系人管理器
                            self.contacts.append(new_contact)
                            self.wxid_to_contact[wxid] = new_contact

                            new_contacts_count += 1
                            logger.info(f"添加新联系人: {user_info.name} ({wxid})")

                    # 每处理几个批次休眠一下，避免请求过于频繁
                    if batch_index < total_batches - 1:  # 不是最后一个批次
                        await asyncio.sleep(0.5)  # 休眠500毫秒

                except Exception as e:
                    logger.error(f"处理批次 {batch_index + 1} 时出错: {str(e)}")
                    continue

            # 保存所有更改到文件
            if new_contacts_count > 0:
                await self._save_contacts()
                success_msg = f"✅ 同步完成！新增 {new_contacts_count} 个联系人到contact.json"
            else:
                success_msg = "✅ 同步完成！所有联系人已存在，无新增联系人"

            logger.info(success_msg)

            # 发送统计信息
            stats_msg = f"""
    📊 **同步统计**
    • 总好友数: {len(all_contacts)}
    • 新增联系人: {new_contacts_count}
    • 处理批次: {total_batches}
    • 当前联系人总数: {len(self.contacts)}
            """
            logger.info(stats_msg)

        except Exception as e:
            error_msg = f"❌ 更新联系人失败: {str(e)}"
            # await telegram_sender.send_text(chat_id, error_msg)
            logger.error(f"update_contacts执行失败: {str(e)}")


# 创建全局实例
contact_manager = ContactManager()
