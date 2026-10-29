const app = document.getElementById("app");
const nav = document.getElementById("nav");
let page = "home";
let socket;
let live = [];
let viewSeq = 0;

function alive(seq) {
    return seq === viewSeq;
}

async function api(url, options = {}) {
    const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
    const response = await fetch(url, Object.assign({ credentials: "same-origin" }, options, { headers }));
    if (response.status === 401) {
        lock();
        throw new Error("请先登录");
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(data.message || "请求失败");
    }
    return data;
}

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
}

function fmtTime(ts) {
    if (!ts) return "";
    const date = new Date(Number(ts) * 1000);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString();
}

function readPage(params, fallback = 1) {
    const value = Number(params.get("page") || fallback);
    return Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback;
}

function readSize(params, fallback = 50) {
    const value = Number(params.get("size") || fallback);
    return value === 100 ? 100 : 50;
}

function pageCount(total, size) {
    return Math.max(1, Math.ceil((total || 0) / Math.max(size || 1, 1)));
}

function pagerHtml(data) {
    const total = data.total || 0;
    const size = data.size || 50;
    const current = data.page || 1;
    const pages = pageCount(total, size);
    const from = total ? Math.min(total, (current - 1) * size + 1) : 0;
    const to = Math.min(total, current * size);
    return `<div class="pager">
        <label class="pager-size">每页
            <select id="page-size">
                <option value="50" ${size === 50 ? "selected" : ""}>50</option>
                <option value="100" ${size === 100 ? "selected" : ""}>100</option>
            </select>
            条
        </label>
        <button class="ghost" type="button" data-page-nav="${current - 1}" ${current <= 1 || pages <= 1 ? "disabled" : ""}>上一页</button>
        <span class="hint">${from}-${to} / ${total} · 第 ${current}/${pages} 页</span>
        <button class="ghost" type="button" data-page-nav="${current + 1}" ${current >= pages ? "disabled" : ""}>下一页</button>
    </div>`;
}

function bindPager(route, query) {
    app.querySelectorAll("[data-page-nav]").forEach((button) => {
        button.onclick = () => {
            if (button.disabled) return;
            const next = Number(button.dataset.pageNav);
            if (!Number.isFinite(next) || next < 1) return;
            const params = new URLSearchParams(query);
            params.set("page", String(next));
            location.hash = route + "?" + params.toString();
            show();
        };
    });
    const sizeSelect = document.getElementById("page-size");
    if (sizeSelect) {
        sizeSelect.onchange = () => {
            const params = new URLSearchParams(query);
            params.set("size", sizeSelect.value === "100" ? "100" : "50");
            params.delete("page");
            const text = params.toString();
            location.hash = route + (text ? "?" + text : "");
            show();
        };
    }
}

nav.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-page]");
    if (!button) return;
    page = button.dataset.page;
    location.hash = page;
    nav.classList.remove("open");
    show();
});

document.getElementById("nav-toggle").addEventListener("click", () => {
    nav.classList.toggle("open");
});

document.addEventListener("click", (event) => {
    if (!nav.classList.contains("open")) return;
    if (event.target.closest("#nav") || event.target.closest("#nav-toggle")) return;
    nav.classList.remove("open");
});

function lock() {
    document.body.classList.add("locked");
    document.title = "登录 · Wegram";
    if (socket) {
        socket.onclose = null;
        socket.close();
        socket = null;
    }
}

function unlock() {
    document.body.classList.remove("locked");
    page = (location.hash || "#home").slice(1).split("?")[0] || "home";
    if (!pages[page]) page = "home";
    show();
}

document.getElementById("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = document.getElementById("login-msg");
    message.textContent = "";
    const response = await fetch("/admin/api/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            username: document.getElementById("login-user").value.trim(),
            password: document.getElementById("login-pass").value
        })
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        message.textContent = data.message || "登录失败";
        return;
    }
    document.getElementById("login-pass").value = "";
    unlock();
});

document.getElementById("logout-btn").addEventListener("click", async () => {
    await fetch("/admin/api/logout", { method: "POST", credentials: "same-origin" });
    lock();
});

