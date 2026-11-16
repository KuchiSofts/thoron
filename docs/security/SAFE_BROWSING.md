# Safe Browsing: what protects against phishing and malware pages (ROADMAP S.14)

What stops a harmful page or download in Thoron today, what is left of it without Google's API keys,
the options, the one that is recommended, and the work order for it. The keys themselves are ROADMAP
**L.8** (the owner's decision); the network contacts are in [NETWORK.md](NETWORK.md) (**S.10**) and
[NETWORK_REDUCTION.md](NETWORK_REDUCTION.md) (**S.15**).

Status: measured 2026-11-16 on Thoron build 158.0.8127.3010 (Chromium 158.0.8127.30, Windows x64) with
[`tools/qa/safe_browsing_check.py`](../../tools/qa/safe_browsing_check.py). No source change has been
made yet; this page records the choice and says what to change.

How to read it:

- **Measured** means seen in a run on that build, on a new throwaway profile, headless, nobody signed in.
- **From the source** means read in the public Chromium source at tag 158.0.8127.30 (file and line are
  given) or in Thoron's published patch series (`source/overlay/`), not seen in a run.
- **Inferred** and **not measured** are said where they apply.

## 1. In short

- **Today** Google's Safe Browsing protects, and only because the build carries upstream's Google API
  keys. Google's phishing, malware, unwanted-software and billing test pages get the red warning, and
  its test downloads are flagged (measured). A new profile has no protection for its first 1 to 5
  minutes: the phishing page was first blocked 188 s, 219 s and 235 s after the start in three runs.
- **Without the keys** all of it is gone (measured): the list request is answered `400`, no test page
  is blocked and the test downloads are saved without a word. The browser still counts Safe Browsing
  as on, and still sends Google a request for every program downloaded, answered `400`.
- **Thoron adblock alone** stops what its lists name and nothing else: none of Google's test pages
  and none of 100 addresses of a public phishing feed of the same day, with its default lists and also
  with its optional phishing list switched on, which does not stop pages at all today (measured,
  section 3.4). Safe Browsing as shipped warned of 48 of the same 100.
- **Recommended: both, and never a dead switch.** Thoron adblock gets a phishing list by default and is
  the protection every build has. Google's Safe Browsing stays as the second layer, standard protection
  only, in a build that has a key Thoron owns. A build without such a key starts with Safe Browsing off
  instead of on and broken. Only the key itself needs the owner (section 7).

## 2. What was measured, and how

- **Tool.** `safe_browsing_check.py` starts the browser headless on a new profile, opens the addresses
  of Google's test site `testsafebrowsing.appspot.com` over the DevTools protocol and reads what the tab
  shows: the Safe Browsing warning (an error page whose data names it `SAFEBROWSING`), Thoron adblock's
  "Thoron blocked this page", or the page itself. It opens the phishing page every 15 s until it is
  stopped, so the time of the first list is known to 15 s. Downloads are read from `chrome://downloads`.
- **Requests.** In ten of the runs the browser also wrote Chromium's network log
  (`--switch=--log-net-log=<file>`), read with `tools/qa/netlog_hosts.py`: host, path without query,
  seconds since the start, answer. Queries are dropped because they hold the API key.
- **Without the keys.** A build that is not Google Chrome takes its keys from the environment when the
  variables are set (from the source: `google_apis/api_key_cache.cc`, line 89, and
  `google_apis/default_api_keys-inc.cc`, line 141). The tool sets `GOOGLE_API_KEY`,
  `GOOGLE_DEFAULT_CLIENT_ID` and `GOOGLE_DEFAULT_CLIENT_SECRET` to Chromium's own value for "not set",
  `dummytoken` (`google_apis/default_api_keys.h`), for that one process. An empty value would not do:
  Windows has no empty variable, and the build's own key would be used. That the change took hold is
  measured: the same request is answered `200` with the build's keys and `400` with the placeholder.
- **Runs.** 15, one browser at a time, each on its own new profile: as shipped from a cold start (3),
  as shipped with the first list brought forward (1), with the placeholder keys (2), with Safe
  Browsing off (2), with `OptimizationHints` off (2), and five with names made unresolvable (section
  3.4 and the last check of 7.1). The four commands below were each run as written.
- **Not measured:** a visible window; a profile's later starts (the lists are then on disk); a
  signed-in profile; Enhanced protection; the Settings page's wording; Linux. Google's test pages are
  entries Google put on its lists for testing: they show that the mechanism works, not how much of the
  real web it covers.

The commands, from the repository's root:

```powershell
# as the build ships: phishing and malware must be blocked (exit status 0)
py -3 -I tools/qa/safe_browsing_check.py --browser <out dir>\thoron.exe --work <scratch folder> `
    --downloads
# the same without Google's API keys
py -3 -I tools/qa/safe_browsing_check.py --browser <out dir>\thoron.exe --work <scratch folder> `
    --no-google-keys --downloads
# Thoron adblock alone
py -3 -I tools/qa/safe_browsing_check.py --browser <out dir>\thoron.exe --work <scratch folder> `
    --safe-browsing off --wait 0 --downloads
# without the optimization guide's models (ROADMAP S.15); the second switch brings the first list forward
py -3 -I tools/qa/safe_browsing_check.py --browser <out dir>\thoron.exe --work <scratch folder> `
    --switch=--disable-features=OptimizationHints --switch=--safebrowsing-fast-initial-lists-update
```

## 3. Results

### 3.1 The test site, in three states of the same build (measured)

| Test address (`testsafebrowsing.appspot.com/s/...`) | As shipped | Placeholder keys | Safe Browsing off |
|---|---|---|---|
| `phishing.html` | **blocked**, "Dangerous site" | open | open |
| `malware.html` | **blocked**, "Dangerous site" | open | open |
| `unwanted.html` (unwanted software) | **blocked**, "Dangerous site" | open | open |
| `trick_to_bill.html` (billing) | **blocked**, "The page ahead may try to charge you money" | open | open |
| `shortlink.html` (sends on to the malware page) | **blocked** | not tried | open |
| `malware_in_iframe.html`, `image_small.html`, `bad_javascript.html` (a bad part inside a page; the site calls them deprecated) | open | not tried | open |
| `suspicious.html` (needs a live lookup) | open | not tried | open |
| `badrep.exe` | **held back**, "dangerous host" | **saved, no question** | held back for its file type |
| `unknown.exe` | **held back**, "uncommon" | **saved, no question** | held back for its file type |
| `pua.exe` | **held back**, "unwanted app" | **saved, no question** | held back for its file type |
| Seconds from the start to the first block | 188, 219 and 235 | never (343 s waited) | never |

What the browser asked meanwhile (measured):

| State | `safebrowsing.googleapis.com` | `sb-ssl.google.com` |
|---|---|---|
| As shipped | `GET /v4/threatListUpdates:fetch` once, at 207 s and 230 s, `200`; then `GET /v4/fullHashes:find` twice for each blocked page, `200` | `POST /safebrowsing/clientreport/download` once for each test download, `200` |
| Placeholder keys | `GET /v4/threatListUpdates:fetch` once, at 224 s, `400` | the same `POST` for each download, `400` |
| Safe Browsing off | nothing | nothing |

- **The warning shows** in the headless browser: title "Security error", heading "Dangerous site", and
  the navigation ends in `net::ERR_BLOCKED_BY_CLIENT`.
- **The first minutes are open.** A new profile opens the phishing page until the first list is there.
  The wait is drawn between 60 s and 300 s (from the source:
  `components/safe_browsing/core/browser/db/sb_update_protocol_manager.h`, lines 35 to 37);
  [NETWORK.md](NETWORK.md) saw 79 s to 297 s. With `--safebrowsing-fast-initial-lists-update` the list
  came at 19 s and the page was blocked at 33 s.
- **The lists on disk** after the first update: 7 lists, 19 MB, the phishing list alone 16 MB
  (`UrlSoceng`). One of them is the list of harmful extensions (`ChromeExtMalware`, 1.9 MB), so the
  keys also carry the extension blocklist (the meaning of the name is inferred).
- **On without a key is worse than off.** With Safe Browsing off the browser itself keeps a program
  back for the person to decide, when the download was not started by a click on a known site (its
  file type rule, from the source: `chrome/browser/download/download_target_determiner.cc`, lines
  1401 to 1420; `chrome://downloads` lists it as dangerous for its file type). With Safe
  Browsing on it waits for Google's verdict instead; without a key that verdict is a `400`, and the
  file is saved (measured; why the question is skipped is inferred).
- **The test site's `content.exe`** ("malicious, based on content") is sent as a page, not as a file,
  so no download starts in any state. The check leaves it out.

### 3.2 What each part needs

| Part | Asks | API key | Google account | In Thoron 158 |
|---|---|---|---|---|
| Lists of hash prefixes: phishing, malware, unwanted software, billing, harmful downloads, harmful extensions | `safebrowsing.googleapis.com/v4/threatListUpdates:fetch` | **yes** (measured: `400` without) | no | works with upstream's keys (measured) |
| Full hash for an address whose prefix is on a list | `.../v4/fullHashes:find` | **yes** (from the source: the same address builder, `sb_protocol_manager_util.cc`, lines 598 to 617; without lists there is never such a request) | no | works (measured) |
| Download protection | `sb-ssl.google.com/safebrowsing/clientreport/download` | **yes** (measured: `400` without) | no; a signed-in profile with Enhanced protection adds its token (from the source) | works with upstream's keys (measured) |
| Client-side phishing detection | `sb-ssl.google.com/safebrowsing/clientreport/phishing` | **yes** (from the source: `client_side_detection_service_base.cc`, lines 463 to 467) | as above | no such request in any run; it also needs a model (section 3.5) |
| Live lookups of hash prefixes (Google Chrome's standard protection) | a relay, then Google | yes | no | **off**: only builds with Google Chrome branding (from the source: `hash_realtime_utils.cc`, lines 25 to 31 and 107 to 110) |
| Live lookups of the whole address | `safebrowsing.google.com/safebrowsing/clientreport/realtime` | not looked up | a token when signed in | only with Enhanced protection or "Make searches and browsing better" (from the source: `realtime/policy_engine.cc`, lines 95 to 98); not measured |
| The browser's question before it keeps a program | nothing | no | no | works, but only while Safe Browsing is off (measured) |
| Thoron adblock's lists and its warning page | the list hosts, without cookies | no | no | works (section 3.4) |

Standard protection needs no account: every block in section 3.1 happened with nobody signed in.

Where the files named on this page are: `sb_*` and `v4_*` in `components/safe_browsing/core/browser/db/`;
`client_side_detection_service_base.cc` and `realtime/` in `components/safe_browsing/core/browser/`;
`hash_realtime_utils.cc` in `components/safe_browsing/core/common/hashprefix_realtime/`;
`notification_content_detection/` in `components/safe_browsing/content/browser/`;
`download_protection_delegate_desktop.cc` in `chrome/browser/safe_browsing/download_protection/`;
`safe_browsing_service.cc` and `client_side_detection_intelligent_scan_delegate_desktop.cc` in
`chrome/browser/safe_browsing/`.

### 3.3 What Google learns from standard protection

- **The list update:** the address of the PC on the network, as with any request; the API key; the
  browser's version; a client name (`thorium` in upstream's `thorium-install-static-branding.patch`).
  No cookies: the request is made without credentials and without the cache (from the source:
  `v4_update_protocol_manager.cc`, lines 249 and 250). How often it repeats is set by Google's answer
  and was not measured.
- **A full hash request:** only for an address whose hash prefix is on a local list. It carries the
  prefixes and the state of the lists, not the address, and no cookies (from the source:
  `v4_get_hash_protocol_manager.cc`, lines 374, 375 and 518 to 540). Measured: two for each test page,
  none for a page that is on no list.
- **A download check:** for programs and archives, "URL of the file to be downloaded, its referrer
  chain, digest and other features extracted from the downloaded file" (the request's own description
  in `download_protection_delegate_desktop.cc`). This is the part that tells Google the most.
