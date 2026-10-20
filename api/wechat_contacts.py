from loguru import logger

import config
from api.wechat_api import wechat_api


# 获取用户信息
class UserInfo:
    def __init__(self, name, avatar_url):
        self.name = name
        self.avatar_url = avatar_url


async def get_user_info(towxids):
    # 处理输入参数：如果是列表则用逗号连接，如果是字符串则直接使用
    if isinstance(towxids, list):
        if not towxids:  # 空列表检查
            return {}
        wxid_list = towxids
        towxids_str = ','.join(towxids)
        is_batch = True
    else:
        # 企业微信用户无信息，跳过调用API
        if towxids.endswith('@openim'):
            qwid = towxids[:-8]
            return UserInfo(f'企微_{qwid}', 'https://raw.githubusercontent.com/finalpi/wechat2tg/refs/heads/wx2tg-v3/qywx.jpg')

        wxid_list = [towxids]
        towxids_str = towxids
        is_batch = False

    # 构建请求体
    body = {
        "Wxid": config.WXID,
        "ChatRoom": "",
        "Towxids": towxids_str
    }

    # logger.debug(f"==> body: {body}")

    # 发送请求
    result = await wechat_api("USER_INFO", body)
    if not isinstance(result, dict) or not result.get("Success"):
        error_msg = result.get("Message", "未知错误") if isinstance(result, dict) else "wechat861 无响应"
        logger.error(f"API请求失败: {error_msg}")
        if is_batch:
            return {wxid: None for wxid in wxid_list}
        return None

    try:
            contact_list = result["Data"]["ContactList"]
            if contact_list and len(contact_list) > 0:
                if is_batch:
                    # 批量查询：返回字典，key为wxid，value为UserInfo
                    user_info_dict = {}
                    for i, wxid in enumerate(wxid_list):
                        if i < len(contact_list):
                            contact = contact_list[i]
                            name = (contact.get("Remark", {}).get("string") or
                                    contact.get("NickName", {}).get("string") or
                                    f"微信_{wxid}")
                            avatar_url = (contact.get("BigHeadImgUrl") or
                                          contact.get("SmallHeadImgUrl") or
                                          "")
                            user_info_dict[wxid] = UserInfo(name, avatar_url)
                        else:
                            # 如果contact_list长度不够，填充None
                            user_info_dict[wxid] = None
                    return user_info_dict
                else:
                    # 单个查询：返回单个UserInfo对象（保持原功能）
                    contact = contact_list[0]
                    name = (contact.get("Remark", {}).get("string") or
                            contact.get("NickName", {}).get("string") or
                            towxids_str)
                    avatar_url = (contact.get("BigHeadImgUrl") or
                                  contact.get("SmallHeadImgUrl") or
                                  "")
                    return UserInfo(name, avatar_url)
    except (KeyError, IndexError, TypeError) as e:
        logger.error(f"解析联系人信息时出错: {str(e)}")

    if is_batch:
        return {wxid: None for wxid in wxid_list}
    return None


# 修改后的函数
async def get_friends():
    """
    获取所有好友联系人并分类
    
    Returns:
        tuple: (friend_contacts, gh_contacts, chatroom_contacts)
            - friend_contacts: 私聊联系人ID列表（个人用户）
            - gh_contacts: 以gh_开头的联系人ID列表（公众号）
            - chatroom_contacts: 以@chatroom结尾的联系人ID列表（群聊）
    """

    # 初始化变量
    current_wx_seq = 0
    current_chatroom_seq = 0
    continue_flag = 1

    # 存储所有联系人
    all_contacts = []
    page_count = 0

    # 循环获取直到没有更多数据
    while continue_flag == 1:
        page_count += 1
        logger.debug(f"正在获取第 {page_count} 页数据...")

        # 构建请求体
        body = {
            "CurrentChatRoomContactSeq": current_chatroom_seq,
            "CurrentWxcontactSeq": current_wx_seq,
            "Wxid": config.WXID
        }

        try:
            # 调用API
            response = await wechat_api("USER_LIST", body)
            if not isinstance(response, dict) or not response.get("Success", False):
                error_msg = response.get("Message", "未知错误") if isinstance(response, dict) else "wechat861 无响应"
                logger.info(f"API调用失败: {error_msg}")
                break

            # 获取数据
            data = response.get('Data', {})

            # 更新分页参数
            continue_flag = data.get('CountinueFlag', 0)
            current_wx_seq = data.get('CurrentWxcontactSeq', 0)
            current_chatroom_seq = data.get('CurrentChatRoomContactSeq', 0)

            # 获取当前页的联系人列表
            contact_list = data.get('ContactUsernameList', [])
            contact_count = len(contact_list)

            logger.debug(f"第 {page_count} 页获取到 {contact_count} 个联系人")

            # 添加到总列表
            all_contacts.extend(contact_list)

            # 如果没有更多数据，退出循环
            if continue_flag == 0:
                logger.debug("已获取所有联系人数据")
                break

        except Exception as e:
            logger.error(f"请求第 {page_count} 页时发生错误: {str(e)}")
            break

    # 分类联系人
    gh_contacts = []  # 公众号（以gh_开头）
    chatroom_contacts = []  # 群聊（以@chatroom结尾）
    friend_contacts = []  # 私聊联系人（其余）

    for contact in all_contacts:
        if contact.startswith('gh_'):
            gh_contacts.append(contact)
        elif contact.endswith('@chatroom'):
            chatroom_contacts.append(contact)
        else:
            friend_contacts.append(contact)

    # 统计信息
    total_count = len(all_contacts)
    gh_count = len(gh_contacts)
    chatroom_count = len(chatroom_contacts)
    friend_count = len(friend_contacts)

    logger.debug("=" * 50)
    logger.debug("获取完成！")
    logger.debug(f"总页数: {page_count}")
    logger.debug(f"总联系人数: {total_count}")
    logger.debug(f"🏢 公众号数量 (gh_开头): {gh_count}")
    logger.debug(f"👥 群聊数量 (@chatroom结尾): {chatroom_count}")
    logger.debug(f"👤 私聊联系人数量: {friend_count}")
    logger.debug("=" * 50)

    return friend_contacts, chatroom_contacts, gh_contacts
