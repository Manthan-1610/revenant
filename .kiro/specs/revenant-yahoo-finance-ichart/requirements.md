# Requirements Document

## Introduction

This document specifies the revenant for the dead API `yahoo-finance-ichart`. It is rendered by Autopsy from `crypt/yahoo-finance-ichart/contract.json`, which was inferred from 160 archived captures (Index SHA-256 `e4c3c7e8daeed5310134783101e22161c4cf60eba6156631d19a8a323a721654`). Every requirement cites its Evidence_Count; regenerate this file from the contract instead of editing it.

## Glossary

- **Revenant**: the FastAPI server that answers requests the dead API used to answer.
- **Donor**: the living data source that supplies the rows the Revenant serves.
- **Interval**: the value of `g`, or `none` when `g` is absent or empty.
- **Header_Line**: the first line of a CSV response body.
- **Data_Row**: a non-empty line after the Header_Line that is not a Comment_Line.
- **Row_Date**: the first field of a Data_Row.
- **Comment_Line**: a line of the form `<!-- ... -->` inside a body.
- **Evidence_Count**: the number of archived captures that support a fact.
- **Yahoo_Number**: a value formatted with 6 decimals, trailing zeros stripped, keeping at least 2 decimals, so `60.860001`, `61.18`, `52.00`.

## Requirements

### Requirement 1: Routes

**User Story:** As an unmodified old client, I want every dead hostname and path to answer again, so that my hard-coded URL works.

#### Acceptance Criteria

1. WHEN a client sends `GET http://ichart.finance.yahoo.com/table.csv`, THE Revenant SHALL answer it as the dead API did (Evidence_Count 50: `ichart.finance.yahoo.com/20041021172219-RJ7IHOMXNHN7KMJEXPSXKWP2TSK6C7B7`, `ichart.finance.yahoo.com/20050414212136-RPTFTIQVVQNRUUE7NY3MRG3IH3HIL6L2`, `ichart.finance.yahoo.com/20050427190628-XEPUQFNCYI3THTUYPDNJKMKHNHRMQV7Q`).
2. WHEN a client sends `GET http://ichart.yahoo.com/table.csv`, THE Revenant SHALL answer it as the dead API did (Evidence_Count 50: `ichart.yahoo.com/20041129204236-2ADTBRSLGIS5YZLXF4LRCFLO363WOUXW`, `ichart.yahoo.com/20050125022251-WLBIV5HP7PWA4NBQRQAWY2H33PFVJUE6`, `ichart.yahoo.com/20050125175736-GXVK4UWCFXCG6QV7NK6DFOK6H7STUQ2U`).
3. WHEN a client sends `GET http://real-chart.finance.yahoo.com/table.csv`, THE Revenant SHALL answer it as the dead API did (Evidence_Count 50: `real-chart.finance.yahoo.com/20140706194927-Q6BBDEGZRLFIGCRUIWVW2EESOH2FY63U`, `real-chart.finance.yahoo.com/20140819110511-5OXWX644JAAKOVYJQFQO4EN5KFYIMX7Z`, `real-chart.finance.yahoo.com/20140819112705-2MF4LC4QTQDMRDDBKTRGJE6ZVYXFQ7GW`).

### Requirement 2: Parameters

**User Story:** As an unmodified old client, I want every parameter I send accepted, so that no request the dead API served is rejected.

#### Acceptance Criteria