- **Nothing is sent for an ordinary page.** The check against the lists is local.

### 3.4 Thoron adblock alone, on addresses from lists and from a phishing feed (measured)

For these runs every name except the list hosts was made unresolvable inside the browser
(`--host-resolver-rules`), so no listed host was contacted; the network log shows requests sent to the
list hosts only. An address then ends on Thoron adblock's page or as a name that does not resolve,
which means that nothing stopped it. Addresses that are bare IP numbers were left out. The feed is the
public feed of OpenPhish of the same day (section 5): 100 of its 300 addresses, evenly spread.

| Addresses, Safe Browsing off | Tried | Stopped by Thoron adblock |
|---|---|---|
| Bundled badware list, rules for pages (`$doc`) | 10 | 10 |
| Bundled badware list, `$all` rules | 10 | 10 |
| Bundled malware list, single addresses | 10 | 10 |
| Bundled EasyList, whole ad hosts | 10 | 10 |
| Another address on a host of which the malware list names one address | 9 | 3 |
| In today's malware list and not in the bundled copy, after the first list update | 20 | 20 |
| In today's badware list and not in the bundled copy, after the first list update | 10 | 10 |
| The phishing feed, with the default lists | 100 | **0** |
| The phishing feed, with the optional "Phishing URL Blocklist" switched on | 100 | **0** |
| Hosts taken from that phishing list itself, with it switched on | 20 | **0** |

