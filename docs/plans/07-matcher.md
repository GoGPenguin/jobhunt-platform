# Plan 07: Matcher

Spec: [07-matcher](../spec/07-matcher.md)
Status: approved 2026-10-21

## Design

**Code layout:** `jobhunt.matching`:
- `places.py`: city → country, region → countries;
- `infer.py`: seniority, years and skills from job text;
- `score.py`: components, weights, filters and ranking, all pure functions;
- `data/`: the generated city table (`cities.tsv.gz`) and `regions.yaml`.

The digest calls `rank(postings, profile)` and gets back ranked postings with score, reasons and flags.

**City data:** `scripts/gen_places.py` downloads GeoNames `cities15000.zip` (all cities over 15,000 people) and `countryInfo.txt` (country → continent), both CC BY 4.0.
- **Output:** `cities.tsv.gz`: folded name → country code, the most populous kept on a clash. The name and the ASCII name are both indexed ("Đà Nẵng" and "Da Nang" both give VN). An estimated 25,000 names, about 250 KB compressed.
- **Header:** the download date, the source URL and "GeoNames, CC BY 4.0"; the attribution is repeated in `docs/` and the README.

**Regions** (`regions.yaml`, reviewed here; `preferences.yaml` can override or add):

| Label | Countries |
| ----- | --------- |
| WORLDWIDE | every ISO country |
| ASEAN | BN, KH, ID, LA, MY, MM, PH, SG, TH, TL, VN (11 members: Timor-Leste joined in October 2025, so the spec's "10 members" is updated) |
| APAC | ASEAN plus CN, HK, MO, TW, JP, KR, MN (East Asia); IN, PK, BD, LK, NP, BT, MV (South Asia); AU, NZ, PG, FJ and the Pacific island states (Oceania) |
| EU | the 27 member states |
| EMEA | every country GeoNames puts in Europe or Africa, plus the Middle East (AE, BH, IL, IQ, IR, JO, KW, LB, OM, PS, QA, SA, SY, TR, YE) |
| AMERICAS | every country GeoNames puts in North or South America |
| LATAM | Mexico, Central and South America, and the Spanish/Portuguese-speaking Caribbean (CU, DO, PR) |

A job's region label that isn't known counts as "not stated" (spec 07).

**Preferences additions** (spec 07 amends spec 06; still version 1, both optional): `regions: {LABEL: [codes]}` (codes validated) and `matching: {weights: {title, market, skills, seniority, experience}}` (non-negative, known names only).

**Digest integration:**
- `compose` receives ranked postings.
- The cap of 30 applies after ranking.
- Each block gets a reasons line.
- Filtered-out postings are marked as sent but not shown, counted on the header ("… · 2 filtered out").
- `digest list` gains `score`, `reasons` and `filtered`.

## Dependencies

None new (`gzip`, `csv`, `zipfile`, `urllib` for the generator). The generator needs network access once, when it is run; the committed data needs none.

## Tasks

Each task is test-first, ends with `make check` passing, a decision note, a commit and a push.

1. **Places.** The generator, the committed `cities.tsv.gz` and `regions.yaml`, and lookups with suffix stripping ("Hanoi Capital Region") (M2, M10).
2. **Preferences additions.** `regions` and `matching.weights` in the model and schema, checked by `profile check` (M7, validation part).
3. **Inference.** Seniority words in titles, "N+ years" in descriptions, CV skills by name or alias as whole words. Pure functions.
4. **Score, filters, ranking.** The five components, default and overridden weights, the four filters, the order (M1, M3–M8).
5. **Digest.** Reasons line, ranking, cap after ranking, filtered postings marked as sent, `digest list` fields; digest golden tests updated (M9).
6. **Manual check with you:**
   - the real stored postings ranked with reasons, before any digest is sent, to tune the default weights;
   - **then the reminder to fill in your profile** (skill levels, filters, `looking_for`), as you asked, and a second ranking with it.

## Risks

- **GeoNames name clashes** (a small city sharing a big city's name elsewhere): the most populous wins, and a country stated in the job always wins.
- **Inferring seniority from title words misfires** ("Senior" in "Senior-friendly team"): only whole title words count, and unknown is neutral (0.6), not 0.
- **The default weights are guesses.** They are tuned together in task 6, and you can override them in `preferences.yaml`.
