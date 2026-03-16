# Fluss Remote Scan 性能优化可复用经验（2026-02-10）

## 1. 目标与适用范围

本文总结 Fluss 客户端在远程日志回溯消费场景中的性能优化经验，重点覆盖以下手段：

- Release 发布构建
- Block-level 解压缩
- 关闭本地写盘（内存承载）
- 流式并发下载
- 并行解码
- 其他高收益优化

适用场景：`hours-ago` 回溯、bucket 数较多、远程对象存储读取、Arrow 解码路径。

## 2. 优化前统一基线（必须先固定）

在做任何优化前，必须固定以下基线条件，避免结论失真：

- 相同数据区间（同一回溯起点与持续时间）
- 相同 bucket 集合（例如固定 1 或固定 4）
- 相同机器规格与负载背景
- 相同构建产物来源（同一 commit）
- 相同采样窗口（建议 5 分钟主窗口 + 30 秒预热）

核心指标建议统一采集：

- 业务吞吐：`rows_per_s`、`mb_per_s`、`throughput r/s`、`mbps`
- 解码：`avg_decode_ms`、`decode_util`、`read_pct`
- 下载：`remote_dl_mb_per_s`、`remote_dl_rtt_ms`、`remote_dl_read_ms`、`remote_dl_wait_ms`
- 队列与并发：`remote_dl_queue_max`、`remote_dl_inflight_max`、`decode_queue_max`
- 资源：CPU、内存 RSS、磁盘 util、网络带宽

## 3. 方案 1：Release 发布构建

### 3.1 问题与场景

问题：Debug/非优化构建在 Arrow decode、LZ4 解压、循环处理路径上有明显额外开销。

场景：CPU 密集型 decode 已成为主瓶颈，`avg_decode_ms` 高、`rows_per_s` 低。

### 3.2 优化措施

- 统一使用优化构建链路，确保 Rust 侧走 `Cargo release profile`。
- Bazel 侧避免“`compilation_mode=dbg` + release copt 混搭”造成 C++/Rust 优化级别不一致。
- 若要保留可调试性，采用 release + debuginfo，而不是直接回退 debug。

### 3.3 风险与边界

- 调试体验下降（变量可见性、栈形态变化）。
- 构建时间增加。

### 3.4 消融实验设计

- A 组：debug 构建
- B 组：release 构建
- 其余参数完全一致
- 连续运行至少 3 轮，比较中位数与 P95

验收阈值建议：

- `rows_per_s` 提升显著
- `avg_decode_ms` 明显下降
- 无正确性回归

## 4. 方案 2：Block-level 解压缩

### 4.1 问题与场景

问题：压缩格式/解压路径选择不当会放大 CPU 开销，尤其在高吞吐回溯中。

场景：`read_pct` 接近 100%，并且 decode CPU 占比高。

### 4.2 优化措施

- 使用 `FLUSS_LZ4_MODE=block` 走 block-level 解压路径。
- 启动日志中确认 LZ4 mode 已生效。

### 4.3 风险与边界

- 需要确认生产数据编码与读取模式兼容。
- 格式切换应在固定回放数据上先做一致性校验。

### 4.4 消融实验设计

- A 组：`FLUSS_LZ4_MODE=frame`
- B 组：`FLUSS_LZ4_MODE=block`
- 其余参数完全一致，固定 release 构建

验收阈值建议：

- `avg_decode_ms` 下降
- `mb_per_s` 提升
- 数据校验一致

## 5. 方案 3：关闭本地写盘（内存承载）

### 5.1 问题与场景

问题：下载后写本地文件会引入 `write` 与 `sync` 开销，磁盘 util 高时可能成为主瓶颈。

场景：`remote_dl_write_ms` / `remote_dl_sync_ms` 高，或磁盘 util 接近满载。

### 5.2 优化措施

- 设置 `FLUSS_SCANNER_REMOTE_LOG_STORE_IN_MEMORY=1`。
- 让下载结果直接驻留内存，避免落地文件写入与同步。

### 5.3 风险与边界

- 内存占用与 `prefetch_num * segment_size` 近似线性相关。
- 当 segment 为 1GB 时，`prefetch_num` 需要严格受控，否则 OOM 风险高。

### 5.4 消融实验设计

- A 组：`store_in_memory=0`
- B 组：`store_in_memory=1`
- 在相同 `prefetch_num`、`download_threads` 下对比

验收阈值建议：

- `remote_dl_write_ms` 与 `remote_dl_sync_ms` 接近 0
- 吞吐提升且 RSS 在安全水位内

## 6. 方案 4：流式并发下载