- **What the lists name is stopped,** and the lists are renewed: the bundled copies are of 2026-09-16,
  and addresses that only today's lists hold were stopped 205 s after the start. Before that first
  update (it starts 2 minutes after the start) a new profile has the bundled copies only (measured in a
  run that tried them after 54 s: none of 30 stopped).
- **The default lists know no phishing.** None of the 100 feed addresses is stopped. The badware list is
  about bad software and scam sites, the malware list about addresses that hand out malware.
- **The optional phishing list does not stop pages.** It was switched on at `chrome://adblock` as a
  person would, its file arrived (1.9 MB, in the profile's list folder), and five minutes later not one
  of 20 hosts taken from it was stopped, while hosts of today's malware list were (10 of 10 in the same
  run). The cause is inferred, not measured: its lines are bare host names (`host.example`), where the
  malware list has `||host.example^$all`, and Thoron adblock stops a page for a page rule or for a rule
  that names a whole host. The list's AdGuard form, `phishing-filter-ag.txt`, has the second shape.
- **One address is not a host.** Of 9 other addresses on hosts of which the malware list names a single
  address, 3 were stopped (by other rules) and 6 were not.

The same feed against Safe Browsing as shipped, with `safebrowsing.googleapis.com` resolvable as well:

| The same 100 feed addresses, Safe Browsing as shipped | Safe Browsing warning |
|---|---|
| First visit | 3 |
| Second visit | 47 |
| Third visit | 48 |

