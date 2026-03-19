---
name: xray-metrics-analyzer
description: >-
  当用户提到 "分析指标"、"查询 Prometheus 指标"、"Grafana 大盘指标"、"查询 metrics"、
  "指标统计"、"指标对比"、"PQL 查询"、"PromQL"、"查看监控指标"、"xray 指标"、
  "指标趋势"、"指标变化" 时触发此 skill。
  通过 XRay OpenAPI 查询 Grafana/Prometheus 底层存储数据，执行指标统计分析和趋势对比。
version: 1.0.0
---

# XRay Prometheus 指标分析器

通过 XRay OpenAPI 查询 Grafana/Prometheus 底层存储的指标数据，支持 PQL 查询、统计分析、趋势对比。

## 前置条件

- Python 3.8+
- `requests` 库（`pip install requests`）
- 已申请 XRay API Token（[线上申请地址](http://xray.devops.xiaohongshu.com/config/token)）

## 脚本位置

`/Users/zhaohaiyuan/opensource/agent_prompts/skills/xray-metrics-analyzer/scripts/xray_query.py`

## 核心能力

### 1. PQL 查询 + 统计分析（query）

通过 PromQL 查询指标数据，自动计算 avg / max / min / p50 / p90 / p95 / p99 等统计值。

```bash
python /Users/zhaohaiyuan/opensource/agent_prompts/skills/xray-metrics-analyzer/scripts/xray_query.py \
  query \
  --pql 'rate(http_requests_total{app="myapp"}[5m])' \
  --time-range 1h \
  --datasource vms-shequ
```

**参数说明**:

| 参数 | 必选 | 说明 | 示例 |
|------|------|------|------|
| `--pql` | ✅ | PromQL 查询表达式 | `rate(http_requests_total[5m])` |
| `--time-range` | ✅ | 时间范围 | `1h`, `30m`, `2d`, `1w`, 或 `start,end` |
| `--datasource` | 推荐 | VMS 数据源名称 | `vms-shequ` |
| `--app` | 可选 | 应用名（不填 datasource 时必填） | `myapp` |
| `--step` | 可选 | 查询步长（秒），默认自动计算 | `60` |
| `--raw` | 可选 | 输出原始 JSON | 加上即可 |

**时间范围格式**:
- 相对时间: `30m`（最近30分钟）、`1h`、`2d`、`1w`
- 绝对时间: `2024-01-01T00:00:00,2024-01-02T00:00:00`
- Unix 时间戳: `1710000000,1710003600`

### 2. JSON 统计输出（stats）

输出结构化 JSON 统计信息，适合程序消费或进一步处理。

```bash
python /Users/zhaohaiyuan/opensource/agent_prompts/skills/xray-metrics-analyzer/scripts/xray_query.py \
  stats \
  --pql 'node_cpu_seconds_total{mode="idle"}' \
  --time-range 2h \
  --datasource vms-shequ
```

输出格式:
```json
[
  {
    "metric": {"__name__": "node_cpu_seconds_total", "mode": "idle", ...},
    "stats": {
      "count": 120,
      "avg": 0.85,
      "min": 0.72,
      "max": 0.98,
      "p50": 0.86,
      "p90": 0.94,
      "p95": 0.96,
      "p99": 0.97,
      ...
    }
  }
]
```

### 3. 时间段对比（compare）

对比两个时间段的同一指标变化，输出变化率和趋势方向。

```bash
python /Users/zhaohaiyuan/opensource/agent_prompts/skills/xray-metrics-analyzer/scripts/xray_query.py \
  compare \
  --pql 'rate(http_requests_total{app="myapp"}[5m])' \
  --period1 '2024-01-01T00:00:00,2024-01-01T12:00:00' \
  --period2 '2024-01-02T00:00:00,2024-01-02T12:00:00' \
  --datasource vms-shequ
```

也支持相对时间:
```bash
# 对比昨天和今天同时段
python .../xray_query.py compare \
  --pql 'rate(http_latency_seconds_sum[5m])' \
  --period1 2d \
  --period2 1d \
  --datasource vms-shequ
```

### 4. 查询数据源（datasource）

查询可用的 VMS 数据源，帮助用户确定 `--datasource` 参数。

```bash
# 按应用查询
python .../xray_query.py datasource --app myapp

# 按服务查询
python .../xray_query.py datasource --service myservice

# 列出全部数据源
python .../xray_query.py datasource
```

## 工作流程

当用户请求指标分析时，按以下步骤执行：

### 步骤 1: 确认查询参数

向用户确认以下信息（如果用户未提供）：
- **PQL 表达式**: 用户要查询的 PromQL，通常可以直接从 Grafana 面板复制
- **时间范围**: 要查询的时间段
- **数据源**: VMS 数据源名称（如不确定，先用 `datasource` 子命令查询）

### 步骤 2: 执行查询

```bash
python /Users/zhaohaiyuan/opensource/agent_prompts/skills/xray-metrics-analyzer/scripts/xray_query.py \
  query \
  --pql '<用户的PQL>' \
  --time-range '<时间范围>' \
  --datasource '<数据源>'
```

### 步骤 3: 分析结果

根据返回的统计数据，给出分析结论：
- 指标的整体水平（avg）和波动情况（max-min 差距）
- 是否存在尖刺（p99 与 avg 的差距）
- 趋势方向（first vs last）

### 步骤 4（可选）: 时间段对比

如果用户需要对比（如发布前后、日环比、周环比），使用 `compare` 子命令。

## 配置

Token 和 source 通过**环境变量**或**命令行参数**提供，不硬编码在脚本中。

### 环境变量（推荐）

```bash
export XRAY_TOKEN='your-xray-token'       # XRay 平台申请的 Token
export XRAY_SOURCE='your-app-name'         # Token 申请时填写的应用名（调用来源标识）
export XRAY_BASE_URL='http://xray.int.xiaohongshu.com/openapi'  # 可选，默认线上域名
```

建议将上述环境变量写入 `~/.zshrc` 或 `~/.bashrc`。

### 命令行参数

```bash
python xray_query.py --source mysource --token mytoken query ...
```

### 配置项说明

| 配置项 | 环境变量 | 命令行参数 | 说明 |
|--------|----------|------------|------|
| API Token | `XRAY_TOKEN` | `--token` | XRay 平台申请的 Token（[申请地址](http://xray.devops.xiaohongshu.com/config/token)） |
| 调用来源 | `XRAY_SOURCE` | `--source` | 申请 Token 时填写的应用名，用于认证 |
| 基础 URL | `XRAY_BASE_URL` | `--base-url` | 默认 `http://xray.int.xiaohongshu.com/openapi` |

## 使用场景

### 场景 1: 查看服务 QPS
```
用户: "帮我查一下 myapp 最近 1 小时的 QPS"
→ query --pql 'sum(rate(http_requests_total{app="myapp"}[5m]))' --time-range 1h --app myapp
```

### 场景 2: 分析接口延迟
```
用户: "分析一下最近 2 小时 /api/search 接口的 P99 延迟"
→ query --pql 'histogram_quantile(0.99, sum(rate(http_latency_seconds_bucket{path="/api/search"}[5m])) by (le))' --time-range 2h --datasource vms-shequ
```

### 场景 3: 发布前后对比
```
用户: "对比一下发布前后的错误率，发布时间是 2024-03-10 14:00"
→ compare --pql 'sum(rate(http_errors_total[5m]))/sum(rate(http_requests_total[5m]))' \
    --period1 '2024-03-10T12:00:00,2024-03-10T14:00:00' \
    --period2 '2024-03-10T14:00:00,2024-03-10T16:00:00' \
    --datasource vms-shequ
```

### 场景 4: 资源使用分析
```
用户: "查看集群 CPU 使用率的趋势"
→ query --pql 'avg(rate(node_cpu_seconds_total{mode!="idle"}[5m])) * 100' --time-range 6h --datasource vms-infra
```

### 场景 5: 不确定数据源
```
用户: "我不知道数据源叫什么，应用名是 xxx"
→ datasource --app xxx   # 先查数据源
→ query ...               # 再用查到的数据源查询
```

## 输出示例

### query 命令输出
```
查询: rate(http_requests_total{app="myapp"}[5m])
时间: 2024-03-10T10:00:00 ~ 2024-03-10T11:00:00
步长: 15s

共 3 条时间序列

序列 #1: app="myapp", instance="10.0.0.1:8080", method="GET"
    数据点数: 240
    时间范围: 2024-03-10T10:00:00 ~ 2024-03-10T11:00:00 (3600s)
    平均值:   125.3
    最小值:   98.2
    最大值:   203.7
    P50:      121.5
    P90:      158.2
    P95:      175.4
    P99:      198.3
    首个值:   110.2
    末尾值:   132.8

...
```

### compare 命令输出
```
============================================================
指标时间段对比报告
============================================================
PQL: rate(http_requests_total{app="myapp"}[5m])
基准时间段: 2024-03-09T10:00:00 ~ 2024-03-09T11:00:00
对比时间段: 2024-03-10T10:00:00 ~ 2024-03-10T11:00:00

--- 基准时间段 ---
    数据点数: 240
    平均值:   125.3
    ...

--- 对比时间段 ---
    数据点数: 240
    平均值:   142.7
    ...

--- 变化分析 ---
    avg   : 125.3 → 142.7  (↑ 13.89%)
    max   : 203.7 → 245.2  (↑ 20.37%)
    p99   : 198.3 → 231.5  (↑ 16.74%)
============================================================
```

## 注意事项

1. **QPS 限制**: XRay OpenAPI QPS 阈值最大 20，请合理控制查询频次
2. **Ticket 有效期**: 生成的 ticket 有效时间默认 3 分钟，脚本每次请求自动重新生成
3. **数据源**: 如果不填 `--app`，必须指定 `--datasource`；Grafana 上能查到的指标都可以查
4. **大范围查询**: 查询时间范围很大时（>7d），step 会自动增大以避免返回过多数据点

## 故障排除

### 查询无结果
- 检查 PQL 表达式是否正确（可先在 Grafana 中验证）
- 确认数据源名称正确（用 `datasource` 子命令查询）
- 确认时间范围内有数据

### 认证失败 (401/403)
- 检查 Token 是否已审批通过
- 确认 source 名称与申请时一致
- Token 可能已过期，需重新申请

### 网络错误
- 确认可以访问 `http://xray.int.xiaohongshu.com`（需要内网环境）
- 如果是 SIT 环境，改用 `--base-url http://xray.int.sit.xiaohongshu.com/openapi`

## API 参考

详见 [XRay OpenAPI 文档](https://docs.xiaohongshu.com/doc/6673a390cf03cf4f4d6d4bc15eb4e8ad)

## 版本历史

### v1.0.0 (2026-03-19)
- 初始版本
- 支持 PQL 查询 + 自动统计分析
- 支持时间段对比
- 支持数据源查询
- 自动 step 计算
- 支持相对时间和绝对时间格式
