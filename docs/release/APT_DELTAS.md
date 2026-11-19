# Delta updates for the APT repository: `debdelta` (ROADMAP P4.11)

**Decided on 2026-11-17: not adopted.** System installs (`.deb`) keep downloading full packages. People who
want small updates on Linux use the per-user install, which updates with the same signed delta updater as
Windows (design 7.5a, ROADMAP P4.1). This page says why, and when to look again.

## What debdelta does

`debdelta` is a Debian tool in two parts. A server side makes a delta for each pair of an old and a new
version of a package. On the PC, `debdelta-upgrade` runs before `apt upgrade`: for every package apt is
about to upgrade it downloads the delta, rebuilds the new `.deb` from the files the old version installed
plus the delta, and puts it into apt's package cache. apt then installs that `.deb` as if it had downloaded
it, after checking it against the signed index of the repository; when a rebuild fails, apt downloads the
full package. apt itself has no delta support for packages (its "pdiffs" are for the index files only).

## Why not

1. **Almost nobody would get it.** Every PC needs the `debdelta` package installed, a delta source
   configured, and `debdelta-upgrade` run before each upgrade. A plain `apt upgrade`, and every automatic
   upgrade (`unattended-upgrades`, a desktop's software updater), never uses it. A saving that only a few
   people set up by hand does not pay for what it costs to build and keep.
2. **The rebuild is fragile for a browser.** The new `.deb` has to come out byte for byte the same, or
   apt's checksum refuses it. That needs every file of the old package on disk, unchanged, and the
   package's compressed contents made again exactly as the build made them. A browser package has
   hundreds of MB of files to read and compress again, which takes minutes on a laptop, and any change
   in the compressor's version or settings turns the delta into a wasted download followed by the full one.
3. **Storage and hosting.** Deltas from the previous 3 releases (design 7.3), per variant and per
   architecture, add to a repository that is meant to be static files. The repository's place is still
   open in P2.10, and its size limits matter there already (see below).
4. **A second delta format to sign and test.** Thoron already makes, signs and tests its own deltas
   (Zucchini, per file, checked by SHA-256 before and after, ROADMAP P4.1). debdelta would be a second
   tool, a second format and another key or signature path, for the smallest group of users.
5. **The per-user install already gives small updates on Linux**, without root, with the same updater,
   manifest and checks as Windows (design 7.5a, item 2), and the release notes can say so.

Security is not a reason either way: apt checks the rebuilt `.deb` against the signed index, so a bad
delta can waste a download but cannot install anything that was not signed.

## For P2.10, found on the way

A Chromium-based `.deb` is around 100 MB. GitHub refuses files over 100 MiB in a git repository, and a
GitHub Pages site may be at most 1 GB, so the packages may not fit into a Pages site at all. A flat APT
repository can point at the release's own downloads instead (the `Packages` and `InRelease` files beside
the `.deb` in a release; apt follows GitHub's redirect to its file host). This is P2.10's choice to make;
it is written here so that it is not found late.

## When to look again

- apt itself learns delta downloads for packages, or
- the APT repository runs (P2.10) and its download volume, or reports from people on slow or metered
  connections, show that full packages are a real problem for system installs.
