# Bazel Troubleshooting Practices (Bzlmod + Multi-Workspace)

## Purpose
This document captures **practical troubleshooting patterns** for Bazel projects using Bzlmod, especially when builds must work both locally (subdirectory workspace) and for downstream consumers (external repository root). The multi-workspace topic is one section among several, not the core.

## 1) First-Response Checklist (Triage in 5 Minutes)
- **Read the exact label in the error**: is it `@repo//...` or `//...`? This usually tells you which workspace root is being used.
- **Confirm workspace root**: `bazel info workspace` and `pwd` in the same shell.
- **Check module graph**: `bazel mod graph | head -n 80` to see module names and versions.
- **Check repository mapping**: `bazel mod graph | rg "your-module"` to ensure expected module name/version.
- **Verify external repo content**: `bazel query @your-module//...` or inspect the downloaded repo in `$(bazel info output_base)/external/`.

## 2) Label Resolution Pitfalls (Most Common Root Cause)
**Symptom**: `no such package '@@repo//proto'` or `//proto` works locally but fails downstream.

**Cause**: `//...` always resolves from the current workspace root.

**Fix patterns**:
- Use repository-aware labels with `native.repository_name()`.
- Avoid hardcoding `//proto` or `//bindings/cpp/proto` if both roots must be supported.

## 3) Bzlmod Module Resolution Failures
**Symptom**: `No repository visible as '@rules_cc'` or wrong version warnings.

**Checks**:
- Root `MODULE.bazel` exists and is correct.
- `bazel_dep(name=..., version=...)` declared for each external label referenced in BUILD files.
- `repo_name` matches actual label usage.

**Fix patterns**:
- Add missing `bazel_dep` in root `MODULE.bazel`.
- Align `repo_name` and label usage (do not mix `@protobuf` and `@com_google_protobuf`).
- Use explicit overrides only when unavoidable, and document them for downstream users.

## 4) Patch Overrides Are Not Transitive
**Symptom**: Patch fixes work locally but fail in downstream builds.

**Cause**: `single_version_override` applies only in the module graph where it is declared.

**Fix patterns**:
- Prefer local compatibility fixes instead of patching external deps.
- If a patch is mandatory, document that downstreams must add the same override.

## 5) CI vs Local Environment Gaps
**Symptom**: `protoc not found` in CI but works locally.

**Checks**:
- Does `build.rs` read `PROTOC`? Is it exported in Bazel genrules?
- Are `PATH`, `PROTOC`, `RUSTUP_HOME`, `CARGO_HOME` aligned between Bazel and Cargo?

**Fix patterns**:
- Export `PROTOC` explicitly in genrule commands.
- Pin toolchains in CI; avoid relying on system binaries.

## 6) Artifact Completeness and Publishing
**Symptom**: Downstream builds fail with missing `BUILD.bazel` or `MODULE.bazel`.

**Checks**:
- Inspect published artifacts: `zipinfo -1 <artifact>.zip | rg 'MODULE.bazel|BUILD.bazel|bindings/cpp'`.
- Ensure the tag/version is non-empty in CI.

**Fix patterns**:
- Fail early in CI if critical files are missing.
- Ensure module version is set before running publish steps.

## 7) Multi-Workspace Build Compatibility
**Use this only if the repo must be buildable from both root and subdirectory.**

**Pattern**: repository-aware labels.

```bzl
# bindings/cpp/labels.bzl
def fluss_api_cc_proto_label():
    if native.repository_name() == "@":
        return "//proto:fluss_api_cc_proto"
    return "//bindings/cpp/proto:fluss_api_cc_proto"
```

```bzl
load(":labels.bzl", "fluss_api_cc_proto_label")

cc_library(
    name = "fluss_cpp",
    deps = [
        fluss_api_cc_proto_label(),
        "@com_google_protobuf//:protobuf",
    ],
)
```

## 8) Version Skew Warnings
**Symptom**: `root module requires X but got Y`.

