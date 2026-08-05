# censorplayer-libmpv-runtime

Controlled Windows x64 libmpv runtime work for CensorPlayer.

## Gate 0 feasibility proof

The read-only, non-publishing `Gate 0 candidate` workflow runs on pull requests,
including while the workflow is new to the repository. `workflow_dispatch`
remains available for manual runs after the workflow reaches the default
branch. The workflow checks out mpv commit
[`85bf9f4ff46cd45686cfe2fd22f49828877db5cb`](https://github.com/mpv-player/mpv/commit/85bf9f4ff46cd45686cfe2fd22f49828877db5cb)
and replaces only its FFmpeg checkout with FFmpeg commit
[`272c273d30f737632e6630458ed36a0bdbfbc3fc`](https://github.com/FFmpeg/FFmpeg/commit/272c273d30f737632e6630458ed36a0bdbfbc3fc).
It then invokes mpv's own
[`ci/build-mingw64.sh`](https://github.com/mpv-player/mpv/blob/85bf9f4ff46cd45686cfe2fd22f49828877db5cb/ci/build-mingw64.sh).
At that commit, the upstream
[`ci/build-common.sh`](https://github.com/mpv-player/mpv/blob/85bf9f4ff46cd45686cfe2fd22f49828877db5cb/ci/build-common.sh)
sets `-Dlibmpv=true`, and the MinGW script builds in `mingw_build`.

The workflow must prove that `mingw_build/libmpv-2.dll` exists. It walks the
DLL's recursive non-system PE imports, copies only that closure, records PE
machine/import/export inspection, generates a schema-1
`runtime-manifest.json`, runs `mpv_client_api_version()` under Wine, and
verifies the measured API major plus every declared size and SHA-256. The one
short-lived Actions artifact contains both the candidate directory and a
source snapshot of the recipe, upstream build tree, Cargo sources, and Ubuntu
MinGW toolchain sources used by the run.

This is a feasibility artifact, not a release. Gate 0 still uses upstream
network resolution for dependencies other than the exact mpv and FFmpeg
commits. It does not establish locked inputs, an offline build, reproducibility,
full feature parity with mpv.net 7.1.2.0, or full runtime qualification. The
workflow has read-only repository permissions and no GitHub Release step.

## CensorPlayer consumer qualification

After Gate 0 uploads its candidate and source snapshot, a Windows job downloads
that exact same-run artifact and first verifies that its bundled recipe file
contents match the checked-out runtime-recipe head. It then checks out
CensorPlayer commit `6d2586d32d9aa733f5e9c51fdfee28abe54bc1e4`, builds and
tests the extension, stages stock mpv.net 7.1.2.0 with the consumer's pinned
packaging script and its `deps.lock.json` SHA-256 check, verifies the candidate
again, replaces stock `libmpv-2.dll`, adds the candidate's declared recursive
DLL closure, and rejects dependency-name collisions. The staged player must
then pass the pinned consumer's
`Censor.LoaderSmoke`, `smoke-audio-filters.ps1`, and
`smoke-extension-runtime.ps1 -VerifyAudioWatchdog` checks.

The combined portable directory exists only on the ephemeral Windows runner
and is not uploaded. The Windows job intentionally downloads the combined
candidate-and-source artifact even though it executes only the candidate; a
binary-only transfer would weaken the Gate 0 source-binding rule. Its extracted
recipe is compared with `git archive HEAD`, and the expected source/toolchain
subtrees must be present before the candidate is used. The job also proves that
the staged mpv.net process loaded `libmpv-2.dll` from the overlaid path with the
manifest-declared SHA-256. This proves the automated CensorPlayer consumer
contract for the candidate; it does not yet cover the full codec/subtitle
matrix, real D3D11 or hardware decoding, physical UI acceptance, locked offline
reproducibility, or permission to publish a runtime release.

## Artifact contract

`runtime-manifest.json` schema 1 declares:

- target `{ "os": "windows", "arch": "x86_64" }`;
- libmpv path `libmpv-2.dll`, measured client API version, and derived major
  `2`;
- the exact flat DLL set, with byte size and SHA-256 for every file.

`pe-inspection.json` schema 1 records each DLL's `pei-x86-64` machine, imports,
and exports, plus the same measured libmpv API version. Verification rejects a
wrong target or PE machine, missing core libmpv exports, mismatched API evidence,
measured API major other than 2, unsafe or duplicate paths, an incomplete
non-system import closure, missing or extra DLLs or PE records, and size/hash
mismatches.

Run the local contract tests with:

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Gate 0 abort conditions

Do not upload the candidate artifact if any exact checkout fails, the upstream
MinGW build fails, `mingw_build/libmpv-2.dll` is absent, a non-system import
cannot be resolved, PE/manifest verification fails, or the corresponding source
snapshot cannot be created. Do not publish a tag or GitHub Release from Gate 0.
