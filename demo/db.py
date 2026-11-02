"""
演示数据库：建表 + 种子数据。
每次启动都会重建 demo.db，保证演示状态可预期。
"""
import json
import os
import sqlite3
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("MAM_DB") or os.path.join(BASE, "demo.db")


def now():
    return datetime.now().replace(second=0, microsecond=0)


def iso(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,            -- fan / group / channel / admin
    group_id INTEGER,
    channel_id INTEGER,
    phone TEXT
);

CREATE TABLE channels (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    tag TEXT NOT NULL UNIQUE       -- 全平台唯一的渠道标签
);

CREATE TABLE groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT,
    cinema TEXT,                   -- 默认影城
    hall TEXT,                     -- 默认影厅
    receiver TEXT,                 -- 默认收件人
    phone TEXT,
    address TEXT
);

CREATE TABLE admissions (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    UNIQUE (channel_id, group_id)
);

CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    film TEXT,
    status TEXT NOT NULL,          -- draft / pending / published / rejected / closed
    visibility TEXT NOT NULL,      -- public / admitted / private
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    form_schema TEXT NOT NULL,     -- JSON: 报名表字段
    result_schema TEXT NOT NULL,   -- JSON: 返图字段
    share_token TEXT               -- 私密项目的分享凭证
);

