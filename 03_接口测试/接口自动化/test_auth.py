# -*- coding: utf-8 -*-
"""接口自动化-认证模块（登录/鉴权）
注意：登录接口当前无限流保护（BUG-002），错误密码测试不受影响

Allure：本文件全部用例 @allure.feature = 「认证鉴权」。
severity 取值 P0–P3，口径对齐《01_测试计划》§8 缺陷等级定义，映射表见 conftest.py 顶部注释。
"""
import allure
import pytest
import requests

from conftest import BASE, PWD, USER, P0, P1, record

pytestmark = pytest.mark.auth


def _login(identification, password):
    """调用登录接口；响应登记进请求日志，用例失败时自动附加到 Allure 报告"""
    with allure.step(f"调用登录接口 POST /api/token（identification={identification!r}）"):
        r = record(requests.post(BASE + "/api/token",
                                 json={"identification": identification, "password": password},
                                 timeout=20))
    return r


@allure.feature("认证鉴权")
@allure.story("登录成功")
@allure.title("登录-正确账号密码返回 Token 与 userId")
@allure.severity(P0)
def test_login_success():
    """登录-正确账号密码 → 200，返回 token"""
    with allure.step("使用正确账号密码登录"):
        r = _login(USER, PWD)
    with allure.step("校验 HTTP 状态码为 200"):
        assert r.status_code == 200
    with allure.step("校验响应体同时含 token 与 userId"):
        data = r.json()
        assert "token" in data
        assert "userId" in data


@allure.feature("认证鉴权")
@allure.story("登录失败")
@allure.title("登录-错误密码返回 401")
@allure.severity(P1)
def test_login_wrong_password():
    """登录-错误密码 → 401"""
    with allure.step("使用错误密码登录"):
        r = _login(USER, "wrong_password_123")
    with allure.step("校验 HTTP 状态码为 401"):
        assert r.status_code == 401


@allure.feature("认证鉴权")
@allure.story("登录失败")
@allure.title("登录-不存在的用户返回 401")
@allure.severity(P1)
def test_login_nonexistent_user():
    """登录-不存在的用户 → 401"""
    with allure.step("使用不存在的用户名登录"):
        r = _login("no_such_user_xyz", "test12345")
    with allure.step("校验 HTTP 状态码为 401"):
        assert r.status_code == 401


@allure.feature("认证鉴权")
@allure.story("登录失败")
@allure.title("登录-账号密码均为空返回 401")
@allure.severity(P1)
def test_login_blank():
    """登录-空输入 → 401"""
    with allure.step("使用空账号空密码登录"):
        r = _login("", "")
    with allure.step("校验 HTTP 状态码为 401"):
        assert r.status_code == 401


@allure.feature("认证鉴权")
@allure.story("登录限流")
@allure.title("登录-连续 10 次错误密码应触发 429 限流（实际未触发）")
@allure.severity(P1)
@allure.description(
    "缺陷编号：BUG-002（P1 严重）\n"
    "现象：连续 10 次使用错误密码请求 /api/token，全部返回 401，从未出现 429。\n"
    "预期：连续失败达到阈值后应触发限流（HTTP 429）拦截暴力破解。\n"
    "实际：无任何限流，攻击者可无限次尝试口令 —— 登录接口缺失限流保护。\n"
    "对照：同一站点的发帖接口第 2 帖即 429（BUG-003），说明限流中间件存在但未覆盖登录接口。"
)
@pytest.mark.xfail(reason="BUG-002: 登录接口无限流保护，连续错误密码不触发429（已知缺陷）",
                   strict=True)
def test_login_rate_limit_missing():
    """登录-连续错误密码应触发限流429（已知缺陷：未触发）"""
    codes = []
    with allure.step("连续 10 次使用错误密码登录，记录每次响应码"):
        for i in range(10):
            r = _login(USER, f"wrong_{i}")
            codes.append(r.status_code)
            if r.status_code == 429:
                break
    with allure.step("校验这 10 次中出现过 429（已知缺陷：断言失败 → xfail）"):
        assert 429 in codes, f"连续10次错误密码未触发限流: {codes}"


@allure.feature("认证鉴权")
@allure.story("未登录访问")
@allure.title("未登录访问受保护接口返回 401 且错误码为 not_authenticated")
@allure.severity(P1)
def test_unauthenticated_protected_api(client):
    """未登录访问受保护接口 → 401"""
    # 保留 client 形参：借它触发会话级鉴权自检；但本用例必须发「不带 Token」的请求
    with allure.step("不带任何认证头，请求受保护接口 GET /api/notifications"):
        r = record(requests.get(BASE + "/api/notifications", timeout=20))
    with allure.step("校验 HTTP 401 且错误码为 not_authenticated"):
        assert r.status_code == 401
        err = r.json()["errors"][0]
        assert err["code"] == "not_authenticated"
