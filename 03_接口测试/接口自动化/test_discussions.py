# -*- coding: utf-8 -*-
"""接口自动化-帖子/评论模块（读接口为主，写接口控频）

Allure：本文件全部用例 @allure.feature = 「帖子与评论」，
severity 取值 P0–P3，口径对齐《01_测试计划》§8 缺陷等级定义，映射表见 conftest.py 顶部注释。
帖子类与评论类由 @allure.story 区分（同时对应 pytest 的 post / comment marker）。
"""
import time

import allure
import pytest
import requests

from conftest import BASE, P0, P1, P2, P3, log_extract, record


def _assert_not_rate_limited(r):
    """写接口若遇 429 说明触发限流（BUG-003 发帖限流过严）→ xfail"""
    if r.status_code == 429:
        with allure.step("命中限流：HTTP 429 → 标记为已知缺陷 BUG-003"):
            allure.attach(r.request.url or "", "被限流的请求URL", allure.attachment_type.TEXT)
            allure.attach(str(r.status_code), "响应状态码", allure.attachment_type.TEXT)
            allure.attach((r.text or "")[:2000], "响应体", allure.attachment_type.TEXT)
        pytest.xfail("写接口被限流阻断(HTTP 429) —— BUG-003 发帖限流阈值过严")


# --------------------------------------------------------------------------- #
# 帖子
# --------------------------------------------------------------------------- #
@allure.feature("帖子与评论")
@allure.story("帖子列表")
@allure.title("帖子列表-返回非空数据且每条含标题与 id")
@allure.severity(P1)
@pytest.mark.post
def test_list_discussions(client):
    """帖子列表-正常 → 200，含数据"""
    with allure.step("请求帖子列表 GET /api/discussions?page[limit]=10"):
        r = client.get(BASE + "/api/discussions", params={"page[limit]": 10}, timeout=20)
    with allure.step("校验 HTTP 200 且返回条数大于 0"):
        assert r.status_code == 200
        data = r.json().get("data", [])
        assert len(data) > 0
    with allure.step("校验首条数据含 title 且 id 非空"):
        first = data[0]
        assert "title" in first.get("attributes", {})
        assert first.get("id")


@allure.feature("帖子与评论")
@allure.story("帖子详情")
@allure.title("帖子详情-按 id 查询返回 200 且含标题")
@allure.severity(P1)
@pytest.mark.post
def test_discussion_detail(client):
    """帖子详情-任一帖子 → 200，返回标题/内容"""
    with allure.step("先取一条帖子列表数据，拿到一个有效帖子 id"):
        r = client.get(BASE + "/api/discussions", params={"page[limit]": 1}, timeout=20)
        did = log_extract("discussion_id", r.json()["data"][0]["id"])
    with allure.step(f"请求帖子详情 GET /api/discussions/{did}"):
        rd = client.get(BASE + f"/api/discussions/{did}", timeout=20)
    with allure.step("校验 HTTP 200 且 attributes 含 title"):
        assert rd.status_code == 200
        attrs = rd.json()["data"]["attributes"]
        assert "title" in attrs


@allure.feature("帖子与评论")
@allure.story("帖子详情")
@allure.title("帖子详情-查询不存在的 id 返回 404")
@allure.severity(P3)
@pytest.mark.post
def test_discussion_not_found(client):
    """帖子详情-不存在的id → 404"""
    with allure.step("请求不存在的帖子 GET /api/discussions/99999999"):
        r = client.get(BASE + "/api/discussions/99999999", timeout=20)
    with allure.step("校验 HTTP 状态码为 404"):
        assert r.status_code == 404


@allure.feature("帖子与评论")
@allure.story("板块标签")
@allure.title("板块标签列表-返回非空数据")
@allure.severity(P1)
@pytest.mark.post
def test_tags_list(client):
    """标签列表 → 200"""
    with allure.step("请求标签列表 GET /api/tags"):
        r = client.get(BASE + "/api/tags", timeout=20)
    with allure.step("校验 HTTP 200 且返回条数大于 0"):
        assert r.status_code == 200
        assert len(r.json().get("data", [])) > 0


