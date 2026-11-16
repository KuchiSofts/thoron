# Update manifest, schema 1 (ROADMAP P3.1, P3.2)

The update manifest is the one file that tells a copy of Thoron what the newest release is and where its
packages are. It is signed. This page is the format and the rules for reading it, written for whoever
builds the updater in the browser (P3.3) and the small installer (P3.19).

The reference is [`tools/update/manifest.py`](../../tools/update/manifest.py): it builds, checks, signs and
verifies manifests, and its tests ([`tools/update/tests/test_manifest.py`](../../tools/update/tests/test_manifest.py))
hold this page and the code together. The C++ side gives the same answer as `check_update()` there for
every input. Where this page and the reference differ, that is a bug in one of them.

Background: [design, section 7](../design/2026-11-07-thoron-design.md) and the
[release program](../design/2026-11-12-release-program.md).

## 1. The two files

| File | What it is |
|---|---|
| `update.json` | The manifest: one JSON object, at most 262144 bytes |
| `update.json.sig` | Its signature: exactly 64 bytes, nothing else |

Both are assets of the GitHub release and are fetched from the newest one:
`https://github.com/KuchiSofts/thoron/releases/latest/download/update.json` (and `.sig`).
That address is the `stable` channel's. Thoron has no other channel yet; one that is added gets an
address of its own, because "the newest release" can only be one channel's.

- One manifest describes **one release of one channel**, with every variant that release ships.
- The signature is detached, so the manifest stays a plain file a person can read before publishing.
- A manifest is never changed after it is signed. A change of one bit, in either file, is a refusal.
- This file name holds schema 1 for good. A later schema gets a new file name, and `update.json` keeps
  being published in schema 1 for as long as updaters that read schema 1 are in use. That is how the
  format can be strict about unknown keys and still grow.

## 2. Decisions and their reasons

