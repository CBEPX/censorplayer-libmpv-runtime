# Controlled libmpv runtime implementation plan

## Goal

Publish a Windows x64 libmpv runtime whose exact binaries are mechanically
bound to complete corresponding source, build inputs, SPDX metadata, and
provenance, then integrate that immutable release into CensorPlayer.

## Global Constraints

- Runtime repository: `CBEPX/censorplayer-libmpv-runtime`, public.
- mpv commit: `85bf9f4ff46cd45686cfe2fd22f49828877db5cb`.
- FFmpeg commit: `272c273d30f737632e6630458ed36a0bdbfbc3fc`.
- Consumer: mpv.net `7.1.2.0`, Windows x64 only.
- Primary path: the official mpv MinGW build. `ci/build-common.sh` supplies
  `-Dlibmpv=true`; our adapter packages `mingw_build/libmpv-2.dll` and its
  recursive non-system PE dependency closure.
- The runtime is a new, unqualified build. Matching mpv/FFmpeg commits is not
  treated as feature-parity evidence.
- No binary may be uploaded unless its complete source bundle is uploaded in
  the same artifact/release and every hash relationship is verified.
- All network-resolved inputs are full-SHA or SHA-256 locked before a release
  build. The release build consumes only the source bundle with networking
  disabled.
- Use Python standard library and existing toolchain commands; add no package
  dependency merely for manifest or archive validation.
- Use TDD for every validator or parser: observe a focused test fail before
  adding production behavior.
- Do not implement a shinchiro/static fallback. If Gate 0 or required feature
  compatibility fails, stop publication and report that blocker.

## Task 1: Gate 0 build proof and artifact contract

- Add a small, test-first Python verifier for `runtime-manifest.json` and PE
  inspection output. It must reject wrong architecture, missing libmpv API
  exports, API major other than 2, path traversal, duplicate paths, missing or
  extra DLLs, and hash/size mismatches.
- Add a non-publishing GitHub Actions workflow that checks out the exact mpv
  commit, replaces only FFmpeg's checkout with the exact locked commit, invokes
  the upstream MinGW build, and proves `mingw_build/libmpv-2.dll` exists.
- Package a candidate directory containing `libmpv-2.dll`, its recursive
  non-system imports, and a schema-1 runtime manifest. Upload it only together
  with a source snapshot for this feasibility run.
- Record the direct upstream evidence and the Gate 0 abort conditions in the
  README. Do not claim reproducibility or publish a GitHub Release.

## Task 2: Locked source closure and offline build

- Add schema-1 `runtime.lock.json` with target, source epoch, digest-pinned
  builder image, exact build options, every Git source at a full commit, every
  tarball at URL/size/SHA-256, nested shaderc/submodule inputs, Cargo vendor
  inputs, Meson WrapDB inputs, and MinGW runtime provenance.
- Add a manual network-enabled source preparation command that validates the
  lock and creates a normalized `tar.zst` containing all preferred source,
  patches, build scripts, vendored Cargo/WrapDB data, licenses, and BUILDING.md.
  It must not build or publish binaries.
- Add an offline build command that accepts only that archive, rejects mutable
  or undeclared inputs, runs the official build logic in a digest-pinned
  container with networking disabled, and applies only a minimal fetch/pack
  adapter. Do not fork mpv source.
- Set `SOURCE_DATE_EPOCH`, a fixed version string, normalized paths/archive
  metadata, and disabled PE linker timestamps.
- Tests must cover changed source bytes, missing/extra sources, mutable refs,
  duplicate paths, path traversal, and attempts to fetch during offline build.

## Task 3: Runtime packaging, qualification, and immutable release

- Generate `runtime-manifest.json`, `release-manifest.json`, SPDX 2.3 SBOM,
  provenance JSON, build metadata, licenses/notices, and `SHA256SUMS` from the
  build graph and recursive PE imports. Include statically linked components
  in SBOM even though they do not appear in imports.
- Runtime ZIP must contain exactly the manifest-declared DLL set. Generic DLL
  names are allowed only when their hashes and source components are declared.
- Build twice in separate clean workflow runs/runners without shared caches or
  network. All runtime file hashes must match before tagging.
- On Windows, overlay the candidate runtime into stock mpv.net 7.1.2.0 and run
  real H.264/HEVC/AV1 decode, MKV/MP4, Cyrillic SRT/ASS, D3D11 initialization,
  hwdec probe, gblur, and all CensorPlayer audio-filter graphs.
- Generate a capability diff against the currently shipped runtime. Missing
  required capabilities block release; optional differences are documented.
- Publish only from a new exact tag, never replace a tag or asset, give only
  the final release job `contents: write` and `id-token: write`, and attach
  binary and source artifacts together with attestations.

## Task 4: CensorPlayer consumption and package verification

- In `CBEPX/mpvnet-censor-extension`, pin the immutable runtime release in
  `deps.lock.json`: tag, recipe commit, URL/size/SHA-256 for runtime, source,
  SBOM, provenance and attestation, plus the exact DLL set.
- Extend packaging to download and verify all locked inputs, replace stock
  `libmpv-2.dll`, remove only filenames declared by the previous runtime
  manifest, reject collisions/missing/extra files, and record runtime/source
  hashes in `VERSION.json`.
- Extend release verification so the portable payload proves
  DLL -> runtime manifest -> provenance -> source bundle -> SBOM -> lock.
- Make installer install/update/uninstall smoke check exact DLL hashes and
  reject stale runtime DLLs. Attach the same source bundle to the CensorPlayer
  release.
- Correct the player SPDX model so mpv.net is a modified payload and the
  controlled runtime plus all static/dynamic components are represented.

## Task 5: Release gates, documentation, and review loop

- Keep binary publication fail-closed until runtime/source/license/security
  checks, exact-head Windows CI, and physical Windows acceptance are recorded.
- Add exact `refs/tags/v$VERSION` checks, a protected `release` environment,
  a final allowlisted publish job, and re-verification of checksums immediately
  before GitHub Release creation.
- Update Phase 27, issue #4, README, THIRD_PARTY_NOTICES, and Windows test guide
  with the exact hashes and proof boundary. Unchanged MediaInfo/.NET/WPF files
  remain a separate license/notices gate.
- Run Claude Code Opus 5/xhigh adversarial review through `cc` after the runtime
  work and again after player integration. Fix every validated actionable
  finding and repeat review without requesting intermediate confirmation.
- Final physical Windows checklist covers portable and installer install,
  update and uninstall, real D3D11/hwdec, common codecs/subtitles, blur,
  compressor presets/OSD, seek, watchdog, and absence of stale DLLs.
