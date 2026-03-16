# Bazel Build Modes & Fluss Integration - 2026-02-09

## 背景
在 `ris` 与 `red-fluss-rust` 联调中，出现了“以为是 release，实际跑的是 debug”以及“环境变量已设置但行为不符合预期”的排查问题。

## 关键经验

### 1) `bazel_dep` 默认是源码模块，不是预编译二进制
- `bazel_dep(name = "red-fluss-rust", version = "rc-0.0.14.8")` 拉取的是模块源码版本。
- 构建时会按当前 `compilation_mode` 重新分析/构建依赖。
- 因此发布流程用了 release，并不代表下游默认消费 release 产物。

### 2) 构建模式必须显式指定
- Release:
  - `bazel build -c opt //ris/tools/fluss_reader:fluss_reader`
- Debug:
  - `bazel build -c dbg //ris/tools/fluss_reader:fluss_reader`
- 不应依赖 `.bazelrc` 默认值或历史习惯。

### 3) 用 `cquery` 校验“到底链接了哪种库”
- Debug 校验（应看到 `rust_lib_debug.a`）：
  - `bazel cquery "deps(@red-fluss-rust//bindings/cpp:rust_lib,1)" --compilation_mode=dbg`
- Release 校验（应看到 `rust_lib_release.a`）：
  - `bazel cquery "deps(@red-fluss-rust//bindings/cpp:rust_lib,1)" --compilation_mode=opt`

### 4) 本地改动与远端模块版本要分清
- `ris` 依赖 `@red-fluss-rust` 时，不会自动使用本地 `fluss-rust` 工作区改动。
- 若要验证本地改动，使用 `local_path_override` 指向本地源码。

### 5) 环境变量排查要分三层
1. 调用方进程是否设置成功（`setenv` 后 `getenv` 打印）
2. Rust 侧是否读取该变量（必要时加启动日志打印 resolved config）
3. 最终行为是否一致（例如下载路径是否落到指定目录）

### 6) `--config=release` 不等于自动 `opt`
- 如果 `.bazelrc` 有全局 `build --compilation_mode=dbg`，且 `build:release` 只加了 `--copt=-O3 --copt=-DNDEBUG`，那么 `--config=release` 仍可能是 `dbg`。
- 这种情况下会出现“模式是 debug，但 C/C++ 额外带了 release 风格 flags”的混合态，Rust 侧仍可能选到 debug 分支。

### 7) 推荐配置：标准 release 与 release_with_debug 分离
- 建议在 `ris/.bazelrc` 显式声明模式，而不是只靠 `copt`：

```bazelrc
build:debug --compilation_mode=dbg

build:release --compilation_mode=opt
build:release --host_compilation_mode=opt

build:release_with_debug --compilation_mode=opt
build:release_with_debug --host_compilation_mode=opt
build:release_with_debug --strip=never
build:release_with_debug --copt=-g
build:release_with_debug --cxxopt=-g
build:release_with_debug --action_env=CARGO_PROFILE_RELEASE_DEBUG=2
```

- 说明：
  - `release`：追求纯发布行为，便于线上性能对齐。
  - `release_with_debug`：保留发布优化，同时保留调试符号用于排障。
  - 是否强制 `-O3` 应单独决策；`opt` 已可提供稳定发布基线，避免过早引入额外变量。

## 推荐执行清单
- 固化两条命令：
  - `bazel build -c opt ...`
  - `bazel build -c dbg ...`
- 固化配置化命令：
  - `bazel build --config=release ...`
  - `bazel build --config=release_with_debug ...`
- 每次联调前跑一次 `cquery deps(...,1)` 进行模式校验。
- 若定位“本地改动未生效”，优先检查是否缺少 `local_path_override`。
- 若定位“环境变量未生效”，按“设置 -> 读取 -> 行为”三层逐级验证。

## 一句话结论
在 Bazel 体系里，“版本号一致”不等于“二进制一致”；要保证结果可控，必须显式指定模式并用 `cquery` 验证最终依赖解析。
