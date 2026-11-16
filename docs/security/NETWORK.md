# Network contacts (ROADMAP S.10)

Every host a fresh Thoron profile contacts on its own: what in the browser asks for it, when and how
often, whether a fresh profile needs it, how it can be switched off, and what Thoron does about it.
Hosts a person reaches by browsing are not listed. The requests to Google that nobody needs are worked
out one by one in [NETWORK_REDUCTION.md](NETWORK_REDUCTION.md) (ROADMAP **S.15**).

**Since the build of 2026-11-16** a fresh profile no longer contacts
`optimizationguide-pa.googleapis.com`, `accounts.google.com`, `www.google.com` or `mail.google.com`, makes
no time request on `clients2.google.com`, and its New Tab page contacts neither `www.gstatic.com` nor
`ogads-pa.clients6.google.com` (measured, one run with the local page and one with the New Tab page;
NETWORK_REDUCTION.md, section 7). The tables below are those of the build before these changes and are
measured again before the first release.

## 1. What was measured, and what was not

- **Build.** Thoron build 158.0.8127.3010 (Chromium 158.0.8127.30), Windows x64, on 2026-11-16.
- **Method.** [`tools/qa/netlog_hosts.py`](../../tools/qa/netlog_hosts.py) starts the browser headless
  on a new throwaway profile with one page from 127.0.0.1 and Chromium's network log on, waits, stops
  it and reads the log. Nothing is typed or clicked and nobody is signed in. The measurement is online
  on purpose: the browser really reached the hosts below.
- **Runs.** 40 in all, one browser at a time, each on its own new profile: 3 runs of 240 s for the
  tables of section 2; one of 900 s and one with the New Tab page (section 4); 29 of 45 s to 330 s with
  a switch or a starting preference (section 5 and NETWORK_REDUCTION.md); and 6 more without a switch,
  which agree with the tables.
- **Measured** in the tables: the host, the number of requests, the seconds since the browser was
  started, the path asked for, the answer, and who asked. The last is the request's "traffic
  annotation": Chromium makes every caller of the network name itself, and the log holds that name's
  number. The file that defines each annotation is given in NETWORK_REDUCTION.md.
- **From the source, not from a run:** how often something repeats beyond the length of a run, and the
  purpose of a request. Where a statement is inferred, it says so.
- **Not measured:**
  - a visible window with the first-run page: the tool starts headless with `--no-first-run` and
    `--no-default-browser-check` (the New Tab page was measured, section 4);
  - more than the first 15 minutes of a profile, and a profile's later starts;
  - what a person starts: translation, search suggestions while typing, sign-in and sync, a spell-check
    dictionary, protected video (Widevine);
  - policies: setting one needs the machine's registry, which a test must not touch;
  - Linux.
- **One PC, one network.** No proxy was in use and no DNS-over-HTTPS server was contacted; names were
  resolved by the system.

## 2. Hosts of a fresh Thoron 158 profile

Seconds count from the start of the browser. "Measured" after a way to switch something off means that
a run with it no longer had the contact; "its preference measured" means the run started with the
preference the setting or policy writes.

