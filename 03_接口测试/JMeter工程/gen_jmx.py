# -*- coding: utf-8 -*-
"""生成 JMeter 性能测试计划 forum_load_test.jmx

结构（2026-09-15 按性能评审意见优化）：
    TestPlan
    └── ThreadGroup（${__P(users,10)} 线程 × ${__P(loops,50)} 循环，ramp-up ${__P(rampup,5)}s）
        ├── HTTP请求默认值        protocol/domain 只声明一次
        ├── OnceOnlyController    1-登录获取Token（每线程只登录一次，TOKEN 供后续循环复用）
        ├── SimpleController      读接口（共用 Token 头，作用域内声明一次）
        │   ├── HeaderManager     全局请求头 Authorization/Accept
        │   └── 2~5 四个读接口     各带 响应码断言 + JSON 结构断言
        └── 聚合报告

踩坑备忘（本项目实测）：
- HeaderManager 必须作为采样器的 hashTree **子节点**，内嵌在 HTTPSamplerProxy 元素内部会报
  ClassCastException（HeaderManager 不能 cast 为 JMeterProperty）。
- 登录发原始 JSON body：HTTPArgument 的 Argument.name 必须留空、postBodyRaw=true，
  否则 JMeter 发成 name=value 表单，Flarum 收不到 identification/password → 401。
- 公共 Token 头**不能**放在 ThreadGroup 层：ThreadGroup 级的配置元件对该组内**所有**采样器生效，
  登录会带上空的 `Authorization: Token `，可能被认证中间件直接拒掉。故用 SimpleController
  把 4 个读接口圈起来，Token 头只在其作用域内声明，登录不在这个作用域里。
- 不加 Think Time 是**有意设计**（最坏情况/峰值吞吐基线），见 性能结果.md；加 1~3s 思考时间
  会让 TPS 从 ~15 掉到 <1，与已交付数据不可比。
- 详情靶点与搜索关键词均为可覆盖参数：默认 /api/discussions/1、关键词 123，
  跨并发档位保持一致；换实例时用 -Jdiscussion_id / -Jkeyword 指定。
"""
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forum_load_test.jmx")

DOMAIN = "${__P(domain,localhost)}"
PROTOCOL = "${__P(protocol,http)}"


def response_code_assertion(name="断言-响应码200"):
    """响应码断言：Equals 200。Apply to 默认 Main sample only。"""
    return f"""
          <ResponseAssertion guiclass="AssertionGui" testclass="ResponseAssertion" testname="{name}" enabled="true">
            <collectionProp name="Asserion.test_strings">
              <stringProp name="200">200</stringProp>
            </collectionProp>
            <stringProp name="Assertion.custom_message"></stringProp>
            <stringProp name="Assertion.test_field">Assertion.response_code</stringProp>
            <boolProp name="Assertion.assume_success">false</boolProp>
            <intProp name="Assertion.test_type">8</intProp>
          </ResponseAssertion>
          <hashTree/>"""


def json_path_assertion(path, name):
    """JSON 断言：只校验路径存在（JSONVALIDATION=false），不校验取值。"""
    return f"""
          <JSONPathAssertion guiclass="JSONPathAssertionGui" testclass="JSONPathAssertion" testname="{name}" enabled="true">
            <stringProp name="JSON_PATH">{path}</stringProp>
            <stringProp name="EXPECTED_VALUE"></stringProp>
            <boolProp name="JSONVALIDATION">false</boolProp>
            <boolProp name="EXPECT_NULL">false</boolProp>
            <boolProp name="INVERT">false</boolProp>
            <boolProp name="ISREGEX">true</boolProp>
            <boolProp name="EXPECT_EMPTY">false</boolProp>
          </JSONPathAssertion>
          <hashTree/>"""


def http_sampler(name, method, path, comment="", assertions=()):
    """读接口采样器：不写 domain/protocol（由 HTTP 请求默认值提供），不写 HeaderManager
    （由所在的 SimpleController 作用域内那个全局请求头提供）。"""
    return f"""
          <HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="{name}" enabled="true">
            <elementProp name="HTTPsampler.Arguments" elementType="Arguments" guiclass="HTTPArgumentsPanel" testclass="Arguments" testname="用户定义的变量">
              <collectionProp name="Arguments.arguments"/>
            </elementProp>
            <stringProp name="HTTPSampler.path">{path}</stringProp>
            <stringProp name="HTTPSampler.method">{method}</stringProp>
            <boolProp name="HTTPSampler.follow_redirects">true</boolProp>
            <boolProp name="HTTPSampler.use_keepalive">true</boolProp>
            <stringProp name="HTTPSampler.postBodyRaw">false</stringProp>
            <stringProp name="HTTPSampler.comment">{comment}</stringProp>
          </HTTPSamplerProxy>
          <hashTree>
            {response_code_assertion()}
            {''.join(json_path_assertion(p, n) for p, n in assertions)}
          </hashTree>"""


