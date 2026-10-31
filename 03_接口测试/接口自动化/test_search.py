# -*- coding: utf-8 -*-
"""接口自动化-搜索模块（含中文搜索失效已知缺陷 BUG-001）

Allure：本文件全部用例 @allure.feature = 「搜索」。
severity 取值 P0–P3，口径对齐《01_测试计划》§8 缺陷等级定义，映射表见 conftest.py 顶部注释。

注意：Flarum 的 filter[q] 匹配「标题 + 正文」，判定命中是否合理时必须取正文核对，
不能只看标题就判「误命中」——本项目已因此差点误报一次（查 1234 命中标题「软件测试」，
实际该帖正文确实含 1234）。
"""
import allure
import pytest

from conftest import BASE, P1, P3

pytestmark = pytest.mark.search


def _search(client, q):
    with allure.step(f"调用搜索接口 GET /api/discussions?filter[q]={q}"):
        r = client.get(BASE + "/api/discussions",
                       params={"filter[q]": q, "page[limit]": 10}, timeout=20)
    return r


@allure.feature("搜索")
@allure.story("数字关键词搜索")
@allure.title("搜索-数字关键词『123』返回结果")
@allure.severity(P1)
def test_search_number(client):
    """搜索-数字关键词『123』→ 有结果"""
    with allure.step("以『123』为关键词搜索"):
        r = _search(client, "123")
    with allure.step("校验 HTTP 200 且命中条数大于 0"):
        assert r.status_code == 200
        assert len(r.json().get("data", [])) > 0


@allure.feature("搜索")
@allure.story("英文关键词搜索")
@allure.title("搜索-英文关键词『abc』命中且命中项标题确含该关键词")
@allure.severity(P1)
def test_search_english(client):
    """搜索-英文关键词『abc』→ 命中数≥1，且至少一条命中项标题确含该关键词"""
    with allure.step("以『abc』为关键词搜索"):
        r = _search(client, "abc")
    with allure.step("校验 HTTP 200 且命中条数大于 0"):
        assert r.status_code == 200
        data = r.json().get("data", [])
        assert len(data) > 0, "搜索英文关键词『abc』应返回结果（线上存在含 abc 的标题）"
    with allure.step("校验至少一条命中项标题确实包含『abc』（真比较，防止返回无关数据也算通过）"):
        titles = [d["attributes"].get("title", "") for d in data]
        assert any("abc" in t.lower() for t in titles), \
            f"命中项标题均不含关键词『abc』，搜索结果与关键词不符: {titles[:5]}"


@allure.feature("搜索")
@allure.story("中文关键词搜索")
@allure.title("搜索-中文关键词『接口』应命中帖子但返回 0 条")
@allure.severity(P1)
@allure.description(
    "缺陷编号：BUG-001（P1 严重）\n"
    "现象：搜索接口 filter[q] 传中文关键词『接口』返回 0 条，"
    "而论坛中确实存在标题含该词的帖子（帖 345 标题为『接口测试』）。\n"
    "预期：命中数 ≥ 1；实际：返回 0 条。\n"
    "对照：同一接口传数字『123』、英文『abc』均能正常命中，故判定为中文检索"
    "（分词/编码处理）缺陷，而非「确实没有匹配内容」。"
)
@pytest.mark.xfail(reason="BUG-001: 中文搜索失效——『接口』应有结果但返回0条（已知缺陷）",
                   strict=True)
def test_search_chinese(client):
    """搜索-中文关键词『接口』→ 应命中帖345『接口测试』（已知缺陷：0条）"""
    with allure.step("以『接口』为关键词搜索"):
        r = _search(client, "接口")
    with allure.step("校验 HTTP 200"):
        assert r.status_code == 200
    with allure.step("校验命中条数大于 0（已知缺陷：实际 0 条，断言失败 → xfail）"):
        data = r.json().get("data", [])
        assert len(data) > 0, "搜索『接口』应返回结果但为0条（中文搜索失效）"


@allure.feature("搜索")
@allure.story("中文关键词搜索")
@allure.title("搜索-中文关键词『测试』应命中帖子但返回 0 条")
@allure.severity(P1)
@allure.description(
    "缺陷编号：BUG-001（P1 严重）\n"
    "现象：搜索接口 filter[q] 传中文关键词『测试』返回 0 条，"
    "而论坛中存在大量标题/正文含该词的帖子。\n"
    "预期：命中数 ≥ 1；实际：返回 0 条。\n"
    "本条与 test_search_chinese 是同一缺陷的第二个中文样本，用于确认并非个例。"
)
@pytest.mark.xfail(reason="BUG-001: 中文搜索失效——『测试』应有结果但返回0条（已知缺陷）",
                   strict=True)
def test_search_chinese2(client):
    """搜索-中文关键词『测试』→ 应命中测试相关帖（已知缺陷：0条）"""
    with allure.step("以『测试』为关键词搜索"):
        r = _search(client, "测试")
    with allure.step("校验 HTTP 200"):
        assert r.status_code == 200
    with allure.step("校验命中条数大于 0（已知缺陷：实际 0 条，断言失败 → xfail）"):
        data = r.json().get("data", [])
        assert len(data) > 0, "搜索『测试』应返回结果但为0条（中文搜索失效）"


@allure.feature("搜索")
@allure.story("无结果搜索")
@allure.title("搜索-不存在的关键词返回 200 空列表且不报错")
@allure.severity(P3)
def test_search_nonexistent(client):
    """搜索-不存在关键词 → 200 返回空，不报错"""
    with allure.step("以不存在的关键词『zzzznonexist999』搜索"):
        r = _search(client, "zzzznonexist999")
    with allure.step("校验 HTTP 200 且 data 为空列表（不报错、不返回无关数据）"):
        assert r.status_code == 200
        assert r.json().get("data") == []