- **Google's list held 48 of the 100.** On the first visit the warning mostly loses against a name
  that fails at once: the answer to the full hash request comes after the error page. The browser
  keeps that answer, so from the second visit on the warning shows. With a name that resolves, the
  page waits for the answer (inferred; Google's test page, also unresolvable here, got its warning).
  The run sent 113 full hash requests and nothing to any host but Google's and the list hosts.
- **No list holds everything.** Of the same day's feed Google's list held about half, and the lists of
  section 5 name between none and nearly all of it. That is the case for using both.

### 3.5 Without the optimization guide's models (ROADMAP S.15)

The next build turns the feature `OptimizationHints` off by default, so nothing is fetched from
`optimizationguide-pa.googleapis.com` any more. For Safe Browsing this means:

- **Which models Safe Browsing asks for (from the source).** The phishing classifier, target
  `CLIENT_SIDE_PHISHING` (number 25), for every profile with Safe Browsing on
  (`components/safe_browsing/core/browser/client_side_phishing_model.cc`, lines 276 to 281); its image
  model, `CLIENT_SIDE_PHISHING_IMAGE_EMBEDDER` (30), only with Enhanced protection
  (`client_side_detection_service_base.cc`, lines 157 to 159); and the notification classifier,
  `NOTIFICATION_CONTENT_DETECTION` (53)
  (`notification_content_detection/notification_content_detection_model.cc`, line 74). The scam check
  on a model inside the browser is for Enhanced protection only
  (`client_side_detection_intelligent_scan_delegate_desktop.cc`, line 305).
- **Measured.** As shipped, the profile's model store holds 11 models, number 25 among them. With
  `--disable-features=OptimizationHints` it holds none, and the host is not contacted. The four test
  pages are blocked all the same (first list at 20 s, block at 33 s with the fast switch): the lists do
  not depend on the models.
- **What is lost (from the source).** Client-side phishing detection: the browser scores a page that is
  on no list with the model and, when the score is high, asks Google about that page. Without a model
  the service reports that none is available and sends none to the pages
  (`client_side_detection_service_base.cc`, lines 650 to 656;
  `components/safe_browsing/content/browser/client_side_detection_service.cc`, line 161), so no page is
  scored and nothing is asked. This is the only part of standard protection that can catch a phishing
  page before it is on a list.
- **Not shown by a run.** The test site's page for it (`force_csd.html`) was kept open for 40 s with
  the model and without: no request to `sb-ssl.google.com/safebrowsing/clientreport/phishing` either
  time. The headless browser may not score pages at all; the loss is therefore stated from the source.
- **Decision: drop it.** It asks Google about pages a person visits, it works only with a valid key
  and with a model fetched from the host S.15 removes, and nothing in a run showed it working here. It
  is not replaced: a page that is on no list yet is not caught, with Google's lists or with Thoron
  adblock's. If it is wanted back later, the way is to fetch that one model (target 25) and no other,
  which is the larger patch [NETWORK_REDUCTION.md](NETWORK_REDUCTION.md) names in 2.1.

## 4. The options

| Option | Privacy | Protection | Work | Needs the owner |
|---|---|---|---|---|
| **A. Google Safe Browsing with a key of Thoron's own** | Section 3.3: Google sees every browser's address at each list update and the address of every program downloaded; no page addresses | The most: everything in the first column of 3.1, Google's lists (19 MB, about half of one day's phishing feed in 3.4), the extension blocklist. Open for the first 1 to 5 minutes of a new profile | Small: a build setting. To be measured with the new key: whether the two `sb-ssl.google.com` checks accept it (they are not part of the public API) | **Yes**: a Google Cloud project under the owner's name, its terms, and a quota large enough |
| **B. Safe Browsing left on with no key** | Worst for what it gives: the list request and every program's address still go to Google | None (measured), and less than "off" for downloads | None | No |
| **C. Thoron adblock's lists only, Safe Browsing off** | Best: no Google contact; list downloads without cookies or ids | Only hosts and addresses that are on a list at the last update: section 3.4. No download verdicts, no extension blocklist | Small: one more default list, two test rules, Safe Browsing off by default | No |
| **D. Both: C in every build, A on top where there is a key** | As A where the key is, as C elsewhere | A and C together; C also covers a new profile's first minutes | A plus C | Only for the key |