const pages = {
    home: ["首页", "登录状态、心跳和设备"],
    messages: ["消息", "按群和私聊查看会话"],
    groups: ["群聊", "微信群名和群备注"],
    contacts: ["通讯录", "是否接收该联系人的消息"],
    plugins: ["插件", "猜成语和抢红包可以单独开关"],
    settings: ["配置", "通知地址和视频下载上限"]
};

async function show() {
    const seq = ++viewSeq;
    const requested = page;
    const meta = pages[requested] || pages.home;
    document.getElementById("page-title").textContent = meta[0];
    document.getElementById("page-desc").textContent = meta[1];
    document.title = meta[0] + " · Wegram";
    document.querySelectorAll("#nav button").forEach((button) => {
        button.classList.toggle("active", button.dataset.page === requested);
    });
    if (requested !== "messages" && socket) {
        socket.close();
        socket = null;
    }
    const views = { home: renderHome, settings: renderSettings, plugins: renderPlugins, contacts: renderContacts, groups: renderGroups, messages: renderMessages };
    try {
        await views[requested](seq);
    } catch (error) {
        if (!alive(seq)) return;
        app.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
    }
}

function loginBadge(login) {
    if (login === "online") return { text: "在线", cls: "online" };
    if (login === "offline") return { text: "离线", cls: "offline" };
    return { text: "未知", cls: "unknown" };
}

async function renderHome(seq) {
    const status = await api("/admin/api/status");
    if (!alive(seq)) return;
    const flow = status.flow || {};
    const badge = loginBadge(status.login);
    app.innerHTML = `
        <div class="split">
        <section class="card">
            <div class="card-header">运行状态 <span class="badge ${badge.cls}">${badge.text}</span></div>
            <ul class="kv">
                <li><b>wxid</b><span>${escapeHtml(status.wxid)}</span></li>
                <li><b>wechat861</b><span>${escapeHtml(status.baseurl)}</span></li>
                <li><b>回调</b><span>${escapeHtml(status.callback)}</span></li>
                <li><b>队列</b><span>${escapeHtml(status.queue)}</span></li>
                <li><b>登录阶段</b><span>${escapeHtml(flow.phase || "空闲")} ${escapeHtml(flow.message || "")}</span></li>
                <li><b>最近心跳</b><span id="heartbeat">${escapeHtml(status.lastHeartbeat || "查询中")}</span></li>
            </ul>
        </section>
        <section class="card" id="qr-box">
            <div class="card-header">登录</div>
            <div class="card-body">
            <label class="label">固定设备 ID</label>
            <input id="device-id" type="text" value="${escapeHtml(status.deviceId || "")}" placeholder="与 wechat861 登录缓存使用同一个设备 ID">
            <div class="row actions">
                <button class="primary" id="btn-twice">二次登录并开启心跳</button>
                <button id="btn-qr">获取登录二维码</button>
                <button id="btn-check">检测扫码</button>
                <button id="btn-beat">开启自动心跳</button>
                <button class="ghost" id="btn-refresh">刷新</button>
            </div>
            ${flow.qrBase64 ? `<img class="qr" alt="登录二维码" src="${flow.qrBase64}">` : `<p class="hint spaced">二次登录失败后，在这里扫码。</p>`}
            ${flow.needCode ? `<div class="row"><input id="code" type="text" placeholder="验证码"><button id="btn-code">提交验证码</button></div>` : ""}
            </div>
        </section>
        </div>`;
    document.getElementById("btn-refresh").onclick = show;
    api("/admin/api/heartbeat-log").then((data) => {
        const node = document.getElementById("heartbeat");
        if (!node || !alive(seq)) return;
        node.textContent = data.lastHeartbeat || "无";
    }).catch(() => {
        const node = document.getElementById("heartbeat");
        if (node && alive(seq)) node.textContent = status.lastHeartbeat || "无";
    });
    document.getElementById("btn-twice").onclick = () => runLogin("/admin/api/login/twice");
    document.getElementById("btn-qr").onclick = async () => {
        await api("/admin/api/login/qr", { method: "POST", body: JSON.stringify({ deviceId: document.getElementById("device-id").value.trim() }) });
        show();
    };
    document.getElementById("btn-check").onclick = () => runLogin("/admin/api/login/check");
    document.getElementById("btn-beat").onclick = () => runLogin("/admin/api/heartbeat");
    const codeButton = document.getElementById("btn-code");
    if (codeButton) {
        codeButton.onclick = async () => {
            await api("/admin/api/login/code", { method: "POST", body: JSON.stringify({ code: document.getElementById("code").value }) });
            show();
        };
    }
}