| Host | Asked by | When and how often | Purpose | Does a fresh profile need it | Switching it off | Thoron's plan |
|---|---|---|---|---|---|---|
| `accounts.google.com` | `gaia_auth_list_accounts` | 1 request (`POST /ListAccounts`) in the first 2 s of every run | Chromium's sign-in code asks Google which Google accounts the profile's cookies belong to | No: the profile has no Google cookie | No setting. `--enable-features=SkipListAccountsWithoutGaiaCookies` (measured) | Remove (S.15) |
| `www.google.com` | `aim_eligibility_fetch` | 1 request (`GET /async/folae`) in the first 2 s of every run; in 2 runs a second one | Asks Google whether Google Search's "AI Mode" may be offered here; tells Google the browser's country and language | No | No setting. `--disable-features=AimEnabled` (measured); policy `AIModeSettings` (not measured) | Remove (S.15) |
| `www.google.com` | the search engine preconnector; no request is sent, so the log has no annotation | 2 connections in the first 3 s of every run; by the source renewed every 60 s while tabs are in use (not measured: the test browser has no window) | A connection to the default search engine is opened ahead of a search | No | Settings: "Improve search suggestions" off (its preference measured); `--disable-features=PreconnectToSearch` (measured) | The owner decides (S.15) |
| `clients2.google.com` | `network_time_component` | 1 request (`GET /time/1/current`, plain HTTP) in the first 2 s of every run | Google's time service: lets the browser tell a wrong PC clock from a bad certificate | No: only when a certificate's date looks wrong | No setting. `--disable-features=NetworkTimeServiceQuerying` (measured); policy `BrowserNetworkTimeQueriesEnabled` (not measured) | Ask on demand only (S.15) |
| `update.googleapis.com`, `edgedl.me.gvt1.com`, `dl.google.com` | `update_client` | First 5 s of every run: 2 update checks and 1 download (plain HTTP). In 1 run of 3 the download was tried a second time and also on `dl.google.com`, Google's other download host | The manifest of Google's on-device AI models (component `OptimizationGuideModelsManifest`), fetched ahead of the updater's schedule | No | `--disable-component-update` (measured), which stops every component | Remove (S.15, S.16) |
| `update.googleapis.com`, `edgedl.me.gvt1.com` | `update_client` | From 60 s on: 20 update checks and 19 downloads (plain HTTP) within half a minute, every run. By the source the checks come again every 5 hours | The component updater: certificate revocations, the certificate transparency log list, file type rules for downloads and other components (section 4) | Partly: the security data, yes | `--disable-component-update` (measured); policy `ComponentUpdatesEnabled` (not measured) | Keep; review which components Thoron wants |
| `clients2.google.com`, `clients2.googleusercontent.com`, `chromewebstore.googleapis.com` | `extension_manifest_fetcher`, `extension_crx_fetcher`, `cws_fetch_item_snippet` | In the first 4 s, only where other programs have registered extensions for Google Chrome in the Windows registry | Update check, download and Web Store details of those extensions. Thoron reads that key; the extensions stay disabled until the person approves them | No. Without such entries there is nothing to ask for (inferred) | Policy `BlockExternalExtensions` (its preference measured); `--disable-extensions` (measured) | Decide in P2.16 |
| `optimizationguide-pa.googleapis.com` | `optimization_guide_model`, `optimization_guide_model_download` | 12 requests 10 s to 15 s after start, every run | Chromium's optimization guide asks for its list of on-device models and downloads 11 of them, with a Google API key | No | No setting. `--disable-features=OptimizationHints` (measured) | Remove (S.15) |
| `mail.google.com` | `thoron_mail_feed` | 15 s after start, then every 2 minutes (2 requests in 240 s), each answered 401 | Thoron M-Notifier reads Gmail's feed of unread mail; nobody is signed in, so Google refuses | Only a person who uses Gmail in this profile | Flag `chrome://flags/#thoron-mail-notifier` (measured as `--disable-features=ThoronMailNotifier`); the interval is a setting in the notifier's menu | Keep the feature; stop looking while nobody is signed in to Google (S.15) |
| `safebrowsing.googleapis.com` | `safe_browsing_v4_update` | 1 request (`GET /v4/threatListUpdates:fetch`) 79 s to 193 s after start in the 3 runs, and up to 297 s in others; by the source the next one comes when Google's answer says | Safe Browsing downloads its lists of dangerous sites, with a Google API key | It is the browser's protection against dangerous sites | Settings, "Privacy and security", "Security": "No protection" (its preference measured); policy `SafeBrowsingProtectionLevel` (not measured) | ROADMAP **S.14** decides |
| `ublockorigin.github.io`, `malware-filter.gitlab.io` | `thoron_adblock_lists` | 7 and 1 requests, 120 s to 125 s after start, every run of that length | Thoron adblock's filter lists (section 7) | The lists that ship with the browser work without it; the download keeps them current | "Auto-update filter lists" on `chrome://adblock` (checked offline by `tools/qa/adblock_advanced_check.py`, not measured here). The flag does not help (section 5) | Keep |
| `wpad` | Windows' proxy settings; the name is only looked up | 4 to 8 look-ups a run, no request | Where Windows is set to detect a proxy automatically (its default), the browser looks for the name `wpad` on the local network | It is Windows' setting, not Thoron's | "Automatically detect settings" in Windows' proxy settings | Nothing to do |

