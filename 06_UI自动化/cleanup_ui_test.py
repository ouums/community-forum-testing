# -*- coding: utf-8 -*-
"""清理 UI 自动化产生的测试帖子 —— 支撑交付说明中「测试数据全程清理，未污染线上数据」的结论

用法：
    python cleanup_ui_test.py            # 试运行（dry-run）：只列出将被清理的帖子，不删
    python cleanup_ui_test.py --apply    # 实际执行软删除

机制：Flarum 的 UI「删除」= 软删除（PATCH /api/discussions/{id} isHidden=true），
      软删除后其他用户不可见，作者仍可在自己的列表看到已隐藏状态，这是 Flarum 的既有设计。
      本脚本只处理标题含指定关键词、且作者为测试账号的帖子，不会碰他人内容。
      已隐藏的帖子会被识别并跳过（与 03_接口测试/接口自动化/cleanup_api_test.py 口径一致）——
      作者视角的列表**包含自己已隐藏的内容**，不区分就会把早前清理过的帖子反复报成"待清理"。

认证：Flarum 要求 `Authorization: Token <token>`（不是 Bearer）。
"""
import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')
import requests

# 可选：从仓库根目录 .env 读取配置（未安装 python-dotenv 时忽略）
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8")
except ImportError:
    pass

BASE = os.environ.get("FORUM_BASE", "http://localhost:8080")
USER = os.environ.get("FORUM_USER", "testuser")
PWD = os.environ.get("FORUM_PWD", "")
KEYWORDS = ["【UI自动化】", "【测试】"]        # 只清理带这些前缀的本账号测试帖

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "清理结果.json")

PAGE_SIZE = 50
MAX_PAGES = 40           # 防御性上限（2000 条）；触发即视为扫描不完整并告警，不静默截断


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

    # 取本账号全部帖子（filter[author] 收用户名，不是 userId）
    # 翻到某页不足一页为止，不用固定页数 —— 固定页数会**静默截断**，
    # 漏掉的帖子会被误判成"已清理"（与 cleanup_api_test.py 的 _scan_all 同一套做法）
    found, page = [], 1
    while page <= MAX_PAGES:
        data = s.get(BASE + "/api/discussions",
                     params={"filter[author]": USER, "page[limit]": PAGE_SIZE, "page[number]": page},
                     headers=H, timeout=20).json()["data"]
        found.extend(data)
        if len(data) < PAGE_SIZE:
            break
        page += 1
    if page > MAX_PAGES:
        print(f"⚠ 扫描达到 {MAX_PAGES} 页上限，结果可能不完整，请核查。")

    targets = []
    for d in found:
        title = d["attributes"].get("title") or ""
        if any(k in title for k in KEYWORDS):
            targets.append((d["id"], title, d["attributes"].get("isHidden")))
    pending = [t for t in targets if t[2] is not True]

    print(f"账号 {USER} 共 {len(found)} 个帖子，其中测试帖 {len(targets)} 个"
          f"（已隐藏 {len(targets) - len(pending)} 个，待清理 {len(pending)} 个）：")
    for pid, title, hid in targets:
        print(f"  id={pid}  已隐藏={hid}  {title[:60]}")

    if not targets:
        print("\n无需清理。")
    elif not apply:
        print(f"\n[试运行] 以上 {len(pending)} 个**待清理**帖子未被删除"
              f"（另有 {len(targets) - len(pending)} 个此前已隐藏，无需重复处理）。"
              f"确认无误后加 --apply 实际执行软删除。")
    else:
        ok = skipped = 0
        for pid, title, hid in targets:
            if hid is True:           # 此前已隐藏，无需重复请求
                skipped += 1
                print(f"  跳过 id={pid}（此前已隐藏）")
                continue
            rr = s.patch(f"{BASE}/api/discussions/{pid}",
                         json={"data": {"type": "discussions", "id": pid,
                                        "attributes": {"isHidden": True}}},
                         headers=H, timeout=25)
            if rr.status_code == 200:
                ok += 1
                print(f"  已软删除 id={pid}")
            else:
                print(f"  失败 id={pid} HTTP {rr.status_code} {rr.text[:80]}")
        print(f"\n完成：{ok}/{len(targets) - skipped} 个测试帖已软删除（他人不可见），"
              f"{skipped} 个此前已隐藏。")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"user": USER, "scanned": len(found),
                   "targets": [{"id": p, "title": t} for p, t, _ in targets],
                   "already_hidden": [p for p, _, hid in targets if hid is True],
                   "applied": bool(apply)}, f, ensure_ascii=False, indent=1)
    print(f"记录已存：{OUT}")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