# ---- 登录采样器（POST 原始 JSON body + 提取 Token + 断言）----
login_sampler = f"""
          <HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="1-登录获取Token" enabled="true">
            <elementProp name="HTTPsampler.Arguments" elementType="Arguments">
              <collectionProp name="Arguments.arguments">
                <elementProp name="" elementType="HTTPArgument">
                  <boolProp name="HTTPArgument.always_encode">false</boolProp>
                  <stringProp name="Argument.value">{{"identification":"${{__P(user,testuser)}}","password":"${{__P(pwd,)}}"}}</stringProp>
                  <stringProp name="Argument.metadata">=</stringProp>
                  <boolProp name="HTTPArgument.use_equals">true</boolProp>
                  <stringProp name="Argument.name"></stringProp>
                </elementProp>
              </collectionProp>
            </elementProp>
            <stringProp name="HTTPSampler.path">/api/token</stringProp>
            <stringProp name="HTTPSampler.method">POST</stringProp>
            <boolProp name="HTTPSampler.follow_redirects">true</boolProp>
            <boolProp name="HTTPSampler.use_keepalive">true</boolProp>
            <boolProp name="HTTPSampler.postBodyRaw">true</boolProp>
          </HTTPSamplerProxy>
          <hashTree>
            <HeaderManager guiclass="HeaderPanel" testclass="HeaderManager" testname="Headers-Login" enabled="true">
              <collectionProp name="HeaderManager.headers">
                <elementProp name="Content-Type" elementType="Header">
                  <stringProp name="Header.name">Content-Type</stringProp>
                  <stringProp name="Header.value">application/json</stringProp>
                </elementProp>
              </collectionProp>
            </HeaderManager>
            <hashTree/>
            <JSONPostProcessor guiclass="JSONPostProcessorGui" testclass="JSONPostProcessor" testname="提取Token" enabled="true">
              <stringProp name="JSONPostProcessor.referenceNames">TOKEN</stringProp>
              <stringProp name="JSONPostProcessor.jsonPathExprs">$.token</stringProp>
              <stringProp name="JSONPostProcessor.matchNumbers">1</stringProp>
              <stringProp name="JSONPostProcessor.defaultValues">NONE</stringProp>
              <stringProp name="JSONPostProcessor.match_numbers"></stringProp>
            </JSONPostProcessor>
            <hashTree/>
            {response_code_assertion()}
            {json_path_assertion("$.token", "断言-返回token")}
          </hashTree>"""

# ---- 读接口（断言只校验"200 且结构正确"，避免把 HTML 错误页当成功）----
s_home = http_sampler("2-浏览首页帖子列表", "GET", "/api/discussions?page[limit]=10", "读接口-主链路",
                      [("$.data", "断言-返回结构含data")])
s_detail = http_sampler("3-查看帖详情", "GET", "/api/discussions/${__P(discussion_id,1)}", "读接口-帖详情",
                        [("$.data", "断言-返回结构含data")])
s_search = http_sampler("4-搜索关键词", "GET", "/api/discussions?filter[q]=${__P(keyword,123)}", "读接口-搜索",
                        [("$.data", "断言-返回结构含data")])
s_tags = http_sampler("5-板块标签", "GET", "/api/tags", "读接口-标签",
                      [("$.data", "断言-返回结构含data")])

