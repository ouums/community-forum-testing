# -*- coding: utf-8 -*-
"""清理接口自动化产生的测试帖与测试评论 —— 支撑交付说明中「测试数据全程清理，未污染线上数据」的结论

用法：
    python cleanup_api_test.py            # 试运行（dry-run）：只列出将被清理的内容，不删
    python cleanup_api_test.py --apply    # 实际执行软删除

机制：Flarum 的「删除」= 软删除（PATCH .../isHidden=true），软删除后其他用户不可见，
      作者仍可在自己的列表看到已隐藏状态，这是 Flarum 的既有设计。
      本脚本只处理作者为测试账号、且命中测试关键词的内容，不会碰他人内容。
      重复隐藏同一内容无副作用（幂等）。

      与 UI 版（06_UI自动化/cleanup_ui_test.py）的差异：接口套件除了发帖还会**发评论**，
      评论没有标题可匹配，因此额外按 /api/posts 的正文关键词扫描。

认证：Flarum 要求 `Authorization: Token <token>`（不是 Bearer）。
"""
import json
import os
import re
import sys

import requests

sys.stdout.reconfigure(encoding='utf-8')

# 与 conftest.py 用同一组环境变量；可选从仓库根目录 .env 读取
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"), encoding="utf-8")
except ImportError:
    pass

# 与 conftest.py 用同一组环境变量（可用同一套变量把整套套件指向别的站点）
BASE = os.environ.get("FORUM_BASE", "http://localhost:8080")
USER = os.environ.get("FORUM_USER", "testuser")
PWD = os.environ.get("FORUM_PWD", "")

# 帖子标题：test_discussions.py 中 f"【自动化】接口发帖 {rand_suffix}"
#         以及 test_rate_limit_too_strict 的 f"限流回归{time.time():.0f}"（第 1 帖）
#         —— 该用例单独运行（限流窗口空闲）时第 1 帖会发成功，标题不含上面的关键词，
#            漏掉它会把这帖永久留在线上。
DISC_KEYWORDS = ["【自动化】接口发帖", "限流回归"]
# 评论正文：test_discussions.py 中 f"pytest 自动化评论 {rand_suffix}"
POST_KEYWORDS = ["pytest 自动化评论"]

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "清理结果_API.json")

PAGE_SIZE = 50
MAX_PAGES = 40           # 防御性上限（2000 条）；触发即视为扫描不完整并告警，不静默截断


def _plain(html):
    """去掉 HTML 标签，便于按关键词匹配正文"""
    return re.sub(r"<[^>]+>", "", html or "")


def _scan_all(session, path, headers, extra_params=None):
    """翻页取本账号的**全量**内容，返回 (items, 错误说明或 None)。

    翻到某页不足一页为止，不用固定页数 —— 固定页数会**静默截断**，
    漏掉的内容会被误判成"已清理"。
    """
    items, page = [], 1
    while page <= MAX_PAGES:
        params = {"page[limit]": PAGE_SIZE, "page[number]": page}
        params.update(extra_params or {})
        r = session.get(BASE + path, params=params, headers=headers, timeout=20)
        if r.status_code != 200:
            return items, f"{path} HTTP {r.status_code}"
        data = r.json().get("data", [])
        items.extend(data)
        if len(data) < PAGE_SIZE:
            return items, None
        page += 1
    return items, f"超过 {MAX_PAGES} 页上限，结果可能不完整"


