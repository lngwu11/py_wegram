import asyncio
import os
from typing import Tuple

from loguru import logger

import config
from admin.hub import hub
from admin.store import message_store
from api.wechat_download import chunked_download, dated_media_dir


def summarize(msg_type, content, push_content: str) -> Tuple[str, str, str]:
    """返回文本摘要、CDN 文件号、媒体种类。

    结构化消息（文件/引用/表情等）不能只依赖 PushContent，否则 PushContent
    为空时 text 会落成空串，管理台消息列表就会出现只有名字和时间的空气泡。
    """
    cdn = ""
    kind = ""
    push = (push_content or "").strip()
    text = ""

    if isinstance(content, dict):
        msg = content.get("msg") or {}
        if not isinstance(msg, dict):
            msg = {}
        img = msg.get("img")
        video = msg.get("videomsg")
        emoji = msg.get("emoji")
        appmsg = msg.get("appmsg")

        if isinstance(img, dict) and img:
            kind = "image"
            cdn = img.get("cdnbigimgurl") or img.get("cdnmidimgurl") or img.get("cdnthumburl") or ""
            text = push or "[图片]"
        elif isinstance(video, dict) and video:
            kind = "video"
            cdn = video.get("cdnvideourl") or video.get("cdnthumburl") or ""
            text = push or "[视频]"
        elif isinstance(emoji, dict) and emoji:
            text = push or "[表情]"
        elif isinstance(appmsg, dict):
            app_type = str(appmsg.get("type") or "")
            title = appmsg.get("title") or ""
            if isinstance(title, dict):
                title = ""
            title = str(title).strip()
            if app_type == "6":
                text = push or (f"[文件] {title}" if title else "[文件]")
            elif app_type == "57":
                text = push or (f"[引用] {title}" if title else "[引用]")
            elif app_type in ("5", "33", "36"):
                text = push or (f"[链接] {title}" if title else "[链接]")
            elif title:
                text = push or title
            else:
                text = push or "[应用消息]"
        elif isinstance(content.get("sysmsg"), dict):
            revoke = content["sysmsg"].get("revokemsg") or {}
            if isinstance(revoke, dict) and revoke.get("replacemsg"):
                text = str(revoke.get("replacemsg"))
            else:
                text = push or "[系统消息]"
        else:
            text = push
    elif isinstance(content, str):
        text = content
    else:
        text = push

    if not (text or "").strip():
        fallback = {
            3: "[图片]",
            34: "[语音]",
            42: "[名片]",
            43: "[视频]",
            47: "[表情]",
            48: "[位置]",
            49: "[应用消息]",
            2000: "[转账]",
            2001: "[红包]",
            "revokemsg": "[撤回]",
        }
        text = fallback.get(msg_type) or (f"[{msg_type}]" if msg_type not in (None, "") else "[消息]")

    return text[:2000], str(cdn)[:1000], kind


def _as_path(result) -> Tuple[bool, str]:
    if not result:
        return False, ""
    ok = bool(result[0])
    path = result[1] if len(result) > 1 else ""
    if ok and isinstance(path, str):
        return True, path
    return False, ""


async def archive_incoming(
        msg_id,
        new_msg_id,
        msg_type,
        original_type,
        from_wxid: str,
        to_wxid: str,
        sender_wxid: str,
        create_time,
        content,
        push_content: str,
        raw_xml: str,
) -> None:
    text, cdn_file, kind = summarize(original_type, content, push_content or "")
    message_store.save({
        "msg_id": msg_id,
        "new_msg_id": new_msg_id,
        "msg_type": msg_type,
        "from_wxid": from_wxid,
        "to_wxid": to_wxid,
        "sender_wxid": sender_wxid,
        "create_time": create_time or 0,
        "text": text,
        "cdn_file": cdn_file,
        "raw_xml": (raw_xml or "")[:20000],
    })
    item = message_store.get(str(msg_id)) or {}
    await hub.publish({"event": "message", "item": item})

    if kind and isinstance(content, dict):
        import asyncio
        asyncio.create_task(_download_media(str(msg_id), kind, from_wxid, content, create_time))


async def archive_names(msg_id, contact_name: str, sender_name: str) -> None:
    from admin.db import remember_group_name
    message_store.update_names(str(msg_id), contact_name, sender_name)
    saved = message_store.get(str(msg_id)) or {}
    from_wxid = saved.get("from_wxid") or ""
    if from_wxid.endswith("@chatroom"):
        remember_group_name(from_wxid, contact_name)
    await hub.publish({
        "event": "names",
        "msgId": str(msg_id),
        "contactName": contact_name,
        "senderName": sender_name,
    })


async def _download_media(msg_id: str, kind: str, from_wxid: str, content: dict, create_time=0) -> None:
    try:
        if kind == "image":
            save_dir = dated_media_dir(os.path.join(config.ROOT, "chat_images"), create_time)
            result = await chunked_download(
                "GET_IMAGE", msg_id, from_wxid, content, "img", "png", save_dir
            )
        elif kind == "video":
            save_dir = dated_media_dir(os.path.join(config.ROOT, "chat_videos"), create_time)
            result = await chunked_download(
                "GET_VIDEO", msg_id, from_wxid, content, "videomsg", "mp4", save_dir,
                max_bytes=config.cfg.media.max_video_bytes,
            )
        else:
            return
        ok, path = _as_path(result)
        if not ok:
            logger.warning(f"媒体下载未成功 msg_id={msg_id} kind={kind}")
            return
        rel = os.path.relpath(path, config.ROOT).replace("\\", "/")
        message_store.update_media(msg_id, rel)
        await hub.publish({
            "event": "media",
            "msgId": msg_id,
            "mediaUrl": "/admin/media/" + rel,
        })
    except Exception as e:
        logger.error(f"归档媒体失败 msg_id={msg_id}: {e}")