1. WHEN a request carries `a`, THE Revenant SHALL parse it as an optional int, SHALL accept at least every value from 0 to 11 (observed), and SHALL NOT reject an integer only because it lies outside the observed range (Evidence_Count 114, 1 with an empty value).
2. WHEN a request carries `b`, THE Revenant SHALL parse it as an optional int, SHALL accept at least every value from 1 to 31 (observed), and SHALL NOT reject an integer only because it lies outside the observed range (Evidence_Count 113, 1 with an empty value).
3. WHEN a request carries `c`, THE Revenant SHALL parse it as an optional int, SHALL accept at least every value from 1888 to 2015 (observed), and SHALL NOT reject an integer only because it lies outside the observed range (Evidence_Count 110, 1 with an empty value).
4. WHEN a request carries `d`, THE Revenant SHALL parse it as an optional int, SHALL accept at least every value from 0 to 12 (observed), and SHALL NOT reject an integer only because it lies outside the observed range (Evidence_Count 108, 1 with an empty value).
5. WHEN a request carries `e`, THE Revenant SHALL parse it as an optional int, SHALL accept at least every value from 1 to 31 (observed), and SHALL NOT reject an integer only because it lies outside the observed range (Evidence_Count 108, 1 with an empty value).
6. WHEN a request carries `f`, THE Revenant SHALL parse it as an optional int, SHALL accept at least every value from 1983 to 2030 (observed), and SHALL NOT reject an integer only because it lies outside the observed range (Evidence_Count 96, 1 with an empty value, 1 with Template_Junk).
7. WHEN a request carries parameter `g`, THE Revenant SHALL read it as an optional `enum` and accept every observed value: `d` (62), `m` (19), `v` (18), `w` (16) (Evidence_Count 116, 1 with an empty value).
8. WHEN a request carries parameter `ignore`, THE Revenant SHALL read it as an optional `enum` and accept every observed value: `.csv` (106), `.csv"` (1) (Evidence_Count 107).
9. WHEN a request carries the observed, unexplained parameter `j`, THE Revenant SHALL accept it as optional and ignore its value (Evidence_Count 1).
10. WHEN a request carries the observed, unexplained parameter `q`, THE Revenant SHALL accept it as optional and ignore its value (Evidence_Count 7).
11. WHEN a request carries parameter `s`, THE Revenant SHALL read it as a required `string` (117 distinct values observed; Evidence_Count 150).
12. WHEN a request carries the observed, unexplained parameter `x`, THE Revenant SHALL accept it as optional and ignore its value (Evidence_Count 7).
13. WHEN a request carries the observed, unexplained parameter `y`, THE Revenant SHALL accept it as optional and ignore its value (Evidence_Count 7).
14. WHEN a request carries the observed, unexplained parameter `z`, THE Revenant SHALL accept it as optional and ignore its value (Evidence_Count 7).

### Requirement 3: Month indexing

**User Story:** As an unmodified old client, I want months read the way the dead API read them, so that my date ranges select the same rows.

#### Acceptance Criteria

1. WHEN a request carries `a` or `d`, THE Revenant SHALL read the month as the value + 1, so that `a=0` means January (0-indexed; Decisive_Captures for 0-indexed 58, for 1-indexed 0; Ambiguous 9; Unfit 25; e.g. `ichart.finance.yahoo.com/20050414212136-RPTFTIQVVQNRUUE7NY3MRG3IH3HIL6L2`, `ichart.finance.yahoo.com/20100228082204-PEYSYIBB5AMDY55CHWEG7S4XN44STVTN`, `ichart.finance.yahoo.com/20100712060201-PDW3FT7DLMMCHPXUIMMM5E6FD3PTCJPJ`).
2. IF `a` or `d` is 12, THEN THE Revenant SHALL treat it as January of the following year (inferred from 1 capture, `ichart.finance.yahoo.com/20121217014635-DP2RNCXQZKYOFXDUCUXCL34SYCHTKAKU`, which cannot tell rolling over from capping at December, since both give the same rows there).

### Requirement 4: Response format

**User Story:** As an old CSV parser, I want the same header, number format and row order, so that my parsing code keeps working.

#### Acceptance Criteria

1. WHEN the Revenant returns rows, THE Revenant SHALL send `Content-Type: text/csv` (Evidence_Count 150).
2. WHEN a request carries `g=d`, THE Revenant SHALL send the Header_Line `Date,Open,High,Low,Close,Volume,Adj Close`, SHALL write every value outside `Date` and `Volume` as a Yahoo_Number (2016: 108310 of 108310 values; all years: 529180 of 529180) and SHALL write a zero Volume as `000` (10244 of 10244 zero Volumes) (served 2007 to 2016, Evidence_Count 40).
3. WHEN a request carries `g=m`, THE Revenant SHALL send the Header_Line `Date,Open,High,Low,Close,Volume,Adj Close`, SHALL write every value outside `Date` and `Volume` as a Yahoo_Number (2017: 1865 of 1865 values; all years: 21285 of 21285) and SHALL write a zero Volume as `000` (232 of 232 zero Volumes) (served 2011 to 2017, Evidence_Count 17).
4. WHEN a request has no `g` or an empty `g`, THE Revenant SHALL send the Header_Line `Date,Open,High,Low,Close,Volume,Adj Close`, SHALL write every value outside `Date` and `Volume` as a Yahoo_Number (2017: 320 of 320 values; all years: 135470 of 135470) and SHALL write a zero Volume as `000` (168 of 168 zero Volumes) (served 2012 to 2017, Evidence_Count 10).
5. WHEN a request carries `g=v`, THE Revenant SHALL send the Header_Line `Date,Dividends`, SHALL write every value outside `Date` and `Volume` with exactly 6 decimals (2016: 315 of 315 values; all years: 1272 of 1272) (served 2010 to 2016, Evidence_Count 16).
6. WHEN a request carries `g=w`, THE Revenant SHALL send the Header_Line `Date,Open,High,Low,Close,Volume,Adj Close`, SHALL write every value outside `Date` and `Volume` as a Yahoo_Number (2016: 2370 of 2370 values; all years: 22350 of 22350) and SHALL write a zero Volume as `000` (68 of 68 zero Volumes) (served 2012 to 2016, Evidence_Count 14).
7. WHEN the Revenant returns Data_Rows, THE Revenant SHALL order them newest first (each Row_Date strictly earlier than the one before it) (`descending` in 147 bodies).

