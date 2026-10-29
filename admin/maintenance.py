"""启动维护：旧媒体按日期归类、消息只保留最近若干年。"""
import os
import re
import shutil
import time
from datetime import datetime

from loguru import logger

import config
from admin.store import message_store
_MEDIA_ROOTS = ("chat_images", "chat_videos")
_DATE_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MESSAGE_KEEP_YEARS = 5


def run_startup_maintenance() -> None:
    try:
        moved = migrate_flat_media()
        filled = backfill_empty_message_text()
        noise = purge_noise_messages()
        purged = purge_old_messages(_MESSAGE_KEEP_YEARS)
        logger.info(
            f"启动维护完成: 媒体归类 {moved}, 回填摘要 {filled}, "
            f"清理噪音 {noise}, 清理超龄消息 {purged}"
        )
    except Exception as e:
        logger.error(f"启动维护失败: {e}")


_TITLE_CDATA = re.compile(r"<title>\s*<!\[CDATA\[(.*?)\]\]>\s*</title>", re.S | re.I)
_TITLE_PLAIN = re.compile(r"<title>(.*?)</title>", re.S | re.I)
_TYPE_FALLBACK = {
    "5": "[链接]",
    "6": "[文件]",
    "19": "[聊天记录]",
    "33": "[小程序]",
    "34": "[语音]",
    "42": "[名片]",
    "47": "[表情]",
    "51": "[视频号]",
    "57": "[引用]",
    "2000": "[转账]",
    "2001": "[红包]",
    "revokemsg": "[撤回]",
    "pat": "[拍一拍]",
}


def _text_from_raw(msg_type: str, raw_xml: str) -> str:
    raw = raw_xml or ""
    match = _TITLE_CDATA.search(raw) or _TITLE_PLAIN.search(raw)
    if match:
        title = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        title = title.replace("<![CDATA[", "").replace("]]>", "").strip()
        if title:
            if str(msg_type) == "5":
                return f"[链接] {title}"[:2000]
            if str(msg_type) == "57":
                return f"[引用] {title}"[:2000]
            if str(msg_type) == "6":
                return f"[文件] {title}"[:2000]
            return title[:2000]
    return _TYPE_FALLBACK.get(str(msg_type), "")


def backfill_empty_message_text() -> int:
    """把历史空 text 从 raw_xml 标题或类型占位回填。"""
    with message_store.lock:
        rows = message_store.conn.execute(
            """
            SELECT msg_id, msg_type, raw_xml FROM messages
            WHERE text IS NULL OR trim(text)=''
            """
        ).fetchall()
        updated = 0
        for row in rows:
            text = _text_from_raw(row["msg_type"], row["raw_xml"] or "")
            if not text:
                text = _TYPE_FALLBACK.get(str(row["msg_type"]), "[消息]")
            message_store.conn.execute(
                "UPDATE messages SET text=? WHERE msg_id=?",
                (text, str(row["msg_id"])),
            )
            updated += 1
        if updated:
            message_store.conn.commit()
    return updated


def purge_noise_messages() -> int:
    """删除误入库的打开会话等噪音消息。"""
    with message_store.lock:
        cur = message_store.conn.execute(
            "DELETE FROM messages WHERE msg_type IN ('open_chat','bizlivenotify','qy_chat_update','74','paymsg')"
        )
        message_store.conn.commit()
        return cur.rowcount or 0


def _day_from_ts(ts) -> str:
    try:
        value = int(ts or 0)
        if value > 0:
            return datetime.fromtimestamp(value).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        pass
    return datetime.now().strftime("%Y-%m-%d")


def _normalize_rel(path: str) -> str:
    return (path or "").replace("\\", "/").lstrip("/")


def _is_flat_media_rel(rel: str) -> bool:
    parts = _normalize_rel(rel).split("/")
    return len(parts) == 2 and parts[0] in _MEDIA_ROOTS and parts[1] and not _DATE_DIR.match(parts[1])


