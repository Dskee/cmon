# cmon — 淘宝商品与竞品监控 Agent（实现版）

把《贺梦阳-淘宝商品与竞品监控Agent方案-27届》那套设计落成一个能跑的单机系统。
运行时零第三方依赖，只用标准库（sqlite3 / urllib / tomllib / dataclasses / argparse）。

## 一句话定位

可控的采集调度器：三层限流、三层去重、五态状态机、故障注入可复现，附一个竞品分析的落地用例。

真正被验证的是"调度"和"判定"这两层，不是"能不能把网页抓下来"。抓取是适配器，
换成真实接口只需要重写一个类；调度和判定换不掉，所以它们有测试。

## 现状

能跑：

- 五套场景端到端跑通，一条命令出告警卡片和日报
- 82 个测试（限流、去重、状态机、到手价还原、判定边界、模型契约、HTTP 层）
- 故障注入实验，现跑现出数字，写在 `var/out/experiments.md`

没验证：

- 真实淘宝接口。没有开放平台权限，也拿不到能合规调用的竞品字段
- 真实模型往返。请求能打到硅基流动并被受理，但账户余额不足返回 402，
  所以只验证到"协议通"，没验证"回答好"。离线替身覆盖同一套 JSON 契约，
  `python experiments/llm_smoke.py` 有余额时会打印真实延迟与解析结果

这两条不是遗漏，是刻意的边界：没验证的事就不写成验证过。

## 为什么没有爬虫

数据源是自建的 `MockTaobaoSource`，接口契约照开放平台的字段口径写，能按脚本注入降价 / 改标题 /
换主图 / 加差评，也能注入 429 / 403 / 验证码 / 空响应 / 超时。

只有可控的源才能做可复现的故障注入。用真站做实验，等于把"偶发的一次超时"当成"系统性验证"。

## 为什么不用 LangChain

这条链路里模型只出现在一个位置：把判定出来的 evidence 翻译成运营看得懂的一段话，输入输出都是
结构化 JSON。chain / memory / retriever / tool-use 一个都用不上，换来的是排查要穿透三层封装、
以及框架自带的隐式重试会破坏"同一份证据给出同一个建议"这个前提。

FastAPI 用了，但只在 HTTP 层，且 API 层不参与判定——它不产生新数字。

## 跑起来

```bash
python -m cmon demo                       # 列出可用场景
python -m cmon run --scenario price-drop  # 跑一遍降价场景，打印完整 trace
python -m cmon run --scenario mixed --offline
python -m cmon report                     # 汇总指标
```

`--offline` 走本地替身，不调模型，全链路照样跑通。演示现场没网也不怕。

测试与实验：

```bash
python -m pytest -q                       # 82 个测试
python experiments/fault_injection.py     # 五个场景跑一遍，出数字
python experiments/llm_smoke.py           # 真实模型冒烟（没余额会明确说明）
```

HTTP 层：

```bash
python -m cmon.api                        # 起在 127.0.0.1:8000
curl -X POST localhost:8000/runs -H "content-type: application/json" -d "{\"scenario\":\"price-drop\"}"
curl localhost:8000/runs/<run_id>
curl "localhost:8000/alerts?item_id=C8848"
curl -N "localhost:8000/stream?run_id=<run_id>"
```

`POST /runs` 立刻返回 `run_id`，不在请求里跑完——这一条比端点数量重要。

## 实测数字

| 场景 | 模拟窗口 | 请求数 | 实测峰值 QPS | 跨租户去重 | 事件 | 模型调用 | 自动暂停 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `price-drop` | 28h | 70 | 2 | 12.5% | 2 | 3 | 0 |
| `fault-storm` | 14h | 41 | 2 | 12.8% | 0 | 0 | 4 |
| `empty-silent` | 8h | 28 | 2 | 12.5% | 0 | 0 | 0 |
| `title-change` | 8h | 28 | 2 | 12.5% | 3 | 4 | 0 |
| `mixed` | 16h | 48 | 2 | 12.7% | 6 | 8 | 4 |

峰值 QPS 是实测值，不是配置值：令牌桶只保证平均速率，峰值靠事后统计 1 秒滑窗得出。
跨租户去重 12.5% 对应"一个商品平均被 1.14 个租户盯上"，方案里假设的平台级池子是 1.43，对应 30%——
公式是 `1 - 1/k`，拿到真实池子数据只需要换 k。

另外两个数字不是跑出来的，是设计出来的：价格 2 小时一档（一天 8 次），
事件判定要求"连续两次采样都低于基线"，所以采样间隔和持续阈值都取 2 小时，这不是巧合。

## 目录

```
config/settings.toml   频率表、阈值、限流、暂停策略、模型配置
cmon/clock.py          可注入时钟（模拟时间，让"持续 2 小时"能秒级验证）
cmon/mock/             假淘宝：基线数据、事件脚本、故障注入开关
cmon/collect/          限流 / 去重 / 五态状态机 / 采集计划
cmon/normalize/        到手价还原、快照归一化、标题词表归一化
cmon/judge/            事件判定（纯规则，不调模型）
cmon/analyze/          模型解释 + JSON 契约校验（可 stub）
cmon/output/           告警卡片、日报
cmon/api.py            HTTP 层（四个端点，不参与判定）
tests/                 82 个测试
experiments/           故障注入实验、真实模型冒烟
```

## 配置里最该看的六个值

| 配置 | 值 | 为什么是这个值 |
| --- | --- | --- |
| `collect.global_qps` | 2.0 | 16 小时窗口摊 2.1 万请求，平均 0.36 QPS，留 5 倍余量给峰值 |
| `collect.item_min_interval_min` | 30 | 同一商品半小时内不重复打扰，抖动避开整点机器特征 |
| `collect.dedup.ttl_min` | 90 | 小于价格周期的一半，保证不会把上一轮的结果当成这一轮的 |
| `collect.pause.item_fail_streak` | 3 | 连续三次失败按暂定性故障处理，再多就是在加速被封 |
| `judge.sustain_hours` | 2 | 等于价格采样间隔，等价于"连续两次采样都低于基线" |
| `judge.cooldown_hours` | 24 | 同一商品同类事件一天只提醒一次，否则运营会开始无视告警 |

## 边界

- 不爬登录态页面。要读登录态就得有账号，商家自己的账号只能看自己家，看别人家就要用别处来的账号
- 不做销量预测。竞品销量拿不到，算出来的数会看起来很像真的，这是最危险的一种错
- 竞品到手价是推算的，误差带 ±3%，卡片上标了 `error_band`，不假装是精确值
- 每一次运行都是确定性的：同一场景跑两遍，指标完全一致，测试里有这一条