The tool's own report of the three runs (the names of the components are left to section 4):

| Host | In runs (of 3) | Requests | First at | Asked by | Asked for | Answers |
|---|---|---|---|---|---|---|
| clients2.google.com | 3 | 2 | 0.3 to 1.4 | `extension_manifest_fetcher` (3), `network_time_component` (3) | `GET /service/update2/crx` (3), `GET /time/1/current` (3) | `200` (6) |
| update.googleapis.com | 3 | 22 | 0.3 to 1.5 | `update_client` (66) | `POST /service/update2/json` (66) | `200` (66) |
| accounts.google.com | 3 | 1 | 0.3 to 1.7 | `gaia_auth_list_accounts` (3) | `POST /ListAccounts` (3) | `200` (3) |
| www.google.com | 3 | 1 | 0.3 to 1.7 | `aim_eligibility_fetch` (3) | `GET /async/folae` (3) | `200` (3) |
| edgedl.me.gvt1.com | 3 | 20 to 21 | 0.9 to 2 | `update_client` (61) | `GET /edgedl/diffgen-puffin/<id>/<...>` (25), `GET /edgedl/release2/chrome_component/V3P1l2hLvLw_7/7_all_sslErrorAssistant.crx3` (3), `GET /edgedl/release2/chrome_component/ac55zopqc7vere3bm2pinwvz3d6q_4/<id>_all_gjbna5ieot3u4sywv4o74naely.crx3` (3), 10 more | `200` (61) |
| chromewebstore.googleapis.com | 3 | 2 | 0.5 to 2.2 | `cws_fetch_item_snippet` (6) | `POST /v2/items/<id>:fetchItemSnippet` (6) | `200` (6) |
| clients2.googleusercontent.com | 3 | 1 | 0.9 to 2.2 | `extension_crx_fetcher` (3) | `GET /crx/blobs/<...>/<id>.crx` (3) | `200` (3) |
| dl.google.com | 1 | 2 | 4.5 | `update_client` (2) | `GET /diffgen-puffin/<id>/<...>` (2) | `200` (1), `not sent` (1) |
| optimizationguide-pa.googleapis.com | 3 | 12 | 10.2 to 11.3 | `optimization_guide_model_download` (33), `optimization_guide_model` (3) | `GET /downloads` (33), `POST /v1:GetModels` (3) | `200` (36) |
| mail.google.com | 3 | 2 | 15.2 to 16.3 | `thoron_mail_feed` (6) | `GET /mail/u/0/feed/atom` (6) | `401` (6) |
| ublockorigin.github.io | 3 | 7 | 120.4 to 121.6 | `thoron_adblock_lists` (21) | `GET /uAssets/thirdparties/easylist.txt` (3), `GET /uAssets/thirdparties/easyprivacy.txt` (3), `GET /uAssetsCDN/filters/badware.min.txt` (3), 4 more | `200` (21) |
| malware-filter.gitlab.io | 3 | 1 | 121.1 to 122.3 | `thoron_adblock_lists` (3) | `GET /urlhaus-filter/urlhaus-filter-ag-online.txt` (3) | `200` (3) |
| safebrowsing.googleapis.com | 3 | 1 | 79.3 to 193.4 | `safe_browsing_v4_update` (3) | `GET /v4/threatListUpdates:fetch` (3) | `200` (3) |

Looked up without a request: `wpad` (in 3 of 3)

Connected to before any request (preconnect): `www.google.com` (in 3 of 3, 2 a run, first at 0.7 to 2.1)