def _guard_target():
    """默认只允许本地实例；远程环境需显式确认已获授权。"""
    from urllib.parse import urlparse
    host = (urlparse(BASE).hostname or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"} and             os.environ.get("FORUM_ALLOW_REMOTE_TESTS") != "1":
        print(f"FORUM_BASE={BASE} 不是本地地址。为避免误操作未授权站点，"
              "远程运行请设置 FORUM_ALLOW_REMOTE_TESTS=1。")
        return False
    if not USER or not PWD:
        print("请设置 FORUM_USER / FORUM_PWD 环境变量（参考仓库根目录 .env.example）。")
        return False
    return True


def main(apply=False):
    if not _guard_target():
        return
    s = requests.Session()
    r = s.post(BASE + "/api/token", json={"identification": USER, "password": PWD},
               headers={"Content-Type": "application/json"}, timeout=20)
    if r.status_code != 200:
        print("登录失败，终止：", r.status_code, r.text[:120])
        return
    tok = r.json()["token"]
    uid = r.json().get("userId")
    H = {"Authorization": f"Token {tok}",
         "Content-Type": "application/vnd.api+json",
         "Accept": "application/json"}

    # 鉴权自检：写操作前先确认 token 真的生效，避免把「没登录」误判成「没权限」
    chk = s.get(BASE + "/api/notifications", headers=H, timeout=20)
    if chk.status_code != 200:
        print(f"鉴权自检失败：/api/notifications 返回 {chk.status_code}，终止。")
        return
    print(f"登录成功 userId={uid}，鉴权自检通过\n")

    # ---- 1) 测试帖：按标题关键词（filter[author] 收用户名，不是 userId）----
    found, disc_err = _scan_all(s, "/api/discussions", H, {"filter[author]": USER})
    if disc_err:
        print(f"扫描帖子失败：{disc_err}，本次跳过帖子清理。")

    disc_targets = []
    for d in found:
        title = d["attributes"].get("title") or ""
        if any(k in title for k in DISC_KEYWORDS):
            disc_targets.append((d["id"], title, d["attributes"].get("isHidden")))

    # ---- 2) 测试评论：没有标题，按正文关键词扫本账号的帖子 ----
    posts, post_err = _scan_all(s, "/api/posts", H, {"filter[author]": USER})
    if post_err:
        print(f"扫描评论失败：{post_err}，本次跳过评论清理。")

    post_targets = []
    for p in posts:
        attrs = p["attributes"]
        content = _plain(attrs.get("content") or attrs.get("contentHtml")).strip()
        if any(k in content for k in POST_KEYWORDS):
            post_targets.append((p["id"], content[:60], attrs.get("isHidden")))

    print(f"账号 {USER} 共 {len(found)} 个帖子 / {len(posts)} 条内容，命中测试数据："
          f"帖子 {len(disc_targets)} 个、评论 {len(post_targets)} 条")
    for pid, title, hid in disc_targets:
        print(f"  [帖子] id={pid}  已隐藏={hid}  {title[:55]}")
    for pid, text, hid in post_targets:
        print(f"  [评论] id={pid}  已隐藏={hid}  {text[:55]}")

    total = len(disc_targets) + len(post_targets)
    if not total:
        print("\n无需清理。")
    elif not apply:
        print(f"\n[试运行] 以上 {total} 项**未被删除**。确认无误后加 --apply 实际执行软删除。")
    else:
        ok = skipped = 0
        for kind, items in (("discussions", disc_targets), ("posts", post_targets)):
            for pid, _, hid in items:
                if hid is True:           # 此前已隐藏，无需重复请求
                    skipped += 1
                    print(f"  跳过 id={pid}（此前已隐藏）")
                    continue
                rr = s.patch(f"{BASE}/api/{kind}/{pid}",
                             json={"data": {"type": kind, "id": pid,
                                            "attributes": {"isHidden": True}}},
                             headers=H, timeout=25)
                if rr.status_code == 200:
                    ok += 1
                    print(f"  已软删除 {kind[:-1]} id={pid}")
                else:
                    print(f"  失败 id={pid} HTTP {rr.status_code} {rr.text[:80]}")
        print(f"\n完成：{ok}/{total - skipped} 项已软删除（他人不可见），{skipped} 项此前已隐藏。")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"user": USER,
                   "scanned": {"discussions": len(found), "posts": len(posts)},
                   "targets": {
                       "discussions": [{"id": p, "title": t} for p, t, _ in disc_targets],
                       "posts": [{"id": p, "text": t} for p, t, _ in post_targets],
                   },
                   "applied": bool(apply)}, f, ensure_ascii=False, indent=1)
    print(f"记录已存：{OUT}")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
