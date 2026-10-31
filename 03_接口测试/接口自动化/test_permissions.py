# -*- coding: utf-8 -*-
"""接口自动化-权限模块
账号 id 一律由 conftest 的 user_id fixture 自举（来自登录响应），不硬编码。

Allure：本文件全部用例 @allure.feature = 「权限控制」。
severity 取值 P0–P3，口径对齐《01_测试计划》§8 缺陷等级定义，映射表见 conftest.py 顶部注释。

口径提醒：Flarum 的「删除」是软删除（PATCH isHidden=true），普通用户对自己内容有权限；
DELETE 硬删除是管理员权限，普通用户 403 属正常设计，**不是缺陷**。
"""
import allure
import pytest

from conftest import BASE, USER, P1, P2, log_extract

pytestmark = pytest.mark.permission


@allure.feature("权限控制")
@allure.story("管理接口越权")
@allure.title("权限-普通用户访问管理接口返回 403 permission_denied")
@allure.severity(P1)
def test_regular_user_admin_api_denied(client):
    """普通用户访问管理接口 /api/users → 403"""
    with allure.step("以普通用户身份请求管理接口 GET /api/users"):
        r = client.get(BASE + "/api/users", timeout=20)
    with allure.step("校验 HTTP 403 且错误码为 permission_denied"):
        assert r.status_code == 403
        assert r.json()["errors"][0]["code"] == "permission_denied"


@allure.feature("权限控制")
@allure.story("越权删除")
@allure.title("权限-删除他人帖子返回 403")
@allure.severity(P1)
def test_delete_other_post_denied(client, user_id):
    """删除他人帖子 → 403（取一个非自己发布的帖子）"""
    with allure.step("拉取帖子列表，挑一条非当前账号发布的帖子"):
        r0 = client.get(BASE + "/api/discussions", params={"page[limit]": 30}, timeout=20)
        other = next((d for d in r0.json().get("data", [])
                      if d["relationships"].get("user", {}).get("data", {}).get("id") != user_id), None)
        if not other:
            pytest.skip("未找到他人帖子")
        log_extract("他人帖子 id（越权删除靶点）", other["id"])
        allure.attach(other["id"], "选中的他人帖子 id", allure.attachment_type.TEXT)
    with allure.step(f"尝试 DELETE 他人帖子 /api/discussions/{other['id']}"):
        r = client.delete(BASE + f"/api/discussions/{other['id']}", timeout=20)
    with allure.step("校验 HTTP 403（无越权删除权限）"):
        assert r.status_code == 403


@allure.feature("权限控制")
@allure.story("个人资料")
@allure.title("权限-查询个人资料返回 200 且用户名与登录账号一致")
@allure.severity(P2)
def test_profile_read(client, user_id):
    """个人资料查询-自己 → 200，且用户名与登录账号一致"""
    with allure.step(f"请求自己的资料 GET /api/users/{user_id}"):
        r = client.get(BASE + f"/api/users/{user_id}", timeout=20)
    with allure.step("校验 HTTP 200"):
        assert r.status_code == 200
    with allure.step(f"校验返回的 username 与登录账号 {USER!r} 一致（真比较，防止张冠李戴）"):
        attrs = r.json()["data"]["attributes"]
        assert attrs.get("username") == USER


@allure.feature("权限控制")
@allure.story("个人资料")
@allure.title("权限-已登录用户可读取自己的通知列表")
@allure.severity(P2)
def test_user_notifications(client):
    """通知接口-已登录 → 200"""
    with allure.step("以已登录身份请求 GET /api/notifications"):
        r = client.get(BASE + "/api/notifications", timeout=20)
    with allure.step("校验 HTTP 200 且响应结构含 data 字段"):
        assert r.status_code == 200
        assert "data" in r.json()


@allure.feature("权限控制")
@allure.story("账号信息修改")
@allure.title("权限-邮箱已激活账号可修改昵称（回归：非缺陷）")
@allure.severity(P2)
@pytest.mark.write
def test_edit_nickname_activated_account(write_client, user_id):
    """修改昵称-邮箱已激活账号 → 200 成功（回归：非缺陷）"""
    with allure.step(f"以邮箱已激活账号 PATCH /api/users/{user_id} 修改 nickname"):
        r = write_client.patch(BASE + f"/api/users/{user_id}",
                               json={"data": {"type": "users", "id": user_id,
                                              "attributes": {"nickname": USER}}},
                               timeout=20)
    with allure.step("校验 HTTP 200/204（对照：未激活邮箱的账号此处会 403，属账号状态而非缺陷）"):
        assert r.status_code in (200, 204), f"HTTP {r.status_code} {r.text[:100]}"
