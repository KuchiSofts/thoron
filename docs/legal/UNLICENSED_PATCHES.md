# Patches without a licence: what each one does and the way out

Six patches of the series use code from authors who publish no licence. Without a licence the author
keeps all rights, so Thoron does not publish these patches (they are withheld from
[`source/`](../../source/README.md)) and may not release with them (ROADMAP **L.1**, **P2.15**,
**P2.25**). This page decides each one. The changes themselves are a work order at the end; nothing in
the series was changed for this page.

Checked on 2026-11-16 against the series for Chromium 158.0.8127.30 on upstream commit `efc0fffc`.

- **Checked** means: read on that day in the patch, in the build tree (Chromium 158.0.8127.30 with the
  series applied; file and line numbers are from it unless a line says "Chromium's own file") or at the
  link given.
- **Inferred** means: concluded from reading, not tested by running. Nothing was built or run for this
  page. Where only a run can tell, the measurement is named.
- Line counts are of Thoron's copies of the patches (the withheld files, by the hashes in
  `source/UPSTREAM.json`): upstream's patches rebased to Chromium 158 with the header lines added.
  Blank lines are not counted.
- This is an engineering review by the project's own rule, not legal advice.

## Summary

| # | Patch | What it is | What is lost without it | Recommendation |
|---|---|---|---|---|
| 1 | `disable-vulkan-gpu-log-warnings.patch` | 11 file paths added to a list that only ChromeOS builds use | Nothing | Drop |
| 2 | `enable-webrtc-h265-l1t2-l1t3-by-default.patch` | Two Chromium features turned on by default | H.265 video sent in a call uses one temporal layer instead of two or three, where the hardware offers them | Drop; the same defaults are two Thoron lines away if wanted |
| 3 | `llvm-optimized-toolchain-build.patch` | Changes to the script that builds a compiler from source | Nothing: Thoron builds with Chromium's prebuilt compiler | Drop |
| 4 | `enable-mpeg2-ac3-eac3-decoding.patch` | Lets the bundled FFmpeg decode AC-3 and E-AC-3 sound; one MPEG-2 line without effect | Dolby Digital sound in local films stops playing on Linux and on Windows without a system decoder | Write again from the specification below (four small edits) |
| 5 | `disable-encryption.patch` (6 lines of it) | Under three switches, extension settings that fail their integrity check are kept | On Windows, a profile switched to or from portable use loses its extensions once | Remove the part; the rest is BSD-3-Clause |
| 6 | `thorium-build-config-and-simd.patch` (36 lines of it) | Optimizer options for the link step; warnings silenced on Linux | Unknown speed difference, only a benchmark can tell; a noisier Linux build log | Ask RobRich999; without a written yes the 36 lines come out |

**The owner's share:** one message to RobRich999 (patch 6), with a fallback that needs nobody. The
decisions for patches 2 and 5 are taken here and can be overruled. Everything else is engineering.

## The authors' repositories today

