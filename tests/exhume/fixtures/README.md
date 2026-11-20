# Exhume test fixtures

Bodies copied from `.kiro/specs/exhume/requirements.md` Appendix A. No rows are invented.

- `cdx_f1.json`: F1 data page 1, verbatim (header, 3 rows, `[]`, resume key).
- `cdx_f2.json`: F2 data page 2, using only the one row the Appendix shows (it elides the rest
  with `...`), then `[]` and the resume key.
- `cdx_f3.json`: F3 tail rows under the 3-field header of the F3 query
  (`fl=timestamp,statuscode,digest`). The Appendix omits the header and the earlier rows; the
  header here matches the query's `fl`. `CdxRow` needs all six fields, so `parse_page` raises
  `CdxParseError` on this page.
- `cdx_last_page.json`: derived from F1 + F3. F1's three rows under the six-field header, with
  no `[]` + key tail, which is the "last page has no resume key" shape observed in F3.
