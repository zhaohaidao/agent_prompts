# Design Doc Conventions (2026-02-01)

本规范用于指导本仓库各子项目的“概要设计/详细设计”文档撰写。核心原则：设计文档是**面向读者与风险**的沟通产物，而不是模板填空。

## 1. 总体原则

- **Audience-first**: 先写清目标读者（new contributor / reviewer / infra integrator / ops）。
- **Risk-driven**: 哪些地方最可能返工/出错，就把哪些地方前置讲清。
- **Minimal but complete**: 宁可少写不关键的“百科内容”，也要把关键约束与不变量说透。
- **No dead sections**: 不要保留“本节不适用”的空章节；不相关就直接删。

## 2. 文档类型

### 2.1 High-Level Design (HLD)
HLD 用于快速建立系统心智模型与评审共识。

- 本质：**意图与边界的契约**（What/Why/Where）。
- 重点：系统边界、运行模型、一级组件、关键数据/控制流、关键决策与权衡、主要风险与验证。
- 不追求：覆盖所有子系统细节。

### 2.2 Detailed Design (DD)
DD 用于指导实现与代码评审。

- 本质：**实现与验证的契约**（How/Proof）。
- 重点：组件内部结构、接口契约、状态机/算法、错误处理、性能策略、配置、测试计划、迁移/兼容。
- 要求：能回答“怎么实现、怎么验证、怎么演进”。

### 2.3 HLD 与 DD 的关系（推荐写法）

- HLD 给出“骨架与约束”（边界、一级组件、关键不变量、关键决策）；DD 在骨架内补齐“可实现性与可验证性”。
- DD 过程中一旦发现 HLD 的关键假设不成立，应回推更新 HLD，避免出现两套真相。
- 对大型系统建议分层：全局 HLD 只保留跨边界决策；子系统用 DD 或子系统 HLD 深入。
- 评审关注点分工：HLD 先过边界与关键决策，DD 再过接口契约、状态机/并发、测试与演进。

### 2.4 写到什么程度算够（避免“模板填空”）

- 读者能在 5 分钟内回答：系统做什么、怎么跑、边界在哪里、最大的风险是什么。
- HLD 的场景（Scenarios）优先覆盖“最常发生/最昂贵”的关键路径。
- DD 的细节以“契约与验证”为准：只写能指导实现与测试的细节，避免复制整段实现代码。

## 3. 文档头部元信息（必填）

建议在正文前统一包含：版本、日期、作者、状态、目标读者、范围。

```text
Version: 1.0
Date: 2026-02-01
Author: <name>
Status: Draft|Review|Accepted
Audience: <who>
Scope: <in/out>
```

## 4. HLD 核心内容（必含检查清单）

HLD 不需要固定章节名，但应覆盖以下问题：

1) **Goals / Non-goals**: 解决什么、不解决什么。
2) **System Boundary**: 上下游是谁、集成点是什么、信任/一致性边界在哪里。
3) **Execution Model**: 这是库还是服务？进程/线程/协程模型？状态与生命周期？
4) **Component Model**: 2-6 个一级组件的职责边界与依赖方向。
5) **Core Data Model**: 关键实体、生命周期、关键不变量。
6) **Critical Flows (+1 Scenarios)**: 1-3 条主流程串起组件交互（建议用时序图/流程图）。
7) **Key Decisions & Trade-offs**: 为什么这么做，替代方案为何不选。
8) **Risks & Validation**: 主要风险点、验证策略与测试入口。

## 5. 可选横切章节（按触发条件选择）

以下主题**不是 HLD 的固定章节**，只有在它们是架构约束/风险源/跨团队接口时才在 HLD 单独成章，否则折叠进“约束/风险/运行模型”。

- **Language/FFI**: 存在跨语言边界，且影响 API 语义、内存/生命周期、性能、调试或发布（ABI）时。
- **Concurrency/Distributed**: 并发/分布式是正确性或可扩展性的关键约束时（并发模型、不变量、通信模式、一致性边界）。
- **Fault tolerance / Reliability**: 系统承担运行期可靠性责任（恢复/降级/一致性保障）时。
- **Performance**: 性能目标明确且依赖架构策略（hot path、缓存、并行度、瓶颈）。
- **Security**: 输入边界、权限模型、敏感数据与隔离要求显著时。
- **Observability**: 需要统一的指标/日志/trace 语义与关键维度时。
- **Configuration & Compatibility**: 配置矩阵复杂、版本/ABI/序列化兼容敏感时。

## 6. 4+1 视图作为覆盖面检查（不是强制目录）

使用 4+1 视图确保覆盖面，但不强制每个视图单独成章：

- **Logical view**: 核心抽象/领域模型/职责边界（通常对应 HLD 的 component + data model）。
- **Development view**: 代码组织、模块依赖、构建产物、插件点（常对应目录结构与包依赖说明）。
- **Process view**: 进程/线程/协程、并发与通信、性能/可靠性关键路径（按需前置）。
- **Physical view**: 部署拓扑、设备/驱动/运行时依赖（对 infra/ops 读者很重要时）。
- **Scenarios (+1)**: 用关键用例串联上述视图，验证设计能跑通并暴露缺口。

### 6.1 “整体架构”章节推荐写法（单屏总览）

- 本节用“组件/运行时/依赖/代码组织/关键场景”五个视角给出单屏架构总览；每个视角只保留能帮助评审与集成决策的信息，细节在后续章节或 DD 展开。
- 为了让读者快速建立心智模型，FlexKV 更适合按“分层 + 控制面/数据面”理解（依赖方向自上而下，跨层交互以显式接口与 graph/callback 表达）：
- 下面用一张边界图把两种模式放在一起，突出控制面/数据面分工与可选分布式依赖：

提示：这五个视角可以自然映射到 4+1（组件=Logical，运行时=Process，依赖=Physical，代码组织=Development，关键场景=Scenarios），但不要求把“视图”作为章节标题写出来。

## 7. 表达与落地要求

- 图示优先：架构图、时序图、状态机图；默认使用 ASCII；仅在明确约定渲染环境支持 Mermaid 时使用 Mermaid。
- 关键契约要可验证：列出对应的测试入口、指标、日志点。
- 关联代码要可定位：用路径指向关键目录/模块（例如 `torch/`, `aten/`, `c10/`）。
- 维护成本可控：DD 中代码片段仅用于澄清契约/算法，不要复制整段实现。

## 8. Review/Acceptance Checklist

- 读者能在 5 分钟内回答：系统做什么、怎么跑、哪里是边界与风险。
- 关键流程有图或清晰的步骤描述。
- 关键不变量/错误语义/兼容约束被明确写出。
- 测试与验证策略可执行（命令或用例路径明确）。
- 非适用内容已删除，无空章节。

## 9. Change Log

- 2026-02-01: Clarify HLD vs DD as contracts; add relationship guidance and "how much is enough" heuristics.
- 2026-02-01: Add recommended one-page "Architecture Overview" structure; prefer ASCII diagrams by default.
