import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/gate0.yml"
STEP = "      - name: Package and verify recursive runtime closure"
ARCHIVE_PREFETCH_STEP = "Prefetch verified upstream archives"
NV_HEADERS_STEP = "Check out exact nv-codec-headers source"
PACKAGE_STEP = "Package and verify recursive runtime closure"


class WorkflowShellTests(unittest.TestCase):
    def package_script(self):
        result = subprocess.run(
            ["yq", "eval", "-o=json", ".jobs.gate0.steps", str(WORKFLOW)],
            check=True,
            capture_output=True,
            text=True,
        )
        steps = json.loads(result.stdout)
        return next(step["run"] for step in steps if step.get("name") == PACKAGE_STEP)

    def test_new_repository_pull_request_can_trigger_gate0(self):
        result = subprocess.run(
            ["yq", "eval", "-o=json", ".on", str(WORKFLOW)],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        triggers = json.loads(result.stdout)
        self.assertIn("pull_request", triggers)
        self.assertIn("workflow_dispatch", triggers)

    def test_fast_tests_block_long_gate0_build(self):
        result = subprocess.run(
            ["yq", "eval", "-o=json", ".jobs", str(WORKFLOW)],
            check=True,
            capture_output=True,
            text=True,
        )
        jobs = json.loads(result.stdout)

        self.assertIn("tests", jobs)
        needs = jobs["gate0"].get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        self.assertIsInstance(needs, list)
        self.assertIn("tests", needs)

        tests = jobs["tests"]
        self.assertEqual(tests.get("runs-on"), "ubuntu-24.04")
        self.assertEqual(tests.get("timeout-minutes"), 10)
        checkout = [
            step
            for step in tests.get("steps", [])
            if step.get("name") == "Check out runtime recipe"
        ]
        self.assertEqual(len(checkout), 1)
        self.assertEqual(
            checkout[0].get("uses"),
            "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5",
        )
        self.assertIs(
            checkout[0].get("with", {}).get("persist-credentials"), False
        )
        run_steps = [
            step
            for step in tests.get("steps", [])
            if step.get("name") == "Run fast repository tests"
        ]
        self.assertEqual(len(run_steps), 1)
        commands = run_steps[0]["run"].splitlines()
        self.assertEqual(commands[0], "set -euo pipefail")
        yq_command = "yq --version"
        unittest_command = "python3 -m unittest discover -s tests -p 'test_*.py' -v"
        self.assertIn(yq_command, commands)
        self.assertIn(unittest_command, commands)
        self.assertLess(commands.index(yq_command), commands.index(unittest_command))
        self.assertIn("python3 -m compileall -q scripts tests", commands)

    def test_runtime_probe_pipeline_cannot_mask_wine_failure(self):
        lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
        step = lines.index(STEP)
        run = lines.index("        run: |", step)
        first_command = next(line[10:] for line in lines[run + 1 :] if line.strip())

        result = subprocess.run(
            ["bash", "-c", f"{first_command}\nfalse | true"],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(
            result.returncode,
            0,
            "the packaging step can mask a failed command at the start of a pipeline",
        )

    def run_package_script(self, header_api="131077", runtime_api="131077"):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = root / "tools"
            tools.mkdir()
            (root / "upstream/mingw_build").mkdir(parents=True)
            (root / "upstream/mingw_prefix/bin").mkdir(parents=True)
            (root / "upstream/include").mkdir(parents=True)
            (root / "upstream/mingw_build/libmpv-2.dll").write_bytes(b"libmpv")
            runtime = root / "runtime"
            runtime.mkdir()
            runner_temp = root / "runner-temp"
            runner_temp.mkdir()
            for name in ("libgcc_s_seh-1.dll", "libstdc++-6.dll", "libwinpthread-1.dll"):
                (runtime / name).write_bytes(name.encode())

            compiler = textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -euo pipefail
                output=
                for argument in "$@"; do
                  case "$argument" in
                    -print-file-name=*)
                      printf '%s/%s\\n' "$FAKE_RUNTIME" "${argument#*=}"
                      exit
                      ;;
                  esac
                done
                while (($#)); do
                  if [[ $1 == -o ]]; then
                    output=$2
                    shift
                  fi
                  shift
                done
                if [[ -z "$output" ]]; then
                  echo 'fake compiler: missing -o output' >&2
                  exit 67
                fi
                cat >/dev/null
                api_value=${API_VARIABLE}
                printf '#!/usr/bin/env bash\\nAPI_MARKERprintf "%%s\\\\n" "%s"\\n' \
                  "$api_value" > "$output"
                chmod +x "$output"
                """
            )
            for name, api_variable, api_marker in (
                (
                    "cc",
                    "FAKE_HEADER_API",
                    'touch "$RUNNER_TEMP/header-api-ran"\\n',
                ),
                ("x86_64-w64-mingw32-gcc-posix", "FAKE_RUNTIME_API", ""),
            ):
                path = tools / name
                path.write_text(
                    compiler.replace("API_VARIABLE", api_variable).replace(
                        "API_MARKER", api_marker
                    ),
                    encoding="utf-8",
                )
                path.chmod(0o755)

            python = tools / "python3"
            python.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    fail() {
                      local code=$1
                      shift
                      printf 'fake python3: %s\\n' "$*" >&2
                      exit "$code"
                    }
                    command=$1
                    shift
                    case "$command" in
                      scripts/package_candidate.py)
                        libmpv_count=0
                        output_count=0
                        objdump_count=0
                        api_version_count=0
                        libmpv=
                        output=
                        objdump=
                        api_version=
                        search_roots=()
                        while (($#)); do
                          if (($# < 2)); then
                            fail 65 "package_candidate.py: missing value for $1"
                          fi
                          case "$1" in
                            --libmpv)
                              libmpv_count=$((libmpv_count + 1))
                              libmpv=$2
                              ;;
                            --search-root) search_roots+=("$2") ;;
                            --output)
                              output_count=$((output_count + 1))
                              output=$2
                              ;;
                            --objdump)
                              objdump_count=$((objdump_count + 1))
                              objdump=$2
                              ;;
                            --api-version)
                              api_version_count=$((api_version_count + 1))
                              api_version=$2
                              ;;
                            *) fail 64 "package_candidate.py: unknown option $1" ;;
                          esac
                          shift 2
                        done
                        [[ "$libmpv_count" -eq 1 ]] || \
                          fail 67 "package_candidate.py: expected one --libmpv, got $libmpv_count"
                        [[ "$libmpv" == upstream/mingw_build/libmpv-2.dll ]] || \
                          fail 67 "package_candidate.py: --libmpv mismatch: got $libmpv"
                        [[ "${#search_roots[@]}" -eq 2 ]] || \
                          fail 67 "package_candidate.py: expected two --search-root values, got ${#search_roots[@]}"
                        [[ "${search_roots[0]}" == upstream/mingw_prefix/bin ]] || \
                          fail 67 "package_candidate.py: first --search-root mismatch: got ${search_roots[0]}"
                        [[ "${search_roots[1]}" == \
                          "$RUNNER_TEMP/gate0-runtime-support" ]] || \
                          fail 67 "package_candidate.py: second --search-root mismatch: got ${search_roots[1]}"
                        [[ "$output_count" -eq 1 ]] || \
                          fail 67 "package_candidate.py: expected one --output, got $output_count"
                        [[ "$objdump_count" -eq 1 ]] || \
                          fail 67 "package_candidate.py: expected one --objdump, got $objdump_count"
                        [[ "$objdump" == x86_64-w64-mingw32-objdump ]] || \
                          fail 67 "package_candidate.py: --objdump mismatch: got $objdump"
                        [[ "$api_version_count" -eq 1 ]] || \
                          fail 67 "package_candidate.py: expected one --api-version, got $api_version_count"
                        case "$output" in
                          "$RUNNER_TEMP/gate0-api-probe")
                            [[ "$api_version" == "$FAKE_HEADER_API" ]] || \
                              fail 67 "package_candidate.py: probe API mismatch: expected $FAKE_HEADER_API, got $api_version"
                            ;;
                          gate0-candidate)
                            [[ "$api_version" == "$FAKE_RUNTIME_API" ]] || \
                              fail 67 "package_candidate.py: final API mismatch: expected $FAKE_RUNTIME_API, got $api_version"
                            ;;
                          *) fail 66 "package_candidate.py: unknown --output $output" ;;
                        esac
                        mkdir "$output"
                        touch "$output/.packaged-closure"
                        cp upstream/mingw_build/libmpv-2.dll "$output/"
                        ;;
                      scripts/verify_runtime.py)
                        [[ -f gate0-candidate/.packaged-closure ]] || \
                          fail 67 'verify_runtime.py: missing final package marker'
                        ;;
                      *) fail 64 "unexpected command $command" ;;
                    esac
                    """
                ),
                encoding="utf-8",
            )
            python.chmod(0o755)

            wine = tools / "wine"
            wine.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    if [[ "${WINEDEBUG:-}" != fixme-all ]]; then
                      printf 'fake wine: WINEDEBUG mismatch: expected fixme-all, got %s\\n' \
                        "${WINEDEBUG:-<unset>}" >&2
                      exit 67
                    fi
                    if [[ ! -f .packaged-closure ]]; then
                      echo 'Wine ran before package_candidate.py created the probe closure' >&2
                      exit 97
                    fi
                    touch "$RUNNER_TEMP/wine-ran"
                    "$@"
                    """
                ),
                encoding="utf-8",
            )
            wine.chmod(0o755)

            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{tools}:{environment['PATH']}",
                    "RUNNER_TEMP": str(runner_temp),
                    "FAKE_RUNTIME": str(runtime),
                    "FAKE_HEADER_API": header_api,
                    "FAKE_RUNTIME_API": runtime_api,
                }
            )
            step = root / "step.sh"
            step.write_text(self.package_script(), encoding="utf-8")
            result = subprocess.run(
                ["bash", str(step)],
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
            )
            return (
                result,
                (runner_temp / "wine-ran").exists(),
                (runner_temp / "header-api-ran").exists(),
            )

    def test_runtime_probe_runs_from_packager_created_closure(self):
        result, wine_ran, _ = self.run_package_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(wine_ran, "the workflow returned success without running Wine")

    def test_runtime_probe_rejects_api_version_mismatch(self):
        result, wine_ran, _ = self.run_package_script(runtime_api="131078")

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(wine_ran, "the runtime API probe did not run")

    def test_runtime_probe_rejects_header_major_other_than_two(self):
        result, wine_ran, header_api_ran = self.run_package_script(
            header_api="65541", runtime_api="65541"
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(header_api_ran, "the header API helper did not run")
        self.assertFalse(wine_ran, "the invalid header API reached Wine")

    def test_package_uses_curated_runtime_support_root(self):
        result = subprocess.run(
            ["yq", "eval", "-o=json", ".jobs.gate0.steps", str(WORKFLOW)],
            check=True,
            capture_output=True,
            text=True,
        )
        steps = json.loads(result.stdout)
        matching_steps = [step for step in steps if step.get("name") == PACKAGE_STEP]
        self.assertEqual(len(matching_steps), 1)
        script = matching_steps[0]["run"]
        contracts = (
            'task_runtime_support="$RUNNER_TEMP/gate0-runtime-support"',
            'mkdir -p "$task_runtime_support"',
            'task_runtime_roots=(upstream/mingw_prefix/bin "$task_runtime_support")',
            "for task_dll in libgcc_s_seh-1.dll libstdc++-6.dll libwinpthread-1.dll; do",
            'test -f "$task_path"',
            'cp "$task_path" "$task_runtime_support/"',
        )
        for contract in contracts:
            with self.subTest(contract=contract):
                self.assertIn(contract, script)
        self.assertNotIn('dirname "$task_path"', script)
        self.assertNotIn("task_runtime_roots+=(", script)

    def test_archive_prefetch_populates_upstream_wget_cache(self):
        result = subprocess.run(
            ["yq", "eval", "-o=json", ".jobs.gate0.steps", str(WORKFLOW)],
            check=True,
            capture_output=True,
            text=True,
        )
        steps = json.loads(result.stdout)
        matching_steps = [
            step for step in steps if step.get("name") == ARCHIVE_PREFETCH_STEP
        ]
        self.assertEqual(len(matching_steps), 1, "missing verified archive prefetch")
        step = matching_steps[0]
        self.assertEqual(step["working-directory"], "upstream")
        names = [step.get("name") for step in steps]
        self.assertLess(
            names.index(ARCHIVE_PREFETCH_STEP),
            names.index("Build upstream dependency set"),
        )
        script = step["run"]
        self.assertEqual(script.splitlines()[0], "set -euo pipefail")
        contracts = (
            "prefetch_archive() {",
            "curl --fail --show-error --silent --location",
            "--retry 5 --retry-all-errors --connect-timeout 20",
            '--output "$task_archive"',
            'test "$(wc -c < "$task_archive")" -eq "$task_size"',
            "task_sha256",
            "sha256sum --check --strict",
        )
        for contract in contracts:
            with self.subTest(contract=contract):
                self.assertIn(contract, script)
        archives = (
            (
                "libiconv-1.18.tar.gz",
                5822590,
                "3b08f5f4f9b4eb82f151a7040bfd6fe6c6fb922efe4b1659c66ea933276965e8",
                "https://ftp.gnu.org/gnu/libiconv/libiconv-1.18.tar.gz",
            ),
            (
                "zlib-1.3.1.tar.gz",
                1512791,
                "9a93b2b7dfdac77ceba5a558a580e74667dd6fede4585b91eefb60f03b72df23",
                "https://zlib.net/fossils/zlib-1.3.1.tar.gz",
            ),
            (
                "AMF-headers-v1.5.0.tar.gz",
                82755,
                "d569647fa26f289affe81a206259fa92f819d06db1e80cc334559953e82a3f01",
                "https://github.com/GPUOpen-LibrariesAndSDKs/AMF/releases/download/v1.5.0/AMF-headers-v1.5.0.tar.gz",
            ),
            (
                "freetype-2.14.1.tar.xz",
                2664948,
                "32427e8c471ac095853212a37aef816c60b42052d4d9e48230bab3bdf2936ccc",
                "https://download-mirror.savannah.gnu.org/releases/freetype/freetype-2.14.1.tar.xz",
            ),
            (
                "fribidi-1.0.16.tar.xz",
                1098260,
                "1b1cde5b235d40479e91be2f0e88a309e3214c8ab470ec8a2744d82a5a9ea05c",
                "https://github.com/fribidi/fribidi/releases/download/v1.0.16/fribidi-1.0.16.tar.xz",
            ),
            (
                "harfbuzz-12.2.0.tar.xz",
                18221900,
                "ecb603aa426a8b24665718667bda64a84c1504db7454ee4cadbd362eea64e545",
                "https://github.com/harfbuzz/harfbuzz/releases/download/12.2.0/harfbuzz-12.2.0.tar.xz",
            ),
        )
        for archive in archives:
            with self.subTest(archive=archive[0]):
                self.assertIn(" ".join(map(str, archive)), script)

    def test_nv_codec_headers_checkout_is_pinned_before_upstream_build(self):
        result = subprocess.run(
            ["yq", "eval", "-o=json", ".jobs.gate0.steps", str(WORKFLOW)],
            check=True,
            capture_output=True,
            text=True,
        )
        steps = json.loads(result.stdout)
        matching_steps = [step for step in steps if step.get("name") == NV_HEADERS_STEP]
        self.assertEqual(len(matching_steps), 1, "missing pinned nv-codec-headers checkout")
        step = matching_steps[0]
        self.assertEqual(
            step,
            {
                "name": NV_HEADERS_STEP,
                "uses": "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5",
                "with": {
                    "repository": "FFmpeg/nv-codec-headers",
                    "ref": "876af32a202d0de83bd1d36fe74ee0f7fcf86b0d",
                    "path": "upstream/nv-codec-headers",
                    "persist-credentials": False,
                },
            },
        )
        names = [step.get("name") for step in steps]
        self.assertLess(
            names.index(NV_HEADERS_STEP), names.index("Build upstream dependency set")
        )


if __name__ == "__main__":
    unittest.main()