async function runLogin(url) {
    await api(url, { method: "POST", body: "{}" });
    show();
}

async function renderSettings(seq) {
    const cfg = await api("/admin/api/config");
    if (!alive(seq)) return;
    const mb = Math.round((cfg.media && cfg.media.max_video_bytes || 0) / 1024 / 1024);
    app.innerHTML = `
        <section class="card">
            <div class="card-header">运行参数</div>
            <div class="card-body">
            <label class="label">ntfy 地址</label>
            <input id="ntfy" type="text" value="${escapeHtml(cfg.ntfy_url)}">
            <label class="label">视频下载上限（MB，0 表示不限制）</label>
            <input id="video-mb" type="text" value="${mb}">
            <p class="hint">保存后约 3 秒由配置监听重新加载。猜成语和抢红包在「插件」页开关。</p>
            <div class="row end"><button class="primary" id="save-cfg">保存</button></div>
            <p id="cfg-msg" class="hint"></p>
            </div>
        </section>`;
    document.getElementById("save-cfg").onclick = async () => {
        const body = {
            ntfy_url: document.getElementById("ntfy").value.trim(),
            media: { max_video_bytes: Math.max(0, Number(document.getElementById("video-mb").value) || 0) * 1024 * 1024 }
        };
        await api("/admin/api/config", { method: "PUT", body: JSON.stringify(body) });
        document.getElementById("cfg-msg").textContent = "已保存";
    };
}

function pluginForm(item) {
    if (item.id === "ccy") {
        const cfg = item.config || {};
        return `
            <label class="label">保存图片的 wxid，一行一个</label>
            <textarea id="ccy-wxids">${escapeHtml((cfg.saveimg_wxids || []).join("\n"))}</textarea>
            <div class="metrics">
                <div><label class="label">图片时间</label><input id="img-range" type="text" value="${escapeHtml((cfg.img_time_range || []).join(","))}"></div>
                <div><label class="label">文字时间</label><input id="text-range" type="text" value="${escapeHtml((cfg.text_time_range || []).join(","))}"></div>
                <div><label class="label">星期</label><input id="weekdays" type="text" value="${escapeHtml((cfg.weekdays || []).join(","))}"></div>
            </div>`;
    }
    const blacklist = (item.config && item.config.blacklist) || [];
    return `<label class="label">群名黑名单，一行一个。群名包含这些文字时不抢。</label><textarea id="qhb">${escapeHtml(blacklist.join("\n"))}</textarea>`;
}

async function renderPlugins(seq) {
    const items = await api("/admin/api/plugins");
    if (!alive(seq)) return;
    app.innerHTML = items.map((item) => `
        <section class="card" data-plugin="${escapeHtml(item.id)}" data-enabled="${item.enabled ? "1" : "0"}">
            <div class="card-header">
                <span>${escapeHtml(item.name)}</span>
                <span class="badge ${item.enabled ? "on" : ""}">${item.enabled ? "运行中" : "已停止"}</span>
                <button class="toggle" data-enabled="${item.enabled ? "0" : "1"}">${item.enabled ? "停止" : "启用"}</button>
            </div>
            <div class="card-body">
            ${pluginForm(item)}
            <div class="row end"><button class="primary save">保存配置</button></div>
            </div>
        </section>`).join("");
    app.querySelectorAll("section[data-plugin]").forEach((section) => {
        const id = section.dataset.plugin;
        section.querySelector(".toggle").onclick = async (event) => {
            const enabled = event.target.dataset.enabled === "1";
            await api("/admin/api/plugins/" + id, { method: "PUT", body: JSON.stringify({ enabled }) });
            show();
        };
        section.querySelector(".save").onclick = async () => {
            const lines = (selector) => (section.querySelector(selector).value || "").split(/\n|,/).map((s) => s.trim()).filter(Boolean);
            let pluginConfig;
            if (id === "ccy") {
                pluginConfig = {
                    saveimg_wxids: lines("#ccy-wxids"),
                    img_time_range: section.querySelector("#img-range").value.split(",").map((s) => s.trim()).filter(Boolean),
                    text_time_range: section.querySelector("#text-range").value.split(",").map((s) => s.trim()).filter(Boolean),
                    weekdays: lines("#weekdays").map((s) => Number(s))
                };
            } else {
                pluginConfig = { blacklist: lines("#qhb") };
            }
            const enabled = section.dataset.enabled === "1";
            await api("/admin/api/plugins/" + id, { method: "PUT", body: JSON.stringify({ enabled, config: pluginConfig }) });
            section.insertAdjacentHTML("beforeend", `<p class="hint">已保存</p>`);
        };
    });
}