Components in the profile at the end: 18, the same in all 3 runs; they are named in section 4.

**Downloads that Windows would make.** On Windows the component updater normally hands its downloads to
the system's background transfer service (BITS). Those transfers are not in the browser's network log.
The tool therefore starts the browser with `--component-updater=disable-background-downloads`, so that
the browser makes them itself and they are counted. Three runs of 240 s were also made without that
switch: the log then held only 1 or 2 downloads a run (those the browser makes itself in any case), and
3 to 7 components had arrived after 240 s instead of 18, because the Windows service takes its time.
The hosts are expected to be the same either way, since both ways take them from the same answer of
the update check; that is inferred, not measured.

## 3. What the requests carry

Read from the request lines and header names of one run (values are not kept):

- **No cookie** went out in any request: a fresh profile has none. The requests to Google's sign-in,
  search and mail hosts are made with credentials allowed, so they carry the Google cookies once a
  profile has some.
- **Every request** carries the browser's User-Agent, and most of those to Google's hosts the language
  (`accept-language`). Thoron adblock's list downloads carry no language and nothing else that tells
  one browser from another.
- **A Google API key** is in the address of `optimizationguide-pa.googleapis.com/v1:GetModels` and of
  `safebrowsing.googleapis.com/v4/threatListUpdates:fetch` (`key=`), and in a header of the model
  downloads (`x-goog-api-key`). These are the keys the upstream key patch compiles in (ROADMAP **L.8**).
- **`www.google.com/async/folae`** carries the browser's country and language in its address
  (`client_country`, `client_locale`) and the full version list in a header.
- **`clients2.google.com/service/update2/crx`** carries the operating system, the processor
  architecture, the language, the browser version and the ids of the extensions it asks about.
- **`update.googleapis.com`** gets the update check as a POST body, which the log does not hold; a
  header names the component asked about (`x-goog-update-appid`).
- **Plain HTTP** is used for `clients2.google.com/time/1/current` and for the download from
  `edgedl.me.gvt1.com`. Both answers are signed and checked, but anyone on the path sees the request.

## 4. Longer runs and the New Tab page

**The first 15 minutes.** One run of 900 s had the hosts of section 2 and no other. Everything except
the mail check was over 170 s after start: the component updater's 20 checks and 19 downloads between
60 s and 76 s, the filter lists at 120 s, Safe Browsing's update at 167 s. From then to the end the only
contact was the M-Notifier's request to `mail.google.com` every 120 s: 8 in all, each answered 401.

**What the component updater brought.** After 240 s, and still after 900 s, the profile held the same
18 components, by their folder names: `ActorSafetyLists`, `AmountExtractionHeuristicRegexes`,
`CaptchaProviders`, `CertificateRevocation`, `Crowd Deny`, `FileTypePolicies`, `hyphen-data`,
`MEIPreload`, `OnDeviceHeadSuggestModel`, `OptimizationGuideModelsManifest`, `OptimizationHints`,
`PKIMetadata`, `SafetyTips`, `SSLErrorAssistant`, `TrustTokenKeyCommitments`, `WasmTtsEngine`,
`WidevineCdm` and `ZxcvbnData`. Going by Chromium's use of them (not measured), `CertificateRevocation`,
`PKIMetadata`, `FileTypePolicies`, `SafetyTips` and `SSLErrorAssistant` are security data. Two go away
with ROADMAP S.15 (`OptimizationGuideModelsManifest`, `OptimizationHints`). Which of the others Thoron
wants is a review of its own.

**The New Tab page.** The runs above open a local page. A person's first window shows the New Tab page
instead, so one run of 120 s was made with it (`--page chrome://newtab/`). It had everything of section
2 and, in its first 2 s, these on top. All of them come from the page being Google's while Google is the
default search engine:

