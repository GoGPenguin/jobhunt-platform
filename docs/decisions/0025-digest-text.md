# 0025: Digest text

Date: 2026-10-20
Spec: [05-notifications](../spec/05-notifications.md), N4, N5, N6, N9; plan [05](../plans/05-notifications.md) task 3

## Implementation

- `jobhunt.notify.digest.compose(postings, last_run, now=, tz=)` is a pure function returning the Telegram HTML messages and every posting included.
- **Header:** count ("1 new job" / "N new jobs" / "no new jobs") and the local day. Weekday and month names come from fixed English lists, not `strftime("%a")`, which follows the process locale (a systemd unit or container may have another).
- **Collector line:** "last run HH:MM, OK (E emails, N new jobs)", or a ⚠ warning when there is no run, the last run failed (its error, escaped and cut to 200 characters), or the last run is older than 26 hours.
- **Each posting** shows title · company; location (first location as city, region, country, "+N" for more, else `location_raw`), workplace when known, and salary; the representative job's URL with its source and "also on: …" other sources; and the attribution text when present.
- **Salary:** VND in millions ("15–25M VND/month (net)"), other currencies with thousands separators; "from" / "up to" for open ranges; period and net/gross shown only when known; trailing zeros dropped. The range dash is a named constant.
- **Escaping:** `html.escape` on every value, including URLs (`&` → `&amp;`).
- **Cap:** 30 shown, then "… and N more (see: jobhunt digest list)"; all postings are returned for marking (spec 05).
- **Splitting:** blocks are added while the message stays within 4,096 UTF-16 code units of HTML, never less than Telegram's own count after tags are removed. A posting is never cut: the model's field limits keep every block far below the limit, and cutting could produce broken HTML, which Telegram rejects. An earlier truncation safeguard was removed for that reason.

## Verified

- Tests written first (18 new; 425 in total): exact text for a normal and an empty digest, three collector warnings, escaping of `<`/`&` in titles, companies and URLs, multi-source "also on", the cap of 30 + "and 5 more", splitting 30 long postings across messages with every message within the limit and every posting whole, UTF-16 counting, and six salary formats.
- The tests' expected weekday was itself wrong at first ("Tue 21 Oct"); 21 Oct 2026 is a Wednesday, checked with `zoneinfo` and fixed in the tests and in spec 05's example.
- No new dependencies, cost $0.