async function renderContacts(seq) {
    const params = new URLSearchParams(location.hash.split("?")[1] || "");
    const q = params.get("q") || "";
    const current = readPage(params);
    const size = readSize(params);
    const data = await api("/admin/api/contacts?q=" + encodeURIComponent(q) + "&page=" + current + "&size=" + size);
    if (!alive(seq)) return;
    const rows = data.items.map((item) => `
        <tr>
            <td>${escapeHtml(item.name || item.wxId)}</td>
            <td class="muted">${escapeHtml(item.wxId)}</td>
            <td>${item.isGroup ? "群" : "个人"}</td>
            <td><label><input data-wxid="${escapeHtml(item.wxId)}" type="checkbox" ${item.isReceive ? "checked" : ""}> 接收</label></td>
        </tr>`).join("");
    app.innerHTML = `
        <section class="card">
            <div class="card-header">共 ${data.total} 人</div>
            <div class="card-body toolbar">
                <input id="q" type="search" value="${escapeHtml(q)}" placeholder="按名称搜索">
                <button id="search">搜索</button>
                <button class="primary" id="sync-contacts">同步通讯录</button>
            </div>
            <p class="hint" id="contact-hint">共 ${data.total} 人。通讯录来自 wechat861 的好友列表。</p>
            <div class="table-wrap"><table>
                <thead><tr><th>名称</th><th>wxid</th><th>类型</th><th>接收消息</th></tr></thead>
                <tbody>${rows || `<tr><td colspan="4">没有联系人</td></tr>`}</tbody>
            </table></div>
            ${pagerHtml(data)}
        </section>`;
    document.getElementById("search").onclick = () => {
        const next = document.getElementById("q").value.trim();
        const query = new URLSearchParams();
        if (next) query.set("q", next);
        if (size !== 50) query.set("size", String(size));
        location.hash = "contacts" + (query.toString() ? "?" + query.toString() : "");
        show();
    };
    document.getElementById("sync-contacts").onclick = async (event) => {
        event.target.textContent = "同步中";
        event.target.disabled = true;
        try {
            const result = await api("/admin/api/contacts/sync", { method: "POST", body: "{}" });
            if (result.total) {
                show();
                return;
            }
            document.getElementById("contact-hint").textContent = result.message || "没有更新通讯录";
        } catch (error) {
            document.getElementById("contact-hint").textContent = error.message;
        }
        event.target.textContent = "同步通讯录";
        event.target.disabled = false;
    };
    app.querySelectorAll("input[data-wxid]").forEach((input) => {
        input.onchange = () => api("/admin/api/contacts/" + encodeURIComponent(input.dataset.wxid), {
            method: "PUT",
            body: JSON.stringify({ isReceive: input.checked })
        });
    });
    const keep = {};
    if (q) keep.q = q;
    if (size !== 50) keep.size = String(size);
    bindPager("contacts", keep);
}

