# Fluss Rust Cpp Bazel Troubleshooting Notes (2026-02-24)

## Scope

本总结覆盖 `fluss-rust` C++ Bazel 接入在 `source` consumer example 与 `build` mode（Bazel 构建 Arrow C++）推进过程中遇到的主要问题、根因、验证方法与临时/长期修复策略。

## Troubleshooting Principles

1. 分层定位：先判断失败发生在 `bzlmod` 解析、外部仓库拉取、构建动作执行、链接、还是运行时加载阶段。
2. 不要被表面日志误导：`Analyzing...`、`timeout` 文本、`pb` 相关触发点不一定是根因。
3. 每次只改变一个变量（registry / lockfile / proxy / toolchain / strategy）。
4. 记录“已越过的失败层级”，避免重复回退到已解决假设。

## Failure Layers and Lessons

### 1. Rust Cache / glibc Mismatch (Cargo Reuse Issue)

#### Symptom

`cargo build` 触发的 build-script/proc-macro 在 Bazel action 中运行失败，报 `GLIBC_*` / `GLIBCXX_*` 缺失。

#### Root Cause

复用了在更高 glibc 环境构建的 Rust `target/` 缓存，Bazel 的 genrule 在当前环境加载旧产物失败。

#### Fix

1. `cargo clean`（最直接）
2. 或删除相关 `target/debug/build/*` / `deps/*.so` 缓存

#### Lesson

当 Bazel action 内部调用 Cargo 且复用 workspace `target/` 时，要警惕跨环境缓存污染。

### 2. `protoc` Missing for `prost-build`

#### Symptom

`fluss-rs` Rust build script 报 `Could not find protoc`。

#### Root Cause

`prost-build` 需要 `protoc`，但 Bazel action 环境未提供。

#### Fix Path Chosen

先尝试 Bazel-managed `@protobuf//:protoc`，后因版本/工具链兼容问题回退到 host `protoc`。

#### Stable Practice

1. `bindings/cpp/BUILD.bazel` genrule 支持优先读取 `PROTOC` env
2. `bazel run/build` 时显式透传 `--action_env=PROTOC=...`

### 3. Bazel-managed `protoc` (`protobuf` module) Compatibility Issues

#### Symptoms

1. `protobuf@27.0` 在 GCC8 下编译 tool 失败（warning promoted to error）
2. 强 pin `protobuf@21.7` 后，`rules_java/rules_cc` 依赖的 protobuf Bazel labels 不兼容

#### Root Cause

`protobuf` 作为 Bazel module 引入后，会进入 Bazel rules/toolchain 兼容矩阵；版本与 GCC/toolchains/rules 组合不稳定。

#### Decision

回退到 host `protoc`，先打通主路径。将 `protobuf_version` 的治理语义放在 `protoc` 版本上。

### 4. Missing Arrow C++ Bazel Dependency Modeling

#### Symptom

`bindings/cpp/src/table.cpp` 编译失败：`arrow/c/bridge.h` not found。

#### Root Cause

`bindings/cpp/BUILD.bazel` 中 `cc_library(name = "fluss_cpp")` 未声明 Arrow C++ 头文件/库依赖。

#### Fix

为 `fluss_cpp` 显式依赖 Arrow Bazel target（后续演进为稳定 alias）。

### 5. `rules_foreign_cc` and Toolchain Setup Complexity (Build Mode)

#### Observation

使用 `rules_foreign_cc + cmake(...)` 构建 Arrow C++ 时，需要引入：

1. `rules_foreign_cc`
2. `rules_python`
3. CMake/Ninja toolchains
4. foreign_cc framework toolchains

#### Lesson

这些是构建实现细节，不应暴露在最终用户面向的 `MODULE.bazel` 接口层。

### 6. Registry and Metadata Confusion (`module not found`)

#### Symptoms

`module not found in registries: rules_foreign_cc@...` / `apple_support@...`

#### Key Lesson

`curl` 到 `MODULE.bazel` 文件存在，不代表 Bazel 解析一定成功。Bazel 首先依赖 registry metadata (`metadata.json`) 和本地缓存状态。

#### Practical Checks

1. `curl https://bcr.bazel.build/modules/<module>/metadata.json`
2. `bazel clean --expunge`
3. 检查 `MODULE.bazel.lock`
4. 使用 `--ignore_all_rc_files` + `--lockfile_mode=off` 做隔离验证

### 7. `rules_foreign_cc` Prebuilt Ninja ABI Mismatch

#### Symptom

预编译 `ninja` 无法启动，报 `GLIBCXX_*` / `CXXABI_*` 缺失。

#### Root Cause

`rules_foreign_cc` 提供的 `ninja` 与容器运行时 `libstdc++` ABI 不兼容。

#### Fix

将 Arrow CMake generator 从 `Ninja` 切到 `Unix Makefiles`。

#### Lesson