### Requirement 5: Default ranges

**User Story:** As an old client that sends no date range, I want the same default range, so that my under-specified requests still return data.

#### Acceptance Criteria

1. WHEN a request carries `a` to `g` all with empty values (`empty_range`), THE Revenant SHALL return daily rows over the Donor's full history up to its latest day (observed 2008-07-25 to 2015-07-21; 1 of 1 captures ended within 7 days of the capture date; `ichart.finance.yahoo.com/20150722040224-HIF7M5KERUP7NVB4WXUEUFRG6TFV2MWN`).
2. WHEN a request carries `s` (and optionally `ignore`) and no `a` to `g` parameter (`s_only`), THE Revenant SHALL return daily rows over the Donor's full history up to its latest day (observed 1986-07-09 to 2016-10-12; 25 of 28 captures ended within 7 days of the capture date; `ichart.finance.yahoo.com/20050427190628-XEPUQFNCYI3THTUYPDNJKMKHNHRMQV7Q`, `ichart.finance.yahoo.com/20050516112007-AEC45PVM5B6RM46NBTWEPVYUI6LGS33G`, `ichart.finance.yahoo.com/20050516231156-MYH7EWU4M7DGG6DSGFH6DF3QHW5RY2WS`).

### Requirement 6: Donor header

**User Story:** As a user of the Revenant, I want each response to name its data source, so that I know where the rows come from.

#### Acceptance Criteria

1. WHEN the Revenant sends any response, THE Revenant SHALL include an `X-Revenant-Donor` header that names the Donor supplying the rows.

### Requirement 7: Error behaviour

**User Story:** As an old client, I want the same failure status when no data exists, so that my error handling still runs.

#### Acceptance Criteria

1. IF the Donor has no rows for a request, THEN THE Revenant SHALL respond with status 404 with `Content-Type: text/html` and a body modelled on the newest archived 404 page, `real-chart.finance.yahoo.com/20160719090815-E2OZ2DIDZWYGPF3QRTIT4AZCN6A46NBU` (Evidence_Count 10, newest first: `real-chart.finance.yahoo.com/20160719090815-E2OZ2DIDZWYGPF3QRTIT4AZCN6A46NBU`, `real-chart.finance.yahoo.com/20150207083509-C5N5SH6NPK6HKL6MCUGAXITAY24GDUCL`, `real-chart.finance.yahoo.com/20140729192006-MYLVM4L2JQF6HKOPYVCM2F4YCF6ZEVL5`).

## Informational Notes

These observations are not requirements. They record what the evidence shows.

### Unselected Response Variants

- `g=d`: `Date,Open,High,Low,Close,Volume,Adj. Close*` (2005 to 2007, Evidence_Count 22)
- `g=m`: `Date,Open,High,Low,Close,Volume,Adj. Close*` (2005 to 2006, Evidence_Count 2)
- `g=none`: `Date,Open,High,Low,Close,Volume,Adj. Close*` (2004 to 2005, Evidence_Count 25)
- `g=v`: `Date,Open,High,Low,Close,Volume,Adj. Close*` (2005 to 2006, Evidence_Count 2)
- `g=w`: `Date,Open,High,Low,Close,Volume,Adj. Close*` (2005 to 2005, Evidence_Count 2)

### Row_Date Formats

- `%Y-%m-%d`: 2007 to 2017 (Evidence_Count 97)
- `%d-%b-%y`: 2005 to 2007 (Evidence_Count 51)

### Header-Only 200 Responses

- Header-only 200 responses (2004, Evidence_Count 2): a Header_Line with no Data_Row is a valid response (`ichart.finance.yahoo.com/20041021172219-RJ7IHOMXNHN7KMJEXPSXKWP2TSK6C7B7`, `ichart.yahoo.com/20041129204236-2ADTBRSLGIS5YZLXF4LRCFLO363WOUXW`)

### Comment_Line

- Example: `<!-- ichart8.finance.scd.yahoo.com uncompressed Thu Oct 21 10:22:17 PDT 2004 -->` (2 in bodies from 2004; 2 after and 0 before the last Data_Row)

### Observed, Unexplained Parameters

- The Revenant ignores "observed, unexplained" parameters: `j`, `q`, `x`, `y`, `z`.
