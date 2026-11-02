"""
端到端测试：启动一个独立端口的演示服务，把关键业务规则跑一遍。

运行：
    python3 tests/test_api.py

覆盖：可见范围、准入、私密分享、必填校验、驳回重提、
      越权审核、批量发货快照与整批停止、返图评分、指标。
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS = []


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_ready(port, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/api/bootstrap" % port, timeout=0.5)
            return True
        except Exception:
            time.sleep(0.15)
    return False


def make_client(port):
    def req(path, user, method="GET", body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (port, path),
            data=data, method=method,
            headers={"X-Demo-User": str(user), "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")
    return req


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + str(extra)))
    if not cond:
        FAILS.append(name)


def main():
    port = free_port()
    tmpdir = tempfile.mkdtemp(prefix="mam-demo-test-")
    env = dict(os.environ, PORT=str(port), MAM_DB=os.path.join(tmpdir, "test.db"))
    proc = subprocess.Popen(
        [sys.executable, "app.py"], cwd=BASE_DIR, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        if not wait_ready(port):
            raise SystemExit("服务启动失败：%s" % proc.stderr.read().decode())
        req = make_client(port)

        # 1. 可见范围
        s, d = req("/api/projects", 4)  # 北站：无准入
        titles = [p["title"] for p in d["projects"]]
        check("无准入观影团只看到公开项目", titles == ["示例影片 A 首映场物料"], titles)

        s, d = req("/api/projects", 3)  # 江畔：星幕准入
        titles = [p["title"] for p in d["projects"]]
        check("有准入能看到仅准入项目", "IMAX 厅主题周边（限准入）" in titles, titles)
        check("私密项目不进广场", not any("私密" in t for t in titles), titles)

        s, d = req("/api/projects?share=demo-share-001", 2)
        check("私密项目可通过分享凭证访问", any("私密" in p["title"] for p in d["projects"]))
        s, d = req("/api/projects?share=wrong", 2)
        check("错误分享凭证不生效", not any("私密" in p["title"] for p in d["projects"]))

        # 2. 申请权限与校验
        payload = {"session_time": "2026-11-05 19:00", "cinema": "示例影城", "qty": 5,
                   "receiver": "张女士", "phone": "13800000001",
                   "address": "示例路 1 号", "proof": "https://example.com/p"}
        s, d = req("/api/projects/2/apply", 4, "POST", {"values": payload})
        check("无准入不能申请仅准入项目", s in (400, 403), (s, d))
        s, d = req("/api/projects/3/apply", 2, "POST", {"values": payload})
        check("私密项目无分享凭证不能申请", s == 403, (s, d))
        s, d = req("/api/projects/1/apply", 2, "POST", {"values": payload})
        check("公开项目申请成功", s == 200 and d.get("status") == "pending", (s, d))
        new_id = d.get("id")
        s, d = req("/api/projects/1/apply", 2, "POST", {"values": {"session_time": "2026-11-05 19:00"}})
        check("必填缺失被拒绝", s == 400, (s, d))

        # 3. 审核与驳回重提
        s, d = req("/api/applications/%d/review" % new_id, 2, "POST", {"action": "approve"})
        check("非项目归属渠道方不能审核", s == 403, (s, d))
        s, d = req("/api/applications/%d/review" % new_id, 5, "POST", {"action": "reject", "note": "证明不清晰"})
        check("渠道方驳回", s == 200 and d["status"] == "rejected", (s, d))
        s, d = req("/api/applications/%d/resubmit" % new_id, 2, "POST", {"values": payload})
        check("重提后待审核且轮次 +1", s == 200 and d["status"] == "pending" and d["review_version"] == 2, (s, d))
        s, d = req("/api/applications/%d/review" % new_id, 5, "POST", {"action": "approve"})
        check("重新通过", s == 200 and d["status"] == "approved", (s, d))

        # 4. 批量发货：预览后数据变化 → 整批停止
        s, d = req("/api/projects/1/ship/preview", 5, "POST",
                   {"rows": [{"application_id": new_id, "track_no": "DEMO9999"}]})
        check("预览生成快照", s == 200 and d.get("token"), (s, d))
        token = d["token"]
        s, d = req("/api/applications/%d/cancel" % new_id, 2, "POST", {"note": "影城临时取消场次"})
        check("预览后申请变化（流团）", s == 200, (s, d))
        s, d = req("/api/projects/1/ship/confirm", 5, "POST", {"token": token})
        check("数据变化后确认被整批拒绝", s == 409, (s, d))

        # 5. 批量发货：正常确认
        s, d = req("/api/projects/2/ship/preview", 5, "POST",
                   {"rows": [{"application_id": 2, "track_no": "DEMO8888"}]})
        check("第二条预览生成快照", s == 200 and d.get("token"), (s, d))
        token = d["token"]
        s, d = req("/api/projects/2/ship/confirm", 5, "POST", {"token": token})
        check("确认后整批发货", s == 200 and d.get("shipped") == 1, (s, d))
        s, d = req("/api/projects/2/ship/confirm", 5, "POST", {"token": token})
        check("同一凭证不能重复发货", s == 400, (s, d))

        # 6. 返图与评分
        s, d = req("/api/applications/2/feedback", 3, "POST",
                   {"values": {"photos": "https://example.com/f1"}})
        check("提交返图", s == 200 and d["status"] == "feedback", (s, d))
        s, d = req("/api/applications/2/score", 5, "POST", {"score": 4, "comment": "不错"})
        check("评分后归档为已完成", s == 200 and d["status"] == "completed", (s, d))
        s, d = req("/api/applications/2/score", 5, "POST", {"score": 9})
        check("评分范围校验", s == 400, (s, d))

        # 7. 越权与指标
        s, d = req("/api/channel/applications", 2)
        check("观影团不能看渠道审核列表", s == 403, (s, d))
        s, d = req("/api/metrics", 7)
        check("指标接口可用", s == 200 and d["applications"] > 0, (s, d))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("\n结果：%d 项失败" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
