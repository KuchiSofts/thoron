# Fewer Google contacts from a fresh profile (ROADMAP S.15)

The work order for the Chromium engineer: which contacts a fresh Thoron 158 profile makes with Google
without need, what in Chromium causes each one, and the smallest change that stops it. The measurement
itself, with every host and what Thoron keeps, is in [NETWORK.md](NETWORK.md) (ROADMAP **S.10**).

Status: measured 2026-11-16 on Thoron build 158.0.8127.3010 (Chromium 158.0.8127.30, Windows x64) with
[`tools/qa/netlog_hosts.py`](../../tools/qa/netlog_hosts.py). The changes were built on 2026-11-16 and
measured on that build ([section 7](#7-what-was-built-2026-11-16)); the sections before it say what was
found and how each change was tried.

How to read it:

- **Verified** means the measurement was repeated with the command-line switch (or the starting
  preference) shown, and the contact was gone, while every run without it had the contact. It proves
  that the named feature is the cause on this build. The change in the source tree (a default in a
  patch) is still to be made, and is measured again when it is built (section 5).
- **Proposed** means not measured: read from the source, or a design choice.
- File names and line numbers are those of Chromium 158.0.8127.30, read from the public Chromium
  repository at that tag. Every feature named here was also found by name in this build's `chrome.dll`.
  None of these Chromium files is touched by a patch under `source/overlay/` today, so each change is a
  new hunk and the line numbers hold in Thoron's tree.
- A feature is switched with `--enable-features=Name` or `--disable-features=Name`; in the source it is
  the `BASE_FEATURE(kName, ...)` line.

## 1. The contacts and what stops them

Seconds are counted from the start of the browser. 40 runs on fresh profiles were made; "every run"
means every one of them that did not carry the stop for that contact.

| # | What a fresh profile does | When | Cause in Chromium 158 | Smallest change | State |
|---|---|---|---|---|---|
| 1 | `optimizationguide-pa.googleapis.com`: `POST /v1:GetModels`, then 11 `GET /downloads` | 10 s to 15 s, every run | The optimization guide downloads Google's on-device models; feature `OptimizationHints` | `kOptimizationHints` off by default | Verified |
| 2 | `update.googleapis.com` (2 update checks) and `edgedl.me.gvt1.com` (1 download, plain HTTP) for the component `OptimizationGuideModelsManifest` | first 5 s, every run | The manifest of Google's on-device AI models is fetched at once, ahead of the component updater's schedule; no feature decides it | build with `use_on_device_model_service = false`, or a 3-line patch | Proposed |
| 3 | `accounts.google.com`: `POST /ListAccounts` | first 2 s, every run | The sign-in code asks Google which accounts the cookies belong to, also when there is no Google cookie; feature `SkipListAccountsWithoutGaiaCookies` (off) | `kSkipListAccountsWithoutGaiaCookies` on by default | Verified |
| 4 | `www.google.com`: `GET /async/folae` with the browser's country and language | first 2 s, every run | Google Search's "AI Mode" asks whether it may be offered; feature `AimEnabled` | `kAimEnabled` off by default | Verified |
| 5 | `www.google.com`: 2 connections without a request (name look-up, TCP, TLS) | first 3 s, every run; by the source renewed every minute while tabs are in use | The default search engine is connected to ahead of a search; feature `PreconnectToSearch` | `kPreconnectToSearch` off by default | Verified |
| 6 | `clients2.google.com`: `GET /time/1/current` (plain HTTP) | first 2 s, every run | Chromium asks Google's time service in the background; feature `NetworkTimeServiceQuerying`, parameter `FetchBehavior` | `FetchBehavior` default `on-demand-only` | Verified |
| 7 | `mail.google.com`: `GET /mail/u/0/feed/atom`, answered 401 | 15 s, then every 2 minutes, every run | Thoron's own M-Notifier looks for mail although nobody is signed in to Google; feature `ThoronMailNotifier` | do not look while the profile has no Google sign-in (section 2.7) | Proposed; the feature switch is verified |
| 8 | `clients2.google.com/service/update2/crx`, `clients2.googleusercontent.com`, `chromewebstore.googleapis.com` | first 4 s, on a PC where other programs registered extensions | Thoron reads Google Chrome's registry key for extensions installed by other programs | ROADMAP **P2.16** decides (section 2.8) | Cause verified; change proposed |
| 9 | With the New Tab page open: `www.google.com` (3 more requests), `www.gstatic.com` (3), `ogads-pa.clients6.google.com` (2) | first 2 s | The New Tab page is Google's while Google is the default search engine: its bar, its doodle, its suggestions | `kNtpOneGoogleBar` off by default; a patch for the doodle; a decision on suggestions (section 2.9) | Bar: verified. Suggestions: setting verified. Doodle: proposed |

With changes 1, 3, 4, 5 and 6 switched on together, a fresh profile contacted neither
`optimizationguide-pa.googleapis.com` nor `accounts.google.com` nor `www.google.com` in 330 s, and no
longer asked for the time (section 3).

## 2. Each contact

### 2.1 Optimization guide models (`optimizationguide-pa.googleapis.com`)

- **Seen.** One `POST /v1:GetModels` 10 s after start and 11 `GET /downloads` in the next 5 s, in every
  run; the profile then holds 11 folders in `optimization_guide_model_store`. The first request carries
  a Google API key in its address (`key=`), the downloads carry one in an `x-goog-api-key` header: the
  keys the upstream key patch compiles in (ROADMAP **L.8**).
- **Callers** (the log's traffic annotations): `optimization_guide_model`, defined in
  `components/optimization_guide/core/delivery/prediction_model_fetcher_impl.cc`, and
  `optimization_guide_model_download`, in
  `components/optimization_guide/core/delivery/prediction_model_download_manager.cc`.
- **Cause.** `BASE_FEATURE(kOptimizationHints, base::FEATURE_ENABLED_BY_DEFAULT);` in
  `components/optimization_guide/core/optimization_guide_features.cc`, line 60, read by
  `IsOptimizationHintsEnabled()` (line 254).
- **Change.** `FEATURE_DISABLED_BY_DEFAULT` on that line.
- **Verified.** `--disable-features=OptimizationHints`: no request to the host and an empty model
  store.
- **Does not work (measured).** `--disable-features=OptimizationTargetPrediction` (line 63 of the same
  file) and `--disable-features=OptimizationGuideModelExecution` (line 100): the same 12 requests.
- **Check when it is built (not measured).** These models feed other features: the page-language
  detection behind the offer to translate, the permission-prompt predictions, and Safe Browsing's
  on-device phishing check (ROADMAP **S.14**). Open a page in a foreign language and see that
  translation is still offered. If something a person needs is lost, the alternative is to keep the
  feature and stop single models, which is a larger patch. For Safe Browsing it is settled: the
  phishing model (number 25) no longer arrives, client-side phishing detection ends with it and is
  dropped, and the lists block as before ([SAFE_BROWSING.md](SAFE_BROWSING.md), section 3.5).
- **Also gone (measured).** The component `OptimizationHints`: with the switch, 17 components arrive
  in the profile instead of 18, and the component updater makes 18 update checks and 17 downloads
  instead of 20 and 19.

### 2.2 The manifest of Google's on-device AI models (`update.googleapis.com`, `edgedl.me.gvt1.com`)

- **Seen.** In the first 2 s of every run: `POST /service/update2/json` on `update.googleapis.com`
  and a download from `http://edgedl.me.gvt1.com/edgedl/diffgen-puffin/...`, then a second update check
  3 s to 5 s after start. 45 s after start the update client's record in `Local State` holds one
  component, `ceofaddefefcbblgcgnibnonglccbfja`, and the profile folder has
  `OptimizationGuideModelsManifest`. The component updater's regular checks begin only at 60 s.
- **Caller.** `update_client` (`components/update_client/net/network_impl.cc`).
- **Cause.** No feature is asked. `OptimizationGuideGlobalState`'s constructor
  (`chrome/browser/optimization_guide/model_execution/optimization_guide_global_state.cc`, line 169,
  inside `#if BUILDFLAG(USE_ON_DEVICE_MODEL_SERVICE)`) always makes a `ManifestBrokerState`; its
  `ManifestMonitor` calls `ListenForManifestReady()` in its constructor
  (`components/optimization_guide/core/model_execution/manifest_broker/manifest_monitor.cc`); and that
  ends in `ManifestAssetManagerDelegateImpl::MaybeRegisterManifestComponent()`
  (`chrome/browser/component_updater/optimization_guide_on_device_model_installer.cc`, line 531), which
  registers the component (its id is in the comment on line 88) and asks for it at once with
  `OnDemandInstall(..., OnDemandUpdater::Priority::FOREGROUND)`. Whether on-device AI is allowed is
  looked at only after the manifest has arrived.
- **Proposed change,** one of:
  1. Build without the service: `use_on_device_model_service = false`
     (`services/on_device_model/on_device_model.gni`, line 17, is true on Windows, macOS and Linux). The
     constructor's other branch then makes "a stub capability that can't do anything". It belongs in
     `docs/build/RELEASE_ARGS.md` and fits ROADMAP **S.16**: the manifest lists the models of Google's
     built-in AI, which Thoron does not offer.
  2. Or a patch: let `MaybeRegisterManifestComponent()` return without registering anything.
- **Not verified.** Neither can be tried with a switch; both need a build. The check is in section 5.
- **Does not work (measured).** `--disable-features=OptimizationHints`,
  `--disable-features=OptimizationGuideManifestBroker` and
  `--disable-features=OptimizationGuideModelExecution`: the component arrives all the same.
  `--disable-component-update` stops it, together with every other component.

### 2.3 Google sign-in check (`accounts.google.com`)

- **Seen.** `POST /ListAccounts` in the first 2 s of every run, answered 200. The profile has no
  Google cookie, so the answer can only be "no accounts".
- **Caller.** `gaia_auth_list_accounts` (`google_apis/gaia/gaia_auth_fetcher.cc`).
- **Cause.** `GaiaCookieManagerService::MaybeStartFetchingListAccounts()` in
  `components/signin/internal/identity_manager/gaia_cookie_manager_service.cc` (line 879). Chromium 158
  already has the fix behind a feature that is off: with `SkipListAccountsWithoutGaiaCookies` the
  function first reads the cookies for Google's sign-in address and, when there are none, answers "no
  accounts" itself (`OnGaiaCookiesForListAccounts`, line 898) without asking Google.
- **Change.** `BASE_FEATURE(kSkipListAccountsWithoutGaiaCookies, base::FEATURE_DISABLED_BY_DEFAULT);`
  in `components/signin/public/base/signin_switches.cc`, line 943: `FEATURE_ENABLED_BY_DEFAULT`.
- **Verified.** `--enable-features=SkipListAccountsWithoutGaiaCookies`: no request to
  `accounts.google.com`.
- **Does not work (measured).** `--allow-browser-signin=false`, and a profile that starts with the
  preferences `signin.allowed` and `signin.allowed_on_next_startup` set to false: the request is sent
  all the same.
- **Nothing is lost.** Once a person signs in to a Google site the cookie exists and the check runs as
  before, so sign-in, sync and the M-Notifier keep working.

### 2.4 "AI Mode" eligibility (`www.google.com/async/folae`)

- **Seen.** `GET /async/folae` in the first 2 s of every run, answered 200; in 2 runs a second one
  within a second. The address carries `client_country` and `client_locale`, so Google is told the
  browser's country and language, and a header carries the full browser version list.
- **Caller.** `aim_eligibility_fetch` (`components/omnibox/browser/aim_eligibility_service.cc`).
- **Cause.** `AimEligibilityService` asks Google whether Google Search's "AI Mode" may be offered in
  this browser: at start, and again whenever the list of signed-in accounts is refreshed.
- **Change.** `BASE_FEATURE(kAimEnabled, base::FEATURE_ENABLED_BY_DEFAULT);` in
  `components/omnibox/browser/aim_eligibility_service_features.cc`, line 11:
  `FEATURE_DISABLED_BY_DEFAULT`. The service's constructor then returns before it sets anything up
  (`aim_eligibility_service.cc`, line 326), and `IsAimAllowedByFeatureAndPolicy()` (line 440) answers
  no, so AI Mode is not offered anywhere. This matches `other/disable-ai-entrypoints-by-default.patch`.
- **Verified.** `--disable-features=AimEnabled`: no request to `www.google.com`.
- **Does not work (measured).** Each of these still sent the request:
  `--disable-features=AimServerRequestOnStartupEnabled` (it then came a little later, after the account
  list); the same with `AimServerRequestOnIdentityChangeEnabled` added; the same with
  `--enable-features=SkipListAccountsWithoutGaiaCookies` added; and
  `--disable-features=AimServerEligibilityEnabled`. The last one is also unsafe: by the source (line
  470) the browser then stops waiting for Google's answer and decides by itself.
- **Not measured.** The policy `AIModeSettings`: setting a policy needs the machine's registry, which a
  test must not touch.

### 2.5 Connection to the search engine ahead of a search (`www.google.com`)

- **Seen.** With change 4 alone, `www.google.com` is still looked up and connected to: the log has two
  connections marked `is_preconnect` to `https://www.google.com/` in the first 3 s of every run. No
  request is sent on them, but Google's server sees the PC's address. They are made with credentials
  allowed, so a request on them would carry cookies.
- **Caller.** `SearchEnginePreconnector`
  (`chrome/browser/navigation_predictor/search_engine_preconnector.cc`). By the source it runs only for
  a default search engine whose data allows it (`preconnect_to_search_url`) and while "Improve search
  suggestions" is on, and it renews the connection every 60 s (`kPreconnectIntervalSec`, line 106) while
  a tab was shown or changed in the last 2 minutes. The renewals were not seen: the test browser has no
  window.
- **Change.** `BASE_FEATURE(kPreconnectToSearch, base::FEATURE_ENABLED_BY_DEFAULT);` on line 147:
  `FEATURE_DISABLED_BY_DEFAULT`. The first search of a session then takes one connection set-up longer.
- **Verified.** `--disable-features=AimEnabled,PreconnectToSearch`: `www.google.com` is not in the log
  at all in 130 s. The setting also works: a profile that starts with `search.suggest_enabled` false
  ("Improve search suggestions" off) and `--disable-features=AimEnabled` has no `www.google.com` either.
- **The owner decides.** This one trades a little speed for a contact a minute. It is listed because
  ROADMAP S.15 names the `www.google.com` requests and the host stays in the tool's list without it.

### 2.6 Google's time service (`clients2.google.com/time/1/current`)

- **Seen.** One `GET http://clients2.google.com/time/1/current` in the first 2 s of every run, over
  plain HTTP (the answer is signed, so it cannot be forged, but anyone on the path sees the request).
- **Caller.** `network_time_component` (`components/network_time/network_time_tracker.cc`).
- **Cause.** `BASE_FEATURE(kNetworkTimeServiceQuerying, base::FEATURE_ENABLED_BY_DEFAULT);` (line 77)
  with the parameter `kFetchBehavior` (line 116) at `FETCHES_IN_BACKGROUND_AND_ON_DEMAND`. The comment
  above it calls "on-demand-only" the default; the code says otherwise.
- **Change.** Line 118: `NetworkTimeTracker::FETCHES_ON_DEMAND_ONLY`. The browser then asks for the
  time only when something calls `StartTimeFetch()`; in the 158 tree that is the handling of a
  certificate whose date looks wrong (`SSLErrorHandler::HandleCertDateInvalidError()`,
  `components/security_interstitials/content/ssl_error_handler.cc`, line 968), so the "your clock is
  wrong" page keeps working.
- **Verified.** `--enable-features=NetworkTimeServiceQuerying:FetchBehavior/on-demand-only`: the time
  request is gone. `--disable-features=NetworkTimeServiceQuerying` removes it too, but also the
  on-demand check.
- **Not measured.** The preference `network_time.network_time_queries_enabled` (in `Local State`,
  registered on line 309) and its policy `BrowserNetworkTimeQueriesEnabled`.

### 2.7 Thoron's own mail check (`mail.google.com`)

- **Seen.** `GET /mail/u/0/feed/atom` 15 s after start and every 2 minutes after that (15 s, 135 s,
  255 s ...), each answered 401, in every run. A person who never uses Gmail has a browser that tells
  Google it is running every two minutes.
- **Caller.** `thoron_mail_feed`, Thoron's own (`components/thoron_mail/mail_service.cc` in
  `other/ks-native-adblock-hook.patch`).
- **Cause.** `BASE_FEATURE(kThoronMailNotifier, base::FEATURE_ENABLED_BY_DEFAULT);`:
  `MailService::Start()` sets a timer of `kFirstLook` (15 s), `MailService::Fetch()` asks without
  looking whether there is a sign-in, and `MailService::Reschedule()` repeats it after every answer,
  also after a refusal.
- **Proposed change.** The owner decides; the notifier is the owner's design. Smallest first:
  1. Look only while Chromium's own list of signed-in Google accounts has an entry
     (`signin::IdentityManager::GetAccountsInCookieJar()`), and start looking when
     `OnAccountsInCookieUpdated` reports one. With change 3 that list is empty without any request while
     there is no Google cookie, so a profile nobody signed in to Google with asks Google nothing; after a
     sign-in the first look comes at once.
  2. Simpler, less exact: in `MailService::CheckNow()` read the profile's cookies for the feed's address
     first and finish with "signed-out" when there are none. A cookie that is not a sign-in (any Google
     page sets one) lets the request through again.
  3. Besides either: after a 401, stop the timer until a Google cookie changes or the person opens the
     notifier's menu.
  4. Or leave the notifier off until the person switches it on.
- **Verified.** `--disable-features=ThoronMailNotifier` (the flag
  `chrome://flags/#thoron-mail-notifier`): no request to `mail.google.com`. The proposed changes are
  not built, so they are not measured.

### 2.8 Extensions other programs registered for Google Chrome (ROADMAP P2.16)

- **Seen where other programs have registered extensions for Google Chrome.**
  `GET /service/update2/crx` on `clients2.google.com`, an extension file from
  `clients2.googleusercontent.com`, and `POST /v2/items/<id>:fetchItemSnippet` on
  `chromewebstore.googleapis.com`, all in the first 4 s. The profile's extension settings then hold
  entries that Thoron does not ship (location 3: registered with a file; location 6: registered with
  an update address, so it is downloaded), disabled with reason 8192, which is "waiting for the person
  to approve". So before anybody approves anything, Google is told which extensions other software
  put on the PC.
- **Callers.** `extension_manifest_fetcher` and `extension_crx_fetcher`
  (`extensions/browser/updater/extension_downloader.cc`), `cws_fetch_item_snippet`
  (`extensions/browser/webstore_data_fetcher.cc`).
- **Cause.** `chrome/browser/extensions/external_registry_loader_win.cc`, line 38:
  `kRegistryExtensions[] = L"Software\\Google\\Chrome\\Extensions"`. Thoron reads the key that
  installers fill for Google Chrome. `Extensions\external_extensions.json` in Thoron's own folder is
  empty.
- **Verified.** A profile that starts with the preference `extensions.block_external_extensions` set to
  true (what the policy `BlockExternalExtensions` sets; read in
  `chrome/browser/extensions/external_provider_impl.cc`, line 884) sends none of the three, and neither
  does `--disable-extensions`. A PC without such registry entries is expected to send none either;
  that is inferred, not measured.
- **Proposed, for P2.16 to decide.** Either read a key of Thoron's own instead of Google Chrome's, or
  keep reading it but ask Google nothing until the person approves the extension.

### 2.9 The New Tab page (`www.google.com`, `www.gstatic.com`, `ogads-pa.clients6.google.com`)

The tool opens a local page, so the contacts above are those of the browser itself. A person's first
window shows the New Tab page, and one run with it (`--page chrome://newtab/`, 120 s) had these on top,
all in the first 2 s:

- **The bar at the top of the page** (Google's account and apps buttons). `GET /async/newtab_ogb` on
  `www.google.com`, caller `one_google_bar_service`
  (`chrome/browser/new_tab_page/one_google_bar/one_google_bar_loader_impl.cc`); then, loaded by the bar
  itself, a script, a style sheet and the Google logo from `www.gstatic.com` and 2 requests to
  `ogads-pa.clients6.google.com`. **Change:** `BASE_FEATURE(kNtpOneGoogleBar, ...)` in
  `components/search/ntp_features.cc`, line 178 ("This is a kill switch"): `FEATURE_DISABLED_BY_DEFAULT`
  for desktop as it already is for Android. **Verified:** with `--disable-features=NtpOneGoogleBar` the
  request is gone and the two other hosts are not contacted at all.
- **Suggestions for the empty search box.** `GET /complete/search` on `www.google.com`, caller
  `omnibox_zerosuggest` (`components/omnibox/browser/remote_suggestions_service.cc`). **Verified:** a
  profile that starts with `search.suggest_enabled` false ("Improve search suggestions" off) does not
  send it. Whether that setting should be off in a new Thoron profile is the owner's decision: by
  Chromium's design it also ends the suggestions while typing (not measured), and it ends the
  connection of 2.5 (measured).
- **The doodle.** `GET /async/ddljson` on `www.google.com`, caller `logo_service`
  (`components/search_provider_logos/logo_service_impl.cc`). `NewTabPageHandler::GetDoodle()`
  (`chrome/browser/ui/webui/new_tab_page/new_tab_page_handler.cc`, line 617) asks every time the page
  opens, whatever the features say. **Does not work (measured):** `--disable-features=NtpLogo`.
  **Proposed:** a patch that lets `GetDoodle()` answer "no doodle" without asking, unless a feature of
  Thoron's own is on.
- **More connections ahead of a request:** 4 instead of 2; change 5 covers them.

With changes 4 and 5, the bar's switch and the suggestion preference together, the New Tab page run had
one request to `www.google.com` left, the doodle's.

## 3. All changes together

One run of 330 s with the five verified changes as switches, next to the three runs of 240 s without
them (NETWORK.md, section 2):

```powershell
py -3 -I tools/qa/netlog_hosts.py --browser <out dir>\thoron.exe --work <scratch folder> --seconds 330 `
    --switch=--disable-features=OptimizationHints,AimEnabled,PreconnectToSearch `
    --switch=--enable-features=SkipListAccountsWithoutGaiaCookies,NetworkTimeServiceQuerying:FetchBehavior/on-demand-only `
    --absent optimizationguide-pa.googleapis.com --absent accounts.google.com --absent www.google.com
```

It ended with status 0: none of the three hosts is anywhere in the log.

| Host | Without the switches | With them |
|---|---|---|
| `optimizationguide-pa.googleapis.com` | 12 requests | none |
| `accounts.google.com` | 1 request | none |
| `www.google.com` | 1 request and 2 connections ahead | none, and not looked up |
| `clients2.google.com` | 2 requests: the time, and the extension update check | 1 request: the extension update check (change 8) |
| `update.googleapis.com` | 22 update checks, 2 of them in the first 5 s | 20, still 2 of them in the first 5 s (change 2) |
| `edgedl.me.gvt1.com` | 20 or 21 downloads, 1 or 2 of them in the first 5 s | 18, still 1 in the first 5 s (change 2) |
| `mail.google.com` | every 2 minutes, answered 401 | the same (change 7) |
| `clients2.googleusercontent.com`, `chromewebstore.googleapis.com` | 1 and 2 requests | the same (change 8) |
| `safebrowsing.googleapis.com` | 1 request | the same (ROADMAP **S.14**) |
| `ublockorigin.github.io`, `malware-filter.gitlab.io` | 7 and 1 requests | the same (kept) |

**Nothing at all.** A second run of 330 s added what switches off the rest:
`--disable-features=ThoronMailNotifier,ThoronNativeAdblock`, `--disable-component-update`, and the
starting preferences `extensions.block_external_extensions` true and `safebrowsing.enabled` false. Its
log names no outside host at all; only `wpad` was looked up on the local network. So every contact of a
fresh profile has a known cause and a known stop, and what stays after S.15 stays by choice.

## 4. What stays, and why

These are not part of this work order:

| Contact | Why it stays |
|---|---|
| `update.googleapis.com` from 60 s on, and the component downloads | The component updater brings security data: certificate revocations, the certificate transparency log list, the file type rules for downloads. Which components Thoron wants is a later review; `--disable-component-update` stops all of them (verified) and is too blunt as a default |
| `safebrowsing.googleapis.com` | ROADMAP **S.14**: kept, in a build with a key Thoron owns, and off in a build without one ([SAFE_BROWSING.md](SAFE_BROWSING.md)) |
| `ublockorigin.github.io`, `malware-filter.gitlab.io` | Thoron adblock's filter lists: the blocking a person wants, fetched without cookies |

## 5. Checking a build

When the changes are built, the same tool is the test of S.15: it exits with status 1 when a host
named with `--absent` was contacted, looked up or connected to. On today's build it fails as it should:
a run with `--absent accounts.google.com` ended with status 1 and the line "contacted although
--absent: accounts.google.com".

```powershell
py -3 -I tools/qa/netlog_hosts.py --browser <out dir>\thoron.exe --work <scratch folder> --seconds 130 `
    --runs 3 --label "Thoron <version>" `
    --absent optimizationguide-pa.googleapis.com --absent accounts.google.com --absent www.google.com
```

Add `--page chrome://newtab/` for a second pass with the New Tab page, and there also
`--absent www.gstatic.com --absent ogads-pa.clients6.google.com`.

`clients2.google.com`, `update.googleapis.com` and `mail.google.com` cannot be tested by host alone
while other requests to them stay. Read the report instead: no `network_time_component` in "Asked by",
no request to `update.googleapis.com` before 60 s and no `OptimizationGuideModelsManifest` among the
components, and no `thoron_mail_feed` while nobody is signed in.

To try one change before building it:

```powershell
py -3 -I tools/qa/netlog_hosts.py --browser <out dir>\thoron.exe --work <scratch folder> --seconds 45 `
    --switch=--enable-features=SkipListAccountsWithoutGaiaCookies --absent accounts.google.com
```

## 6. Open points

Points 1 to 3 were settled with the build ([section 7](#7-what-was-built-2026-11-16)).

1. **Three decisions for the owner:** the connection to the search engine ahead of a search (2.5),
   what the M-Notifier does while nobody is signed in to Google (2.7), and whether "Improve search
   suggestions" starts off (2.9).
2. **Two changes need a build** before they can be measured: the manifest of the on-device AI models
   (2.2), where the engineer chooses between the build argument and the patch, and the doodle request
   (2.9).
3. **Change 1 may take features with it** (2.1); they are checked on the built browser.
4. **Which components the updater should fetch** is not decided here. NETWORK.md, section 4, lists the
   18 that arrive in a fresh profile. A later review can drop those Thoron has no use for.
5. **Not measured:** policies, a visible window with the first-run page, and later starts of the same
   profile. The changes are measured again on the built browser (section 5).
6. **Extensions from Google Chrome's registry key** (2.8) wait for ROADMAP **P2.16**.

## 7. What was built (2026-11-16)

The changes are in the browser's source (`source/`, patch `other/ks-native-adblock-hook.patch`) and were
measured on the build that holds them, with the commands of section 5.

| Contact | What was built | Differs from the proposal |
|---|---|---|
| Optimization guide models (2.1) | `OptimizationHints` is off | A page's language is found by the built-in detector (CLD3): the other detector needs a model from this service, and without it only the language a page declares was used. Client-side phishing detection ends with its model ([SAFE_BROWSING.md](SAFE_BROWSING.md), 3.5) |
| On-device AI model manifest (2.2) | The component is registered only once on-device AI is switched on (the local setting, which is also on when a model is installed); until then the setting is watched | A patch, not the build argument |
| Sign-in check (2.3) | `SkipListAccountsWithoutGaiaCookies` is on | No |
| "AI Mode" (2.4) | The request is not made while nobody is signed in to Google in the profile | The feature stays on for a signed-in profile |
| Search preconnect (2.5) | `PreconnectToSearch` is off | No |
| Time service (2.6) | On demand only | No |
| Thoron's mail check (2.7) | Gmail is asked only while the browser's list of signed-in Google accounts has an entry, and at once when one appears; other mailboxes are looked at as before | Choice 1 of the proposal |
| Google's bar on the New Tab page (2.9) | Asked for only while somebody is signed in to Google | The bar stays for a signed-in profile; `NtpOneGoogleBar` stays on |
| Suggestions for the empty box (2.9) | Not fetched ahead while nobody is signed in to Google; asked for when the box is used | "Improve search suggestions" stays on |
| Doodle (2.9) | Not asked for while nobody is signed in to Google | No |

"Signed in to Google" is read from the browser's own list of the Google accounts in its cookies. The
browser keeps that list between starts and, with the sign-in check's change, makes it without a request
while there is no Google cookie. So a person who is signed in to Google loses nothing, and a profile
nobody signed in with asks Google nothing on its own account.

Measured on the build, one run each:

- **Local page, 240 s:** the log names none of `optimizationguide-pa.googleapis.com`,
  `accounts.google.com`, `www.google.com` and `mail.google.com`. There is no time request and no
  connection ahead of a request, and the component updater's first request comes at 60 s.
- **New Tab page, 150 s:** none of those four, `www.gstatic.com` or `ogads-pa.clients6.google.com`.
- **Left:** the extensions other programs register (2.8, ROADMAP **P2.16**), the component updater,
  Safe Browsing's list (ROADMAP **S.14**) and Thoron adblock's lists.

Two offline checks hold what a log of a fresh profile cannot show:
[`mail_signin_check.py`](../../tools/qa/mail_signin_check.py) (Gmail is asked with a Google account in the
browser's list and not without) and [`language_detect_check.py`](../../tools/qa/language_detect_check.py)
(a page's language is found with no model). Not checked by a run: the bar, the doodle and "AI Mode" of a
profile that is signed in to Google.