| Repository | Commit read | Licence found |
|---|---|---|
| [RobRich999/Chromium_Clang](https://github.com/RobRich999/Chromium_Clang/tree/c687f786a141e7dd4518b04a628b49a46c6260e0) | `c687f786a1` | None: no licence file, no word about a licence in the README, GitHub reports none |
| [RobRich999/LLVM_Optimized_AVX2](https://github.com/RobRich999/LLVM_Optimized_AVX2/tree/1a9f41c9d3eb10835a1583bbda0d319ab11b61a8) | `1a9f41c9d3` | None, in the same three ways |
| [win32ss/supermium](https://github.com/win32ss/supermium/tree/bf7e71c95f9a5a9a3ae5206ef8274633255de50b) | `bf7e71c95f` | None: the branch holds patch files and Chromium's README, no licence file |
| [Muril-o/electron-chromium-codecs](https://github.com/Muril-o/electron-chromium-codecs/tree/33c8013764a1f7dcc39ff32a9a4bff2a8c56ae61) | `33c8013764` | The file [`COPYING.LGPLv2.1`](https://github.com/Muril-o/electron-chromium-codecs/blob/33c8013764a1f7dcc39ff32a9a4bff2a8c56ae61/COPYING.LGPLv2.1) at the root; the README does not say what it covers and GitHub reports no licence |

All four are checked. Three more facts, also checked:

- Publishing on GitHub without a licence lets others view and fork the repository there, nothing more
  ([GitHub terms, D.5](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#5-license-grant-to-other-users),
  [choosealicense.com](https://choosealicense.com/no-permission/)).
- Neither RobRich999 nor win32ss has a commit, pull request or issue in `Alex313031/thorium` (GitHub
  search, 0 results). So the rule that a contribution to a repository carries that repository's licence
  ([D.6](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#6-contributions-under-repository-license))
  does not help: Thorium copied these lines in, their authors did not contribute them.
- RobRich999 gave option lists to Thorium's author himself, in public
  ([Chromium_Clang issue 26](https://github.com/RobRich999/Chromium_Clang/issues/26#issuecomment-976883814),
  2021), and Thorium's README thanks him. That he agreed to Thorium using them can be read there. A
  licence for everybody else is not written anywhere.

## 1. `disable-vulkan-gpu-log-warnings.patch`

**What it changes.** One file, 2 hunks, 13 lines added, 1 removed. No logic: 11 paths, 1 comment, 1
copyright line.

- Hunk 1: the copyright line of `content/common/gpu_pre_sandbox_hook_linux.cc` gets two names.
- Hunk 2: the list of files the GPU process may read in `AddAmdGpuPermissions` gets a comment and 11
  paths: Mesa's EGL, GLES and glapi libraries and three Radeon drivers under `/usr/lib`, the Radeon
  Vulkan driver, and the two Vulkan driver folders with the Radeon entry.

**Where it comes from.** All 12 lines of hunk 2 are in Chromium_Clang's
[`Linux/linux64-avx.patch`](https://github.com/RobRich999/Chromium_Clang/blob/c687f786a141e7dd4518b04a628b49a46c6260e0/Linux/linux64-avx.patch)
(from line 295). No licensed project has the list. Chromium itself already lets the GPU process of
every Linux build read both Vulkan driver folders and the Radeon entry (`AddVulkanICDPermissions`,
lines 449-464, called on line 641).

**What is lost.** Nothing, checked in the tree. `AddAmdGpuPermissions` is called in one place only,
inside `if (IsChromeOS())` (lines 643-670, the call on 657), and `IsChromeOS()` is fixed at build time
by `BUILDFLAG(IS_CHROMEOS)` (lines 51-57). Thoron builds for `target_os = "win"` and `"linux"`. On
Windows the file is not built at all (`content/common/BUILD.gn`, line 372).

**The way out: drop it.** Sure: high.

## 2. `enable-webrtc-h265-l1t2-l1t3-by-default.patch`

**What it changes.** One file, 1 hunk, 2 lines changed. Configuration only: in
`media/webrtc/webrtc_features.cc` the features `kWebRtcH265L1T2` and `kWebRtcH265L1T3` go from off to
on by default (lines 61 and 66).

**Where it comes from.** Both lines are in Chromium_Clang's
[`Windows/win64-avx2.patch`](https://github.com/RobRich999/Chromium_Clang/blob/c687f786a141e7dd4518b04a628b49a46c6260e0/Windows/win64-avx2.patch)
(line 325) and `Linux/linux64-avx.patch` (line 420). The features and all code behind them are
Chromium's own (BSD-3-Clause). Chromium's main branch still has both off
([file](https://github.com/chromium/chromium/blob/main/media/webrtc/webrtc_features.cc), checked).
The same effect needs no patch at all: `--enable-features=WebRtcH265L1T2,WebRtcH265L1T3` (a feature's
name is its identifier without the `k`, `base/feature_internal.h`, lines 81-87).

**What is lost.** Checked in
`third_party/blink/renderer/platform/peerconnection/rtc_video_encoder_factory.cc` (lines 61-91) and
`rtc_video_encoder.cc` (lines 551-562): with the features off, the modes with two and three temporal
layers are left out of what an H.265 hardware encoder offers to WebRTC, and a request for them is
refused. It matters only when a page sends H.265 in a call, asks for these modes, and the PC's
hardware encoder reports them. The video is then sent with one layer. Inferred: nobody notices in
ordinary calls. The run that shows it: `RTCRtpSender.getCapabilities('video')` on a PC with an H.265
hardware encoder, the `scalabilityModes` of the H.265 entry, with and without.

**The way out: drop it.** Thoron then has Chromium's default, which Chromium itself has not turned on.
If the same behaviour as Thorium is wanted later, it is configuration only: a Thoron patch that sets
the two defaults to `base::FEATURE_ENABLED_BY_DEFAULT`, the way `ks-native-gpc.patch` turns on another
Chromium feature. There is one way to write that, so it will be the same two lines; nobody's design is
in them. Sure: high that the loss is this narrow; not run.

## 3. `llvm-optimized-toolchain-build.patch`

**What it changes.** One file, `tools/clang/scripts/build.py`, the script that builds Clang and LLD
from LLVM's source. 31 hunks, 235 lines added, 97 removed. About 140 added lines are option strings
for other tools (configuration), about 95 are script code. The designed parts are the mimalloc step
(about 50 lines) and the four-way split of the final build.

| Hunks | What they do |
|---|---|
| 1, 4, 15 | New step: download mimalloc 3.1.4, build it, link it into the compiler |
| 2 | `git clean` also removes untracked folders |
| 3, 5, 23, 24 | The same optimization options for libxml2, zstd and the runtime libraries: O3, tuning for one CPU family, unused sections removed, identical code folded |
| 6, 7, 8, 10, 12, 25 | Removes the options for the inliner model, position-independent code and "without zstd", and the old block that embedded the model |
| 9 | Refuses to run unless on Linux, with `--bootstrap`, without `--skip-checkout` |
| 11, 13, 14, 16, 30 | Default flags for every stage; Polly added; position-independent code, zstd always on; language bindings off |
| 17, 18, 19, 20 | Polly in the bootstrap and the instrumented compiler; more options for the training compile |
| 21, 22 | The final build: inliner and register allocation models always embedded; four option sets by profile use and ThinLTO |
| 26, 27, 28, 29 | BOLT: full instrumentation, the compiler's profile reused in training, more passes |
| 31 | Links `clang++` and `clang-cl` to `clang` at the end |

**Where it comes from.** Not from Chromium_Clang, with which it shares no line. It is from
RobRich999's other repository: 83 of the 235 added lines (54 of the 127 longer ones) are identical to
lines added by
[`llvm-avx2.patch`](https://github.com/RobRich999/LLVM_Optimized_AVX2/blob/1a9f41c9d3eb10835a1583bbda0d319ab11b61a8/llvm-avx2.patch)
of LLVM_Optimized_AVX2, and 137 are once the tuning option, a warning switch and spacing are ignored:
where his patch requires the AVX2 level, upstream tunes for a CPU family instead (upstream's own note
in
[`docs/PATCHES.md`](https://github.com/gz83/thorium/blob/efc0fffc256e7402ad4c3dc38ae1e5754221c03d/docs/PATCHES.md)).
The rest are the same steps reworded.
That repository has no licence either. The script itself is Chromium's (BSD-3-Clause), and its own
options `--pgo`, `--thinlto` and `--bolt` exist without the patch.

**What is lost.** Nothing in any Thoron build, checked:

- The patch changes this one script. No other patch touches the script or uses Polly.
- The script runs only when somebody builds a compiler. Upstream offers `infra/build_llvm.py` for
  that as a separate step.
- Thoron's builds take Chromium's prebuilt compiler: `gclient runhooks` in
  [`docs/build/WINDOWS.md`](../build/WINDOWS.md) and [`LINUX.md`](../build/LINUX.md); the stamp in the
  build tree, `third_party/llvm-build/Release+Asserts/cr_build_revision`, is the revision named in
  `tools/clang/scripts/update.py` (lines 43-44); the tree has no `third_party/llvm` source.
- With the patch applied the script refuses to run on Windows.

**The way out: drop it.** Sure: high. A compiler of Thoron's own would be a project of its own, started
from Chromium's unchanged script and judged by Thoron's benchmarks.

## 4. `enable-mpeg2-ac3-eac3-decoding.patch`

**What it changes.** 3 files, 6 hunks, 14 lines added, 5 removed: 2 list entries, 1 copyright line and
11 lines of glue. Nothing in it is designed; each line sits where Chromium's code asks for it.

| Hunk | File | What it does |
|---|---|---|
| 1 | `media/base/supported_types.cc` | "Can this build decode AC-3 and E-AC-3?" is answered yes whenever FFmpeg is built in, before the system's decoders are asked |
| 2 | same | MPEG-2 video moves from "not supported" to "supported" |
| 3 | `media/ffmpeg/ffmpeg_common.cc` | AC-3 and E-AC-3 are mapped to FFmpeg's codec numbers |
| 4 | same | Both are added to the audio decoders FFmpeg may open |
| 5 | `media/filters/ffmpeg_glue.cc` | Copyright line |
| 6 | same | Both are added to the file formats FFmpeg may open (bare `.ac3` and `.eac3` streams) |

**Where it comes from.**

- RobRich999: no line. The patch shares nothing with Chromium_Clang; his name stands only in the
  copyright line of hunk 5.
- Muril-o: the four lines of hunk 3 (two `case`, two `return`) are identical to
  [his Chromium patch](https://github.com/Muril-o/electron-chromium-codecs/blob/33c8013764a1f7dcc39ff32a9a4bff2a8c56ae61/v29.1.4/look_chromium_hevc_ac3.patch);
  three more shared lines are a bare `return true;` and a `case` label. The four lines mirror
  Chromium's own mapping in the other direction in the same file (lines 137-141), and the names in them
  are Chromium's and FFmpeg's.
- Chromium itself: the build argument `enable_platform_ac3_eac3_audio = true`, already in Thoron's
  arguments ([`RELEASE_ARGS.md`](../build/RELEASE_ARGS.md)), brings the MIME types, the demuxing, and
  on Windows decoding through the system's Dolby decoder where there is one
  (`media/mojo/services/gpu_mojo_media_client_win.cc`, lines 80-102).
- The decoders inside FFmpeg come from another patch, `add-ac3-eac3-ffmpeg-decoders.patch`, Thorium's
  own (BSD-3-Clause). Checked in `third_party/ffmpeg/chromium/config/Chrome/win/x64/config_components.h`:
  the AC-3 and E-AC-3 decoders, parser and demuxers are on.

**What is lost.** Read in the tree, not run.

- AC-3 and E-AC-3 sound: without hunks 1, 3 and 4 FFmpeg may not open these decoders. On Windows the
  sound then plays only where the system has a Dolby decoder, and Chromium's own comment says that
  Windows 11 from build 25992 no longer ships one (`gpu_mojo_media_client_win.cc`, lines 81-85). On
  Linux nothing decodes it (inferred: the support question is still answered yes, then playback fails).
  This is the sound track of many local films and TV recordings in MP4 and MKV files. Web video is
  rarely affected.
- Bare `.ac3` and `.eac3` files no longer open (hunk 6).
- MPEG-2 (hunk 2): nothing is lost, the line has no effect. FFmpeg is built without an MPEG-2 video
  decoder (`CONFIG_MPEG2VIDEO_DECODER 0`), `FFmpegVideoDecoder::IsCodecSupported` accepts only H.264
  and H.265 (`media/filters/ffmpeg_video_decoder.cc`, lines 119-123), and nothing in `media/` ever
  produces the MPEG-2 codec value. The line only makes a support question answer yes for video that
  cannot play.
- The run that shows it: an MP4 file with an AC-3 and an E-AC-3 track on Linux and on a Windows 11
  without a Dolby decoder, with and without; `MediaSource.isTypeSupported('audio/mp4; codecs="ac-3"')`.

**The way out: write it again as a Thoron patch from this specification.** The loss is real, the
change is four small edits, and no author's choices are needed for it.

*Given:* a build with `enable_platform_ac3_eac3_audio = true`, proprietary codecs, and an FFmpeg that
contains the AC-3 and E-AC-3 decoders (the Thorium patch above).

1. The function that tells whether this build can decode AC-3 or E-AC-3 answers yes when the bundled
   FFmpeg is part of the build, without asking the system's decoders. A build without FFmpeg keeps
   Chromium's behaviour.
2. The conversion from Chromium's audio codec value to FFmpeg's codec number knows AC-3 and E-AC-3,
   only when the platform AC-3 build flag is on. The opposite conversion exists already.
3. In builds with proprietary codecs, the list of audio decoders FFmpeg may open holds both.
4. In builds with proprietary codecs, the list of file formats FFmpeg may open holds the bare AC-3 and
   the bare E-AC-3 stream.

*Not part of it:* MPEG-2 video; any name in a copyright line other than Thoron's own.

*Done when:* an MP4 with one AC-3 and one E-AC-3 track plays with sound on Linux and on Windows
without a system Dolby decoder; a bare `.ac3` file plays; `isTypeSupported` answers yes for `ac-3` and
`ec-3`; no support question answers yes for MPEG-2 video. The header says `Origin: Thoron`, and
`CREDITS.md` keeps crediting Thorium and electron-chromium-codecs for the idea.

Said plainly: the new lines will look much like the old ones, because Chromium's code leaves one place
and one form for each. That is what glue is. Sure: fairly high that this is clean; it is not a legal
opinion. The other ways: drop it and rely on the system's decoder (Windows only, and not on new Windows
11 installs), or ask Muril-o whether the LGPL file covers his patches (LGPL-2.1 code may be used in a
GPL-3.0 release, but the repository has not changed since 2024, so an answer is uncertain).

## 5. `disable-encryption.patch`

**What it changes.** 6 files, 18 hunks, 60 lines added, 6 removed: 6 copyright lines, 6 includes, and
48 lines of C++ in 9 small blocks that each test a command-line switch and leave early.

| File (hunks) | What it does |
|---|---|
| `components/metrics/machine_id_provider_nonwin.cc` (3), `machine_id_provider_win.cc` (3) | With `--disable-machine-id` the browser says it has no machine id and returns an empty one |
| `services/preferences/tracked/device_id_win.cc` (2) | With `--disable-machine-id` the id that signs protected settings is "not implemented", so the signatures no longer depend on the PC |
| `components/os_crypt/async/browser/dpapi_key_provider.cc` (3), `os_crypt_win.cc` (4) | With `--disable-encryption` Windows' data protection is skipped: what would be encrypted is stored as it is |
| `services/preferences/tracked/tracked_split_preference.cc` (3) | **The part in question:** a name in the copyright line, an include, and one condition of 6 lines: with `--disable-machine-id`, `--disable-encryption` or `--revert-from-portable`, a protected setting that fails its check is not reset |

**Where it comes from.**

- The first five files: ungoogled-chromium-windows'
  [`windows-disable-machine-id.patch`](https://github.com/ungoogled-software/ungoogled-chromium-windows/blob/f85bc55429/patches/ungoogled-chromium/windows/windows-disable-machine-id.patch)
  and
  [`windows-disable-encryption.patch`](https://github.com/ungoogled-software/ungoogled-chromium-windows/blob/f85bc55429/patches/ungoogled-chromium/windows/windows-disable-encryption.patch)
  (BSD-3-Clause), reworked by Thorium (BSD-3-Clause). They are not in question.
- The part: Supermium's commit
  [`697055c2`](https://github.com/win32ss/supermium/commit/697055c2e65074bf50d30c58e124ddfe293c3f8c)
  (8 lines in the same file), which Thorium's older records name. Three of the part's six lines are
  found only in Supermium; today the same condition stands there in the neighbouring file
  ([`general_features.patch`](https://github.com/win32ss/supermium/blob/bf7e71c95f9a5a9a3ae5206ef8274633255de50b/general_features.patch),
  lines 1414-1417). ungoogled-chromium-windows has nothing like it, and no other licensed project does.
- In Thoron's tree `--revert-from-portable` is read here and nowhere else; no patch of the series
  defines or documents it. In Supermium it is an entry on the flags page with a warning.

**What is lost.** Read in the tree, not run.

- The part acts on one setting: `extensions.settings`, the only one tracked per entry
  (`chrome/browser/prefs/chrome_pref_service_factory.cc`, lines 130-131). Its check is enforced on
  Windows and macOS only (lines 213-233 and 259-265). On Linux nothing is ever reset, so the part does
  nothing there.
- On Windows, entries whose signature no longer fits are removed
  (`tracked_split_preference.cc`, lines 117-149), which takes the extensions out of the profile.
  Signatures stop fitting when the signing id changes: the first start with `--disable-machine-id` on
  a profile made without it, and the first start without it on a profile made with it.
- With the part, under one of the three switches the entries are kept and signed again (lines 109-114
  and 151-160).
- So without it: a user who turns a profile into a portable one, or back, loses the installed
  extensions once. A profile always used with the switches is not affected: upstream's portable
  launchers pass both
  ([`windows-browser.cmd`](https://github.com/gz83/thorium/blob/efc0fffc256e7402ad4c3dc38ae1e5754221c03d/infra/portable/launchers/windows-browser.cmd)).
  Thoron's own portable launcher, `Thoron.exe`, passes neither: it adds only `--user-data-dir`
  (`components/thoron_update/launcher/thoron_launcher_win.cc`), so no Thoron package depends on the part.
- The part is half a solution in this tree. The other protected settings (home page, start pages,
  default search, pinned tabs) are checked in `tracked_atomic_preference.cc` (lines 83-89), which has no
  such condition, so they are reset in the same situation with or without the part.
- It also costs protection: while one of the switches is on the command line, extension settings that
  another program has changed are accepted. The check exists to stop that.
- The run that shows it: on Windows, a profile with two extensions, one start with
  `--disable-machine-id`, count the extensions, with and without the part.

**The way out: remove the part.** That is the name in the copyright line, the include and the
condition in `tracked_split_preference.cc`. Every line left is BSD-3-Clause and the patch can be
published. Reasons: no Thoron package uses the switches, the part covers one setting of many, and it
weakens a protection through a switch nobody documents. Sure: high for the licence, medium for what
users see (read, not run).

Thoron will need the behaviour once, in a better form: the design plans to import an upstream portable
folder ([design](../design/2026-11-07-thoron-design.md), "Importing an upstream portable folder",
ROADMAP **P4**). The specification for that work, or for an earlier rewrite if the owner wants one:

1. When a profile is being converted between a portable, PC-independent form and a normal one,
   protected settings whose signature does not fit are kept and signed again with the profile's new
   identity.
2. This holds for every protected setting alike, the single-value ones and the per-entry ones. It is
   decided in one place: where the result of a check becomes an action.
3. It happens only when the conversion is asked for by name (a switch of Thoron's own, or the
   importer), and for one start. Running with `--disable-machine-id` or `--disable-encryption` alone
   does not switch any check off.
4. That start shows the warning Thoron shows for switches that weaken security (ROADMAP **S.4**) and
   writes the names of the kept settings to the log.
5. The checks themselves and what they report do not change.

*Done when:* unit tests beside Chromium's tracked-preference tests show that with the request a changed
value is kept and gets a new signature, and without it is reset as in Chromium; a profile with
extensions and a home page keeps both across the conversion.

The third way is to ask win32ss: "May Thoron use and publish the change of Supermium commit 697055c2
(8 lines in `tracked_split_preference.cc`) under the BSD 3-Clause licence?" It is the owner's to send,
and only worth it if the old behaviour is wanted as it is.

## 6. `thorium-build-config-and-simd.patch`

**What it changes.** 7 files, 25 hunks, 386 lines added, 31 removed. All of it is build configuration
in GN; there is no program code. The designed part is Thorium's own: one setting,
`thorium_x86_profile`, from which the CPU instructions, the tuning and the package names follow (about
250 lines).

| File (hunks) | What it does |
|---|---|
| `build/config/BUILDCONFIG.gn` (4) | Copyright line; declares `is_thorium_build` and `thorium_x86_profile`; a plain build-host toolchain when the target needs AVX-512; adds the profile's flags to every target |
| `build/config/compiler_opt.gni` (1, new file) | The profile: checks the value, then sets instruction-set flags, tuning, floating-point contraction and the labels for installers and packages; declares `is_full_optimization_build` and `is_raspi` |
| `build/config/compiler/BUILD.gn` (12) | See the next table |
| `build/config/compiler_cpu_abi.gn` (2), `build/config/win/BUILD.gn` (1 of 4) | Remove Chromium's fixed SSE3 flag, which the profile now sets |
| `build/config/win/BUILD.gn` (3 of 4) | Copyright line; the linker merges string tails; `/PROFILE` is switched off |
| `build/toolchain/gcc_toolchain.gni` (1), `build/toolchain/linux/BUILD.gn` (1) | Rust's build tools and the build-host toolchain get no profile |

| Hunk in `compiler/BUILD.gn` | What it does | From RobRich999 |
|---|---|---|
| 1, 2 | Copyright line (it names him); import of the new file | - |
| 3 | Linux, Android, Fuchsia: every warning of the compiler, assembler, linker and Rust is silenced | 4 lines |
| 4, 5 | Floating-point contraction from the profile; a larger ThinLTO import limit on macOS | - |
| 6 | `thinlto_optimize_default`: in official x86 builds for Windows and Linux every target is optimized at link time at level 2, with code generation at level 3 and three optimizer options | 8 lines |
| 7 | `thinlto_optimize_max`: at level 2 also code generation at level 3 and eleven optimizer options | 24 lines |
| 8, 9 | Three new configs (instruction set, x86 tuning, ARM tuning) and their use | - |
| 10, 11, 12 | `optimize` and `optimize_max`: clang's O3 instead of O2 in full-optimization builds | 4 lines, also Chromium's own |

**Where it comes from.**

- 40 added lines are identical to lines of Chromium_Clang's
  [`Windows/win64-avx2.patch`](https://github.com/RobRich999/Chromium_Clang/blob/c687f786a141e7dd4518b04a628b49a46c6260e0/Windows/win64-avx2.patch)
  (from line 82) and
  [`Linux/linux64-avx.patch`](https://github.com/RobRich999/Chromium_Clang/blob/c687f786a141e7dd4518b04a628b49a46c6260e0/Linux/linux64-avx.patch)
  (lines 13-16 and from 63), as the last column shows.
- 4 of the 40, the O3 lines, are Chromium's own text as well: its config `optimize_speed` has the same
  two lines (`build/config/compiler/BUILD.gn`, lines 2910-2925). They are not in question.
- That leaves **36 lines**: the 4 that silence warnings, 4 that set the code generation level, and 28
  that name 11 optimizer options, each in a Windows and a Linux spelling.
- Every other line matches no compared project and is Thorium's own (BSD-3-Clause). Level 2 for every
  target in hunk 6 is his idea too, but the line that sets it is Chromium's.
- Elsewhere under a licence: each of the options belongs to LLVM and LLD themselves, which list them
  (`opt --help-hidden`); Chromium's file passes other options the same way (Chromium's own file, lines
  830 and 858). Link-time optimization at level 2 for the main targets is Chromium's own build
  argument, `thin_lto_enable_optimizations` (lines 119-128 and 1357-1363), already `true` in Thoron's
  arguments. The choice of these 11 options and their values is found only at RobRich999's.

**What is lost** without the 36 lines.

- The warning lines: the Linux build log shows warnings again. The build does not stop, because
  upstream's argument file sets `treat_warnings_as_errors = false`. Windows is not touched. The browser
  does not change. Checked.
- The optimizer lines: what stays is O3, link-time optimization at level 2, and the whole profile. What
  goes is code generation at level 3 during linking and the 11 options. They act on how far hot
  functions are inlined across files, on dead loops, on moving equal computations, on when a branch
  becomes a conditional move, and on aligning jumps to 32 bytes, which helps some Intel CPUs and costs
  size.
- What a user would notice is unknown. Inferred: a small difference in either direction. Only a
  measurement can tell: two release builds from one tree, one without the 36 lines, on the same PC with
  nothing else running; Speedometer 3, JetStream 2 and MotionMark (the suite of ROADMAP **Q.1**),
  start-up and memory with `tools/qa/bench.py`, the size of `chrome.dll`, the link time. A difference
  inside the suite's own spread from run to run counts as none.

**The way out: ask the author.** It is the owner's to send. Reasons to ask here and nowhere else:

- It is the one patch where the value is unknown and costly to find out (two release builds and the
  benchmark runs).
- A list of options cannot be "written again" in other words. A rewrite is either the same list or a
  new choice, and a new choice needs the same measurement.
- He has helped Thorium in public for years. A yes is likely, and one answer settles this patch and
  the origin of patches 1 to 3 for good.

What to ask, in his repository's issues or wherever he asks to be reached:

> Thoron is a fork of Thorium. Thorium carries lines from your Chromium_Clang patches: compiler and
> linker options in `build/config/compiler/BUILD.gn`. May Thoron use and publish these lines under the
> BSD 3-Clause licence, the licence of the Chromium files they change? A LICENSE file or one sentence
> in the README would settle it for every project that builds on your work; a written reply is enough
> for us.

The reply's link goes into [`PATCH_ORIGINS.md`](PATCH_ORIGINS.md) and the patch's header.

**Without a written yes when the release build is made:** take the 36 lines out. The patch is then
Thorium's and Chromium's text only (BSD-3-Clause) and can be published.

**Ready since 2026-11-22:** that patch, made by taking out exactly the 36 lines and nothing else of his, is
[`source/alternatives/thorium-build-config-and-simd.without-36-lines.patch`](../../source/alternatives/thorium-build-config-and-simd.without-36-lines.patch),
published, with its header saying Thorium and BSD-3-Clause. What went: the four lines of hunk 3 (back to
Chromium's own), and in `thinlto_optimize_default` (hunk 6) and `thinlto_optimize_max` (hunk 7) the link
step's code generation level and the eleven options, with the blocks that held only them, the Windows variable
that only they used (GN refuses an unused one) and the comment's words about the GVN exception, which went with
them. What stays: O3, link-time optimization at level 2 (Chromium's line), Thorium's SLP exception for AVX-512
and the whole profile. Checked: the whole series applies with it in that patch's place (151 of 151, the rebase
report), and GN generates the Windows release build with it (37,109 targets); not built or measured yet. Taking
it means putting it in the series in place of the patch, then step 5 below. Then measure as above. If the
loss matters, choose options anew, from LLVM's own list, by this specification:

1. Scope: official x86 and x64 builds for Windows and Linux, the link step of ThinLTO, both configs.
2. Code generation at link time runs at the highest level the linker offers.
3. An option is added only when Thoron's benchmarks show a gain beyond the spread from run to run, and
   no crash, on a release build. Candidates, named by what they do: jumps aligned so that none crosses
   or ends on a 32-byte boundary; more inlining of hot calls across files; removal of loops proven
   dead; moving equal computations up or down (LLVM is known to crash with it on 32-bit Linux, so not
   there); the limits that turn branches into conditional moves; moving instructions to avoid saving
   registers.
4. The AVX-512 Linux build keeps its existing exception.
5. No option that changes floating-point results.
6. Each option gets one comment line with the measured gain and the date; the measurement is kept
   under `docs/perf/`.
7. Warnings on Linux are not silenced as a whole. If the log is too long, single warnings are named.

Sure: high about which lines are his (line by line), low about their worth (not measured). Whether a
list of option names is protected at all is doubtful, which is one more reason why asking is the cheap
and clean way.

## Found in the wider inventory

The line comparison of [`PATCH_ORIGINS.md`](PATCH_ORIGINS.md) was run again on 2026-11-16 for all 158
patches of the series, against the four repositories above and the two others without a licence
(chromium-win64, chromium-patches). The method was not changed. What it and a reading of the tools
showed:

1. **The release script does not stop on a patch without a licence.** Its gate asks only that every
   licence in the inventory is named in `NOTICE` (`tools/release/release.py`, lines 393-396), and
   `NOTICE` names "NOT STATED" (line 51). Nothing in it looks at the withheld files.
   `patch_licenses.py` does fail on such a row, but it is run by hand. The new check below closes this
   once the release script calls it.
2. **The inventory is one patch behind and cannot be made again as it is.** The series has 158 patches,
   [`PATCH_LICENSES.md`](PATCH_LICENSES.md) has 157 rows (`ks-thoron-version.patch` is missing). A new
   run reports 2 UNKNOWN: `patch_licenses.py` reads a header only in a patch's first 40 lines (line 82),
   and the two ad blocker patches now carry theirs on lines 43-45 and 63-65. `patch_headers.py` reads
   the whole text before the diff (lines 31-37) and accepts them. The fix is to read the same text in
   both.
3. **A header wins over the research** in `patch_licenses.py` (lines 84-91). A header changed to a
   licence name would turn a NOT STATED row into a licensed one; only `patch_headers.py lint` would say
   so, and nothing runs the two together.
4. **Wrong repository for patch 3.** The inventory, `CREDITS.md` and `NOTICE` name Chromium_Clang; the
   code is in LLVM_Optimized_AVX2, which they do not list. Same author, no licence either, so the
   verdict stood.
5. **Patch 4's row is stricter than the source.** It says neither RobRich999 nor Muril-o publishes a
   licence. RobRich999 has no line in the patch, and Muril-o's repository carries the LGPL-2.1 text.
6. **Two patches name unlicensed authors in copyright lines but took their licence from upstream's
   one-line description** (they were among those not compared line by line):
   - `mini_installer.patch` (inventory: Thorium, BSD-3-Clause) names Hibiki Tachibana (chromium-win64),
     Shane Fournier (win32ss) and ltguillaume. Checked now: the 5 lines it shares with
     [Hibbiki's patch](https://github.com/Hibbiki/chromium-win64/blob/1e8c812330/patch/0001-Patch-installer-to-close-previous-browser-instance-o.patch)
     are Chromium's own (Chromium's own file `chrome/installer/setup/uninstall.cc`, lines 146-181), and
     it shares no line with Supermium. The step itself, closing the running browser before a
     system-wide install, follows Hibbiki's idea. No line needs to go.
   - `enable-hevc-ffmpeg-decoding.patch` (inventory: MIT) names RobRich999. Its lines in that file are
     the same in StaZhu's
     [MIT-licensed patch](https://github.com/StaZhu/enable-chromium-hevc-hardware-decoding/blob/027325135a/enable-hevc-ffmpeg-decoding.patch).
     No line needs to go.

   Both rows should say this instead of resting on upstream's description. A limit of the comparison:
   it finds identical lines, not code that was copied and then renamed.
7. **One "pending" is left**, in `CREDITS.md`, not in `NOTICE`: the Debian row still reads "see licence
   inventory (ROADMAP L.1)". No patch of the series names Debian as its origin, so the row can say so,
   as the Vanadium row does.
8. **Nothing else of weight.** No other patch has more than single lines found only in a repository
   without a licence: lines of Chromium's own idiom in a few patches, three one-number assignments in
   `thorium-2024-ui-core.patch` (Supermium has them too), and one setting, the compression option for
   the rpm package, in `thorium-linux-installer-packaging.patch` (Chromium_Clang has it too). The
   licences `CREDITS.md` states for the 14 other projects are the ones their repositories state today.

## The check

[`tools/legal/unlicensed_patches.py`](../../tools/legal/unlicensed_patches.py) keeps four records in
step: the inventory's rows marked NOT STATED, the research, the withheld files of `source/`, and the
sections of this page. It fails when a patch without a licence is not withheld, is in the overlay, or
has no section here; when anything else is withheld without a known reason; and when the inventory
holds an UNKNOWN.

```powershell
py -3 -I tools/legal/unlicensed_patches.py check
py -3 -I tools/legal/unlicensed_patches.py check --tree <series tree> --release
```

With `--tree` it also reads the series: every patch has a row, and a header says NOT STATED for exactly
these patches (today this names the patch of finding 2). With `--release` a patch that still has no
licence is itself a problem; this is the form for the release script.

## Done on 2026-11-16

- Patches 1, 2 and 3 left the series; their files are gone and their research rows removed.
- Patch 4 left the series. Its four edits were written again from the specification of section 4, as lines of Thoron's own patch (`other/ks-native-adblock-hook.patch`, each marked `// Thoron:`), without the MPEG-2 line. The build answers `MediaSource.isTypeSupported` as before for `ac-3` and `ec-3` and claims no MPEG-2 video. The playback run of section 4 (a file with an AC-3 and an E-AC-3 track) is not made yet.
- Patch 5 lost its part in `tracked_split_preference.cc`; its header and research row say ungoogled-chromium-windows and Thorium, BSD-3-Clause.
- The inventory was made again (154 patches, 0 UNKNOWN, 1 NOT STATED); `patch_licenses.py` reads a header up to the first file of a patch (finding 2); the release script runs `unlicensed_patches.py check` with `--release` (finding 1).
- `source/` is exported with two withheld files: the credentials (L.8) and patch 6.
- Left: patch 6 (section 6): the owner's question, or the 36 lines come out before the first release; findings 4 to 7 in `PATCH_ORIGINS.md` and `CREDITS.md`.

## Work order

In this order. The only wait, the author's answer, starts first and runs beside the rest.

1. **Owner:** send the question of section 6 to RobRich999, or decide not to.
2. **Drop patches 1, 2 and 3:** take their lines out of the series and their files out of the tree;
   remove their three rows from `tools/legal/patch_origins.tsv`. On Windows only patch 2 changes a
   compiled file.
3. **Patch 5:** remove the part in `tracked_split_preference.cc`; header and research row become
   ungoogled-chromium-windows and Thorium, BSD-3-Clause.
4. **Patch 4:** write the Thoron patch from the specification of section 4 and put it in the old one's
   place in the series; remove the old patch and its research row.
5. **Patch 6**, when the release build is prepared: with a written yes, keep the lines, name the reply
   in the header and the research row, and set the licence he gave. Without one, remove the 36 lines (the
   patch without them is ready, see section 6); header and research row become Thorium, BSD-3-Clause.
6. **One rebuild** for all of it, Windows then Linux; the smoke tests; the playback test of section 4;
   if the 36 lines went, the measurement of section 6.
7. **Tools:** read the same header text in `patch_licenses.py` as in `patch_headers.py` (finding 2);
   make the release script call `unlicensed_patches.py check --release` (finding 1).
8. **Records:** make the inventory again; export `source/` with the credentials patch as the only
   withheld file; correct `PATCH_ORIGINS.md`, `CREDITS.md`, `NOTICE` and `source/README.md` (findings
   4 to 7, and the six patches' new state).
9. **Close L.1** when `unlicensed_patches.py check --tree <series tree> --release` prints
   `0 problem(s)` and `NOTICE` has no component without a licence.
