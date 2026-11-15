# Ad blocking

Thoron has two ad blockers. One is **Thoron adblock**, built into the browser itself, on by default and
meant to replace the extension. The other is the uBlock Origin extension, which a profile that already has
it keeps.

## Thoron adblock

### How it works

- **Same lists as uBlock Origin.** EasyList, EasyPrivacy, the uBlock filter lists (ads, privacy, badware,
  quick fixes, unbreak), Peter Lowe's list and a list of malware sites.
- **Works from the first page.** The lists come with the browser, already prepared, so nothing has to be
  downloaded before it blocks.
- **Keeps itself current.** It fetches newer lists at most every 4 days, over HTTPS, without cookies or
  identifiers. A list that looks wrong is refused and the previous one stays.
- **Blocks before the request leaves.** A request for an ad or a tracker is stopped inside the browser.
  This covers pages, frames, redirects, web workers and WebSocket connections.
- **Sees through disguised ad servers.** Some ad servers change their names all the time. When a
  server's answer gives it away, the answer is thrown away before the page sees it.
- **Skips tracking detours.** A link that leads to a tracker first, which then sends you on, goes straight
  to the real page.
- **Switches off ad-tech features.** Browser features that were built for ad targeting, or that help to
  tell your browser from others (ad topics, ad auctions, idle detection and a few more), are off on every
  site.
- **Cleans addresses.** Tracking parts of addresses are taken out, also where a site writes them into
  the path.
- **Cleans the page.** Leftover ad boxes are hidden (also inside widgets that keep their content apart),
  tracking parameters are removed from addresses, and
  small scripts from uBlock Origin defuse anti-blocker code. A blocked script that a page needs is answered
  with a harmless stand-in, so the page keeps working.
- **Private.** What is blocked is counted in memory only. Nothing is stored or sent.

Because it is part of the browser, it starts before any page script runs, and it measures faster and
lighter than the extension with the same blocking.

### On by default

It is **on by default**. A new profile no longer gets uBlock Origin; a profile that has it keeps it,
and the menu of the shield says when both run: two blockers do the same work and slow pages down, so
turn one of them off ("Open extensions"), or choose "Keep both". To take Thoron adblock out
entirely, set "Thoron adblock" to **Disabled** on `chrome://flags/#thoron-native-adblock` and
relaunch.

When the browser starts, the tabs it opens again wait for Thoron adblock to be ready, a few milliseconds
as a rule and four seconds at most, so they are filtered like every other page.

### Off and on

You switch it off and on whenever you like, with no relaunch:

- in the menu of the shield, the **On** switch at the top: it asks for how long (5 minutes, 1 hour,
  until the browser closes, or until you turn it on). While it is off the shield is grey, and the
  menu's big button turns it on again;
- on `chrome://adblock`, "Block ads and trackers on every site" and "Turn it off for a while";
- with a shortcut you set there: "Blocking off or on for every site".

Off, nothing is blocked or hidden on any site. Off for a while comes back on by itself; off for good
stays off until you turn it on. The filter lists stay up to date either way: they are looked for every
few days, again as soon as the network is back, and after the computer wakes up.

### Use it