Google's conditions for A, from its own pages (read 2026-11-16):

- [API keys for Chromium](https://www.chromium.org/developers/how-tos/api-keys/): "Software distribution
  with keys acquired for yourself is allowed, but the keys themselves cannot be shared with parties
  outside the legal entity that accepted the API ToS", and "a number of the APIs will have no or very
  limited quota". The Safe Browsing API is on its list of APIs to switch on.
- [Safe Browsing API, usage limits](https://developers.google.com/safe-browsing/v4/usage-limits): "for
  non-commercial use only", with "a default usage quota, which can be increased upon request". The
  size of that quota is not on the page.
- [Its terms](https://developers.google.com/safe-browsing/terms): people must be told of the service's
  limits and warnings must name Google. Whether the built-in warning's text does was not checked.
- The v4 API that Chromium 158 uses for its lists is marked deprecated in favour of v5 on
  [its overview](https://developers.google.com/safe-browsing/v4). Chromium has the v5 code behind a
  feature that is off (from the source: `SafeBrowsingLocalListsUseSBv5` in
  `components/safe_browsing/core/common/features.cc`, line 410). Follow it at each rebase.
- A key inside a public program can be read out by anyone, as upstream's can. Restrict it to the Safe
  Browsing API in Google's console, so that it is of no other use.

What other browsers without Google's own keys do:

| Browser | What it does | Source |
|---|---|---|
| ungoogled-chromium | Safe Browsing is disabled; "If you are looking for a feature like Safe Browsing, I recommend uBlock Origin or uMatrix" | its [README](https://github.com/ungoogled-software/ungoogled-chromium/blob/master/README.md) and [FAQ](https://ungoogled-software.github.io/ungoogled-chromium-wiki/faq#why-is-safe-browsing-disabled) |
| Brave | Google Safe Browsing, on; on desktop "we proxy this service in order to prevent your IP address from being shared with Google" | its [privacy policy](https://brave.com/privacy/browser/#safe-browsing) |
| LibreWolf (Firefox) | Off by default; "to be fully functional, Safe Browsing requires to include a developer key at build time", so it "cannot provide a fully functional Safe Browsing experience at the moment" | its [FAQ](https://librewolf.net/docs/faq/) |
| Helium | "Originally branched off ungoogled-chromium", ships its own fork of uBlock Origin; its README does not name Safe Browsing | its [README](https://github.com/imputnet/helium/blob/main/README.md) (not checked further) |
| Thorium (upstream) | Google Safe Browsing with keys compiled in by `thorium-default-api-keys.patch` | ROADMAP **L.8** |

Brave's way (a proxy between the browsers and Google) needs servers of Thoron's own and is left out.

## 5. Lists for phishing and malware

Every list was fetched on 2026-11-16; size, entries and pace are the file's own, the licence is from the
list's own page. "Feed" is how many of the 300 addresses of OpenPhish's public feed of that day the
list names by host or by address, counted outside the browser. At least two of the lists are built
from that feed, so for them the number says how fast they pass it on, not how much phishing they know.

| List | Entries | Size | Asks to be fetched every | Licence | Feed (of 300) |
|---|---|---|---|---|---|
| [uBlock filters - Badware risks](https://github.com/uBlockOrigin/uAssets) (default in Thoron) | 4,834 | 0.2 MB | 5 days | GPL-3.0 | 0 (its pattern rules not counted) |
| [Online Malicious URL Blocklist](https://gitlab.com/malware-filter/urlhaus-filter) (default in Thoron) | 109,084 | 12.0 MB | 12 hours | CC0 and MIT; data from URLhaus, CC0 | 0 |
| [Phishing URL Blocklist](https://gitlab.com/malware-filter/phishing-filter) (optional in Thoron) | 42,621 | 1.9 MB | 12 hours | CC BY-SA 4.0; built from OpenPhish and PhishTank ("free of charge") and IPThreat (CC BY-SA 4.0) | 86 |
| [Phishing Army](https://phishing.army/) | 144,046 | 3.1 MB | 4 hours | none of its own: "does not impose an additional restriction", "Free for personal and individual use", the sources' terms stay | 291 |
| [HaGeZi Threat Intelligence Feeds, medium](https://github.com/hagezi/dns-blocklists) | 353,545 | 7.6 MB | 8 hours | GPL-3.0 | 64 |
| the same, full | 1,462,039 | 31.0 MB | 8 hours | GPL-3.0 | 81 |
| [Phishing.Database, active domains](https://github.com/Phishing-Database/Phishing.Database) | 392,178 | 11.0 MB | not said | MIT | 30 |
| [CERT Polska's Warning List](https://cert.pl/en/warning-list/) | 123,515 | 3.4 MB | 1 hour | "may be used by any user for any purpose, including commercial purposes" | 13 (made for Poland) |
| [Dandelion Sprout's Anti-Malware List](https://github.com/DandelionSprout/adfilt) | 13,964 | 0.4 MB | 1 day | Dandelicence 1.4 | 0 (its pattern rules not counted) |

- **The feed itself** ([OpenPhish](https://openphish.com/phishing_feeds.html), community feed, renewed
  every 12 hours) may not be shipped: its terms allow personal and research use only. It was used here
  once, as a sample; no address of it is in this repository.
- **Thoron adblock already honours the pace** a list asks for, from 12 hours to 14 days, 4 days when the
  list says nothing (from the source: `list_update_hours` in `components/thoron_adblock/engine.rs`,
  `kUpdateInterval` and `kMaxListInterval` in `list_store.h`). It accepts lists up to 20 MB
  (`kMaxListBytes`), so the full HaGeZi list is too large.
- **Lists know hosts, not pages.** Many phishing pages sit on shared hosts (site builders, form
  services, storage). A list can name the one address, and misses the next one on the same host.

## 6. Recommendation

**Option D.** In the order in which it can be done:

1. **Thoron adblock is the protection every build has.** A phishing list becomes a default list, next
   to the badware and malware lists it already has, in a form that stops pages (today's optional one
   does not, section 3.4). This needs nobody, costs no privacy, covers the first minutes of a new
   profile and every build without a key. It is a floor, not an equal: a list knows only what was
   reported before its last update, and none of them holds everything (sections 3.4 and 5).
2. **Google's Safe Browsing stays, as standard protection only, in a build with a key Thoron owns.** It
   is the only thing measured here that stops Google's test pages, judges downloads and brings the
   extension blocklist. For pages it sends Google no address, only hash prefixes when a local list
   has a hit; for a downloaded program it does send the address (section 3.3). Enhanced protection is
   not offered: it sends the addresses of pages to Google (from the source, section 3.2).
3. **A build without a valid key starts with Safe Browsing off.** Then the browser asks nothing of
   Google, counts nothing as on that is not, and keeps a program back for the person to decide.
4. **Client-side phishing detection is dropped** with the models (section 3.5).

Why not C alone: it gives up the download verdicts, the extension blocklist and by far the largest
list, for a privacy gain that is small where no page address is sent. Why not A alone: it leaves every
build without a key, and every new profile's first minutes, with nothing. B is not an option.

## 7. Work order

Nothing here is built yet. Files of Chromium are named from the public source at tag 158.0.8127.30,
files of Thoron adblock from `source/overlay/other/ks-native-adblock-engine.patch`.

**7.1 Thoron adblock: the phishing list by default** (needs nobody)

- `components/thoron_adblock/list_store.cc`: add the Phishing URL Blocklist to the table of default
  lists, next to `urlhaus-1`, in its AdGuard form, whose lines are `||host^$all` like the malware
  list's: `https://malware-filter.gitlab.io/phishing-filter/phishing-filter-ag.txt`, with
  `https://curbengh.github.io/malware-filter/phishing-filter-ag.txt` as the second address (both
  answered on 2026-11-16; no new host is contacted). Take the list out of the optional ones in
  `settings_page.js` (group "Malware and phishing"), where it is offered in the form that does not
  stop pages.
- The cause of that should be found and mended on its own, because other lists of bare host names are
  offered too: read a line that is only a host name as a rule for that whole host, as uBlock Origin
  does (`components/thoron_adblock/engine.rs`, and what `page_block_throttle.cc` asks it).
- `components/thoron_adblock/extract_lists.py`: bundle a copy, so that a new profile has it from the
  first page. `third_party/thoron_notices/NOTICE.filter_lists` and `CREDITS.md`: name it with its
  licence (CC BY-SA 4.0) and sources.
- Two rules of Thoron's own for the two test addresses, `testsafebrowsing.appspot.com/s/phishing.html`
  and `.../s/malware.html` as page rules (`$doc`), so that any build can be shown to stop a harmful
  page, with or without Google. They prove the mechanism, as Google's own test entries do.
- Check: `safe_browsing_check.py --safe-browsing off --wait 0` reports both pages as `adblock` and
  exits 0; `tools/qa/adblock_strict_check.py` still passes; and a host taken from the phishing list is
  stopped without being contacted: with `--page http://<a host of the list>/` and
  `"--switch=--host-resolver-rules=MAP * ~NOTFOUND"` added, that page is reported as `adblock` (no name
  resolves in that run, so nothing is contacted).
- Next, as its own step: Phishing Army as a second phishing list. It named 291 of the feed's 300
  addresses where the Phishing URL Blocklist named 86 (section 5). It is a list of bare host names, so
  it needs the mending above, and it has no licence that allows passing it on: it would be fetched by
  each browser and not bundled, and its terms should be read for that first (a licensing question).
- Later, if wanted: let the security lists be looked for more often than they ask (the badware list
  asks for 5 days).

**7.2 The key** (the owner, ROADMAP L.8)

- The owner creates a Google Cloud project, switches on the Safe Browsing API only, makes one API key
  restricted to that API, and asks for the quota a release needs. No OAuth client: sign-in and sync are
  a separate decision of L.8.
- The release build gets it as the build argument `google_api_key` (`google_apis/BUILD.gn`, line 25)
  and leaves `google_default_client_id` and `google_default_client_secret` empty. Upstream's
  `thorium-default-api-keys.patch` leaves the series. The key is never committed.
- Check with that build: the first command of section 2 exits 0. If its downloads are no longer
  flagged, the `sb-ssl.google.com` checks do not take the key. Then the download check alone is
  switched off, so that no program's address is sent for nothing: `MayCheckClientDownload()` and
  `MayCheckFileSystemAccessWrite()` in `download_protection_delegate_desktop.cc` (lines 68 to 80)
  answer false. Whether the browser's own question before a program is saved then comes back, as it
  does with Safe Browsing off, must be measured with that build.

**7.3 No key, no Safe Browsing** (needs nobody; wanted in any case, because a build made from the
published source has no key)

- `components/safe_browsing/core/common/safe_browsing_prefs.cc`, lines 366 to 368: register
  `safebrowsing.enabled` with `google_apis::HasAPIKeyConfigured()` (`google_apis/google_api_keys.h`,
  line 72) in place of `true`, and let `IsSafeBrowsingEnabled()` (line 253) answer false without a key,
  for a profile that has the setting stored. The services, download protection and client-side
  detection all read that function (`safe_browsing_service.cc`, lines 754 to 766;
  `download_protection_delegate_desktop.cc`, lines 48 to 52).
- Settings, "Privacy and security", "Security": say that Safe Browsing is not part of this build
  instead of offering it, and do not offer Enhanced protection in any build. The page's files were not
  looked up.
- Check: with `--no-google-keys`, [`netlog_hosts.py`](../../tools/qa/netlog_hosts.py) run with
  `--absent safebrowsing.googleapis.com --absent sb-ssl.google.com` passes, and the test downloads are
  held back for their file type as in the third column of 3.1.

**7.4 Nothing to do**

- Live lookups of hash prefixes: off in a build without Google Chrome branding (section 3.2).
- Client-side phishing detection: ends with S.15's change (section 3.5).

## 8. Checking a build

`safe_browsing_check.py` is online on purpose: it opens Google's test pages. It exits 0 only when the
phishing and the malware page are both blocked, by Safe Browsing or by Thoron adblock, and says which.
Its unit tests (`tools/qa/tests/test_safe_browsing_check.py`) cover the decisions, not the run.

With today's build it passes because of upstream's keys. It is the test of ROADMAP S.14 once 7.1 is
built (it then passes with Safe Browsing off too) and of 7.2 once there is a key.

## 9. Open points

- The key and its quota (7.2): the owner.
- Whether a key of Thoron's own is taken by the download check, and how often the list update repeats:
  measure with the first build that has one.
- The Settings page without a key, a visible window, a signed-in profile and Linux were not measured.
- [NETWORK.md](NETWORK.md), section 7, says Thoron adblock looks for its lists "at most every 4 days";
  the source lets a list ask for as little as 12 hours (section 5). One of the two needs correcting.
