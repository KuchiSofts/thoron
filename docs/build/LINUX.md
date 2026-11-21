# Building Thoron on Linux (Ubuntu 24.04, in WSL2 or native)

This guide reproduces the Linux x64 AVX2 build. Every step was verified on the reference machine in a
dedicated Ubuntu 24.04 WSL2 distro (ROADMAP **P1.2**, **P1.5**). On a native Ubuntu 24.04 machine,
skip the WSL parts.

## What you need

- Ubuntu 24.04 LTS (x64), at least 200 GB free on its disk, 32 GB of RAM at least (the release
  build used 16 parallel jobs within 44 GB).
- Git and Python 3 (both come with Ubuntu).

## 1. A dedicated WSL distro (Windows only)

Keep the build away from any distro you already use:

```powershell
wsl --install -d Ubuntu-24.04 --location C:\thoron-build\wsl\Ubuntu-24.04 --no-launch
wsl -d Ubuntu-24.04 -u root -- useradd -m -s /bin/bash thoron
```

In the distro's `/etc/wsl.conf`, make `thoron` the default user and keep the Windows `PATH` out of
Linux, which would otherwise confuse the build:

```ini
[user]
default=thoron

[interop]
appendWindowsPath=false
```

The `thoron` user has no password and no `sudo`; the one step that needs root is run with
`wsl -d Ubuntu-24.04 -u root`.

WSL limits its memory (24 GB on the reference machine). For the build, raise it only while
building, with a byte-exact backup of `.wslconfig`, then restore it:

```powershell
py -3 -I tools\build\wslconfig.py raise          # prints the backup file name (see BUILD_BUDGET for values)
wsl --shutdown                                   # stops every WSL distro briefly
# ... build ...
py -3 -I tools\build\wslconfig.py restore <backup file>
wsl --shutdown
```

## 2. depot_tools and the Chromium source

As `thoron`, in `~/thoron-build`:

```bash
export DEPOT_TOOLS_UPDATE=0 PATH="$HOME/thoron-build/depot_tools:$PATH"
git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git ~/thoron-build/depot_tools
~/thoron-build/depot_tools/ensure_bootstrap
mkdir -p ~/thoron-build/chromium && cd ~/thoron-build/chromium
```