jmx = f"""<?xml version="1.0" encoding="UTF-8"?>
<jmeterTestPlan version="1.2" properties="5.0" jmeter="5.6.3">
  <hashTree>
    <TestPlan guiclass="TestPlanGui" testclass="TestPlan" testname="社区论坛-读接口并发压测" enabled="true">
      <stringProp name="TestPlan.comments">仅压读接口（发帖写接口限流过严，BUG-003）；登录每线程仅一次（OnceOnlyController），不在循环内</stringProp>
      <boolProp name="TestPlan.functional_mode">false</boolProp>
      <boolProp name="TestPlan.tearDown_on_shutdown">true</boolProp>
      <boolProp name="TestPlan.serialize_threadgroups">false</boolProp>
      <elementProp name="TestPlan.user_defined_variables" elementType="Arguments" guiclass="ArgumentsPanel" testclass="Arguments">
        <collectionProp name="Arguments.arguments"/>
      </elementProp>
    </TestPlan>
    <hashTree>
      <ThreadGroup guiclass="ThreadGroupGui" testclass="ThreadGroup" testname="读接口并发用户" enabled="true">
        <stringProp name="ThreadGroup.on_sample_error">continue</stringProp>
        <elementProp name="ThreadGroup.main_controller" elementType="LoopController" guiclass="LoopControlPanel" testclass="LoopController" testname="循环控制器" enabled="true">
          <boolProp name="LoopController.continue_forever">false</boolProp>
          <stringProp name="LoopController.loops">${{__P(loops,50)}}</stringProp>
        </elementProp>
        <stringProp name="ThreadGroup.num_threads">${{__P(users,10)}}</stringProp>
        <stringProp name="ThreadGroup.ramp_time">${{__P(rampup,5)}}</stringProp>
        <boolProp name="ThreadGroup.same_user_on_next_iteration">true</boolProp>
        <boolProp name="ThreadGroup.scheduler">false</boolProp>
        <stringProp name="ThreadGroup.duration"></stringProp>
        <stringProp name="ThreadGroup.delay"></stringProp>
      </ThreadGroup>
      <hashTree>
        <ConfigTestElement guiclass="HttpDefaultsGui" testclass="ConfigTestElement" testname="HTTP请求默认值" enabled="true">
          <elementProp name="HTTPsampler.Arguments" elementType="Arguments" guiclass="HTTPArgumentsPanel" testclass="Arguments" testname="用户定义的变量">
            <collectionProp name="Arguments.arguments"/>
          </elementProp>
          <stringProp name="HTTPSampler.domain">{DOMAIN}</stringProp>
          <stringProp name="HTTPSampler.port"></stringProp>
          <stringProp name="HTTPSampler.protocol">{PROTOCOL}</stringProp>
          <stringProp name="HTTPSampler.contentEncoding"></stringProp>
        </ConfigTestElement>
        <hashTree/>
        <OnceOnlyController guiclass="OnceOnlyControllerGui" testclass="OnceOnlyController" testname="仅一次-登录" enabled="true"/>
        <hashTree>
          {login_sampler}
        </hashTree>
        <GenericController guiclass="LogicControllerGui" testclass="SimpleController" testname="读接口（共用Token头）" enabled="true"/>
        <hashTree>
          <HeaderManager guiclass="HeaderPanel" testclass="HeaderManager" testname="全局请求头-读接口" enabled="true">
            <collectionProp name="HeaderManager.headers">
              <elementProp name="Authorization" elementType="Header">
                <stringProp name="Header.name">Authorization</stringProp>
                <stringProp name="Header.value">Token ${{TOKEN}}</stringProp>
              </elementProp>
              <elementProp name="Accept" elementType="Header">
                <stringProp name="Header.name">Accept</stringProp>
                <stringProp name="Header.value">application/json</stringProp>
              </elementProp>
            </collectionProp>
          </HeaderManager>
          <hashTree/>
          {s_home}
          {s_detail}
          {s_search}
          {s_tags}
        </hashTree>
        <ResultCollector guiclass="StatVisualizer" testclass="ResultCollector" testname="聚合报告" enabled="true">
          <boolProp name="ResultCollector.error_logging">false</boolProp>
          <objProp>
            <name>saveConfig</name>
            <value class="SampleSaveConfiguration">
              <time>true</time><latency>true</latency><timestamp>true</timestamp>
              <success>true</success><label>true</label><code>true</code><message>true</message>
              <threadName>true</threadName><dataType>true</dataType><encoding>false</encoding>
              <assertions>true</assertions><subresults>true</subresults><responseData>false</responseData>
              <samplerData>false</samplerData><xml>false</xml><fieldNames>true</fieldNames>
              <responseHeaders>false</responseHeaders><requestHeaders>false</requestHeaders>
              <responseDataOnError>false</responseDataOnError><saveAssertionResultsFailureMessage>true</saveAssertionResultsFailureMessage>
              <assertionsResultsToSave>0</assertionsResultsToSave><bytes>true</bytes><sentBytes>true</sentBytes>
              <threadCounts>true</threadCounts><idleTime>true</idleTime><connectTime>true</connectTime>
            </value>
          </objProp>
          <stringProp name="filename">${{__P(resultfile,results.jtl)}}</stringProp>
        </ResultCollector>
        <hashTree/>
      </hashTree>
    </hashTree>
  </hashTree>
</jmeterTestPlan>
"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(jmx)
print(f"已生成 JMX: {OUT}")