### 6.1 问题与场景

问题：单连接或低并发下载无法吃满对象存储带宽，导致下载 RTT 偏高、等待时间偏大。

场景：`remote_dl_read_ms` 高、`remote_dl_wait_ms` 高、`remote_dl_inflight_max` 未打满。

### 6.2 优化措施

- 启用流式读取：`scanner_remote_log_streaming_read=true`
- 设置单文件流式并发：`scanner_remote_log_streaming_read_concurrency=4`（起点）
- 配置全局下载并发：`scanner_remote_log_download_threads`
- 配置预取深度：`scanner_remote_log_prefetch_num`

参数分工原则：

- `download_threads`：全局并发下载任务上限
- `prefetch_num`：可同时持有的 segment 上限（也是内存/磁盘占用硬上限之一）
- `streaming_read_concurrency`：单 segment 内部并发

### 6.3 风险与边界

- 并发过高可能触发对象存储限流或抖动。
- 内存模式下，`prefetch_num` 过深会迅速放大内存。

### 6.4 消融实验设计

分两阶段：

- 阶段一（形态）：streaming off vs on
- 阶段二（强度）：`streaming_concurrency` 取 `1/2/4/8`，再扫 `download_threads` 与 `prefetch_num`

验收阈值建议：

- `remote_dl_mb_per_s` 提升
- `remote_dl_wait_ms` 下降
- 无异常重试放大

## 7. 方案 5：并行解码

### 7.1 问题与场景

问题：下载提速后，decode 阶段可能成为新瓶颈。

场景：`decode_queue_max` 增长、`avg_decode_ms` 高、CPU 尚有可用核心。

### 7.2 优化措施

- 设置 `FLUSS_SCANNER_DECODE_THREADS=4` 作为起始值。
- 根据 CPU 与 `decode_queue_*` 指标调整为 `2/4/8`。

### 7.3 风险与边界

- 线程过多会导致调度开销和缓存竞争。
- 与下载并发叠加时可能产生 CPU 峰值争抢。

### 7.4 消融实验设计

- A 组：`decode_threads=0`（串行）
- B/C/D：`decode_threads=2/4/8`
- 保持下载参数不变

验收阈值建议：

- `avg_decode_ms` 下降
- 总吞吐提升
- `decode_queue_wait_ms` 下降或稳定

### 7.5 并行解码流水线接入优化（records 路径）

#### 7.5.1 问题机制

在 records 消费路径中，即使 decode worker 已并行工作，也可能因为消费侧接入方式不当而“看起来并行、实际低效”：

- 情况 A：`decode_inflight > 0` 但 `pending_decoded` 还未到达时，`fetch_records` 直接空返回，触发上层高频 `poll` 空转（busy poll）。
- 情况 B：每次只取很少 decoded 结果，无法把并行产出摊平到 records loop，固定路径开销（调度、状态检查、merge）被重复支付。

#### 7.5.2 针对性优化措施

- 增加“有 inflight 则短等待一个结果”策略：
  - 当 `pending_decoded` 为空且 `decode_inflight > 0` 时，阻塞等待短窗口（例如 `recv_timeout(5ms)`）接收一条 decode 结果，避免空转。
- 增加 `ready_decoded_batches` 本地队列：
  - 一次批量获取多个 decoded batch，随后在 records loop 中连续消费，降低每次 poll 的固定开销占比。
- 让 records 路径复用 decoded `RecordBatch`：
  - 通过 `from_record_batch` / `drain_to` 直接走批量迭代，减少逐条冷路径调用与分支跳转。

#### 7.5.3 预期效果与判定信号

有效优化后，通常会看到：

- `records_per_s` 明显上升（典型可达 2x 级别提升，取决于数据与机器）。
- `empty_ok_calls` 显著下降。
- `avg_rust_poll_ms` 与 `poll_collect_avg_ms` 同步下降。
- `decode_inflight_max`、`decode_queue_max` 的利用更稳定，不再频繁“有 inflight 但无可消费结果”。

#### 7.5.4 风险与边界

- `recv_timeout` 设得过大可能抬高低负载时延；设得过小可能重新引入空转。
- `ready_decoded_batches` 过深会增加内存占用，应与 `prefetch_num` 和 batch size 联合约束。
- 必须保持 decoded 结果按序消费（`decode_expected_seq`），避免 offset 语义回归。

### 7.6 标准消融模板（并行解码流水线）

#### 7.6.1 实验目标

验证“并行解码流水线接入优化”是否在相同数据与相同资源前提下稳定提升吞吐，同时不引入正确性回归。

#### 7.6.2 固定条件（必须一致）