@allure.feature("帖子与评论")
@allure.story("发帖")
@allure.title("发帖-选择板块正常发布返回 200/201")
@allure.severity(P0)
@pytest.mark.post
@pytest.mark.write
@pytest.mark.slow
def test_create_discussion(write_client, rand_suffix):
    """发帖-正常（选板块）→ 201（写接口，控频）"""
    title = f"【自动化】接口发帖 {rand_suffix}"
    with allure.step(f"以标题「{title}」+ 板块 id=1 发布新帖"):
        r = write_client.post(BASE + "/api/discussions",
                              json={"data": {"attributes": {"title": title, "content": "pytest 自动化发帖验证"},
                                             "relationships": {"tags": {"data": [{"type": "tags", "id": "1"}]}}}},
                              timeout=25)
    with allure.step("校验 HTTP 200/201 且返回新帖 id"):
        assert r.status_code in (200, 201), f"HTTP {r.status_code} {r.text[:100]}"
        assert r.json()["data"]["id"]
    with allure.step("记录新帖 id（供数据清理脚本核对）"):
        new_id = log_extract("新帖 id（供 cleanup_api_test.py 核对）", r.json()["data"]["id"])
        allure.attach(new_id, "新帖 id", allure.attachment_type.TEXT)


@allure.feature("帖子与评论")
@allure.story("发帖校验")
@allure.title("发帖-空标题返回 400/422 拒绝")
@allure.severity(P2)
@pytest.mark.post
@pytest.mark.write
@pytest.mark.slow
def test_create_discussion_blank_title(write_client, rand_suffix):
    """发帖-空标题 → 422 拒绝（受限流影响标记 xfail）"""
    with allure.step("以空标题提交发帖请求"):
        r = write_client.post(BASE + "/api/discussions",
                              json={"data": {"attributes": {"title": "", "content": "空标题测试"},
                                             "relationships": {"tags": {"data": [{"type": "tags", "id": "1"}]}}}},
                              timeout=25)
    _assert_not_rate_limited(r)
    with allure.step("校验 HTTP 400/422（服务端拒绝空标题）"):
        assert r.status_code in (400, 422), f"HTTP {r.status_code} {r.text[:100]}"


@allure.feature("帖子与评论")
@allure.story("发帖校验")
@allure.title("发帖-不选板块返回 400/422 拒绝")
@allure.severity(P2)
@pytest.mark.post
@pytest.mark.write
@pytest.mark.slow
def test_create_discussion_no_tag(write_client, rand_suffix):
    """发帖-无板块标签 → 422 拒绝（业务规则；受限流影响标记 xfail）"""
    with allure.step("提交不带 tags 关系的发帖请求"):
        r = write_client.post(BASE + "/api/discussions",
                              json={"data": {"attributes": {"title": f"无标签 {rand_suffix}", "content": "test"}}},
                              timeout=25)
    _assert_not_rate_limited(r)
    with allure.step("校验 HTTP 400/422（服务端拒绝无板块发帖）"):
        assert r.status_code in (400, 422), f"HTTP {r.status_code} {r.text[:100]}"


@allure.feature("帖子与评论")
@allure.story("发帖限流")
@allure.title("发帖限流回归-连续发第 2 帖应成功（实际第 2 帖即 429）")
@allure.severity(P2)
@allure.description(
    "缺陷编号：BUG-003（P2 一般）\n"
    "现象：第 1 帖发布成功后，紧接着发第 2 帖即返回 HTTP 429；"
    "限流间隔过长，正常用户连续发帖（如发帖后立即补充说明）会被阻断。\n"
    "预期：连续发第 2 帖应返回 200/201；实际：第 2 帖返回 429。\n"
    "影响：连带阻断 test_create_post_comment / test_create_discussion_blank_title / "
    "test_create_discussion_no_tag 三条写接口用例（运行时标记 xfail）。"
)
@pytest.mark.post
@pytest.mark.xfail(reason="BUG-003: 发帖限流阈值过严——第2帖即429，正常连续发帖被阻断（已知缺陷）",
                   strict=True)
