import os

from aiohttp import web

import config
from admin import auth, login_flow
from admin.hub import hub
from admin.db import load_profiles, set_custom_name
from admin.store import message_store
from utils.contact_manager import contact_manager
from utils.group_manager import group_manager


def _json(data, status=200):
    return web.json_response(data, status=status)


def register(app: web.Application) -> None:
    app.router.add_get("/", index_page)
    app.router.add_static("/web/", config.WEB_DIR, show_index=False)
    app.router.add_get("/admin/api/session", session_info)
    app.router.add_post("/admin/api/login", admin_sign_in)
    app.router.add_post("/admin/api/logout", admin_sign_out)
    app.router.add_get("/admin/api/status", admin_status)
    app.router.add_get("/admin/api/heartbeat-log", admin_heartbeat_log)
    app.router.add_get("/admin/api/config", admin_get_config)
    app.router.add_put("/admin/api/config", admin_put_config)
    app.router.add_get("/admin/api/contacts", admin_contacts)
    app.router.add_put("/admin/api/contacts/{wxid}", admin_update_contact)
    app.router.add_get("/admin/api/groups", admin_groups)
    app.router.add_post("/admin/api/groups/sync-names", admin_sync_group_names)
    app.router.add_put("/admin/api/groups/profile", admin_group_profile)
    app.router.add_get("/admin/api/groups/members", admin_group_members)
    app.router.add_get("/admin/api/conversations", admin_conversations)
    app.router.add_get("/admin/api/messages", admin_messages)
    app.router.add_get("/admin/api/plugins", admin_plugins)
    app.router.add_put("/admin/api/plugins/{pid}", admin_plugin_update)
    app.router.add_post("/admin/api/login/twice", admin_login_twice)
    app.router.add_post("/admin/api/login/qr", admin_login_qr)
    app.router.add_post("/admin/api/login/check", admin_login_check)
    app.router.add_post("/admin/api/login/code", admin_login_code)
    app.router.add_post("/admin/api/heartbeat", admin_heartbeat)
    app.router.add_get("/admin/api/login/state", admin_login_state)
    app.router.add_get("/admin/ws/messages", admin_message_ws)
    app.router.add_get("/admin/media/{tail:.*}", admin_media)
    app.router.add_route("OPTIONS", "/admin/{tail:.*}", options_ok)


async def options_ok(_request):
    return web.Response(status=204)


async def index_page(_request):
    path = os.path.join(config.WEB_DIR, "index.html")
    return web.FileResponse(path)


async def session_info(request):
    return _json({"authenticated": auth.valid(auth.read_token(request))})


async def admin_sign_in(request):
    ip = auth.client_ip(request)
    if not auth.allow_login(ip):
        return _json({"ok": False, "message": "登录失败，请稍后再试"}, status=429)
    if not auth.configured():
        return _json({"ok": False, "message": "请先在 config.yaml 填写 admin.username 和 admin.password"}, status=403)
    try:
        body = await request.json()
    except Exception:
        body = {}
    username = str(body.get("username") or "")
    password = str(body.get("password") or "")
    if not auth.check_password(username, password):
        return _json({"ok": False, "message": "账号或密码错误"}, status=401)
    return auth.attach(_json({"ok": True}), auth.issue())


async def admin_sign_out(request):
    auth.drop(auth.read_token(request))
    return auth.clear_cookie(_json({"ok": True}))


_last_heartbeat = ""


async def admin_status(_request):
    import wechat_handler
    import wechat_syncer

    return _json({
        "wxid": config.cfg.service.wxid,
        "baseurl": config.cfg.service.baseurl,
        "port": config.cfg.service.port,
        "callback": f"/msg/SyncMessage/{config.WXID}",
        "login": wechat_syncer.login_status,
        "lastHeartbeat": _last_heartbeat,
        "queue": wechat_handler.message_processor.get_queue_size(),
        "deviceId": config.cfg.service.device_id,
        "flow": login_flow.public_state(),
    })


async def admin_heartbeat_log(_request):
    global _last_heartbeat
    from utils import call_wechat_api

    last = ""
    log = await call_wechat_api.auto_heart_beat_log(config.cfg.service.wxid, timeout=3)
    if isinstance(log, dict):
        data = log.get("Data") or []
        if data:
            last = data[0]
            _last_heartbeat = last
    return _json({"lastHeartbeat": last or _last_heartbeat})


async def admin_get_config(_request):
    data = config.cfg.model_dump()
    data["admin"] = {"username": config.cfg.admin.username}
    return _json(data)


async def admin_put_config(request):
    body = await request.json()
    raw = config.load_raw_config()
    for key in ("ntfy_url", "media"):
        if key in body:
            raw[key] = body[key]
    try:
        config.save_raw_config(raw)
    except Exception as e:
        return _json({"ok": False, "message": str(e)}, status=400)
    return _json({"ok": True})


async def admin_contacts(request):
    keyword = (request.query.get("q") or "").strip()
    contacts = await contact_manager.search_contacts_by_name(keyword)
    page = _page(request)
    size = _size(request)
    start = (page - 1) * size
    return _json({
        "total": len(contacts),
        "page": page,
        "size": size,
        "items": contacts[start:start + size],
    })


async def admin_update_contact(request):
    wxid = request.match_info["wxid"]
    body = await request.json()
    await contact_manager.load_contacts()
    contact = contact_manager.wxid_to_contact.get(wxid)
    if not contact:
        return _json({"ok": False, "message": "联系人不存在"}, status=404)
    if "name" in body:
        contact["name"] = str(body["name"])
    if "isReceive" in body:
        contact["isReceive"] = bool(body["isReceive"])
    await contact_manager._save_contacts()
    return _json({"ok": True, "item": contact})