- 固定 commit 与构建模式（release）
- 固定数据区间（相同 start timestamp 与运行时长）
- 固定 bucket 集合（例如固定 4 buckets）
- 固定下载参数（`download_threads/prefetch_num/streaming_concurrency`）
- 固定观测窗口（建议 5 分钟，含 30 秒预热）

#### 7.6.3 实验矩阵

| Case | Pipeline Variant | decode_threads | max_poll_records | 预期 |
|---|---|---:|---:|---|
| A1 | Baseline（优化前） | 1 | 500 | 作为基线 |
| A2 | Optimized（优化后） | 1 | 500 | 吞吐显著上升 |
| B1 | Baseline（优化前） | 4 | 500 | 并行但可能空转 |
| B2 | Optimized（优化后） | 4 | 500 | 并行收益充分释放 |
| C1 | Optimized（优化后） | 4 | 1000 | 评估批次上限影响 |

#### 7.6.4 采集指标

- 吞吐：`records_per_s`、`avg_rust_poll_ms`
- 消费路径：`poll_collect_avg_ms`、`poll_record_loop_pct`、`poll_record_next_pct`
- decode 管线：`decode_inflight_max`、`decode_queue_max`
- 下载侧：`remote_dl_mb_per_s`、`remote_dl_inflight_max`
- 空轮询：`empty_ok_calls`

#### 7.6.5 验收门槛

- 主目标：`records_per_s` 相比基线提升 >= 50%
- 次目标：`avg_rust_poll_ms` 明显下降，`empty_ok_calls` 不上升
- 约束：无 offset 乱序、无重复消费、无异常错误率上升

#### 7.6.6 结论记录模板

| Case | records_per_s | avg_rust_poll_ms | empty_ok_calls | remote_dl_mb_per_s | 结论 |
|---|---:|---:|---:|---:|---|
| A1 |  |  |  |  |  |
| A2 |  |  |  |  |  |
| B1 |  |  |  |  |  |
| B2 |  |  |  |  |  |
| C1 |  |  |  |  |  |

#### 7.6.7 判定规则

- 若 A2/B2 均达到门槛，则该优化可进入默认配置候选。
- 若仅 B2 达标，则说明收益依赖并行 decode 线程，应按部署规格分层启用。
- 若 C1 提升不明显且延迟上升，保持 `max_poll_records=500` 作为默认值。

## 8. 其他高收益优化（按优先级）

### 8.1 参数按 bucket 数分层

问题：1 bucket 与多 bucket 的最优并发参数差异大。

措施：在调用层按订阅 bucket 数注入不同环境变量（已在 RIS 侧落地）。

### 8.2 限制 prefetch 深度优先于盲目加线程

问题：内存模式下，内存风险主要由 `prefetch_num` 决定，而非 `download_threads`。

措施：先控 `prefetch_num`，再提 `download_threads`。

### 8.3 统一指标窗口与口径

问题：不同窗口会导致 `rows_per_s` 与 `decode_util` 解释偏差。

措施：统一统计窗口，所有对比实验使用同一窗口长度和同一日志采样频率。

### 8.4 Segment 大小策略

问题：单 segment 过大（如 1GB）会放大失败重试成本与内存峰值。

措施：在允许范围内评估更小 segment（例如 256MB/512MB）对延迟与稳定性的平衡。

## 9. 严格消融实验规范（后续执行）

### 9.1 实验矩阵

最小建议矩阵：

- Build: `debug` vs `release`
- LZ4: `frame` vs `block`
- Storage: `file` vs `memory`
- Streaming: `off` vs `on`
- Streaming concurrency: `1/2/4/8`
- Download threads: `3/4/8`
- Prefetch num: `4/8/12`
- Decode threads: `0/2/4/8`

### 9.2 执行规则

- 单次实验固定 5 分钟有效窗口（外加 30 秒预热）
- 每组至少重复 3 次
- 对比中位数 + P95，不只看单次峰值
- 任意优化必须同时满足：吞吐提升、资源可控、正确性无回归

### 9.3 输出模板

每次实验至少输出：

- 配置快照（构建模式 + 全部 env）
- 吞吐指标
- 下载指标
- 解码指标
- 资源指标
- 结论（通过/不通过）

## 10. 当前建议默认组合（可作为起点）

在多 bucket 回溯场景，建议从以下组合起步再微调：

