# Fluss Datum 使用经验总结（消费侧/写入侧）

日期：2026-02-12  
主题：C++ 侧 `Datum` 在 Fluss 中的职责、边界与最佳实践

## 1. 核心认知

- `Datum` 是字段值容器（value carrier），不是 schema 定义对象。
- schema 决定逻辑类型；`DatumType` 决定当前值在 FFI 中如何解释。
- 当前 Fluss 公共类型体系无 `UINT*` 逻辑类型，C++ 的 `UInt*` 是兼容入口。

## 2. 消费侧经验

### 2.1 先看 `DatumType`，再取值

- 严格按 `d.type` 分支读取：`Int32` 读 `i32_val`，`Int64` 读 `i64_val`，`String` 读 `string_val`。
- `Null` 必须单独处理，避免默认值污染业务语义。

### 2.2 无符号字段反解规则（按 schema 解释）

- `UInt8` 逻辑字段：消费到 `DatumType::Int16`
- `UInt16` 逻辑字段：消费到 `DatumType::Int32`
- `UInt32` 逻辑字段：消费到 `DatumType::Int64`
- `UInt64` 逻辑字段：消费到 `DatumType::Int64`

### 2.3 必做范围检查

- 先校验非负与上界，再做 `static_cast`。
- 禁止裸转：负值或越界必须走错误路径（告警/丢弃/失败）。

### 2.4 列表与嵌套

- `List` 按元素 `Datum` 递归处理。
- 元素类型校验要与 schema 对齐，避免“容器通过、元素错型”。

## 3. 写入侧经验

### 3.1 用 `SetXxx` / `Datum::Xxx` 封装

- 不要手工拼 `DatumType + value`。
- 无符号输入优先使用 `Datum::UInt*` 或 `row.SetUInt*`，让框架执行扩位映射。

### 3.2 无符号写入映射

- `UInt8 -> Int16`
- `UInt16 -> Int32`
- `UInt32 -> Int64`
- `UInt64 -> Int64`（要求 `<= i64::MAX`）

### 3.3 `UInt64` 边界策略

- 超过 `i64::MAX` 会失败（overflow）。
- 若业务确实需要全量 `u64`，应改 schema 承载方式（如 `DECIMAL/STRING/BYTES`）。

## 4. 常见误区

- 误区1：把 `DatumType` 当 schema 类型。
  - 纠正：`DatumType` 是 runtime value tag。
- 误区2：认为消费侧还能还原“原始无符号类型”。
  - 纠正：需要依赖 schema 语义反解，`Datum` 本身不保留原始 `UInt*` 标签。
- 误区3：写入侧直接把 `uint32_t` 塞进 `Int32`。
  - 纠正：会溢出风险，必须走 `UInt32 -> Int64` 路径。

## 5. 推荐实践清单

- 写入前：按 schema 建立字段级转换函数（含边界检查）。
- 消费时：按 schema + `DatumType` 双重校验读取。
- 桥接层：对 `UInt64` 超界单独统计与告警。
- 回归测试：覆盖 `0`、上界、越界、负值、Null、List 嵌套。

## 6. 一句话结论

`Datum` 负责值承载与跨语言传递；无符号兼容靠“扩位到有符号”实现，业务必须在消费侧按 schema 做反解与边界校验，在写入侧走统一封装入口避免隐式溢出。