**Interpretation**:
- A higher-priority override or downstream dep is pinning a different version.

**Fix patterns**:
- Decide if skew is acceptable; if not, override explicitly at the root module.
- Record approved version ranges in docs or CI checks.

## 9) Cache & Sync Hygiene
**Symptom**: Changes in module files not reflected in downstream builds.

**Fix patterns**:
- `bazel sync --configure` after module updates.
- `bazel clean --expunge` if repository mapping is stale.

## 10) Output Base Collisions in CI
**Symptom**: Flaky builds in concurrent CI jobs.

**Fix patterns**:
- Use job-unique `--output_base`.
- Avoid sharing output directories across parallel jobs.

## 11) Bazel + Cargo (build.rs) Sandbox Scan Failure
**症状**：
- Cargo 报错类似：
  - `failed to determine list of files in .../bindings/cpp`
  - `Failed to read the directory at '.../bazel-build/.bazel-output-base/sandbox/...': No such file or directory`
- 多出现在 Bazel 触发 `cargo build` 的场景（genrule 或 `cargo_build`）。

**根因**：
- 当 `--output_base` 放在 Cargo crate 目录内（例如 `bindings/cpp/bazel-build/...`），Cargo 会在计算 build script 指纹时遍历 crate 内文件；
- Bazel sandbox 目录在构建过程中频繁创建/回收，Cargo 扫描时遇到刚被删除的目录，直接失败。

**修复**：
- 把 Bazel output base 移到 crate 目录外，例如仓库根：
  - `--output_base="$ROOT_DIR/bazel-build/.bazel-output-base"`
- 清理旧的 output base，避免残留路径影响：
  - `rm -rf bindings/cpp/bazel-build`
  - `rm -rf bazel-build`

**建议**：
- 避免将 Bazel 的 output base 放在任何 Cargo crate 根目录下。
- 如果需要稳定输出路径，优先选择仓库根或 `/tmp` 下的独立目录。

## Operational Checklists

### A) Publishing Checklist (Module Artifact)
- Confirm root `MODULE.bazel` exists and contains all deps used in BUILD files.
- Ensure tag/version is non-empty before generating metadata.
- Verify artifact contents:
  - `MODULE.bazel`
  - `BUILD.bazel` (if root aliases are used)
  - `bindings/cpp/**`
- Run `zipinfo -1` or `tar -tf` and validate file list.

### B) Downstream Integration Checklist
- Use `@repo//bindings/cpp:target` if you want to bypass root aliases.
- Run `bazel sync --configure` after updating the module version.
- If dependency labels fail, inspect `$(bazel info output_base)/external/<repo>/`.

### C) CI Failure Checklist
- Capture the exact label in the error; classify as root vs subdir.
- Confirm `bazel info workspace` and `bazel info output_base`.
- Validate `PROTOC` availability when Cargo is invoked from Bazel.
- Check for stale module mapping; consider `bazel clean --expunge`.

## FAQ

**Q: Why does `@repo//proto:...` work locally but fail downstream?**
A: Locally you may be using a subdirectory workspace root where `//proto` exists. Downstream sees the repository root, where `proto/` may not exist.

**Q: Do root `BUILD.bazel` aliases fix subdir path errors?**
A: Only for labels like `@repo//:target`. They do not affect `@repo//subdir:target` or internal dependencies.

**Q: Why does a patch fix my local build but not downstream?**
A: `single_version_override` is not transitive. Downstream must repeat the override to see the patch.

**Q: Why do I see version skew warnings?**
A: Another module or override in the dependency graph is selecting a different version. Decide if skew is acceptable or enforce a pin.

## Quick Validation Matrix
| Scenario | Command | Expected |
|---|---|---|
| Root workspace (local) | `./ci.sh compile` | Success |
| Subdir workspace (local) | `cd bindings/cpp && bazel build //:fluss_cpp` | Success |
| Downstream (external) | `bazel build @your-module//bindings/cpp:fluss_cpp` | Success |
