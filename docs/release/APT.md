# Thoron's APT repository (ROADMAP P2.10)

The `.deb` installs of Thoron are updated only through Thoron's own signed APT repository (design 7.5a).
Upstream's repository is unsigned (upstream issues #1164 and #1049); this one never is.

## 1. How it is laid out

A Chromium-based `.deb` is over 100 MB. A git repository refuses files over 100 MiB and a GitHub Pages site
may hold at most 1 GB, so the repository cannot live on Pages as the design first said. It is a *flat*
repository in one release of its own, tag `apt`, whose files are replaced at each version:

| File | What it is |
|---|---|
| `thoron-browser_<version>_amd64.deb` | the AVX2 build for x64 |
| `thoron-browser-sse4_<version>_amd64.deb` | the SSE4.2 build for older x64 processors |
| `thoron-browser_<version>_arm64.deb` | the ARM64 build |
| `Packages`, `Packages.gz` | the index: every package with its size, SHA-256 and SHA-512 |
| `Release` | the hashes of the index, its date and its `Valid-Until` |
| `InRelease`, `Release.gpg` | `Release` signed with Thoron's APT key (clear-signed, and detached) |
| `thoron-archive-keyring.gpg` | the public key, for the person's `Signed-By` |

A person's source (deb822, `/etc/apt/sources.list.d/thoron.sources`):

```
Types: deb
URIs: https://github.com/KuchiSofts/thoron/releases/download/
Suites: apt/
Signed-By: /usr/share/keyrings/thoron-archive-keyring.gpg
```

apt then fetches `.../releases/download/apt/InRelease` and follows GitHub's redirect to its file host. The
source names the folder `apt/` rather than `./`, so no request holds a `./` part, which a strict server
refuses; the index names each package as `apt/<file>`. The steps for a person are in the
[Linux install guide](../user/INSTALL_LINUX.md#2a-updates-through-apt).

## 2. Two x64 builds, two package names

The AVX2 and the SSE4.2 builds share the architecture `amd64`, and one index cannot hold one package twice. So
the SSE4.2 build is the package `thoron-browser-sse4`, and each x64 package conflicts with and replaces the
other. `apt upgrade` therefore never swaps one for the other: the AVX2 build would stop on a processor without
AVX2. Only the control file differs from the build's `.deb`; the program files are the build's, byte for byte.
`tools/release/release.py` writes the release's own `.deb` the same way, so a package downloaded by hand and the
one in the repository are the same file.

## 3. What apt checks

- `InRelease` must be signed by the key in `Signed-By`, and apt trusts that key for this repository only.
- The index must have the hashes `InRelease` names, and each package the hashes the index names.
- `Valid-Until` is 30 days after signing by default (at most 90). Without it, someone could keep serving an old,
  validly signed index and hold back a security update for good.

`tools/qa/linux_apt_repo_check.py` checks all of this with apt itself on a clean Ubuntu, with a throwaway key
and a local server that redirects the way GitHub does: the update, an install of `thoron-browser-sse4`, an
upgrade that brings the newer SSE4.2 build and never the AVX2 one, and four refusals (a changed `InRelease`, an
index signed with another key, an expired index, a package list that is not the one `InRelease` names).

## 4. For the release

```
py -3 -I tools/release/apt_repo.py build --deb <release>/thoron-<version>-linux-x64-avx2.deb \
    --deb <release>/thoron-<version>-linux-x64-sse4.deb --deb <release>/thoron-<version>-linux-arm64-armv8.deb \
    --out <apt folder> --gnupg-home <the APT key's GnuPG folder> --key <its fingerprint>
```

Then the files of `<apt folder>` replace those of the release `apt` (the owner publishes it). Between versions,
before `Valid-Until` passes, the same packages are signed again:

```
py -3 -I tools/release/apt_repo.py resign --repo <apt folder> --gnupg-home <...> --key <fingerprint>
```

`resign` checks first that every package is the one the index names. The signing key is the owner's APT key
(ROADMAP P2.11, `docs/release/KEYS.md`); it never leaves the owner's machine, and its public fingerprint goes in
the README.