| Host | Asked by | What |
|---|---|---|
| `www.google.com` | `one_google_bar_service` | `GET /async/newtab_ogb`: the bar with Google's account and apps buttons at the top of the page |
| `www.gstatic.com`, `ogads-pa.clients6.google.com` | `blink_resource_loader` (the page itself) | That bar's script and style sheet, 2 requests for its data, and the Google logo image |
| `www.google.com` | `logo_service` | `GET /async/ddljson`: whether a doodle is to be shown instead of the logo |
| `www.google.com` | `omnibox_zerosuggest` | `GET /complete/search`: suggestions for the still empty search box |
| `www.google.com` | the search engine preconnector | 4 connections ahead of a request instead of 2 |

Stops tried on that page, one run of 60 s each, both with the AI Mode and preconnect switches of
NETWORK_REDUCTION.md:

- `--disable-features=NtpOneGoogleBar`: the bar's request is gone, and neither `www.gstatic.com` nor
  `ogads-pa.clients6.google.com` is contacted.
- The preference `search.suggest_enabled` false on top ("Improve search suggestions" off): the
  suggestion request is gone too.
- The doodle question stayed in both runs: `--disable-features=NtpLogo` does not stop it. With the New
  Tab page open, `www.google.com` is therefore still asked once after every switch of this page.

### 4.1 A person's first start, and the start after it (2026-11-17)

Measured with `tools/qa/netlog_hosts.py --visible --again` on a build of 158 from 2026-11-17: a real window
on the screen as a person's first start (no `--no-first-run`, so the first-run page is shown), 180 s, then
the same profile started once more for 180 s. Online, one run, the PC in use.

| Host | First start | Later start | What asks |
|---|---|---|---|
| `clients2.google.com`, `clients2.googleusercontent.com`, `chromewebstore.googleapis.com` | at 1 s | at 1 s | extensions other programs registered for Google Chrome on this PC (section 2): checked, downloaded and described again at each start, since they stay off until a person approves them |
| `update.googleapis.com`, `edgedl.me.gvt1.com` | from 61 s: 18 checks, 17 downloads | at 61 s: 1 check, 1 download | the component updater (section 2), which fills the new profile's components once |
| `ublockorigin.github.io`, `malware-filter.gitlab.io` | at 121 s: 9 lists | at 121 s: 1 list | Thoron adblock's list check (section 7) |
| `safebrowsing.googleapis.com` | at 124 s | none | Safe Browsing's list update |

The first-run page itself asks no host: every host above is one the headless runs of section 2 list too, at
the same moments. No time request (`clients2.google.com/time`) was made (S.15). The only other name looked up
is `wpad`, Windows' automatic proxy discovery on the local network, which asks no outside host. On the later
start one filter list was fetched again because the first start was stopped by force (as the tool does) before
it wrote down that it had the list; a normal exit keeps that.

## 5. Switches that were tried

One run each on a fresh profile, compared with the runs of section 2. The switches that remove the
Google contacts of ROADMAP S.15 are in NETWORK_REDUCTION.md.

| Switch or starting preference | What changed |
|---|---|
| `--disable-features=ThoronMailNotifier` (the flag `chrome://flags/#thoron-mail-notifier`) | No request to `mail.google.com` |
| `--disable-features=ThoronNativeAdblock` (the flag `chrome://flags/#thoron-native-adblock`) | Thoron adblock's downloads are gone, but the hand-over puts the preinstalled uBlock Origin into the new profile, and it fetches its own lists 14 s to 28 s after start: 12 requests to `cdn.jsdelivr.net`, `ublockorigin.github.io`, `ublockorigin.pages.dev`, `curbengh.github.io`, `pgl.yoyo.org` and `publicsuffix.org` (caller `blink_resource_loader`, the extension's own fetches). The flag does not make the browser quieter |
| `--disable-component-update` | No request to `update.googleapis.com` or `edgedl.me.gvt1.com` |
| `--disable-extensions`, or the preference `extensions.block_external_extensions` set to true (what the policy `BlockExternalExtensions` sets) | No extension update check on `clients2.google.com`, nothing from `clients2.googleusercontent.com` or `chromewebstore.googleapis.com` |
| `--disable-background-networking` | Less than its name says. Gone: the extension update check and download, one of the two Web Store requests, and no Safe Browsing update came in 240 s (it came in 7 of 8 other runs of that length). Unchanged: the time request, `accounts.google.com`, `www.google.com`, the optimization guide's downloads, the component updater, the mail check and the filter lists |
| The preference `safebrowsing.enabled` set to false (what "No protection" writes) | No request to `safebrowsing.googleapis.com` in 330 s; with Safe Browsing on, it came by 297 s in both other runs that long |
| `--allow-browser-signin=false`, or the preferences `signin.allowed` and `signin.allowed_on_next_startup` set to false | Nothing: `accounts.google.com` is asked all the same |
| A profile that starts with an unrelated preference | Nothing: writing a preference file before the first start does not change what is contacted |
| Everything at once: the switches of NETWORK_REDUCTION.md, both Thoron features off, `--disable-component-update`, and the preferences `extensions.block_external_extensions` true and `safebrowsing.enabled` false | No outside host in the log in 330 s; only `wpad` was looked up. Every contact of this page has a known cause and a known stop |

