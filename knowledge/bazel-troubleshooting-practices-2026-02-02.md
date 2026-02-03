# Bazel Best Practices: Workspace Root vs Subdirectory Workspaces

## Summary
When a repository can be built from the root **and** from a subdirectory (e.g., `bindings/cpp`), label resolution changes because `//...` always resolves relative to the **current workspace root**. This document lists practices to keep builds stable for both local development and downstream consumers.

## Core Principles
1. **There is exactly one workspace root** at build time. All `//...` labels resolve from that root.
2. **Downstream consumers always see the repository root** as the external workspace root.
3. **Subdirectory workspaces are local conveniences** and must not break the external root view.

## Common Failure Modes
- A label like `//proto:foo` resolves to different directories depending on the workspace root.
- Downstream builds fail because a dependency only exists in a subdirectory workspace.
- Patch-based overrides for external deps work locally but do not propagate to downstream users.

## Recommended Patterns

### 1) Use Repository-Aware Labels for Dual-Root Builds
When a target is consumed by both the repo root and a subdirectory workspace, define a label helper that branches on `native.repository_name()`.

```bzl
# bindings/cpp/labels.bzl
def fluss_api_cc_proto_label():
    if native.repository_name() == "@":
        return "//proto:fluss_api_cc_proto"
    return "//bindings/cpp/proto:fluss_api_cc_proto"
```

Then use it in `BUILD.bazel`:

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

### 2) Keep Root `MODULE.bazel` Authoritative
Downstream users always load the root `MODULE.bazel`. If you keep a subdirectory `MODULE.bazel` for local workspace builds, ensure the dependency block stays synchronized with the root module file.

### 3) Avoid Patch-Only Fixes for External Dependencies
Patches via `single_version_override` do not propagate to downstream users unless they also configure the same override. Prefer local compatibility fixes (e.g., repository-aware labels) that do not rely on downstream config.

### 4) Use Root Aliases Sparingly
Root aliases in `BUILD.bazel` only apply when users build `@repo//:target`. If downstreams use `@repo//bindings/cpp:target`, they bypass root aliases entirely. Do not depend on aliases to fix structural issues.

## Minimal Compatibility Checklist
- Root `MODULE.bazel` is present and accurate.
- Subdirectory workspace builds do not rely on root-only paths.
- External repository builds do not rely on subdirectory-only paths.
- All external dependencies referenced in `BUILD.bazel` are declared in the root `MODULE.bazel`.

## Validation Matrix
| Scenario | Command | Expected |
|---|---|---|
| Root workspace (local) | `./ci.sh compile` | Success |
| Subdir workspace (local) | `cd bindings/cpp && bazel build //:fluss_cpp` | Success |
| Downstream (external) | `bazel build @red-fluss-rust//bindings/cpp:fluss_cpp` | Success |

## When to Add a Root `proto/BUILD.bazel`
Only if you decide that downstreams should reference `@repo//proto:...` directly. Otherwise, use repository-aware labels to avoid maintaining duplicated packages at the root.

## Additional Lessons Worth Recording

### Root `MODULE.bazel` Is the Only Entry for Bzlmod
Downstream module resolution only reads the repository root `MODULE.bazel`. Subdirectory `MODULE.bazel` files are local-only and do not affect external consumers.

### External Repository vs Local Workspace Semantics
External consumers always see the repository root as the workspace root. Any `//...` label used by external builds must resolve correctly from the root, even if local subdirectory builds work.

### Patch Overrides Are Not Transitive
`single_version_override` or `archive_override` patches only apply in the module graph where they are declared. Downstream users will not inherit them unless they repeat the same overrides.

### Root Aliases Do Not Fix Pathing Errors
Aliases in the root `BUILD.bazel` are only used by labels like `@repo//:target`. They do not affect `@repo//subdir:target` or internal dependencies.

### CI Script Expectations
CI publishing scripts commonly assume:
- A root `MODULE.bazel` exists.
- Version/tag is non-empty.
Missing tags may lead to missing `metadata.json` or invalid module metadata paths.

### `protoc` Visibility Across Toolchains
Rust `build.rs` looks for `PROTOC` in the environment. If Bazel provides `protoc` only via tools, you must export `PROTOC` in the genrule or ensure the environment bridges correctly between Bazel and Cargo.

### `repo_name` Consistency
If you set `bazel_dep(name = "protobuf", repo_name = "com_google_protobuf")`, all labels must consistently use `@com_google_protobuf//...`. Mixing `@protobuf` and `@com_google_protobuf` causes hard-to-debug load failures.

### Handling Version Skew Warnings
Warnings like `root module requires X but got Y` indicate an override in the dependency graph. Record when skew is acceptable and when to pin or override explicitly.

### Cache and Sync Hygiene
After publishing a new module version, downstreams may need:
- `bazel sync --configure`
- `bazel clean --expunge` (if repository mapping is stale)

### CI Artifact Completeness Checks
When publishing zipped modules, verify key files are present:
- `MODULE.bazel`
- `BUILD.bazel` (if root aliases are required)
- `bindings/cpp/**`
A simple `zipinfo -1` check prevents missing-file regressions.

### Bazel-Cargo Environment Bridging
If Bazel runs Cargo via genrule, explicitly control:
- `PROTOC`
- `PATH`
- `RUSTUP_HOME` / `CARGO_HOME`
Otherwise containerized builds may fail while local builds pass.

### Fixed `output_base` in CI
A fixed `--output_base` path can collide across concurrent jobs. If CI runs multiple builds in parallel, prefer a job-unique output base.

### `.bazelrc` Bzlmod Flags
`--enable_bzlmod` is global and affects all targets. Document when it is required and avoid mixing legacy `WORKSPACE` assumptions.