- **The shield:** in the address bar on every page, and in the toolbar next to it, where extensions'
  icons sit. `chrome://adblock` sets where it is: in both, in the address bar only, or in the toolbar
  only; and where exactly: in the toolbar right after the address bar, after the extensions or next to the
  menu, and in the address bar with the other icons, before them or at the far end. A small preview shows
  your choice. It is teal while it blocks and grey where it is off; its number is what was blocked on the page
  you look at. Click it for the menu, click it again to close it; the menu is loaded ahead, so it opens
  at once:
  - the big **power button** switches blocking off or on for this site (the page reloads);
  - **Filter lists:** every list with its number of rules; switch a list off or on, **Update now**,
    add a list by its address or remove one you added. A change is in use at once;
  - the counts: blocked on this page (and its share of the page's requests), domains connected out of
    all the page asked, blocked so far;
  - **Block element:** click the thing you want gone, choose or edit the rule, press Enter or
    Create. The rule goes into My filters and works at once;
  - **Zapper:** click things to remove them until the page reloads; Esc stops. A page a cookie wall had
    locked can scroll again;
  - or right-click the thing on the page and choose **Block element...**: the picker opens on it
    (inside a frame, **Block element in frame...** picks in that frame; where large media is stopped,
    **Temporarily allow large media elements** lets it through on the site until you close the browser);
  - **Logger:** the requests of your open tabs, blocked and let through; "Block" or "Allow" on a row
    makes a rule for that host; "Why?" names the rule that blocked it or let it through, and its list.
    Show one type of request only, **Pause** to look at what is there, **Clear** to see only what
    comes next, and **Export** what is shown as a text file. "3p" marks a request to another site;
    show first or third party only. The filter takes words that must all be there, `-word` for one
    that must not, and `/.../` for a regular expression. While it is open, the hide rules that
    hid something on a page you load are listed too, as "hidden", and the scriptlets it got, as
    "injected";
  - **Settings:** the full page, `chrome://adblock`;
  - switches for this site: pop-ups (no window the site opens, also from a click), large media (sound
    and video over 50 KB, or the size you set; a stopped one gets a bar: click it to load it), no hiding, remote fonts, JavaScript, 3rd-party scripts and 3rd-party frames
    (nothing of that kind from other sites). A blue switch means it is on;
  - **Rules for this page** (open it once, it stays open): uBlock Origin's grid. A row for each kind
    of request and for each domain the page used, with how many requests went there and how many
    were blocked. Each row has a cell for every site and one for this site: allow (✓), leave it to
    the lists (○) or block (✕). A strong color is a rule set there, a light one comes from a
    broader rule; click a set rule again to take it out. Changes work after **Reload** but only for
    now: **Save** keeps them in My rules, **Revert** takes them back. On `chrome://adblock`, My rules
    show these changes too, under "Changed in the menu for now", with "Save them" and "Revert them".

- **Pop-ups:** ad windows and tabs a page tries to open are not opened at all, and count on the shield.
- **Subscribe links:** on filter list websites, a "subscribe" link (or right-click it and choose
  **Subscribe to filter list...**) opens the settings page, which asks before it adds the list.
- **Blocked pages:** a page your lists name as harmful (malware, phishing) or as an ad site is not
  opened. A page says why. To open it anyway, click the shield: "Open it now" opens that site until
  you close the browser, "Always on this site" for good (you can take it back on `chrome://adblock`,
  under the switches of sites). If the blocked page only sends you on somewhere else, the page offers
  that address as a link.

- **See what happened:** when something was blocked, an icon appears in the address bar. Click it to see
  how many ads and trackers were blocked on the page, and from which sites.
- **Allow a site:** tick "Always allow ads and trackers on this site" in that bubble, or click the icon
  left of the address, open "Site settings" and set "Ads and trackers" to Allow. Reload the page.
- **Manage allowed sites:** on `chrome://adblock`, under the sites: add one, take one out, or
  **Import** and **Export** them as a text file (one site a line). To allow everywhere: Settings,
  "Privacy and security", "Site settings", "Additional content settings", "Ads and trackers".

### Lists and your own rules

- **Finding things:** type in "Find a setting" or "Find a list, a country or a language" and only what
  matches stays. The lists for regions and languages show each country's flag and name, and the ones for
  your browser's languages are suggested at the top (nothing is added unless you tick it).

Open `chrome://adblock`.

- **Settings:** as in uBlock Origin. Show the count on the shield; privacy options (no pre-fetching, no
  hyperlink auditing, WebRTC without local IP addresses, no CSP reports); what every site gets by default
  (no hiding, no large media, no remote fonts, no JavaScript, no third-party scripts or frames: uBlock
  Origin's "medium mode"), which the menu's switches change for one
  site; ignoring hide rules written for every site; the size of "large media"; "Block element..." in
  the right-click menu; the grid of rules in the menu ("I am an advanced user"), in blue and orange
  with "Color-blind friendly"; the theme of these pages (as the system, light or dark), their accent
  color and "Disable tooltips"; and, under the lists,
  whether they update on their own (otherwise only "Update now" downloads them).
- **Language:** the settings page and the menu follow the browser's language: English, Spanish,
  French, German, Portuguese or Russian. Rules, addresses and list names stay as they are.
- **Shortcuts:** under Settings, click a box and press Ctrl or Alt with a letter, a digit or F1 to F12
  to open the picker, the zapper or the logger, or to switch blocking, hiding or JavaScript for the site,
  with the keyboard. They work while a page has the focus.
- **My rules:** uBlock Origin's dynamic filtering, one rule per line: `* * 3p-script block` blocks
  scripts from other sites everywhere, `example.com * 3p-script noop` gives them back to the lists on
  example.com, `example.com cdn.example.net * allow` lets a host through on a site (also when the menu's
  switches block other sites' scripts or frames). The most specific rule decides. A rule can name an
  address too, as in uBlock Origin: `example.com https://cdn.example.net/ads/ * block` blocks what
  starts with that address on example.com, before the rules of hosts. "Import and append"
  adds the lines of a text file, "Export" saves your rules as one. uBlock Origin's switch lines work
  too (`no-scripting: example.com true`, `no-large-media: * true` and the others): when you save, they
  go to the sites' switches and the settings; Export writes them, so the file also works in uBlock Origin.
- **Backup:** "Back up to file" saves your lists, own rules, allowed sites, switches and settings in a
  file; "Restore from file" brings them back, on this or another computer; "Reset to default settings"
  starts over (back up first). "Send to cloud storage" keeps the same backup with the browser's own
  sync (on your other computers too, when sync is on); "Restore from cloud storage" brings it back.
- **Troubleshooting:** "Copy troubleshooting info" copies the browser's version, the lists in use and
  the settings you changed, to paste where you ask for help. It holds no address you visited.

- **More lists:** cookie notices, annoyances, more privacy and lists for your region or language, as
  uBlock Origin offers them. Tick a list to add it; untick it to remove it.
- **Filter lists:** every list has a checkbox. A list that is switched off is neither used nor downloaded.
  **View** shows the rules of a list in use (and what it says about itself); "Show only lines with"
  finds the lines with some words.
  "Update now" looks for newer lists at once.
- **Add a list:** paste its address (it must start with `https://`) and press Add. The list is checked
  first; something that is not a filter list is refused, and the page says why. Remove takes it out again.
- **My filters:** write your own rules, one per line, and press Save. For example `||ads.example.com^`
  blocks a host, `example.com##.banner` hides something on a site, and `@@||example.com^` allows a site.
  After Save, the page names any line that is not a filter it can use, and why.
  "Import and append" adds the lines of a text file, "Export" saves your filters as one. "Allow custom
  filters requiring trust" lets your filters use what only uBlock Origin's lists may (scriptlets that
  set cookies or click elements, for example): turn it on only for filters you understand.

Every change is in use at once, and stays after a restart and after an update of the browser. What you
choose stays on your computer. Each list is fetched again as often as it says (from twice a day to every
two weeks; every 4 days when it does not say), without cookies; the page shows its next check.

Rules of a list you add, and your own rules, block and hide like any other. They cannot use the powerful
scripts that only uBlock Origin's own lists may use, unless you allow it for your own filters (above).

### Beyond uBlock Origin in Chromium

- **HTML filtering, `##^responseheader()` and `$replace`** work in every page: uBlock Origin
  can do these only in Firefox. A script a list names is taken out of the page before it runs, also
  when the rule depends on the rest of the page.
- **A page's quiet answers hold everywhere.** Some rules answer a blocked request inside the page with an
  empty success, so the site does not notice (Google Docs needs this, or it keeps reconnecting). Thoron
  adblock gives the same answer at the network as well, so it holds for a page that started before its
  rules were ready, and for the page's workers.

## uBlock Origin

The genuine, unmodified uBlock Origin extension. Its dashboard has everything it always had: choosing
lists, your own filters, the element picker and the logger. Thoron never changes its settings or your
filters, also not when the built-in blocker becomes the default.
