# Cargo Build Experience (2026-02-05)

## Arrow IPC Patch Usage
- Ensure the workspace `[patch.crates-io]` points `arrow-ipc` to `third_party/arrow-ipc`.
- Pin `arrow` and `arrow-schema` with exact versions (e.g. `=57.1.0`) to avoid semver drift that bypasses the patch.
- If `Cargo.lock` is missing in CI, dependency resolution can float to newer `57.x` and ignore the patch.
- Verify with `cargo tree -i arrow-ipc`.
  - If you see `patch ... was not used`, the patch is not in effect.

## Release Build Behavior
- Prefer `cargo build --release` for performance-sensitive runs.
- Large decode throughput differences can be caused by release vs debug builds even when configs are identical.

## LZ4 Mode Signals
- `FLUSS_LZ4_MODE=block` is required to force block-level decoding.
- A stack trace that shows `lz4_flex::frame::FrameDecoder` indicates frame mode, which can happen if the patched `arrow-ipc` is not used.

## CI Environment Notes
- `protoc` must be available in PATH or passed via `PROTOC`.
- If CI lacks `Cargo.lock`, pin versions or add lockfile to prevent patch drift.
- Avoid tooling assumptions like `rg`; use `grep` for portability.