## 6. Compared with Thoron 156

The first measurement (2026-11-09, Thoron 156.0.8078.28, one run of 90 s) counted log entries per host,
which the tool still prints. The first Thoron 158 build was measured the same day and matched it.

| Host | 156, log entries in 90 s | 158 on 2026-11-16, log entries in a run of 240 s |
|---|---|---|
| `optimizationguide-pa.googleapis.com` | 83 | 78 |
| `update.googleapis.com` | 47 | 133 to 138 (61 to 79 when Windows makes the downloads, as in 156) |
| `edgedl.me.gvt1.com` | 7 | 103 to 114 (7 to 18 when Windows makes the downloads) |
| `chromewebstore.googleapis.com` | 24 | 22 |
| `clients2.google.com` | 18 | 18 |
| `clients2.googleusercontent.com` | 12 | 12 |
| `www.google.com` | 20 | 20 |
| `accounts.google.com` | 12 | 12 |
| `mail.google.com` | none | 25 |
| `safebrowsing.googleapis.com` | none | 12 |
| `dl.google.com` | none | 15 in 1 run of 3 |
| `ublockorigin.github.io` | none | 54 |
| `malware-filter.gitlab.io` | 12 | 12 |
| `cdn.jsdelivr.net` | 42 | none |
| `ublockorigin.pages.dev` | 25 | none |
| `pgl.yoyo.org` | 12 | none |
| `publicsuffix.org` | 12 | none |

What changed, and why:

- **New: `mail.google.com`.** The M-Notifier did not exist in 156.
- **New in the table: `safebrowsing.googleapis.com`.** Its first update came 79 s to 297 s after start,
  in all but one run later than the 90 s of the first measurement, so 156 very likely had it too.
  `dl.google.com` is the component updater's second download host and was used in one run.
- **Gone: `cdn.jsdelivr.net`, `ublockorigin.pages.dev`, `pgl.yoyo.org`, `publicsuffix.org`** (and
  `curbengh.github.io` of the first 158 build). They were the bundled uBlock Origin fetching its lists.
  A new profile no longer gets that extension while Thoron adblock is on; Thoron adblock fetches fewer
  files from fewer hosts, `ublockorigin.github.io` first. Two of the old hosts remain as fallbacks
  (section 7), and all of them come back when Thoron adblock is switched off by its flag (section 5).
- **The same: all eight Google hosts** of the first measurement, with about the same number of log
  entries. Nothing has been switched off yet; that is ROADMAP **S.15**.
- **Better known:** the first measurement put all of `clients2.google.com` down to extensions. One of
  its requests is Google's time service, and `www.google.com` is also connected to ahead of any search.
  `update.googleapis.com` and `edgedl.me.gvt1.com` are contacted in the first seconds for the manifest
  of Google's on-device AI models, a minute before the component updater's regular checks.

## 7. Thoron adblock's list updates (ROADMAP P5.15)

