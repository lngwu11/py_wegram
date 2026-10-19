import asyncio
import os
from typing import Tuple

from loguru import logger

import config
from admin.hub import hub
from admin.store import message_store
from api.wechat_download import chunked_download


def summarize(msg_type, content, push_content: str) -> Tuple[str, str, str]:
    """返回文本摘要、CDN 文件号、媒体种类。"""
    cdn = ""
    kind = ""
    if msg_type == 3 and isinstance(content, dict):
        img = (content.get("msg") or {}).get("img") or {}
        if isinstance(img, dict):
            cdn = img.get("cdnbigimgurl") or img.get("cdnmidimgurl") or img.get("cdnthumburl") or ""
        kind = "image"
        text = push_content or "[图片]"
    elif msg_type == 43 and isinstance(content, dict):
        video = (content.get("msg") or {}).get("videomsg") or {}
        if isinstance(video, dict):
            cdn = video.get("cdnvideourl") or video.get("cdnthumburl") or ""
        kind = "video"
        text = push_content or "[视频]"
    elif isinstance(content, str):
        text = content
    else:
        text = push_content or ""
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
        asyncio.create_task(_download_media(str(msg_id), kind, from_wxid, content))


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


async def _download_media(msg_id: str, kind: str, from_wxid: str, content: dict) -> None:
    try:
        if kind == "image":
            save_dir = os.path.join(config.ROOT, "chat_images")
            result = await chunked_download(
                "GET_IMAGE", msg_id, from_wxid, content, "img", "png", save_dir
            )
        elif kind == "video":
            save_dir = os.path.join(config.ROOT, "chat_videos")
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
