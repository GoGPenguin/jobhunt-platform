# 0034: Place data: GeoNames cities and region definitions

Date: 2026-10-21
Spec: [07-matcher](../spec/07-matcher.md), M2, M10; plan [07](../plans/07-matcher.md) task 1

## Implementation

- `scripts/gen_places.py` downloads GeoNames `cities15000.zip` and `countryInfo.txt` (CC BY 4.0) and writes, into `jobhunt/matching/data/`:
  - `cities.tsv.gz`: 32,590 folded names (name and ASCII name) → ISO country, the most populous kept on a clash; 172 KB, written with gzip `mtime=0` so a rerun gives identical bytes;
  - `regions.yaml`, from the lists reviewed in plan 07 plus continent data: WORLDWIDE 249, APAC 52, ASEAN 11 (with Timor-Leste since October 2025; spec 07 updated from "10 members"), EU 27, EMEA 125, AMERICAS 55, LATAM 24.
- Attribution ("GeoNames (https://www.geonames.org), CC BY 4.0") and the download date are in both file headers.
- `jobhunt.matching.places`:
  - `country_of_city` folds the name, strips a "Greater " prefix and "Capital Region" / "Metropolitan Area" / "Area" / "Region" suffixes, and also tries the name without spaces ("Ha Noi" → "Hanoi"). Words like "Remote" or "Hybrid" are never places.
  - `location_countries` uses a stated country first, then the city, then the region.
  - `Regions` (bundled, `with_overrides` for preferences): a country code stands for itself, and an unknown label returns `None`, meaning "not stated".

## Bugs found by the tests

- **The YAML "Norway problem":** the first `regions.yaml` listed codes unquoted, and YAML 1.1 reads `NO` as the boolean `false`, so EMEA and WORLDWIDE contained `False`. Fixed twice:
  - the generator quotes every code;
  - **the shared strict YAML reader (`config_files`) now follows YAML 1.2 booleans** (only `true`/`false`). A user's `countries: [NO]` in `preferences.yaml` stays "NO". `yes`/`no` become strings, which Pydantic still accepts for boolean fields, and all existing files validate unchanged (the real profile check: 0 errors).

## Verified

- Tests written first (21 new; 525 in total); `make check` passes.
- M2: "Đà Nang", "Đà Nẵng", "Da Nang", "Ha Noi", "Hanoi", "Hanoi Capital Region" and "Ho Chi Minh City" → VN; "Singapore" → SG; "Greater Tokyo Area" → JP; "Berlin Metropolitan Area" → DE.
- A stated country beats the city lookup.
- Every code in both files is an ISO country code; the city file carries the CC BY attribution.
- No new dependencies; the download is a development-time step only. Cost $0.