Create `.gclient` exactly as for Windows ([`WINDOWS.md`](WINDOWS.md#5-chromium-source)), but with
`target_os = ["linux"]`, then:

```bash
gclient sync --nohooks --no-history -D
```

The sync took 11 minutes on the reference machine (31 GB). Then install Chromium's build
dependencies as root, and run the hooks and the arm64 sysroot as `thoron`:

```bash
sudo ./src/build/install-build-deps.sh --no-prompt --no-chromeos-fonts      # as root in WSL: no sudo
gclient runhooks
src/build/linux/sysroot_scripts/install-sysroot.py --arch=arm64
```

Check that the toolchain works on unmodified Chromium, for both architectures:

```bash
cd src
gn gen out/stock-check-x64 --args='is_debug=false is_component_build=false target_cpu="x64"'
gn gen out/stock-check-arm64 --args='is_debug=false is_component_build=false target_cpu="arm64"'
```

## 3. Upstream overlay and patches

Copy the upstream M156 tree and this repository into the Linux file system with `git archive`
(no history), and apply it with the same pipeline as on Windows:

```bash
python3 -I tools/build/pipeline.py apply --tree ~/thoron-build/upstream-M156 \
    --src ~/thoron-build/chromium/src --profile avx2 --log ~/thoron-build/logs/apply-M156-linux.log
```

Expected: 0 rejects, 149 of 152 patches. Some upstream files are stored with Windows line endings;
that is how upstream ships them, so do not convert them.

## 4. Build

The release configuration is upstream's `other/AVX2/AVX2_args.gn` with Thoron's privacy choices
applied by `tools/build/release_args.py` (see [`RELEASE_ARGS.md`](RELEASE_ARGS.md); Widevine is
downloaded from Google at runtime instead of being bundled):

```bash
python3 -I tools/build/release_args.py compose --platform linux --upstream <upstream>/other/AVX2/AVX2_args.gn \
    --source "gz83 <commit> other/AVX2/AVX2_args.gn" --out out/thoron-m156-avx2/args.gn
python3 -I tools/build/release_args.py check --platform linux --args out/thoron-m156-avx2/args.gn
python3 -I tools/build/pipeline.py preflight --root ~/thoron-build --need-gb 200 --require-wsl-memory-gb 40
autoninja -j 16 -C out/thoron-m156-avx2 chrome
```

On the reference machine the build took about 2 hours 37 minutes (9.6 GB output). Raise WSL's
memory only for the build: 36 GB with 32 GB of swap and `autoMemoryReclaim=dropCache` kept Windows
responsive with 10 jobs (see [`BUILD_BUDGET.md`](BUILD_BUDGET.md)). If GitHub cannot be reached,
the step that downloads the bundled uBlock Origin package fails; it accepts a copy placed in
`out/<dir>/gen/chrome/browser/resources/ublock_origin/` only if its SHA-256 matches the pinned value.

## 5. Check the build

Run the smoke test with a fresh profile. On Linux it proves the sandbox from `/proc`: every renderer
must run under a seccomp-BPF filter and in its own PID namespace.

```bash
python3 -I tools/build/smoke.py --browser out/thoron-m156-avx2/thorium --work ~/thoron-build/smoke/linux \
    --jxl-sample third_party/blink/web_tests/external/wpt/jpegxl/resources/3x3_srgb_lossless.jxl
```

Expected: `SMOKE: PASSED`. On the reference build the renderer ran with `Seccomp: 2` in its own PID
namespace. The build also starts in a normal window under WSLg.

Never start a test build with `--no-sandbox`. (The exceptions are the emulated smoke tests below, ARM64 and SSE4, which run under QEMU's
user-mode emulation, where the sandbox cannot work, headless, on a throwaway profile and a local page.)

## 6. Thoron 158: the package, the other processors, fuzzing

The 158 tree is `~/thoron-build/chromium158/src`, made from the patch series of this repository's `source/`
(`tools/build/source_tree.py materialize`) with LF line endings: archives for WSL are made with
`git -c core.autocrlf=false -c core.eol=lf archive`. The program is `out/<dir>/thoron`.

**The package.** After `chrome`, `autoninja -C out/thoron-m158-avx2 chrome/installer/linux:stable_deb` makes
`thoron-browser_<version>_<variant>.deb` (`AVX2`, `SSE4.2` or `arm64`). Build with `-k 0` so that one failing
file does not hide the next.

**The portable package (P2.9, P3.12)** is made from that `.deb`: its files under `/opt/kuchisofts/thoron` go into
`ThoronPortable/Application/<version>/`, beside a shell launcher `thoron`, `variant` and `Application/current`
(the Windows package's layout), packed reproducibly into `thoron-<version>-<variant>-portable.tar.xz`:

```bash
autoninja -C out/thoron-m158-avx2 components/thoron_update:thoron_update_cli   # the updater's command line
python3 -I tools/release/portable_linux.py build --deb out/thoron-m158-avx2/thoron-browser_<version>_AVX2.deb \
    --variant linux-x64-avx2 --dist <folder> --updater out/thoron-m158-avx2/thoron_update
```

The launcher sets `BREAKPAD_DUMP_LOCATION`, because Chromium on Linux otherwise keeps crash reports beside the
default profile (`~/.config/thoron`) whatever `--user-data-dir` says. `tools/qa/linux_portable_check.py` checks the
package on a clean Ubuntu machine, the update of a moved copy to a newer version and back included.

**ARM64 (P2b.2)**, cross-compiled on the x64 machine with the Debian arm64 sysroot that `gclient sync` puts into
`build/linux/debian_bullseye_arm64-sysroot`. The arguments are upstream's `arm/raspi/raspi_args.gn` with
Thoron's decisions (its only tuning, `-mtune=cortex-a72`, changes no instruction: any ARMv8-A runs the result):

```bash
python3 -I tools/build/release_args.py compose --platform linux --upstream <upstream>/arm/raspi/raspi_args.gn \
    --source "gz83 <commit> arm/raspi/raspi_args.gn" --out out/thoron-m158-arm64/args.gn
autoninja -C out/thoron-m158-arm64 chrome chrome/installer/linux:stable_deb
python3 -I tools/release/elf_check.py --deb out/thoron-m158-arm64/thoron-browser_<version>_arm64.deb --variant linux-arm64
```

The smoke test (P2b.3) is `tools/qa/linux_arm64_smoke_check.py`: on a clean x64 Ubuntu test machine it adds
Ubuntu's ARM64 libraries from the ports archive (`dpkg --add-architecture arm64`), installs `qemu-user` and the ARM64
`.deb` with apt, restarts the machine (QEMU's handling of the browser's ARM64 child processes works from the next
start on) and runs `qemu-aarch64 -L / /opt/kuchisofts/thoron/thoron --headless=new --no-zygote --no-sandbox
--user-data-dir=<throwaway> --dump-dom <a local page>`, which must print the page as its script changed it. The
build's sysroot cannot be used for this: its loader is a stub for linking only. `--single-process` stops on a
check of its own.

**SSE4 (P2.7)**, for processors without AVX: upstream's `other/SSE4.2/args_SSE4.2.gn` composed the same way into
`out/thoron-m158-sse4`. `tools/qa/linux_sse4_smoke_check.py` installs its `.deb` on a clean test machine and runs
every process of it under QEMU's emulation of a processor without AVX (`qemu-x86_64 -cpu Westmere`): the browser
directly, its renderer, utility and GPU processes through Chromium's own launch prefixes (`--renderer-cmd-prefix`,
`--utility-cmd-prefix`, `--gpu-launcher`). An AVX instruction outside the code that picks one at run time would
stop it with an illegal instruction; the AVX2 package, run the same way as the control, must stop so.

**Fuzzing (S.2, P4.9, P3.22).** libFuzzer with AddressSanitizer, in its own out folder (`is_asan = true`,
`use_libfuzzer = true`, a release and static build): `thoron_update_manifest_fuzzer`,
`thoron_update_delta_list_fuzzer`, `thoron_portable_key_file_fuzzer` and `thoron_open_tabs_fuzzer`, each started
from its seeds (`tools/qa/update_fuzz.py seeds`; the golden session files of `tools/migrate/tests/data/sessions`)
with `-max_total_time`. On Windows the AddressSanitizer build of these targets stops in the build's own `protoc`,
so they run on Linux.

**The checks on clean Ubuntu machines** (`tools/qa/wsl_test_vm.py`, [`../qa/TEST_MACHINES.md`](../qa/TEST_MACHINES.md)):
`linux_package_check.py` (install, names, coexistence with upstream's package, `chrome://sandbox`, lintian,
upgrade; `--online` Widevine; `--netlog` the hosts a fresh profile contacts), `linux_portable_check.py`,
`linux_dark_mode_check.py`, `linux_keyring_check.py`, `linux_settings_import_check.py` (Settings' import from upstream
Thorium, with GNOME's keyring), `linux_arm64_smoke_check.py` and `linux_sse4_smoke_check.py`.