| Decision | Reason |
|---|---|
| The signature covers the exact bytes of the file, and is checked before any byte is read as data | A JSON reader never sees bytes Thoron did not sign, so a flaw in the reader is out of an attacker's reach. No step that rewrites the data sits between the file and the check |
| What is signed starts with a fixed prefix that names the purpose | The same key may sign other things (the ad blocker's resources, checksums). A signature made for one of them can never be passed off as a manifest's, or the reverse |
| The signature file is the raw 64 bytes | Nothing to decode, so nothing to decode wrongly: text forms such as base64 have more than one spelling of the same bytes |
| One written form (section 3), and anything else is refused | One content, one byte sequence. Two readers cannot understand the same file differently, because whatever they could read differently (repeated keys, number spellings, escapes, spacing) is not in that form |
| Printable ASCII and LF only; no lists, no null, no fractions; whole numbers up to 2147483647 | Every JSON library reads these the same way. Text encodings and large or fractional numbers are where libraries differ |
| Objects keyed by variant, package kind and delta base, not lists | No duplicates by construction, and the updater finds its entry by one exact name |
| Unknown keys are refused at every level | A key the updater does not know is a key it cannot check. Growth goes through a new schema (section 1) |
| Times are text in UTC (`2026-12-01T12:00:00Z`), not numbers | Readable in review, one spelling, and no 32-bit limit in 2038 |
| `serial` is the UTC day of `published` plus a two-digit count | It only goes up, and it cannot run ahead of the calendar: a manifest dated in the future is refused before its serial is stored, so no mistake can use up the serials that later manifests need |
| The build version (four numbers) decides what is newer; the Thoron version is for people | It is the version Windows, the installer and Chromium compare, see [`tools/release/version.py`](../../tools/release/version.py). `chromium_version` must agree with it, so the three cannot drift apart |
| `min_updater_version` is a build version | The updater is built with the browser, so its version is the build it came with. No second counter to keep |
| A manifest is good for 30 days by default and never for more than 90; the clock may be off by 24 hours | The expiry bounds how long a copy can be kept on an old release by replaying an old manifest. 24 hours covers a wrongly set time zone and is small next to 30 days |
| The same version is "up to date"; a lower one is refused; the same serial is accepted | A copy that checks daily fetches the same manifest most days. Only something newer is ever installed, and only a manifest at least as new as the last accepted one is believed |
| Download addresses are plain `https://host/path` on hosts the caller allows, compared as whole names | The updater connects nowhere else, whatever the manifest says. No user, port, query, escape or `..` means there is one way to read an address |
| The channel is inside the signed bytes | A manifest of another channel is still validly signed; only the name in it tells them apart |
| A public key that is all zero, or another point of small order, is no key | A build made before the real key is put in holds zeros. Under such a key a signature anybody can write down fits one manifest in four, so with it everything is refused (section 5) |
| The release tool signs only what a copy would accept today: a valid manifest, dated by the clock, not below the manifest before it, with the key copies hold; and it verifies the signature it made | A manifest that copies would refuse must fail at the desk, not after publishing. A manifest dated ahead could be kept and served later |

## 3. The bytes

A manifest is refused (`malformed`) unless all of this holds:

1. It is 1 to 262144 bytes long.
2. Every byte is LF (0x0A) or printable ASCII (0x20 to 0x7E). No CR, no tab, no byte order mark.
3. It is JSON (RFC 8259) in which no object has the same key twice and every number is a whole number
   written with digits only.
4. It follows the schema of section 4.
5. It is in the one written form below: writing the parsed content out again gives the same bytes.

The written form:

- An object is `{`, a line end, its members, a line end, the indent of the object, `}`.
- Members are in ascending order of their keys, compared byte by byte. Each is on its own line: two
  spaces for each level of nesting, the key in double quotes, `: ` (colon, one space), the value.
  Members are separated by `,` at the end of the line.
- A string is its characters in double quotes. No valid string holds a character that needs an escape.
- A number is its decimal digits: no sign, no leading zero, no fraction, no exponent.
- A boolean is `true` or `false`.
- The file ends with one LF after the last `}`. Line ends are LF.

A valid manifest holds no list, no null, no empty object and no zero. In Python the form is
`json.dumps(data, indent=2, sort_keys=True) + "\n"`; the example in section 8 shows it byte for byte.

## 4. The fields

All eleven top-level keys are required. No other key is allowed, here or at any level below.

| Key | Type | Rule | Meaning |
|---|---|---|---|
| `schema` | number | Exactly `1` | The schema of this page |
| `channel` | string | A lower-case letter, then up to 31 lower-case letters, digits or `-` | The channel this manifest speaks for, such as `stable`. A copy accepts only its own channel |
| `serial` | number | 1 to 2147483647, and `serial / 100` (whole division) is the UTC day of `published` as YYYYMMDD | Counts the manifests of a channel: every manifest signed has a higher serial than the one before. `2026120100` is the first of 1 December 2026 |
| `published` | string | A time (below) | When this manifest was made |
| `expires` | string | A time, later than `published` and at most 90 days after it | After this, the manifest no longer shows what the newest release is |
| `version` | string | A build version (below), higher than `0.0.0.0` | The build version of the release. This is what is compared with the installed copy |
| `thoron_version` | string | Three numbers of 0 to 9999 joined by `.`, no leading zeros | Thoron's own version, shown to people: `0.1.2` |
| `chromium_version` | string | A build version in form, and equal to `version` with its last number divided by 100 (whole division) | The Chromium version the release is built on: build `158.0.8127.4500` is Chromium `158.0.8127.45` |
| `critical` | boolean | `true` or `false` | `true` for a security release that should not wait: the browser makes the prompt stand out |
| `min_updater_version` | string | A build version, not higher than `version` | The oldest updater that may apply this release. An updater from an older build does not (section 6, step 12) |
| `packages` | object | At least one variant | What can be downloaded, per variant and package kind |

**A time** is exactly 20 characters, `YYYY-MM-DDTHH:MM:SSZ`: UTC, to the second, a real date of the
calendar, year 1970 or later, hours 00 to 23, minutes and seconds 00 to 59. No other spelling is accepted
(no offset, no fraction, no lower-case letters).

**A build version** is four numbers joined by `.`, each 0 to 65535 and written without leading zeros, as
`158.0.8127.4500`. Two build versions are compared number by number from the left. Because there is one
spelling, equal versions are equal strings. `0.0.0.0` stands for "nothing installed" (the installer's
installed version): it is never the `version` of a manifest and never the base of a delta.

Digits are the ten ASCII digits everywhere. The serial ties schema 1 to dates up to the end of 2147.

### Packages

```
packages
  <variant>                one of the six below
    <kind>                 installed, portable, or both
      full                 a file: the whole package
      deltas               optional; 1 to 8 members
        <build version>    a file: the delta that applies from exactly this version
```

| Variant | For |
|---|---|
| `win-x64-avx2` | Windows, x64 processors with AVX2 |
| `win-x64-sse4` | Windows, x64 processors without AVX2 |
| `win-arm64-armv8` | Windows on ARM64 |
| `linux-x64-avx2` | Linux, x64 processors with AVX2 |
| `linux-x64-sse4` | Linux, x64 processors without AVX2 |
| `linux-arm64-armv8` | Linux on ARM64 |

| Kind | Windows | Linux |
|---|---|---|
| `installed` | The installer (`.exe`) for an installed copy | The package for the per-user copy that updates itself |
| `portable` | The portable archive (`.zip`) | The portable archive (`.tar.xz`) |

A Linux copy installed from the `.deb` is updated by APT alone and never reads this manifest.

- A variant holds `installed`, `portable` or both, and nothing else. An empty variant is refused.
- A package holds `full` and, only when there are deltas, `deltas`. An empty `deltas` is refused.
- Each key of `deltas` is a build version lower than `version` and higher than `0.0.0.0`. The delta
  under it turns exactly that installed version into `version`. The release policy is the previous 3
  releases; the limit of 8 leaves room.
- A variant or kind that is missing has no update in this manifest (`no_package`).

A **file** (`full`, and each member of `deltas`) has exactly these three keys:

| Key | Type | Rule |
|---|---|---|
| `url` | string | At most 1024 characters. `https://`, a host, then a path. The host is lower-case letters, digits, `.` and `-`, and is one of the hosts the updater allows, compared as a whole name (a sub-domain of an allowed host is not allowed). The path is one or more segments, each a `/` followed by one or more of `A-Z a-z 0-9 . _ ~ + -`; no segment is `.` or `..`. So: no user name, port, query, fragment, `%` escape, backslash, empty segment or slash at the end |
| `size` | number | 1 to 2147483647: the length of the file in bytes |
| `sha256` | string | 64 characters of `0-9a-f`: the SHA-256 of the file |

The hosts are not part of the manifest. The updater has its own list, compiled in; the reference takes
it from the caller, and the command line defaults to `github.com`.

## 5. The signature

- **Algorithm:** Ed25519 as in RFC 8032, over the message itself (no pre-hash, no context).
- **Message:** the 26 bytes `thoron-update-manifest-v1` and LF
  (hex `74 68 6f 72 6f 6e 2d 75 70 64 61 74 65 2d 6d 61 6e 69 66 65 73 74 2d 76 31 0a`),
  followed by every byte of `update.json` as fetched.
- **`update.json.sig`:** the 64 bytes of the signature (R, then S). No encoding, no line end.
- **Public key:** 32 bytes, compiled into the updater and into the small installer.
- **Private key:** the release key of the key ceremony (P2.11). It is never in the repository, the
  build tree or a log. The tool reads it from a file holding the 32 bytes in base64, the form the ad
  blocker's tool ([`tools/release/adblock_resources.py`](../../tools/release/adblock_resources.py)) uses.

The check is the strict one: a signature whose S is not below the group order is refused (BoringSSL's
`ED25519_verify` does this). The prefix belongs to this schema; a later schema signs under another one.

**What is no key.** Before the signature is checked, the public key itself is: clear the top bit of its
last byte and compare the 32 bytes with the seven values below. If it is one of them, there is no key,
and every check ends in `bad_signature`. The first is all zeros, which is what a build holds until the
real key is put in. Together the seven are the points of small order of the curve, in every spelling:
under them a signature that anybody can write down (for example R `01 00 .. 00` and S zero) fits at
least one message in eight. The Ed25519 check alone does not refuse them (seen with OpenSSL), so this
comparison is a step of its own.

```
0000000000000000000000000000000000000000000000000000000000000000
0100000000000000000000000000000000000000000000000000000000000000
26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05
c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a
ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f
edffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f
eeffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f
```

## 6. Reading a manifest: the order of the checks

The updater knows, without the manifest: the public key, the hosts it allows, its channel, the installed
build version, its own build version, its variant and package kind, the highest serial it has accepted
on the channel (0 on a fresh copy), and the clock. The installer (P3.19) has nothing installed: its
installed version is `0.0.0.0` and its serial 0.

Each step ends the check with the outcome named, or goes on to the next.

| Step | Check | Outcome when it fails |
|---|---|---|
| 1 | `update.json` is 1 to 262144 bytes (read at most 262145: a file that long is too long) | `malformed` |
| 2 | The public key is a key (section 5), `update.json.sig` is 64 bytes, and it is the signature of prefix plus manifest under that key | `bad_signature` |
| 3 | Every byte is LF or printable ASCII | `malformed` |
| 4 | It parses as JSON with no repeated key and whole numbers only | `malformed` |
| 5 | Every rule of section 4 holds, with the updater's own hosts | `malformed` |
| 6 | It is in the written form of section 3 | `malformed` |
| 7 | `channel` is the updater's channel | `wrong_channel` |
| 8 | `serial` is not below the highest serial accepted | `replayed` |
| 9 | `published` is not later than the clock plus 24 hours | `not_yet_valid` |
| 10 | The clock is not later than `expires` plus 24 hours | `expired` |
| | *The manifest is now the channel's current word: store its serial as the highest accepted* | |
| 11 | `version` is not below the installed version; if it is equal, the copy is current | `downgrade`; `up_to_date` |
| 12 | The updater's own version is not below `min_updater_version` | `updater_too_old` |
| 13 | `packages` has this variant and, in it, this kind | `no_package` |
| 14 | Nothing left to check | `update` |

- Nothing of the manifest is looked at before step 2 has passed. Steps 3 to 6 all end in `malformed`,
  so their order among themselves does not show.
- The bytes that step 2 checks are the bytes that steps 3 to 6 read: one buffer that nothing can change
  in between, never a second read of the file.
- What the updater knows about itself (its channel, versions, variant, kind) is not input from the
  network. The reference treats a value there that makes no sense as an error, before it looks at
  the files.
- With `update`, the updater has the `full` file and, when `deltas` has a key equal to the installed
  version, that delta. Which of the two it downloads is P4.2. A delta is never used from any other
  version.
- The stored serial only goes up. It is kept per channel, outside the profile.
- The download is P3.4: over HTTPS, no more than `size` bytes, and the file is opened or run only
  after its length is `size` and its SHA-256 is `sha256`. GitHub answers a release download with a
  redirect to another host; which hosts a redirect may lead to is decided there. Either way it is the
  size and the hash that make the file trusted, not the host it came from. The name of the local file
  is the updater's own choice and is never taken from the address.
- The two files are fetched one after the other. A check that falls between the upload of a new
  manifest and of its signature gets `bad_signature`; the updater checks again later, as after any
  other outcome.
- A manifest that cannot be fetched at all is the updater's "error", not one of these outcomes.

## 7. The outcomes

| Outcome | What it means | About page (P3.9) | Serial stored |
|---|---|---|---|
| `update` | A newer release with a package for this copy | Downloading, then ready to relaunch | Yes |
| `up_to_date` | The channel's current manifest names the installed version | Up to date | Yes |
| `bad_signature` | The signature does not hold. Nothing was read | Cannot verify | No |
| `malformed` | Not a schema 1 manifest: empty, too long, or signed and still against section 3 or 4 | Cannot verify | No |
| `wrong_channel` | A manifest of another channel | Cannot verify | No |
| `replayed` | Older than a manifest this copy has already accepted | Cannot verify | No |
| `not_yet_valid` | Dated after the clock: the clock is behind, or the manifest is wrong | Cannot verify, with a hint to check the date and time | No |
| `expired` | Too old to show what the newest release is | Cannot verify | No |
| `downgrade` | Names a version below the installed one. Nothing is installed | Cannot verify | Yes |
| `updater_too_old` | A newer release that this updater may not apply | Its own message: update with the installer (until P4.6) | Yes |
| `no_package` | A newer release with nothing for this variant and kind | Its own message: a newer version exists, but not for this computer | Yes |

Only `up_to_date` is ever shown as "up to date". The seven outcomes from `bad_signature` to `downgrade`
are the "cannot verify updates" state of the design: the updater does not know whether this copy is
current, and says so. The wording on the page is P3.9's.

## 8. An example

Made by `py -3 -I tools/update/manifest.py example`. The packages and their hashes are made up.

```json
{
  "channel": "stable",
  "chromium_version": "158.0.8127.45",
  "critical": true,
  "expires": "2026-12-31T12:00:00Z",
  "min_updater_version": "158.0.8127.3000",
  "packages": {
    "win-x64-avx2": {
      "installed": {
        "deltas": {
          "158.0.8127.3000": {
            "sha256": "d1453fc2ac526446e9daf1379c4701e2af24ee7eb8686ffc6dd7700c45d49f29",
            "size": 9437184,
            "url": "https://github.com/KuchiSofts/thoron/releases/download/v0.1.2/thoron-158.0.8127.3000-to-158.0.8127.4500-win-x64-avx2-installed.delta"
          }
        },
        "full": {
          "sha256": "ac60555676060f4ff7febfa0fdb5c52754fe64ed443f6951de80230807218ed4",
          "size": 104857600,
          "url": "https://github.com/KuchiSofts/thoron/releases/download/v0.1.2/thoron-158.0.8127.4500-win-x64-avx2-installer.exe"
        }
      },
      "portable": {
        "full": {
          "sha256": "b915dcbaad935d13eb57f786379fe66736d250c87fe38219936e5e9f1b10fad0",
          "size": 157286400,
          "url": "https://github.com/KuchiSofts/thoron/releases/download/v0.1.2/thoron-158.0.8127.4500-win-x64-avx2-portable.zip"
        }
      }
    },
    "win-x64-sse4": {
      "installed": {
        "full": {
          "sha256": "4369d3f54d229f8c0dade05b13e4429c392f3408303033618a5a12fbedbd7eac",
          "size": 103809024,
          "url": "https://github.com/KuchiSofts/thoron/releases/download/v0.1.2/thoron-158.0.8127.4500-win-x64-sse4-installer.exe"
        }
      }
    }
  },
  "published": "2026-12-01T12:00:00Z",
  "schema": 1,
  "serial": 2026120100,
  "thoron_version": "0.1.2",
  "version": "158.0.8127.4500"
}
```

These are 1644 bytes with the SHA-256
`78694825ce6c7e4f5c7549946bd23b546530599b9419461a7a42658d41cfc8de`.

What copies on channel `stable` make of it (the tests run every row):

| Installed | Updater | Variant | Kind | Clock | Highest serial accepted | Outcome |
|---|---|---|---|---|---|---|
| `158.0.8127.3000` | `158.0.8127.3000` | `win-x64-avx2` | `installed` | `2026-12-02T00:00:00Z` | `0` | `update`: the full package, or the delta from `158.0.8127.3000` |
| `158.0.8127.2900` | `158.0.8127.3000` | `win-x64-avx2` | `installed` | `2026-12-02T00:00:00Z` | `0` | `update`: the full package only |
| `158.0.8127.2900` | `158.0.8127.2900` | `win-x64-avx2` | `installed` | `2026-12-02T00:00:00Z` | `0` | `updater_too_old` |
| `0.0.0.0` | `158.0.8127.4500` | `win-x64-sse4` | `installed` | `2026-12-02T00:00:00Z` | `0` | `update`: the full package only (the installer) |
| `158.0.8127.3000` | `158.0.8127.3000` | `win-x64-sse4` | `portable` | `2026-12-02T00:00:00Z` | `0` | `no_package` |
| `158.0.8127.3000` | `158.0.8127.3000` | `linux-x64-avx2` | `installed` | `2026-12-02T00:00:00Z` | `0` | `no_package` |
| `158.0.8127.4500` | `158.0.8127.4500` | `win-x64-avx2` | `installed` | `2026-12-02T00:00:00Z` | `0` | `up_to_date` |
| `158.0.8127.4600` | `158.0.8127.4600` | `win-x64-avx2` | `installed` | `2026-12-02T00:00:00Z` | `0` | `downgrade` |
| `158.0.8127.3000` | `158.0.8127.3000` | `win-x64-avx2` | `installed` | `2026-12-02T00:00:00Z` | `2026120100` | `update`: the same manifest again, with the delta from `158.0.8127.3000` |
| `158.0.8127.3000` | `158.0.8127.3000` | `win-x64-avx2` | `installed` | `2026-12-02T00:00:00Z` | `2026120101` | `replayed` |
| `158.0.8127.3000` | `158.0.8127.3000` | `win-x64-avx2` | `installed` | `2026-11-30T12:00:00Z` | `0` | `update`: 24 hours before `published`, with the delta from `158.0.8127.3000` |
| `158.0.8127.3000` | `158.0.8127.3000` | `win-x64-avx2` | `installed` | `2026-11-30T11:59:59Z` | `0` | `not_yet_valid` |
| `158.0.8127.3000` | `158.0.8127.3000` | `win-x64-avx2` | `installed` | `2027-01-01T12:00:00Z` | `0` | `update`: 24 hours after `expires`, with the delta from `158.0.8127.3000` |
| `158.0.8127.3000` | `158.0.8127.3000` | `win-x64-avx2` | `installed` | `2027-01-01T12:00:01Z` | `0` | `expired` |
| `158.0.8127.4500` | `158.0.8127.4500` | `win-x64-avx2` | `installed` | `2027-01-01T12:00:01Z` | `0` | `expired`, not `up_to_date` |

### A signature to test against

The example was signed once with a key made for that and thrown away, so the C++ tests have a fixed
vector without any private key existing. It is a test value only and signs nothing else.

```
public key (32 bytes, hex)
a21d28d09d8eb9b329c984c3a47d1c885630be54588bfc6720634ef2d23cccbc

update.json.sig (64 bytes, hex)
945aa027baf3df0751a4dbf005dacc89f9d100fb24d2e3d7bcfbf62e6027abed
45fd2727f0d246fd41da72cdcb1a5d937290f265dfe017c5076ec50544fad70a
```

With this key, the example verifies; with any one bit of the example or of the signature changed, it
does not.

## 9. Threats and what answers them

| Threat | Answer |
|---|---|
| A forged or altered manifest | The Ed25519 signature over the exact bytes (step 2). The key is not on GitHub, so a taken-over account can publish files but not sign them |
| A crafted file aimed at the JSON reader | Nothing is parsed before the signature holds, and the read is capped at 262144 bytes |
| A signature made for something else, shown as a manifest's | The purpose prefix (section 5) |
| A build that went out without its real key, or with a key of small order | Such a key is no key: every manifest is refused (section 5, step 2) |
| An old, vulnerable release offered as an update | Only a higher build version is installed (step 11) |
| An older manifest replayed to a copy that has seen a newer one | The serial (step 8) |
| Updates withheld by serving an old manifest again and again (freeze) | The expiry (step 10): at most 90 days, 30 by default. An expired manifest is "cannot verify", never "up to date" |
| A wrong clock, or one set back on purpose | 24 hours of tolerance both ways; a manifest from the future is `not_yet_valid` and its serial is not stored |
| A serial so high that no later manifest could follow it | The serial is tied to the day of `published` and is stored only after steps 9 and 10 |
| A manifest of one channel served on another | The channel is signed and compared (step 7) |
| A download from somewhere unexpected, or an address read two ways | HTTPS only, the updater's own host list, one plain form of address (section 4) |
| A swapped, cut or padded package | `size` and `sha256` come from the signed manifest and are checked before the file is used (P3.4) |
| A package for another processor or install type | Fixed variant and kind names, found by exact match |
| An old updater with a flaw applying a new release | `min_updater_version` (step 12) |
| Two programs reading the same manifest differently | The one written form, ASCII only, no repeated keys, small whole numbers (section 3) |
| A mistake at signing: a wrong date, a wrong key file, a manifest that goes back | The tool signs only what a copy would accept today, dated by its own clock; it is told the public key copies hold and refuses a private key that is not its other half; it compares with the manifest before; it verifies the signature it made |
| A manifest dated ahead, kept and served when its day comes | The tool does not sign one: `published` is at most 10 minutes ahead of the signer's clock |
| A lost or stolen signing key | Not answered by the manifest: the key is kept offline (P2.11), and rotation is P4.7 |

## 10. Making and signing a manifest

The release script makes the manifest with the release.
[`tools/release/release.py prepare`](../../tools/release/release.py) calls the tool's functions: `file_entry`
(the size and hash of each package as it lies in the release folder), `build` (the bytes of the manifest,
with the next serial) and `sign`.

```
py -3 -I tools/release/release.py prepare <the release's options> --manifest-key <private key file> --manifest-public-key <base64> --gh-repo KuchiSofts/thoron --previous-manifest <the last update.json>
py -3 -I tools/release/release.py publish --dist <release folder> --version <Thoron version> --gh-repo KuchiSofts/thoron --manifest-public-key <base64>
```

- `prepare` takes the build version and Thoron's version from the build tree (`chrome/VERSION`), and
  gives each package the address it will have as an asset of the release tagged `v<Thoron version>`.
  `--critical` marks a security release; `--channel` and `--manifest-days` change `stable` and 30 days.
- `--previous-manifest` is the manifest this one replaces. The first manifest of a channel is made with
  `--first-manifest --min-updater-version <build version>` instead. Later manifests keep the
  `min_updater_version` of the one before; giving the option again changes it.
- What would stop the manifest is found before anything is packaged: a private key that is not the other
  half of `--manifest-public-key`, a version that does not follow the manifest before, a variant this
  schema does not know, a build without Thoron's version.
- Without `--manifest-key` there is no manifest, and `prepare` says so; it never writes an unsigned one.
  The key is read from the file named and from nowhere else, and a key file inside the repository, the
  build tree or the release folder is refused unread.
- `prepare` reads back the two files it wrote and verifies them with the public key.
- `publish` makes no draft of a release folder whose manifest is missing, unsigned, does not verify
  with `--manifest-public-key`, would be refused by a copy today for its dates, or names a file whose
  address, size or SHA-256 is not that of the file in the folder under the draft's tag. So the draft is
  made with `--version <Thoron version>`.
- `update.json` is not listed in `SHA256SUMS`. It carries its own signature, and it is replaced by a
  newer one while its release is still the newest.

For signing and for checking by hand there is a command line:

```
py -3 -I tools/update/manifest.py validate update.json
py -3 -I tools/update/manifest.py sign update.json --key <private key file> --public-key <base64> --previous <the last update.json>
py -3 -I tools/update/manifest.py verify update.json --public-key <base64>
py -3 -I tools/update/manifest.py verify update.json --public-key <base64> --installed 158.0.8127.3000 --variant win-x64-avx2 --kind installed
py -3 -I tools/update/manifest.py example --out example.json
```

- `validate` lists every problem of a manifest. `verify` checks the signature first, then the manifest,
  then its dates; with `--installed` it shows what that copy would do. `example` gives the manifest of
  section 8, for reading and for tests. Exit codes: 0 fine, 1 refused, 2 could not run.
- `sign` writes `update.json.sig` next to the manifest. It needs three things besides the private key:
  - `--public-key`, the key that copies of Thoron hold. A private key that is not its other half signs
    nothing, so a wrong key file is noticed at the desk.
  - `--previous`, the manifest this one replaces, or `--first` when the channel has none. With
    `--previous` it refuses a manifest whose serial is not higher, whose `published` is earlier, whose
    version is lower, whose channel differs, or whose Thoron version does not move together with the
    build version.
  - a right clock: it refuses a manifest whose `published` is more than 10 minutes ahead of it, and one
    that has expired.
- `--host` (repeatable) sets the allowed hosts; the default is `github.com`.
- `sign` and `verify` need the Python package `cryptography`; `example` and `validate` do not.
- The tool never overwrites a file. Of a file that is no manifest (another file given by mistake), a
  message names at most the keys, never the content.
- A manifest is good for 30 days. Sign a new one (the same release, new dates, the next serial) at every
  release and, when there is none, at the latest a week before the current one expires; the two new
  files take the place of the old ones in the newest release. When none is signed in time, every copy
  shows "cannot verify updates" until one is.
- Write the file once and leave it alone: an editor or a transfer that changes line ends breaks the
  signature. `build()` and `example --out` write the bytes as they must be; redirecting the output of
  `example` in PowerShell does not, because PowerShell re-encodes what it redirects.

## 11. Left for later stages

- **P3.3, P3.19:** the C++ reader. It keeps the highest accepted serial per channel outside the profile,
  caps the fetch, and sends no cookies or identifiers.
- **P3.2, P2.12:** `release.py prepare` packages one variant at a time, so its manifest names one variant.
  A release of several variants needs the build matrix of P2.12 first. Signing the manifest of the same
  release again before it expires (section 10) has no command of its own yet.
- **P4.2:** schema 1 lists deltas that lead straight to `version`. A chain over releases in between
  would need their deltas too.
- **P4.4:** the reference looks up one variant. A processor with AVX2 can also run `sse4`; whether the
  updater falls back to it when `avx2` is missing is decided there.
- **P4.6:** `updater_too_old` only stops an old updater. How it gets a newer one by itself is not in
  schema 1. The small installer is an updater too: a `min_updater_version` above its own build stops it
  as well, so it is raised only when old updaters must really not be used.
- **P4.7:** one public key. The signature file names no key; an updater that trusts two keys tries both.
- **`critical`** speaks for this release only. A copy two releases behind does not learn that the release
  it skipped was critical.
- **One version per manifest:** when a platform ships later than the others, its copies get `no_package`
  until it does.