async def admin_groups(request):
    keyword = (request.query.get("q") or "").strip().lower()
    await contact_manager.load_contacts()
    profiles = load_profiles()
    rows = []
    for chatroom_id, members in group_manager.data.items():
        contact = contact_manager.wxid_to_contact.get(chatroom_id) or {}
        profile = profiles.get(chatroom_id) or {}
        group_name = profile.get("group_name") or contact.get("name") or ""
        custom_name = profile.get("custom_name") or contact.get("alias") or ""
        haystack = " ".join((chatroom_id, group_name, custom_name)).lower()
        if keyword and keyword not in haystack:
            continue
        rows.append({
            "id": chatroom_id,
            "name": group_name,
            "groupName": group_name,
            "customName": custom_name,
            "count": len(members) if isinstance(members, list) else 0,
        })
    rows.sort(key=lambda item: (item["customName"] or item["groupName"] or item["id"]).lower())
    page = _page(request)
    size = _size(request)
    start = (page - 1) * size
    return _json({
        "total": len(rows),
        "page": page,
        "size": size,
        "items": rows[start:start + size],
    })


async def admin_sync_group_names(_request):
    result = await group_manager.sync_names()
    if not result.get("updated"):
        result["message"] = "没有从 wechat861 取到群名，请确认 861 已登录"
    return _json(result)


async def admin_group_profile(request):
    body = await request.json()
    chatroom_id = (body.get("id") or "").strip()
    if not chatroom_id:
        return _json({"ok": False, "message": "缺少群 id"}, status=400)
    set_custom_name(chatroom_id, body.get("customName") or "")
    return _json({"ok": True})


async def admin_conversations(request):
    kind = request.query.get("kind") or "group"
    if kind not in ("group", "private"):
        kind = "group"
    rows = message_store.list_peers(kind, config.cfg.service.wxid)
    profiles = load_profiles()
    for row in rows:
        if kind == "group":
            profile = profiles.get(row["peer"]) or {}
            row["groupName"] = profile.get("group_name") or row.get("contact_name") or ""
            row["customName"] = profile.get("custom_name") or ""
            row["title"] = row["customName"] or row["groupName"] or row["peer"]
        else:
            row["title"] = row.get("contact_name") or row["peer"]
            row["groupName"] = ""
            row["customName"] = ""
    return _json(rows)


async def admin_group_members(request):
    chatroom_id = request.query.get("id") or ""
    members = group_manager.get_all_members(chatroom_id)
    page = _page(request)
    size = _size(request, default=50)
    start = (page - 1) * size
    return _json({
        "id": chatroom_id,
        "total": len(members),
        "page": page,
        "size": size,
        "items": members[start:start + size],
    })


async def admin_messages(request):
    peer = (request.query.get("peer") or "").strip()
    if peer:
        return _json({"peer": peer, "items": message_store.list_for_peer(peer, _size(request, default=80))})
    page = _page(request)
    size = _size(request)
    keyword = (request.query.get("q") or "").strip()
    return _json(message_store.list_messages(page, size, keyword))


async def admin_login_twice(_request):
    return _json(await login_flow.relogin())


async def admin_login_qr(request):
    body = {}
    if request.body_exists:
        try:
            body = await request.json()
        except Exception:
            body = {}
    return _json(await login_flow.start_qr((body or {}).get("deviceId") or ""))


async def admin_plugins(_request):
    from plugins.registry import list_plugins
    return _json(list_plugins())


async def admin_plugin_update(request):
    from plugins.registry import update
    from utils import caichengyu
    body = await request.json()
    item = update(request.match_info["pid"], body.get("enabled"), body.get("config"))
    if not item:
        return _json({"ok": False, "message": "插件不存在"}, status=404)
    if item["id"] == "ccy" and item["enabled"]:
        caichengyu.init(os.path.join(config.ROOT, "chat_images"))
    return _json(item)


async def admin_login_check(_request):
    return _json(await login_flow.check_qr())


async def admin_login_code(request):
    body = await request.json()
    return _json(await login_flow.submit_code(body.get("code") or ""))


async def admin_heartbeat(_request):
    return _json(await login_flow.open_heartbeat())


async def admin_login_state(_request):
    return _json(login_flow.public_state())


async def admin_message_ws(request):
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    await hub.register(ws)
    try:
        async for _msg in ws:
            pass
    finally:
        await hub.unregister(ws)
    return ws


async def admin_media(request):
    rel = request.match_info["tail"].replace("\\", "/")
    full = os.path.realpath(os.path.join(config.ROOT, rel))
    allowed = [
        os.path.realpath(os.path.join(config.ROOT, "chat_images")),
        os.path.realpath(os.path.join(config.ROOT, "chat_videos")),
    ]
    if not any(full == root or full.startswith(root + os.sep) for root in allowed):
        return _json({"ok": False, "message": "路径不允许"}, status=403)
    if not os.path.isfile(full):
        return _json({"ok": False, "message": "文件不存在"}, status=404)
    return web.FileResponse(full)


def _page(request) -> int:
    try:
        return max(int(request.query.get("page") or 1), 1)
    except ValueError:
        return 1


def _size(request, default=30) -> int:
    try:
        return min(max(int(request.query.get("size") or default), 1), 100)
    except ValueError:
        return default


@web.middleware
async def admin_auth_middleware(request, handler):
    if request.method == "OPTIONS":
        return await handler(request)
    path = request.path
    protected = path.startswith("/admin/api/") or path.startswith("/admin/ws/") or path.startswith("/admin/media/")
    public = path in ("/admin/api/session", "/admin/api/login", "/admin/api/logout")
    if protected and not public:
        denied = auth.require(request)
        if denied:
            return denied
    return await handler(request)