def _move_file(src: str, dest: str):
    """移动文件，返回最终路径；无需移动时返回已存在的 dest 或 None。"""
    if os.path.isfile(dest) and (not os.path.isfile(src) or os.path.abspath(src) == os.path.abspath(dest)):
        return dest
    if not os.path.isfile(src):
        return None
    if os.path.abspath(src) == os.path.abspath(dest):
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        try:
            if os.path.getsize(src) == os.path.getsize(dest):
                os.remove(src)
                return dest
        except OSError:
            pass
        stem, ext = os.path.splitext(dest)
        dest = f"{stem}_{int(time.time())}{ext}"
    shutil.move(src, dest)
    return dest


def migrate_flat_media() -> int:
    """把 chat_images|chat_videos 根目录下的文件迁到 YYYY-MM-DD，并更新 messages.media_path。"""
    moved = 0
    with message_store.lock:
        rows = message_store.conn.execute(
            "SELECT msg_id, create_time, media_path FROM messages WHERE media_path IS NOT NULL AND media_path != ''"
        ).fetchall()

    for row in rows:
        rel = _normalize_rel(row["media_path"])
        if not _is_flat_media_rel(rel):
            continue
        root, name = rel.split("/", 1)
        src = os.path.join(config.ROOT, root, name)
        day = _day_from_ts(row["create_time"])
        dest = os.path.join(config.ROOT, root, day, name)
        final = _move_file(src, dest)
        if not final:
            continue
        new_rel = f"{root}/{day}/{os.path.basename(final)}"
        if new_rel != rel:
            message_store.update_media(str(row["msg_id"]), new_rel)
        moved += 1

    for root_name in _MEDIA_ROOTS:
        base = os.path.join(config.ROOT, root_name)
        if not os.path.isdir(base):
            continue
        for name in os.listdir(base):
            src = os.path.join(base, name)
            if not os.path.isfile(src):
                continue
            try:
                day = datetime.fromtimestamp(os.path.getmtime(src)).strftime("%Y-%m-%d")
            except OSError:
                day = datetime.now().strftime("%Y-%m-%d")
            if _move_file(src, os.path.join(base, day, name)):
                moved += 1

    return moved


def purge_old_messages(keep_years: int = _MESSAGE_KEEP_YEARS) -> int:
    """删除 create_time 早于保留年限的消息，并尽量删除对应媒体文件。"""
    now = datetime.now()
    try:
        cutoff_dt = now.replace(year=now.year - keep_years)
    except ValueError:
        # 2/29 等边界
        cutoff_dt = now.replace(month=2, day=28, year=now.year - keep_years)
    cutoff = int(cutoff_dt.timestamp())

    with message_store.lock:
        rows = message_store.conn.execute(
            "SELECT msg_id, media_path FROM messages WHERE create_time > 0 AND create_time < ?",
            (cutoff,),
        ).fetchall()
        if not rows:
            return 0
        ids = [str(row["msg_id"]) for row in rows]
        media_paths = [_normalize_rel(row["media_path"]) for row in rows if row["media_path"]]
        message_store.conn.executemany("DELETE FROM messages WHERE msg_id=?", [(mid,) for mid in ids])
        message_store.conn.commit()

    for rel in media_paths:
        if not rel or ".." in rel.split("/"):
            continue
        root = rel.split("/", 1)[0]
        if root not in _MEDIA_ROOTS:
            continue
        full = os.path.realpath(os.path.join(config.ROOT, rel.replace("/", os.sep)))
        allowed = os.path.realpath(os.path.join(config.ROOT, root))
        if full == allowed or not full.startswith(allowed + os.sep):
            continue
        try:
            if os.path.isfile(full):
                os.remove(full)
        except OSError as e:
            logger.warning(f"删除过期媒体失败 {rel}: {e}")

    logger.info(
        f"已清理 {len(ids)} 条早于 {cutoff_dt.strftime('%Y-%m-%d')} 的消息（保留最近 {keep_years} 年）"
    )
    return len(ids)
