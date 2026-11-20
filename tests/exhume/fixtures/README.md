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
- `f5_csv_head.csv`: the three F5 body lines shown in Appendix A (head only, not the full
  15479-byte body; the full F5 fixture is deferred to task 12).
- `f9_offline.html`: a minimal page built only from the F9 description (title
  "Internet Archive: Temporarily Offline"). F9 was never observed, so the rest is synthetic.
- `f10_yahoo_404_head.html`: the F10 body head as shown in Appendix A.
- `f12_header_only.csv`: the 44-byte F11/F12 header-only body; its digest is the F11 CDX digest.
- `f14_dish_20041129.csv`: byte copy of the live task 5.5 evidence file
  `evidence/yahoo-finance-ichart/ichart.yahoo.com/20041129204236-2ADTBRSLGIS5YZLXF4LRCFLO363WOUXW.csv`
  (F14, F16), 125 bytes.