CREATE TABLE applications (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    status TEXT NOT NULL,          -- pending/approved/rejected/shipped/feedback/completed/cancelled
    review_version INTEGER NOT NULL DEFAULT 1,
    note TEXT,
    form_values TEXT NOT NULL,     -- JSON
    qty INTEGER NOT NULL DEFAULT 0,
    carrier TEXT,
    track_no TEXT,
    feedback TEXT,                 -- JSON
    score INTEGER,
    comment TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE certs (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    type TEXT NOT NULL,            -- group / channel
    name TEXT NOT NULL,
    status TEXT NOT NULL,          -- pending / approved / rejected
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


FORM_A = [
    {"key": "session_time", "label": "活动时间", "type": "datetime", "required": True},
    {"key": "cinema", "label": "活动影城", "type": "text", "required": True, "prefill": "group.cinema"},
    {"key": "hall", "label": "影厅", "type": "text", "required": False, "prefill": "group.hall"},
    {"key": "qty", "label": "申请数量", "type": "number", "required": True},
    {"key": "receiver", "label": "收件人", "type": "text", "required": True, "prefill": "group.receiver"},
    {"key": "phone", "label": "联系电话", "type": "text", "required": True, "prefill": "group.phone"},
    {"key": "address", "label": "收货地址", "type": "text", "required": True, "prefill": "group.address"},
    {"key": "proof", "label": "成团证明链接", "type": "text", "required": True},
    {"key": "photos", "label": "现场图（可多个，逗号分隔）", "type": "text", "required": False},
]

FORM_B = [
    {"key": "session_time", "label": "活动时间", "type": "datetime", "required": True},
    {"key": "cinema", "label": "活动影城", "type": "text", "required": True, "prefill": "group.cinema"},
    {"key": "qty", "label": "申请数量", "type": "number", "required": True},
    {"key": "receiver", "label": "收件人", "type": "text", "required": True, "prefill": "group.receiver"},
    {"key": "phone", "label": "联系电话", "type": "text", "required": True, "prefill": "group.phone"},
    {"key": "address", "label": "收货地址", "type": "text", "required": True, "prefill": "group.address"},
    {"key": "theme", "label": "城市主题", "type": "text", "required": True},
]

RESULT_A = [
    {"key": "photos", "label": "现场返图链接（多图，逗号分隔）", "type": "text", "required": True},
    {"key": "note", "label": "活动说明", "type": "text", "required": False},
]


def init(reset=True):
    if reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = connect()
    conn.executescript(SCHEMA)

    users = [
        (1, "小周（影迷）", "fan", None, None, "13800000000"),
        (2, "城南团长", "group", 1, None, "13800000001"),
        (3, "江畔团长", "group", 2, None, "13800000002"),
        (4, "北站团长", "group", 3, None, "13800000003"),
        (5, "星幕渠道", "channel", None, 1, "13900000001"),
        (6, "光影渠道", "channel", None, 2, "13900000002"),
        (7, "平台管理员", "admin", None, None, "13700000000"),
    ]
    conn.executemany("INSERT INTO users VALUES (?,?,?,?,?,?)", users)

    conn.executemany(
        "INSERT INTO channels VALUES (?,?,?)",
        [(1, "星幕影厅", "星幕"), (2, "光影工作室", "光影")],
    )

    conn.executemany(
        "INSERT INTO groups VALUES (?,?,?,?,?,?,?,?)",
        [
            (1, "城南观影团", "上海", "示例影城", "1 号厅", "张女士", "13800000001", "示例省示例市示例区示例路 1 号"),
            (2, "江畔观影团", "杭州", "示例影城二店", "3 号厅", "李先生", "13800000002", "示例省示例市示例区示例路 2 号"),
            (3, "北站观影团", "北京", "示例影城三店", "IMAX 厅", "王女士", "13800000003", "示例省示例市示例区示例路 3 号"),
        ],
    )

    # 星幕准入：城南、江畔；光影准入：城南
    conn.executemany(
        "INSERT INTO admissions (channel_id, group_id) VALUES (?,?)",
        [(1, 1), (1, 2), (2, 1)],
    )

    t = now()
    projects = [
        (1, 1, "示例影片 A 首映场物料", "示例影片 A", "published", "public",
         iso(t - timedelta(days=1)), iso(t + timedelta(days=7)),
         json.dumps(FORM_A, ensure_ascii=False), json.dumps(RESULT_A, ensure_ascii=False), None),
        (2, 1, "IMAX 厅主题周边（限准入）", "示例影片 B", "published", "admitted",
         iso(t - timedelta(days=2)), iso(t + timedelta(days=5)),
         json.dumps(FORM_A, ensure_ascii=False), json.dumps(RESULT_A, ensure_ascii=False), None),
        (3, 2, "城市限定票根（私密）", "示例影片 C", "published", "private",
         iso(t - timedelta(days=1)), iso(t + timedelta(days=10)),
         json.dumps(FORM_B, ensure_ascii=False), json.dumps(RESULT_A, ensure_ascii=False), "demo-share-001"),
        (4, 1, "中秋场物料（草稿）", "示例影片 A", "draft", "public",
         iso(t), iso(t + timedelta(days=14)),
         json.dumps(FORM_A, ensure_ascii=False), json.dumps(RESULT_A, ensure_ascii=False), None),
    ]
    conn.executemany("INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?,?)", projects)

    def values(**kw):
        return json.dumps(kw, ensure_ascii=False)

    apps = [
        # 待审核：城南 → 公开项目
        (1, 1, 1, "pending", 1, None, values(session_time=iso(t + timedelta(days=2)), cinema="示例影城", hall="1 号厅",
                                            qty=20, receiver="张女士", phone="13800000001",
                                            address="示例省示例市示例区示例路 1 号", proof="https://example.com/proof/1", photos=""),
         20, None, None, None, None, None, iso(t - timedelta(hours=5)), iso(t - timedelta(hours=5))),
        # 已通过，待发货：江畔 → 限准入项目
        (2, 2, 2, "approved", 1, "将按 15 人发货", values(session_time=iso(t + timedelta(days=3)), cinema="示例影城二店", hall="3 号厅",
                                                      qty=15, receiver="李先生", phone="13800000002",
                                                      address="示例省示例市示例区示例路 2 号", proof="https://example.com/proof/2", photos=""),
         15, None, None, None, None, None, iso(t - timedelta(days=1)), iso(t - timedelta(hours=20))),
        # 已发货：江畔 → 公开项目
        (3, 1, 2, "shipped", 1, None, values(session_time=iso(t - timedelta(days=1)), cinema="示例影城二店", hall="3 号厅",
                                             qty=10, receiver="李先生", phone="13800000002",
                                             address="示例省示例市示例区示例路 2 号", proof="https://example.com/proof/2", photos=""),
         10, "示例快递", "DEMO0001", None, None, None, iso(t - timedelta(days=4)), iso(t - timedelta(days=2))),
        # 已驳回：城南 → 公开项目（可修改重提）
        (4, 1, 1, "rejected", 1, "成团证明链接无法打开，请重新上传", values(session_time=iso(t + timedelta(days=4)), cinema="示例影城", hall="1 号厅",
                                                                    qty=12, receiver="张女士", phone="13800000001",
                                                                    address="示例省示例市示例区示例路 1 号", proof="https://example.com/broken", photos=""),
         12, None, None, None, None, None, iso(t - timedelta(days=2)), iso(t - timedelta(days=1))),
        # 已返图，待评分：城南 → 私密项目
        (5, 3, 1, "feedback", 1, None, values(session_time=iso(t - timedelta(days=3)), cinema="示例影城", qty=8,
                                               receiver="张女士", phone="13800000001",
                                               address="示例省示例市示例区示例路 1 号", theme="城市限定"),
         8, "示例快递", "DEMO0002",
         values(photos="https://example.com/photo/1,https://example.com/photo/2", note="现场 30 人，物料已发放"),
         None, None, iso(t - timedelta(days=6)), iso(t - timedelta(days=2))),
        # 已完成：城南 → 限准入项目
        (6, 2, 1, "completed", 1, None, values(session_time=iso(t - timedelta(days=8)), cinema="示例影城", hall="1 号厅",
                                               qty=6, receiver="张女士", phone="13800000001",
                                               address="示例省示例市示例区示例路 1 号", proof="https://example.com/proof/1", photos=""),
         6, "示例快递", "DEMO0003", values(photos="https://example.com/photo/3", note="活动顺利"),
         5, "返图清晰，现场物料露出完整", iso(t - timedelta(days=12)), iso(t - timedelta(days=7))),
        # 已返图待评分：江畔 → 公开项目（让星幕渠道的「返图评分」页有内容）
        (7, 1, 2, "feedback", 1, None, values(session_time=iso(t - timedelta(days=0)), cinema="示例影城二店", hall="3 号厅",
                                              qty=9, receiver="李先生", phone="13800000002",
                                              address="示例省示例市示例区示例路 2 号", proof="https://example.com/proof/2", photos=""),
         9, "示例快递", "DEMO0004",
         values(photos="https://example.com/photo/4,https://example.com/photo/5", note="现场 40 人，物料已发完"),
         None, None, iso(t - timedelta(days=5)), iso(t - timedelta(days=2))),
        # 已发货：城南 → 公开项目（让团长端有可返图的申请）
        (8, 1, 1, "shipped", 1, None, values(session_time=iso(t - timedelta(days=1)), cinema="示例影城", hall="1 号厅",
                                             qty=14, receiver="张女士", phone="13800000001",
                                             address="示例省示例市示例区示例路 1 号", proof="https://example.com/proof/1", photos=""),
         14, "示例快递", "DEMO0005", None, None, None, iso(t - timedelta(days=3)), iso(t - timedelta(days=1))),
    ]
    conn.executemany(
        "INSERT INTO applications VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", apps
    )

    certs = [
        (1, 1, "group", "城西观影团", "pending", json.dumps({"city": "上海", "contact": "小周"}, ensure_ascii=False), iso(t - timedelta(hours=3))),
        (2, 6, "channel", "拾光文化", "pending", json.dumps({"type": "赞助商", "contact": "陈先生"}, ensure_ascii=False), iso(t - timedelta(hours=1))),
    ]
    conn.executemany("INSERT INTO certs VALUES (?,?,?,?,?,?,?)", certs)

    conn.commit()
    conn.close()


def dict_rows(rows):
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init()
    print("seeded", DB_PATH)