Thoron adblock is on by default (the flag `chrome://flags/#thoron-native-adblock` turns it off). It
checks its filter lists at most every 4 days: the first check comes 2 minutes after start, then an
hourly look at whether one is due. A new profile has never checked, so its first start always does. It
fetches the same files uBlock Origin uses, from the same hosts, each with one fallback:

| List | Host (fallback) |
|---|---|
| EasyList, EasyPrivacy | `ublockorigin.github.io` (`ublockorigin.pages.dev`) |
| uBlock filters, privacy, badware, quick fixes, unbreak | `ublockorigin.github.io` (`ublockorigin.pages.dev`) |
| URLhaus malware list | `malware-filter.gitlab.io` (`curbengh.github.io`) |
| A list a person switched on or added on `chrome://adblock` | the host of that list (HTTPS only) |

Each request is a plain HTTPS GET through the browser's own network context: no profile, no cookies
or other credentials, not stored in the HTTP cache, no identifiers. A redirect away from HTTPS is
refused. What happens to a downloaded list is in the native ad-blocking design, section 6. "Auto-update
filter lists" on `chrome://adblock` switches the downloads off; "Update now" still fetches.

Not contacted yet (from the source): once Thoron has its signing key (ROADMAP **P2.11**), the same
check also asks `github.com` for a signed file of the blocker's stand-in scripts
(`KuchiSofts/thoron/releases/download/adblock-resources/`). Without a key nothing is asked.

### 7.1 The updater (ROADMAP P3.20)

Not contacted yet: a build has no update key until the key ceremony (ROADMAP **P2.11**), and without one
the updater asks nothing, also when the About page is opened. With a key, an installed copy on Windows
asks `github.com` for three small files of the newest published release
(`KuchiSofts/thoron/releases/latest/download/update.json`, `update.json.sig` and `update.key`, the last
one only there when the release moves to a new key), and, when they name a newer release, for its
package; GitHub answers those with a redirect to its file host (`objects.githubusercontent.com` or
`release-assets.githubusercontent.com`). It looks 10 minutes after the start and then every 5 hours,
only in the update mode `auto` (`thoron_update --mode`), and whenever the About page is opened. The
switch `--disable-background-networking` stops the looks on its own; the About page still looks. On a
metered connection the looks on their own fetch the three small files and download no package. A package
download that breaks goes on with an HTTP `Range` request for the rest. The requests use the browser's
network settings, so a proxy set in Windows is used as for any page.

`ThoronSetup.exe` (ROADMAP P3.19) asks the same `github.com` addresses for the same three files and then
for the newest full installer, through Windows' own HTTP client: HTTPS only (a redirect to HTTP is
refused), no cookies, the system's proxy. Without a key in the build (every build until P2.11) nothing it
fetches verifies, so it installs nothing.

The requests are plain HTTPS GETs through the browser's own network context: no profile, no cookies or
other credentials, not stored in the HTTP cache, no identifiers; a redirect away from HTTPS is refused.
A manifest is read only after its signature holds (`docs/update/MANIFEST.md`), a package is used only
when its length and SHA-256 are the signed manifest's, and what the updater keeps (the highest serial
it accepted, the key statements it trusts) is in the browser's `Local State`, outside every profile.

## 8. Measuring again

```powershell
py -3 -I tools/qa/netlog_hosts.py --browser <out dir>\thoron.exe --work <scratch folder> --seconds 240 `
    --runs 3 --label "Thoron <version>" --md <scratch folder>\hosts.md --json <scratch folder>\hosts.json
```

`--page chrome://newtab/` opens the New Tab page instead of the local page,
`--switch=--disable-features=Name` tries a change, and `--absent <host>` makes the run fail when that
host is contacted (NETWORK_REDUCTION.md, section 5).

The report is made to be published: queries are dropped, extension and component ids are replaced by
`<id>`, and addresses of the local network are not shown. Read it once all the same: a path can hold
something the tool does not know to hide, as the addresses of the New Tab page's scripts hold the
browser's language. A raw network log (`--keep-log`) holds the PC's addresses and paths and is never
committed.
