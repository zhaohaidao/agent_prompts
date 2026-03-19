# XRay 指标分析器 - 快速开始

## 最简单的用法

只需一句话：
```
帮我查一下 myapp 最近 1 小时的 QPS
```

Skill 会自动：
1. ✅ 构造 PromQL 查询
2. ✅ 调用 XRay OpenAPI 获取数据
3. ✅ 计算统计值（avg/max/min/p50/p90/p95/p99）
4. ✅ 输出分析结论

## 常见使用场景

### 场景 1: 查看服务指标

**用户说**:
```
查一下 myapp 最近 1 小时的请求量
```

**执行命令**:
```bash
python scripts/xray_query.py query \
  --pql 'sum(rate(http_requests_total{app="myapp"}[5m]))' \
  --time-range 1h \
  --app myapp
```

### 场景 2: 分析延迟分布

**用户说**:
```
分析一下最近 2 小时 /api/search 的延迟
```

**执行命令**:
```bash
python scripts/xray_query.py query \
  --pql 'histogram_quantile(0.99, sum(rate(http_latency_seconds_bucket{path="/api/search"}[5m])) by (le))' \
  --time-range 2h \
  --datasource vms-shequ
```

### 场景 3: 发布前后对比

**用户说**:
```
对比发布前后的错误率，发布时间是 2024-03-10 14:00
```

**执行命令**:
```bash
python scripts/xray_query.py compare \
  --pql 'sum(rate(http_errors_total{app="myapp"}[5m])) / sum(rate(http_requests_total{app="myapp"}[5m]))' \
  --period1 '2024-03-10T12:00:00,2024-03-10T14:00:00' \
  --period2 '2024-03-10T14:00:00,2024-03-10T16:00:00' \
  --datasource vms-shequ
```

### 场景 4: 不知道数据源

**用户说**:
```
我要查 myapp 的指标，但不知道数据源叫什么
```

**先查数据源**:
```bash
python scripts/xray_query.py datasource --app myapp
```

**再查指标**:
```bash
python scripts/xray_query.py query \
  --pql '...' \
  --time-range 1h \
  --datasource <查到的数据源>
```

### 场景 5: 获取原始数据

**用户说**:
```
把原始数据导出来，我要自己分析
```

**执行命令**:
```bash
# 原始 JSON
python scripts/xray_query.py query \
  --pql 'up{app="myapp"}' \
  --time-range 30m \
  --app myapp \
  --raw

# 结构化统计 JSON
python scripts/xray_query.py stats \
  --pql 'up{app="myapp"}' \
  --time-range 30m \
  --app myapp
```

## 触发关键词

Skill 会在检测到以下关键词时自动激活：
- "查询指标" / "分析指标"
- "Grafana 大盘" / "Prometheus 指标"
- "PQL 查询" / "PromQL"
- "指标统计" / "指标对比" / "指标趋势"
- "查看监控" / "xray 指标"

## 参数速查

### 时间范围
| 格式 | 示例 | 说明 |
|------|------|------|
| `Nm` | `30m` | 最近 N 分钟 |
| `Nh` | `1h` | 最近 N 小时 |
| `Nd` | `2d` | 最近 N 天 |
| `Nw` | `1w` | 最近 N 周 |
| `start,end` | `2024-01-01T00:00:00,2024-01-02T00:00:00` | 精确范围 |

### 子命令
| 命令 | 用途 |
|------|------|
| `query` | PQL 查询 + 统计输出 |
| `stats` | PQL 查询 + JSON 统计 |
| `compare` | 两个时间段对比 |
| `datasource` | 查询可用数据源 |