- release 构建
- `FLUSS_LZ4_MODE=block`
- `FLUSS_SCANNER_REMOTE_LOG_STORE_IN_MEMORY=1`（前提：内存预算充足）
- `FLUSS_SCANNER_REMOTE_LOG_STREAMING_READ=true`
- `FLUSS_SCANNER_REMOTE_LOG_STREAMING_READ_CONCURRENCY=4`
- `FLUSS_SCANNER_REMOTE_LOG_DOWNLOAD_THREADS=8`
- `FLUSS_SCANNER_REMOTE_LOG_PREFETCH_NUM=12`
- `FLUSS_SCANNER_DECODE_THREADS=4`

若 segment=1GB，优先先降低 `prefetch_num` 再提其它并发。

## 11. 当前分支校准与必要分析（2026-02-11）

### 11.1 当前分支实现校准（以代码为准）

当前分支：`perf/records-decode-single-thread`。

关键实现状态：

- `scanner_decode_threads` 在 `LogFetcher::new` 中被固定为 `1usize`（单线程 decode）。
- `max_poll_records` 已支持通过 `FLUSS_SCANNER_MAX_POLL_RECORDS` / `FLUSS_MAX_POLL_RECORDS` 配置，默认 500。
- records 路径已包含并行解码接入优化框架（`wait_one_decode_result`、`ready_decoded_batches`、`drain_to`），即使 decode 线程固定为 1，也复用了该消费路径。

这意味着：当前版本更接近“单线程 decode + 低固定开销 records loop”基线，不是“并行 decode 默认开启”的形态。

### 11.2 基于最新指标的假设与验证（按概率排序）

#### 假设 1（最高概率）

**瓶颈在 `poll_record_next` 热路径本身，而不是调度/offset 检查。**

证据（来自最新 `scanner_metrics`）：

- `poll_record_loop_pct ≈ 99.9% ~ 100%`
- `poll_record_next_pct ≈ 99.8% ~ 99.9%`
- `poll_offset_check_pct ≈ 0%`
- `poll_merge_pct/poll_send_fetches_pct ≈ 0%`

结论：`fetch_records` 的主耗时已收敛到逐条推进路径（`iter.drain_to` 内部的 `reader.read + ScanRecord::new` 等），其他阶段不是当前主矛盾。

#### 假设 2（中概率）

**当前窗口中下载侧并非主瓶颈，但并发利用仍不稳定。**

证据：

- `remote_dl_inflight_max` 常见为 `2`（配置上限更高时也未持续打满）。
- 但 `remote_dl_mb_per_s` 仍有 `200~800+ MB/s` 区间，且 `poll_collect` 并未频繁等待下载返回。

结论：此时“下载不够快”不是首要矛盾；优先级低于 `poll_record_next` 热路径优化。

#### 假设 3（中低概率但高收益）

**`max_poll_records=500` 引入了明显“每 poll 固定成本”，形成吞吐上限。**

证据：

- `poll_collect_calls` 在 5 秒窗口通常 `150~190` 次；
- 即使单次 `poll_collect_avg_ms` 约 `25~29ms`，也会因为高调用频率重复支付固定路径成本。

结论：这是最直接且低风险的下一步杠杆，应先做 AB（500/1000/2000/4000）。

### 11.3 当前分支的优化优先级（建议执行顺序）

1. **先做 `max_poll_records` AB**  
   在当前单线程 decode 下扫描 `500/1000/2000/4000`，观察 `records_per_s`、`avg_rust_poll_ms`、尾延迟与内存。

2. **再做 `poll_record_next` 微观热点剖析**  
   细分 `reader.read`、`ColumnarRow` 构造、`ScanRecord` 构造占比，确认是否存在可去除的拷贝/Arc clone/重复边界检查。

3. **最后回到 decode 并行度 AB**  
   以“单线程最优参数”为基线，再比较 `decode_threads=1/2/4` 的增益与稳定性，避免把阶段性瓶颈混淆为下载瓶颈。

### 11.4 当前分支下的最小可执行消融矩阵

| Case | decode_threads | max_poll_records | 目的 |
|---|---:|---:|---|
| S1 | 1 | 500 | 当前基线 |
| S2 | 1 | 1000 | 验证固定开销摊薄收益 |
| S3 | 1 | 2000 | 继续验证吞吐弹性 |
| S4 | 1 | 4000 | 观察收益拐点与内存/延迟代价 |
| P1 | 2 | S2/S3 最优值 | 验证并行 decode 净增益 |
| P2 | 4 | S2/S3 最优值 | 验证扩展上限与稳定性 |

判定标准（建议）：

- 主指标：`records_per_s` 提升幅度
- 约束：`empty_ok_calls` 不恶化、错误率不升高、内存可控
- 解释指标：`poll_record_next_pct` 是否下降，`remote_dl_inflight_max` 是否随消费提升而自然上升