async function renderGroups(seq) {
    const params = new URLSearchParams(location.hash.split("?")[1] || "");
    const selected = params.get("id") || "";
    const q = params.get("q") || "";
    const current = readPage(params);
    const size = readSize(params);
    const data = await api("/admin/api/groups?q=" + encodeURIComponent(q) + "&page=" + current + "&size=" + size);
    let memberHtml = "";
    if (selected && data.items.some((item) => item.id === selected)) {
        const detail = await api("/admin/api/groups/members?id=" + encodeURIComponent(selected));
        const people = detail.items.map((m) => `<div class="person"><strong>${escapeHtml(m.displayname || m.nickname || m.username)}</strong><div class="meta">${escapeHtml(m.nickname || "")} · ${escapeHtml(m.username)}</div></div>`).join("");
        memberHtml = `<tr class="member-row"><td colspan="5"><p class="hint">共 ${detail.total} 人</p><div class="member-list">${people || `<p class="hint">没有成员</p>`}</div></td></tr>`;
    }
    const rows = data.items.map((item) => {
        const open = item.id === selected;
        return `<tr class="${open ? "is-open" : ""}">
            <td>${escapeHtml(item.groupName || "未同步")}</td>
            <td>${escapeHtml(item.customName || "无")}</td>
            <td class="num">${item.count}</td>
            <td class="muted">${escapeHtml(item.id)}</td>
            <td class="nowrap">
                <button class="ghost${open ? " active" : ""}" data-id="${escapeHtml(item.id)}">${open ? "收起" : "成员"}</button>
            </td>
        </tr>${open ? memberHtml : ""}`;
    }).join("");
    if (!alive(seq)) return;
    app.innerHTML = `
        <section class="card">
            <div class="card-body toolbar">
                <input id="q" type="search" value="${escapeHtml(q)}" placeholder="群名、群备注或群 id">
                <button id="search">搜索</button>
                <button class="primary" id="sync-names">同步群名</button>
            </div>
            <p class="hint" id="group-hint">共 ${data.total} 个群</p>
            <div class="table-wrap"><table>
                <thead><tr><th>群名</th><th>群备注</th><th class="num">人数</th><th>群 id</th><th>操作</th></tr></thead>
                <tbody>${rows || `<tr><td colspan="5">没有群数据</td></tr>`}</tbody>
            </table></div>
            ${pagerHtml(data)}
        </section>`;
    document.getElementById("search").onclick = () => {
        const next = document.getElementById("q").value.trim();
        const query = new URLSearchParams();
        if (next) query.set("q", next);
        if (size !== 50) query.set("size", String(size));
        location.hash = "groups" + (query.toString() ? "?" + query.toString() : "");
        show();
    };
    document.getElementById("sync-names").onclick = async (event) => {
        event.target.textContent = "同步中";
        event.target.disabled = true;
        try {
            const result = await api("/admin/api/groups/sync-names", { method: "POST", body: "{}" });
            if (result.updated) {
                show();
                return;
            }
            document.getElementById("group-hint").textContent = result.message || "没有更新群名";
            event.target.textContent = "同步群名";
            event.target.disabled = false;
        } catch (error) {
            document.getElementById("group-hint").textContent = error.message;
            event.target.textContent = "同步群名";
            event.target.disabled = false;
        }
    };
    app.querySelectorAll("button[data-id]").forEach((button) => {
        button.onclick = () => {
            const next = button.dataset.id === selected ? "" : button.dataset.id;
            const query = new URLSearchParams();
            if (next) query.set("id", next);
            if (q) query.set("q", q);
            if (current > 1) query.set("page", String(current));
            if (size !== 50) query.set("size", String(size));
            location.hash = "groups" + (query.toString() ? "?" + query.toString() : "");
            show();
        };
    });
    const keep = {};
    if (q) keep.q = q;
    if (size !== 50) keep.size = String(size);
    bindPager("groups", keep);
}

function bubble(item) {
    const media = item.mediaUrl ? (
        /\.(png|jpg|jpeg|gif|webp)$/i.test(item.mediaUrl)
            ? `<img class="media" alt="" src="${item.mediaUrl}">`
            : `<a href="${item.mediaUrl}" target="_blank">打开文件</a>`
    ) : "";
    return `<article class="bubble" data-id="${escapeHtml(item.msg_id)}">
        <div class="who">${escapeHtml(item.sender_name || item.sender_wxid || "")}</div>
        <div class="msg">${escapeHtml(item.text || "")}</div>
        ${media}
        <time>${escapeHtml(fmtTime(item.create_time))}</time>
    </article>`;
}