在老基础镜像（如 devtoolset-8 / EL7）上，优先选择 `Unix Makefiles` 作为临时稳定路径。

### 8. Arrow Bundled Third-Party Toolchain (`EP_CMAKE_RANLIB`) Failure

#### Symptom

Arrow CMake configure 报 `Could not find EP_CMAKE_RANLIB ... :`

#### Root Cause

`rules_foreign_cc` 传入空的 `CMAKE_RANLIB`，Arrow bundled dependency toolchain 在该环境下解析失败。

#### Fix

在 Arrow `cmake(cache_entries=...)` 中显式设置：

1. `EP_CMAKE_RANLIB`
2. `EP_CMAKE_AR`
3. `EP_CMAKE_NM`

#### Technical Debt

当前使用 devtoolset-8 绝对路径，仅为临时 workaround。应改为可配置或 PATH-based。

### 9. Network / Proxy in `linux-sandbox` for Arrow Third-Party Downloads

#### Symptoms

Arrow `jemalloc_ep` / `xsimd_ep` 下载失败，报 DNS 或 proxy connect failure。

#### Root Cause Variants

1. 代理未透传到 Bazel action
2. 代理变量错误（容器内 `127.0.0.1`）
3. `linux-sandbox` 网络路径与容器 shell 不一致

#### Practical Fixes

1. 显式传 `--repo_env` + `--action_env`（http/https/no_proxy 全套）
2. 清理 `ALL_PROXY`
3. 必要时将 `CcCmakeMakeRule` / bootstrap actions 改为 `local`

### 10. Arrow `config.h` Compile Failure from Bazel Redacted Builtin Macros

#### Symptom

Arrow `config.cc` 编译失败：

1. `stray '\\' in program`
2. `operator""redacted`

#### Root Cause

Bazel 为可复现构建注入 `-D__DATE__=\"redacted\"` 等宏，Arrow 15 在生成 `ARROW_CXX_COMPILER_FLAGS` 字符串时转义处理不兼容，形成 `\\"redacted\\"` 并破坏 C/C++ 字符串字面量。

#### Fix

在 Arrow `http_archive` 解压后 patch `cpp/src/arrow/util/config.h.cmake`，将：

`#define ARROW_CXX_COMPILER_FLAGS "@CMAKE_CXX_FLAGS@"`

替换为：

`#define ARROW_CXX_COMPILER_FLAGS ""`

#### Impact

仅影响 Arrow 暴露的编译参数元信息字符串，不影响功能行为。

### 11. Runtime Linker Failure after Successful Build (`libarrow.so.1500`)

#### Symptom

`bazel run` 时二进制启动失败：

`libarrow.so.1500: cannot open shared object file`

#### Root Cause

`rules_foreign_cc` `cmake(...)` 仅声明 `out_shared_libs = ["libarrow.so"]`，但运行时 SONAME 依赖是 `libarrow.so.1500`（以及真实文件版本）。

#### Fix

在 `out_shared_libs` 中补齐 Linux 下的 SONAME / real file：

1. `libarrow.so`
2. `libarrow.so.1500`
3. `libarrow.so.1500.2.0`

#### Lesson

第三方共享库接入 Bazel 时，需同时考虑 link name 和 runtime SONAME。

### 12. `Analyzing ... (0/0)` and `Analyzing ... (44/644)` Long Stalls

#### Observation

1. `0/0` 常见于 bzlmod/repo mapping/external repo 前置阶段
2. `44/644` 固定很久说明分析阶段重（不一定是错误）
3. 偶发情况下可能是 Bazel server 状态异常导致“看似卡住”

#### Practical Handling

1. 排障时使用 `--ignore_all_rc_files` / `--lockfile_mode=off`
2. 常规跑通后恢复 lockfile，减少每次重新解析
3. 怀疑 server 状态异常时：
   - `bazel shutdown`
   - `bazel --batch ...`

## Diagnostic Checklist (Recommended Order)

1. 确认失败层级
   - bzlmod / fetch / analyze / compile / link / runtime
2. 搜索第一条 `ERROR:` 前后 30-80 行
3. 对 `rules_foreign_cc` 问题查看：
   - `Environment:` 段
   - `_____ BEGIN BUILD LOGS _____`
4. 对运行时问题查看：
   - `ldd bazel-bin/<target>`
   - Bazel runfiles/solib symlink targets
5. 对分析阶段卡住：
   - `bazel shutdown`
   - `--batch`
   - `--nobuild` 区分分析 vs 执行

## Recommended Long-Term Direction

1. 将 `registry` 模式作为主路径（用户仅写 `bazel_dep(...)`）
2. 将 `build` 模式复杂实现隐藏在 module extension 中
3. `system` 模式作为快速接入备选
4. `protobuf_version` 在当前阶段主要映射 `protoc` 版本治理
5. 为 `rules_foreign_cc` / Arrow 的 workarounds 明确注释和退出条件（何时可以删除）

