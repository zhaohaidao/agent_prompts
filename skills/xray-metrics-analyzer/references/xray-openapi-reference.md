# XRay OpenAPI 接口参考

**文档来源**: https://docs.xiaohongshu.com/doc/6673a390cf03cf4f4d6d4bc15eb4e8ad

## 1. 访问域名

| 环境 | 域名 |
|------|------|
| 线上 | `http://xray.int.xiaohongshu.com/openapi` |
| SIT | `http://xray.int.sit.xiaohongshu.com/openapi` |
| 海外 | `http://xray.int.rednote.life/openapi` |

## 2. 认证方式

### 生成 Ticket

规则: `base64(${source}&${token}&${timestamp_ms})`

- `source`: 来源应用名称，不能为空
- `token`: XRay 平台申请的 Token，需审批通过
- `timestamp_ms`: 当前时间戳（毫秒），ticket 有效期 3 分钟

### 传参方式

HTTP Header: `xray_ticket: <ticket_value>`

### Token 申请

- SIT: http://xray.devops.sit.xiaohongshu.com/config/token
- PROD: http://xray.devops.xiaohongshu.com/config/token
- QPS 阈值最大 20

## 3. 接口列表

### 3.1 根据应用获取 VMS 数据源

```
GET /openapi/application/metric/datasource/get?app=${app}
```

### 3.2 根据服务获取 VMS 数据源

```
GET /openapi/application/metric/datasource/get/service?service=${service}
```

### 3.3 获取全部 VMS 数据源列表

```
GET /openapi/application/metric/datasource/list
```

### 3.4 通过 PQL 查询数据详情（核心接口）

```
POST /openapi/application/metric/data/query_range/v1
```

**请求参数**:

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| `pql` | string | ✅ | PromQL 查询表达式 |
| `start` | long | ✅ | 开始时间（Unix 秒） |
| `end` | long | ✅ | 结束时间（Unix 秒） |
| `step` | int | 可选 | 步长（秒） |
| `app` | string | 可选 | 应用名（不填须指定 datasource） |
| `datasource` | string | 可选 | VMS 数据源名称 |
| `metric` | string | 可选 | 指标名 |
| `system` | bool | 可选 | 是否系统指标 |
| `format` | bool | 可选 | 是否格式化精度（false 不设置） |

**注意**: 
- 只要在 Grafana 上能查到的指标，都可以通过此 API 查到
- 不支持 `query/v1` 接口（仅支持 `query_range/v1`）
- 需选择正确的 VMS 数据源

## 4. 返回格式

返回 Prometheus 标准格式：

```json
{
  "status": "success",
  "data": {
    "resultType": "matrix",
    "result": [
      {
        "metric": {
          "__name__": "http_requests_total",
          "app": "myapp",
          "instance": "10.0.0.1:8080"
        },
        "values": [
          [1710000000, "125.3"],
          [1710000060, "130.1"],
          ...
        ]
      }
    ]
  }
}
```

其中 `values` 中每个元素为 `[unix_timestamp, "string_value"]`。