let msgKind = "group";
let msgPeer = "";

async function renderMessages(seq) {
    const params = new URLSearchParams(location.hash.split("?")[1] || "");
    msgKind = params.get("kind") === "private" ? "private" : "group";
    msgPeer = params.get("peer") || "";
    const peers = await api("/admin/api/conversations?kind=" + msgKind);
    const peerButtons = peers.map((item) => `
        <button class="peer ${item.peer === msgPeer ? "active" : ""}" data-peer="${escapeHtml(item.peer)}">
            <strong>${escapeHtml(item.title)}</strong>
            ${msgKind === "group" && item.customName ? `<div class="meta">备注 ${escapeHtml(item.customName)}</div>` : ""}
            <div class="preview">${escapeHtml(item.text || "")}</div>
            <div class="meta">${escapeHtml(fmtTime(item.create_time))} · ${item.total} 条</div>
        </button>`).join("");
    let thread = `<p class="hint">${msgKind === "group" ? "选择一个群" : "选择一个联系人"}</p>`;
    let title = "";
    if (msgPeer) {
        const current = peers.find((item) => item.peer === msgPeer);
        title = current ? current.title : msgPeer;
        const data = await api("/admin/api/messages?peer=" + encodeURIComponent(msgPeer) + "&size=80");
        thread = (data.items || []).map(bubble).join("") || `<p class="hint">这个会话还没有消息</p>`;
    }
    if (!alive(seq)) return;
    app.innerHTML = `
        <div class="seg">
            <button data-kind="group" class="${msgKind === "group" ? "active" : ""}">群消息</button>
            <button data-kind="private" class="${msgKind === "private" ? "active" : ""}">私聊</button>
        </div>
        <div class="inbox ${msgPeer ? "reading" : ""}">
            <div class="peers">${peerButtons || `<p class="hint empty">还没有${msgKind === "group" ? "群" : "私聊"}消息</p>`}</div>
            <section class="thread card">
                <div class="thread-head">
                    <button class="ghost" id="back-peers">返回</button>
                    <strong>${escapeHtml(title)}</strong>
                    <span class="hint" id="ws-state"></span>
                </div>
                <div id="msg-body">${thread}</div>
            </section>
        </div>`;
    app.querySelectorAll("button[data-kind]").forEach((button) => {
        button.onclick = () => {
            location.hash = "messages?kind=" + button.dataset.kind;
            show();
        };
    });
    document.getElementById("back-peers").onclick = () => {
        location.hash = "messages?kind=" + msgKind;
        show();
    };
    app.querySelectorAll("button[data-peer]").forEach((button) => {
        button.onclick = () => {
            location.hash = "messages?kind=" + msgKind + "&peer=" + encodeURIComponent(button.dataset.peer);
            show();
        };
    });
    connectSocket();
}

function connectSocket() {
    if (socket) {
        socket.onclose = null;
        socket.close();
    }
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${protocol}://${location.host}/admin/ws/messages`);
    const state = () => document.getElementById("ws-state");
    socket.onopen = () => { if (state()) state().textContent = "消息监听已连接"; };
    socket.onclose = () => { if (state()) state().textContent = "消息监听已断开，5 秒后重连"; setTimeout(() => { if (page === "messages") connectSocket(); }, 5000); };
    socket.onmessage = (event) => {
        const payload = JSON.parse(event.data);
        const body = document.getElementById("msg-body");
        if (!body || !msgPeer || payload.event !== "message" || !payload.item) return;
        const item = payload.item;
        const peer = (item.from_wxid || "").endsWith("@chatroom") ? item.from_wxid : item.from_wxid;
        if (peer !== msgPeer && item.to_wxid !== msgPeer) return;
        body.insertAdjacentHTML("beforeend", bubble(item));
    };
}

window.addEventListener("hashchange", () => {
    if (document.body.classList.contains("locked")) return;
    const next = (location.hash || "#home").slice(1).split("?")[0] || "home";
    if (!pages[next] || next === page) return;
    page = next;
    show();
});

api("/admin/api/session").then((session) => {
    if (session.authenticated) unlock();
}).catch(() => lock());
