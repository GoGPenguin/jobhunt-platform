# 0016: Posting fingerprints

Date: 2026-10-20
Spec: [04-dedupe-store](../spec/04-dedupe-store.md), "Postings"; plan [04](../plans/04-dedupe-store.md) task 1

## Implementation

- `fold(text)`: NFKD, combining marks removed, case-folded, punctuation and `_` turned into spaces, whitespace collapsed. `đ/Đ`, `ø`, `ł` are mapped first, because Unicode decomposition leaves them as they are ("Đà Nẵng" would otherwise fold to "đa nang").
- `normalize_company(name)`:
  - drops LinkedIn's `| Part of …` suffix;
  - removes Vietnamese legal-form phrases wherever they appear as whole words (`cong ty co phan`, `cong ty tnhh`, `cong ty`, `co phan`, `tnhh`, `mot thanh vien`, `mtv`), longest first, so "Cổ phần" goes but the "phần" in "Phần mềm" (software) stays;
  - removes international legal words from the end (`ltd`, `limited`, `company`, `jsc`, `inc`, `llc`, `corp`, `corporation`, `pte`, `gmbh`, `plc`, `co`);
  - never reduces a name to nothing (a company called "Company" stays "company").
- `normalize_title(title)` is `fold(title)`. Word order and seniority words are kept, so "DevOps Engineer (Senior)" and "Senior DevOps Engineer" differ. Accepted; fuzzy matching comes with the matcher.
- `fingerprint(company, title)` is SHA-256 of `company|title`, both normalized. `|` can't occur inside a normalized part, so the parts can't run together.

## Verified

- Tests written first (25 new; 345 in total); `make check` passes.
- "Lumen Robotics Pte. Ltd." / "Senior DevOps Engineer" and "Lumen Robotics" / "senior devops engineer" share a fingerprint (spec D4); different titles, companies and word splits don't.
- Real company-name shapes from the LinkedIn alerts are covered (fictional names in tests): "… Company Limited.", "… | Part of …", "Công ty TNHH …", "… JSC".
- No new dependencies, no secrets, cost $0.