@pytest.mark.write
@pytest.mark.slow
def test_rate_limit_too_strict(write_client):
    """回归 BUG-003：连续发第2帖应成功（实际429）"""
    with allure.step("发布第 1 帖（预期成功，作为限流回归的基线）"):
        r1 = write_client.post(BASE + "/api/discussions",
                               json={"data": {"attributes": {"title": f"限流回归{time.time():.0f}", "content": "x"},
                                              "relationships": {"tags": {"data": [{"type": "tags", "id": "1"}]}}}},
                               timeout=25)
    with allure.step("校验第 1 帖发布成功"):
        assert r1.status_code in (200, 201), f"第1帖失败 {r1.status_code}"
    with allure.step("紧接着发布第 2 帖（已知缺陷：此处返回 429，断言失败 → xfail）"):
        r2 = write_client.post(BASE + "/api/discussions",
                               json={"data": {"attributes": {"title": f"限流回归{time.time():.0f}2", "content": "x"},
                                              "relationships": {"tags": {"data": [{"type": "tags", "id": "1"}]}}}},
                               timeout=25)
    with allure.step("校验第 2 帖也发布成功"):
        assert r2.status_code in (200, 201), f"第2帖即429，限流阈值过严: {r2.text[:60]}"


# --------------------------------------------------------------------------- #
# 评论
# --------------------------------------------------------------------------- #
@allure.feature("帖子与评论")
@allure.story("评论列表")
@allure.title("评论列表-按帖子过滤返回 200")
@allure.severity(P1)
@pytest.mark.comment
def test_list_posts_by_discussion(client):
    """评论列表-按帖子过滤 → 200"""
    with allure.step("先取一条帖子，拿到 discussion id"):
        r = client.get(BASE + "/api/discussions", params={"page[limit]": 1}, timeout=20)
        did = log_extract("discussion_id", r.json()["data"][0]["id"])
    with allure.step(f"按帖子过滤请求评论列表 GET /api/posts?filter[discussion]={did}"):
        rp = client.get(BASE + "/api/posts", params={"filter[discussion]": did, "page[limit]": 5}, timeout=20)
    with allure.step("校验 HTTP 状态码为 200"):
        assert rp.status_code == 200


@allure.feature("帖子与评论")
@allure.story("发表评论")
@allure.title("评论-在已有帖子下正常发表返回 200/201")
@allure.severity(P0)
@pytest.mark.comment
@pytest.mark.write
@pytest.mark.slow
def test_create_post_comment(write_client, rand_suffix):
    """评论-正常 → 201（写接口，控频；受限流影响标记 xfail）"""
    with allure.step("先取一个帖子，作为评论的目标 discussion"):
        rl = record(requests.get(BASE + "/api/discussions", params={"page[limit]": 1}, timeout=20))
        did = log_extract("discussion_id", rl.json()["data"][0]["id"])
    with allure.step(f"向帖子 {did} 发表评论（正文含自动化关键词，便于清理）"):
        r = write_client.post(BASE + "/api/posts",
                              json={"data": {"attributes": {"content": f"pytest 自动化评论 {rand_suffix}"},
                                             "relationships": {"discussion": {"data": {"type": "discussions",
                                                                                        "id": did}}}}},
                              timeout=25)
    _assert_not_rate_limited(r)
    with allure.step("校验 HTTP 200/201（评论发表成功）"):
        assert r.status_code in (200, 201), f"HTTP {r.status_code} {r.text[:100]}"
