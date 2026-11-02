"""
MAM 产品原型 · 零依赖服务端
运行：python3 app.py  →  http://localhost:8000

只实现产品规则内核，不实现登录、支付、真实物流、图片识别。
数据每次启动重建，保证演示状态可预期。
"""
import hashlib
import json
import os
import re
import secrets
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import db

BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, "web")
SNAPSHOT_TTL = 600  # 批量发货预览快照有效期（秒）
SHIP_SNAPSHOTS = {}


class ApiError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


# ---------------------------------------------------------------- 工具

def rows_to_dicts(rows):
    return [dict(r) for r in rows]


def parse_dt(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def get_user(conn, handler):
    uid = handler.headers.get("X-Demo-User", "1")
    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if not row:
        raise ApiError(401, "演示身份不存在")
    return dict(row)


def has_admission(conn, channel_id, group_id):
    if not group_id:
        return False
    row = conn.execute(
        "SELECT 1 FROM admissions WHERE channel_id = ? AND group_id = ?",
        (channel_id, group_id),
    ).fetchone()
    return row is not None


def project_visible(conn, user, p, share=None):
    role = user["role"]
    if role == "admin":
        return p["status"] != "draft"
    if role == "channel":
        return p["channel_id"] == user["channel_id"]
    if p["status"] != "published":
        return False
    if p["visibility"] == "public":
        return True
    if role != "group":
        return False
    if p["visibility"] == "admitted":
        return has_admission(conn, p["channel_id"], user["group_id"])
    if p["visibility"] == "private":
        return bool(share) and share == p["share_token"]
    return False


def apply_block_reason(conn, user, p, share=None):
    if user["role"] != "group":
        return "只有认证观影团可以申请"
    if p["status"] != "published":
        return "项目未发布"
    t = now_str()
    if t < p["start_at"]:
        return "报名尚未开始"
    if t > p["end_at"]:
        return "报名已截止"
    if p["visibility"] == "admitted" and not has_admission(conn, p["channel_id"], user["group_id"]):
        return "需要该渠道的准入资格"
    if p["visibility"] == "private" and share != p["share_token"]:
        return "私密项目需要有效的分享链接"
    return None


def project_public(conn, p):
    ch = conn.execute("SELECT name, tag FROM channels WHERE id = ?", (p["channel_id"],)).fetchone()
    return {
        "id": p["id"],
        "title": p["title"],
        "film": p["film"],
        "status": p["status"],
        "visibility": p["visibility"],
        "start_at": p["start_at"],
        "end_at": p["end_at"],
        "channel_id": p["channel_id"],
        "channel_name": ch["name"] if ch else "",
        "channel_tag": ch["tag"] if ch else "",
        "form_schema": json.loads(p["form_schema"]),
        "result_schema": json.loads(p["result_schema"]),
    }


def app_public(conn, a):
    p = conn.execute("SELECT * FROM projects WHERE id = ?", (a["project_id"],)).fetchone()
    g = conn.execute("SELECT * FROM groups WHERE id = ?", (a["group_id"],)).fetchone()
    return {
        "id": a["id"],
        "project_id": a["project_id"],
        "project_title": p["title"] if p else "",
        "film": p["film"] if p else "",
        "channel_id": p["channel_id"] if p else None,
        "group_id": a["group_id"],
        "group_name": g["name"] if g else "",
        "status": a["status"],
        "review_version": a["review_version"],
        "note": a["note"],
        "form_values": json.loads(a["form_values"]),
        "qty": a["qty"],
        "carrier": a["carrier"],
        "track_no": a["track_no"],
        "feedback": json.loads(a["feedback"]) if a["feedback"] else None,
        "score": a["score"],
        "comment": a["comment"],
        "created_at": a["created_at"],
    }


def prefill_value(conn, user, path, form_values):
    if not path or not path.startswith("group."):
        return form_values.get(path, "")
    field = path.split(".", 1)[1]
    g = conn.execute("SELECT * FROM groups WHERE id = ?", (user["group_id"],)).fetchone()
    return (g[field] if g and field in g.keys() else "") or ""


def fingerprint(rows):
    """批量发货快照指纹：任何一条申请的关键字段变化都会导致整批失效。"""
    h = hashlib.sha256()
    for r in sorted(rows, key=lambda x: x["id"]):
        vals = json.loads(r["form_values"]) if r["form_values"] else {}
        h.update(("%s|%s|%s|%s|%s|%s|%s\n" % (
            r["id"], r["status"], r["review_version"], r["qty"],
            vals.get("receiver", ""), vals.get("phone", ""), vals.get("address", ""),
        )).encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------- 路由表
ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


# ---------------------------------------------------------------- 接口

@route("GET", "/api/bootstrap")
def api_bootstrap(conn, handler, m, body):
    users = rows_to_dicts(conn.execute("SELECT id, name, role, group_id, channel_id FROM users ORDER BY id"))
    for u in users:
        if u["group_id"]:
            g = conn.execute("SELECT name FROM groups WHERE id = ?", (u["group_id"],)).fetchone()
            u["display"] = g["name"] if g else u["name"]
        elif u["channel_id"]:
            c = conn.execute("SELECT name FROM channels WHERE id = ?", (u["channel_id"],)).fetchone()
            u["display"] = c["name"] if c else u["name"]
        else:
            u["display"] = u["name"]
    private = rows_to_dicts(conn.execute(
        "SELECT id, title, share_token FROM projects WHERE visibility = 'private'"))
    return {
        "users": users,
        "private_projects": private,
        "status_labels": {
            "pending": "待审核", "approved": "已通过", "rejected": "已驳回",
            "shipped": "已发货", "feedback": "已返图", "completed": "已完成",
            "cancelled": "已流团", "draft": "草稿", "published": "已发布", "closed": "已截止",
        },
    }


@route("GET", r"/api/projects(\?.*)?")
def api_projects(conn, handler, m, body):
    user = get_user(conn, handler)
    qs = parse_qs(urlparse(handler.path).query)
    share = (qs.get("share") or [None])[0]
    out = []
    for p in conn.execute("SELECT * FROM projects ORDER BY id").fetchall():
        if user["role"] == "group" and p["visibility"] == "private" and share != p["share_token"]:
            continue
        if not project_visible(conn, user, p, share):
            continue
        d = project_public(conn, p)
        d["can_apply"] = apply_block_reason(conn, user, p, share) is None
        d["block_reason"] = apply_block_reason(conn, user, p, share)
        if user["role"] == "channel" and p["share_token"]:
            d["share_token"] = p["share_token"]
        out.append(d)
    return {"projects": out}


@route("GET", r"/api/projects/(\d+)(\?.*)?")
def api_project_detail(conn, handler, m, body):
    user = get_user(conn, handler)
    qs = parse_qs(urlparse(handler.path).query)
    share = (qs.get("share") or [None])[0]
    p = conn.execute("SELECT * FROM projects WHERE id = ?", (int(m.group(1)),)).fetchone()
    if not p:
        raise ApiError(404, "项目不存在")
    if not project_visible(conn, user, p, share):
        raise ApiError(403, "无权查看该项目")
    d = project_public(conn, p)
    reason = apply_block_reason(conn, user, p, share)
    d["can_apply"] = reason is None
    d["block_reason"] = reason
    d["prefill"] = {}
    if user["role"] == "group":
        for f in d["form_schema"]:
            if f.get("prefill"):
                d["prefill"][f["key"]] = prefill_value(conn, user, f["prefill"], {})
    return d


@route("POST", r"/api/projects/(\d+)/apply")
def api_apply(conn, handler, m, body):
    user = get_user(conn, handler)
    p = conn.execute("SELECT * FROM projects WHERE id = ?", (int(m.group(1)),)).fetchone()
    if not p:
        raise ApiError(404, "项目不存在")
    share = body.get("share")
    if not project_visible(conn, user, p, share):
        raise ApiError(403, "无权申请该项目")
    reason = apply_block_reason(conn, user, p, share)
    if reason:
        raise ApiError(400, reason)

    schema = json.loads(p["form_schema"])
    values = body.get("values") or {}
    for f in schema:
        if f.get("required") and not str(values.get(f["key"], "")).strip():
            raise ApiError(400, "请填写：%s" % f["label"])
    try:
        qty = int(values.get("qty") or 0)
    except (TypeError, ValueError):
        raise ApiError(400, "申请数量必须是数字")
    if qty <= 0:
        raise ApiError(400, "申请数量必须大于 0")

    cur = conn.execute(
        """INSERT INTO applications
           (project_id, group_id, status, review_version, note, form_values, qty, created_at, updated_at)
           VALUES (?,?,'pending',1,NULL,?,?,?,?)""",
        (p["id"], user["group_id"], json.dumps(values, ensure_ascii=False), qty, now_str(), now_str()),
    )
    conn.commit()
    return {"id": cur.lastrowid, "status": "pending"}


@route("GET", "/api/my/applications")
def api_my_applications(conn, handler, m, body):
    user = get_user(conn, handler)
    if user["role"] != "group":
        raise ApiError(403, "仅观影团可查看")
    rows = conn.execute(
        "SELECT * FROM applications WHERE group_id = ? ORDER BY id DESC", (user["group_id"],)
    ).fetchall()
    return {"applications": [app_public(conn, a) for a in rows]}


@route("POST", r"/api/applications/(\d+)/resubmit")
def api_resubmit(conn, handler, m, body):
    user = get_user(conn, handler)
    a = conn.execute("SELECT * FROM applications WHERE id = ?", (int(m.group(1)),)).fetchone()
    if not a:
        raise ApiError(404, "申请不存在")
    if user["role"] != "group" or a["group_id"] != user["group_id"]:
        raise ApiError(403, "无权修改该申请")
    if a["status"] != "rejected":
        raise ApiError(400, "只有已驳回的申请可以修改重提")

    p = conn.execute("SELECT * FROM projects WHERE id = ?", (a["project_id"],)).fetchone()
    schema = json.loads(p["form_schema"])
    values = body.get("values") or json.loads(a["form_values"])
    for f in schema:
        if f.get("required") and not str(values.get(f["key"], "")).strip():
            raise ApiError(400, "请填写：%s" % f["label"])
    try:
        qty = int(values.get("qty") or a["qty"])
    except (TypeError, ValueError):
        raise ApiError(400, "申请数量必须是数字")

    conn.execute(
        """UPDATE applications SET form_values=?, qty=?, status='pending',
           review_version=review_version+1, note=NULL, updated_at=? WHERE id=?""",
        (json.dumps(values, ensure_ascii=False), qty, now_str(), a["id"]),
    )
    conn.commit()
    return {"id": a["id"], "status": "pending", "review_version": a["review_version"] + 1}


@route("GET", "/api/channel/applications")
def api_channel_applications(conn, handler, m, body):
    user = get_user(conn, handler)
    if user["role"] not in ("channel", "admin"):
        raise ApiError(403, "仅渠道方或管理员可查看")
    if user["role"] == "channel":
        rows = conn.execute(
            """SELECT a.* FROM applications a JOIN projects p ON p.id = a.project_id
               WHERE p.channel_id = ? ORDER BY
               CASE a.status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END,
               a.created_at ASC""",
            (user["channel_id"],),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM applications ORDER BY id DESC").fetchall()
    return {"applications": [app_public(conn, a) for a in rows]}


@route("POST", r"/api/applications/(\d+)/review")
def api_review(conn, handler, m, body):
    user = get_user(conn, handler)
    a = conn.execute("SELECT * FROM applications WHERE id = ?", (int(m.group(1)),)).fetchone()
    if not a:
        raise ApiError(404, "申请不存在")
    p = conn.execute("SELECT * FROM projects WHERE id = ?", (a["project_id"],)).fetchone()
    if user["role"] != "channel" or p["channel_id"] != user["channel_id"]:
        raise ApiError(403, "只有项目所属渠道方可以审核")
    if a["status"] != "pending":
        raise ApiError(400, "只有待审核的申请可以处理")

    action = body.get("action")
    if action not in ("approve", "reject"):
        raise ApiError(400, "action 必须是 approve 或 reject")
    if action == "approve":
        conn.execute(
            "UPDATE applications SET status='approved', note=?, updated_at=? WHERE id=?",
            (body.get("note") or None, now_str(), a["id"]),
        )
    else:
        conn.execute(
            "UPDATE applications SET status='rejected', note=?, updated_at=? WHERE id=?",
            (body.get("note") or "未通过审核", now_str(), a["id"]),
        )
    conn.commit()
    return {"id": a["id"], "status": "approved" if action == "approve" else "rejected"}


@route("POST", r"/api/applications/(\d+)/ship")
def api_ship(conn, handler, m, body):
    user = get_user(conn, handler)
    a = conn.execute("SELECT * FROM applications WHERE id = ?", (int(m.group(1)),)).fetchone()
    if not a:
        raise ApiError(404, "申请不存在")
    p = conn.execute("SELECT * FROM projects WHERE id = ?", (a["project_id"],)).fetchone()
    if user["role"] != "channel" or p["channel_id"] != user["channel_id"]:
        raise ApiError(403, "只有项目所属渠道方可以发货")
    if a["status"] != "approved":
        raise ApiError(400, "只有已通过的申请可以发货")
    carrier = (body.get("carrier") or "").strip()
    track_no = (body.get("track_no") or "").strip()
    if not carrier or not track_no:
        raise ApiError(400, "快递公司与单号都不能为空")
    conn.execute(
        "UPDATE applications SET status='shipped', carrier=?, track_no=?, updated_at=? WHERE id=?",
        (carrier, track_no, now_str(), a["id"]),
    )
    conn.commit()
    return {"id": a["id"], "status": "shipped"}


@route("POST", r"/api/projects/(\d+)/ship/preview")
def api_ship_preview(conn, handler, m, body):
    user = get_user(conn, handler)
    p = conn.execute("SELECT * FROM projects WHERE id = ?", (int(m.group(1)),)).fetchone()
    if not p:
        raise ApiError(404, "项目不存在")
    if user["role"] != "channel" or p["channel_id"] != user["channel_id"]:
        raise ApiError(403, "只有项目所属渠道方可以批量发货")

    incoming = body.get("rows") or []
    if not incoming:
        raise ApiError(400, "没有可处理的行")
    ids = []
    tracks = {}
    for r in incoming:
        try:
            aid = int(r.get("application_id"))
        except (TypeError, ValueError):
            raise ApiError(400, "申请编号不合法")
        track = (r.get("track_no") or "").strip()
        if not track:
            continue  # 未填单号的行跳过，不进入预览
        if len(track) < 4:
            raise ApiError(400, "快递单号过短：%s" % track)
        ids.append(aid)
        tracks[aid] = track
    if not ids:
        raise ApiError(400, "没有填写快递单号的行")
    if len(set(ids)) != len(ids):
        raise ApiError(400, "存在重复的申请编号")

    apps = []
    for aid in ids:
        a = conn.execute("SELECT * FROM applications WHERE id = ?", (aid,)).fetchone()
        if not a or a["project_id"] != p["id"]:
            raise ApiError(400, "申请 %s 不属于该项目" % aid)
        if a["status"] != "approved":
            raise ApiError(400, "申请 %s 当前状态为 %s，只有已通过的申请可以发货" % (aid, a["status"]))
        apps.append(a)

    token = secrets.token_hex(8)
    fp = fingerprint(apps)
    preview_rows = []
    for a in apps:
        vals = json.loads(a["form_values"])
        preview_rows.append({
            "application_id": a["id"],
            "group_name": conn.execute("SELECT name FROM groups WHERE id=?", (a["group_id"],)).fetchone()["name"],
            "qty": a["qty"],
            "receiver": vals.get("receiver", ""),
            "phone": vals.get("phone", ""),
            "address": vals.get("address", ""),
            "track_no": tracks[a["id"]],
        })
    SHIP_SNAPSHOTS[token] = {
        "project_id": p["id"], "fp": fp, "ids": ids, "tracks": tracks,
        "expire": time.time() + SNAPSHOT_TTL,
    }
    return {"token": token, "expires_in": SNAPSHOT_TTL, "rows": preview_rows}


@route("POST", r"/api/projects/(\d+)/ship/confirm")
def api_ship_confirm(conn, handler, m, body):
    user = get_user(conn, handler)
    pid = int(m.group(1))
    p = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
    if not p:
        raise ApiError(404, "项目不存在")
    if user["role"] != "channel" or p["channel_id"] != user["channel_id"]:
        raise ApiError(403, "只有项目所属渠道方可以发货")

    token = body.get("token") or ""
    snap = SHIP_SNAPSHOTS.get(token)
    if not snap or snap["project_id"] != pid:
        raise ApiError(400, "预览已失效，请重新预览")
    if time.time() > snap["expire"]:
        SHIP_SNAPSHOTS.pop(token, None)
        raise ApiError(409, "预览已过期，请重新预览")

    apps = []
    for aid in snap["ids"]:
        a = conn.execute("SELECT * FROM applications WHERE id = ?", (aid,)).fetchone()
        if not a or a["project_id"] != pid or a["status"] != "approved":
            SHIP_SNAPSHOTS.pop(token, None)
            raise ApiError(409, "预览后申请状态已变化，整批停止，请重新预览")
        apps.append(a)
    if fingerprint(apps) != snap["fp"]:
        SHIP_SNAPSHOTS.pop(token, None)
        raise ApiError(409, "预览后申请信息已变化，整批停止，请重新预览")

    try:
        for a in apps:
            conn.execute(
                "UPDATE applications SET status='shipped', carrier=?, track_no=?, updated_at=? WHERE id=?",
                ("示例快递", snap["tracks"][a["id"]], now_str(), a["id"]),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        SHIP_SNAPSHOTS.pop(token, None)
        raise ApiError(500, "发货失败，整批已回滚")
    SHIP_SNAPSHOTS.pop(token, None)
    return {"shipped": len(apps)}


@route("POST", r"/api/applications/(\d+)/feedback")
def api_feedback(conn, handler, m, body):
    user = get_user(conn, handler)
    a = conn.execute("SELECT * FROM applications WHERE id = ?", (int(m.group(1)),)).fetchone()
    if not a:
        raise ApiError(404, "申请不存在")
    if user["role"] != "group" or a["group_id"] != user["group_id"]:
        raise ApiError(403, "只有申请所属观影团可以提交返图")
    if a["status"] not in ("approved", "shipped"):
        raise ApiError(400, "当前状态不能提交返图")
    p = conn.execute("SELECT * FROM projects WHERE id = ?", (a["project_id"],)).fetchone()
    schema = json.loads(p["result_schema"])
    values = body.get("values") or {}
    for f in schema:
        if f.get("required") and not str(values.get(f["key"], "")).strip():
            raise ApiError(400, "请填写：%s" % f["label"])
    conn.execute(
        "UPDATE applications SET status='feedback', feedback=?, updated_at=? WHERE id=?",
        (json.dumps(values, ensure_ascii=False), now_str(), a["id"]),
    )
    conn.commit()
    return {"id": a["id"], "status": "feedback"}


@route("POST", r"/api/applications/(\d+)/score")
def api_score(conn, handler, m, body):
    user = get_user(conn, handler)
    a = conn.execute("SELECT * FROM applications WHERE id = ?", (int(m.group(1)),)).fetchone()
    if not a:
        raise ApiError(404, "申请不存在")
    p = conn.execute("SELECT * FROM projects WHERE id = ?", (a["project_id"],)).fetchone()
    if user["role"] != "channel" or p["channel_id"] != user["channel_id"]:
        raise ApiError(403, "只有项目所属渠道方可以评分")
    if a["status"] != "feedback":
        raise ApiError(400, "只有已返图的申请可以评分")
    try:
        score = int(body.get("score"))
    except (TypeError, ValueError):
        raise ApiError(400, "评分必须是 1-5 的整数")
    if score < 1 or score > 5:
        raise ApiError(400, "评分必须是 1-5 的整数")
    conn.execute(
        "UPDATE applications SET status='completed', score=?, comment=?, updated_at=? WHERE id=?",
        (score, body.get("comment") or None, now_str(), a["id"]),
    )
    conn.commit()
    return {"id": a["id"], "status": "completed", "score": score}


@route("POST", r"/api/applications/(\d+)/cancel")
def api_cancel(conn, handler, m, body):
    user = get_user(conn, handler)
    a = conn.execute("SELECT * FROM applications WHERE id = ?", (int(m.group(1)),)).fetchone()
    if not a:
        raise ApiError(404, "申请不存在")
    if user["role"] != "group" or a["group_id"] != user["group_id"]:
        raise ApiError(403, "只有申请所属观影团可以流团")
    if a["status"] not in ("approved", "shipped"):
        raise ApiError(400, "当前状态不能流团")
    note = (body.get("note") or "").strip()
    if not note:
        raise ApiError(400, "流团必须填写备注")
    conn.execute(
        "UPDATE applications SET status='cancelled', note=?, updated_at=? WHERE id=?",
        (note, now_str(), a["id"]),
    )
    conn.commit()
    return {"id": a["id"], "status": "cancelled"}


@route("GET", "/api/admin/certs")
def api_admin_certs(conn, handler, m, body):
    user = get_user(conn, handler)
    if user["role"] != "admin":
        raise ApiError(403, "仅管理员可查看")
    rows = conn.execute("SELECT * FROM certs ORDER BY id").fetchall()
    return {"certs": [dict(r) for r in rows]}


@route("POST", r"/api/admin/certs/(\d+)/review")
def api_admin_cert_review(conn, handler, m, body):
    user = get_user(conn, handler)
    if user["role"] != "admin":
        raise ApiError(403, "仅管理员可审核")
    c = conn.execute("SELECT * FROM certs WHERE id = ?", (int(m.group(1)),)).fetchone()
    if not c:
        raise ApiError(404, "认证不存在")
    if c["status"] != "pending":
        raise ApiError(400, "该认证已处理")
    action = body.get("action")
    if action not in ("approve", "reject"):
        raise ApiError(400, "action 必须是 approve 或 reject")
    conn.execute("UPDATE certs SET status=? WHERE id=?", ("approved" if action == "approve" else "rejected", c["id"]))
    # 演示简化：不做角色授予，真实系统在此处同步档案并授予角色
    conn.commit()
    return {"id": c["id"], "status": "approved" if action == "approve" else "rejected"}


@route("GET", "/api/metrics")
def api_metrics(conn, handler, m, body):
    by_status = {r["status"]: r["c"] for r in conn.execute(
        "SELECT status, COUNT(*) c FROM applications GROUP BY status")}
    total = sum(by_status.values())
    return {
        "channels": conn.execute("SELECT COUNT(*) c FROM channels").fetchone()["c"],
        "groups": conn.execute("SELECT COUNT(*) c FROM groups").fetchone()["c"],
        "admissions": conn.execute("SELECT COUNT(*) c FROM admissions").fetchone()["c"],
        "projects_published": conn.execute(
            "SELECT COUNT(*) c FROM projects WHERE status='published'").fetchone()["c"],
        "applications": total,
        "by_status": by_status,
        "funnel": {
            "提交申请": total,
            "审核通过": sum(v for k, v in by_status.items() if k in ("approved", "shipped", "feedback", "completed")),
            "已发货": sum(v for k, v in by_status.items() if k in ("shipped", "feedback", "completed")),
            "完成返图评分": by_status.get("completed", 0),
        },
    }


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "MAMDemo/1.0"

    def log_message(self, fmt, *args):
        pass  # 保持输出干净

    def _send(self, status, payload=None, content_type="application/json; charset=utf-8", raw=None):
        data = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method):
        parsed = urlparse(self.path)
        path = parsed.path
        if not path.startswith("/api/"):
            return self._serve_static(path)
        body = {}
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "请求体不是合法 JSON"})
        for m_method, pattern, fn in ROUTES:
            if m_method != method:
                continue
            match = pattern.match(path + (("?" + parsed.query) if method == "GET" else ""))
            if not match:
                match = pattern.match(path)
            if match:
                conn = db.connect()
                try:
                    result = fn(conn, self, match, body)
                    return self._send(200, result)
                except ApiError as e:
                    return self._send(e.status, {"error": e.message})
                except Exception as e:  # 演示环境：不吞异常
                    import traceback
                    traceback.print_exc()
                    return self._send(500, {"error": "服务端异常：%s" % e})
                finally:
                    conn.close()
        return self._send(404, {"error": "接口不存在"})

    def _serve_static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        full = os.path.normpath(os.path.join(WEB, path.lstrip("/")))
        if not full.startswith(WEB) or not os.path.isfile(full):
            return self._send(404, {"error": "文件不存在"})
        import mimetypes
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            data = f.read()
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, raw=data, content_type=ctype)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


def main():
    db.init(reset=True)
    port = int(os.environ.get("PORT", "8000"))
    print("MAM 产品原型已启动： http://localhost:%d" % port)
    print("演示数据每次启动重建，按 Ctrl+C 退出。")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
