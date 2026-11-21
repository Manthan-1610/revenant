# Requirements Document

## Introduction

Autopsy is the second of Revenant's five stages. `revenant autopsy <slug>` reads the Wayback
evidence that Exhume stored (`evidence/<slug>/index.json` and the capture files below
`evidence/<slug>/<host>/`, models in `revenant/exhume/models.py`) and infers the dead API's
contract deterministically, with no LLM. Autopsy writes `crypt/<slug>/contract.json` and renders
`.kiro/specs/revenant-<slug>/requirements.md` from that contract with a fixed template. Reanimate
hands the rendered file to Kiro CLI headless. The inference rules target the Yahoo CSV family
(`yahoo-finance-ichart`); other slugs are deferred. F1 to F21 refer to Appendix A of
`.kiro/specs/exhume/requirements.md`. Unit tests never touch the network.

## Glossary

- **Autopsy_CLI**: the `revenant autopsy` command of the `revenant` console script.
- **Evidence_Reader**: loads the Index and the capture bodies of one Slug.
- **Query_Normalizer**: turns a capture's `original` URL into decoded name-value pairs.
- **Contract_Inferrer**: derives every contract fact from the loaded evidence.
- **Body_Parser**: splits one CSV body into header, Data_Rows and Comment_Lines.
- **Month_Detector**: decides the month indexing of parameters `a` and `d`.
- **Contract**: the Pydantic model written to `crypt/<slug>/contract.json`.
- **Contract_Writer**: serializes the Contract to `contract.json`.
- **Spec_Renderer**: renders `.kiro/specs/revenant-<slug>/requirements.md` from `contract.json`.
- **Data_Capture**: an Index entry with `kind="data"`. **Error_Capture**: one with `kind="error"`.
- **Capture_Year**: the first 4 digits of `served_timestamp`, or of `requested_timestamp` when
  `served_timestamp` is null. **Capture_Date**: the same timestamp's first 8 digits as a date.
- **Capture_Shape**: `s_only`, `empty_range`, `full_range` or `other`, computed by Exhume's
  `parameter_shape` on the Query_Normalizer's pairs.
- **Interval**: Exhume's `interval` of those pairs: the `g` value, or `none` when absent or empty.
- **Documented_Parameter**: one of `s`, `a`, `b`, `c`, `d`, `e`, `f`, `g`, `ignore` (`product.md`).
- **Template_Junk**: a parameter value containing `{{`, `}}` or `{%` (F17), or a non-empty value
  of `a` to `f` that is not all ASCII digits (such as the leaked `f=f6j1`).
- **Header_Line**: the first line of a body. **Header_Variant**: one distinct Header_Line string.
- **Comment_Line**: a line matching `^<!--.*-->\s*$` (F16). In a Header_Only_Body every
  Comment_Line counts as after the last Data_Row.
- **Data_Row**: a non-empty line after the Header_Line that is not a Comment_Line.
- **Row_Date**: the first field of a Data_Row, parsed with `%Y-%m-%d` or `%d-%b-%y`; a two-digit
  year resolves to the latest year not after the Capture_Year.
- **Header_Only_Body**: a body with a Header_Line and no Data_Row (F12).
- **Body_Precision**: the maximum count of fractional digits over all numeric fields of a body's
  Data_Rows, excluding the Date and Volume columns.
- **Response_Variant**: the pair (Interval, Header_Variant).
- **Fit**: under month offset H (0 for 0-indexed, 1 for 1-indexed), a capture fits when the
  requested start `date(c, a + 1 - H, b)` and end `date(f, d + 1 - H, e)` are valid dates and
  start <= oldest Row_Date <= newest Row_Date <= end.
- **Decisive_Capture**: a capture that fits exactly one of H=0 and H=1. **Ambiguous_Capture**:
  a capture that fits both. **Unfit_Capture**: a capture that fits neither.
- **Evidence_Count**: the number of Data_Captures or Error_Captures that support one fact, stored
  with up to 3 supporting Index keys in sorted order.

## Requirements

### Requirement 1: Command and evidence loading

**User Story:** As the Revenant developer, I want one command that reads Exhume's evidence, so that contract inference starts from verified bytes.

#### Acceptance Criteria

1. THE Autopsy_CLI SHALL accept `revenant autopsy <slug> [--evidence-dir PATH] [--crypt-dir PATH] [--specs-dir PATH]`, defaulting to `./evidence`, `./crypt` and `./.kiro/specs`.
2. WHEN the Autopsy_CLI runs, THE Evidence_Reader SHALL load `<evidence-dir>/<slug>/index.json` with Exhume's `Index` model and read each entry's body from `<evidence-dir>/<slug>/<path>` as raw bytes, in sorted Index key order.
3. IF `index.json` is missing, is not valid JSON, fails `Index` validation or has a `slug` other than `<slug>`, or a body file is missing or its SHA-256 differs from the entry's `sha256`, THEN THE Autopsy_CLI SHALL print an error naming the file to stderr, write or modify no output file and exit with a non-zero code.
4. THE Contract_Inferrer SHALL use only Data_Captures for contract facts and only Error_Captures for the Contract's `errors` field, SHALL ignore entries with `kind="error_page"`, and SHALL send no network request.
5. WHEN the Autopsy_CLI has written `contract.json`, THE Autopsy_CLI SHALL print the Contract's month indexing, the Decisive_Capture count for H=0 and for H=1, and the path of each file written in this run.

### Requirement 2: Endpoint and parameters

**User Story:** As the Reanimate stage, I want every parameter the old clients sent, so that the revenant accepts the same requests.

#### Acceptance Criteria

1. THE Query_Normalizer SHALL apply `html.unescape` to the query string of `original` repeatedly until the string stops changing, then parse the result as Exhume's `parse_query` does, so that `&amp;amp;d=0` yields `d=0`; this deliberately goes beyond Exhume's single unescape (F15).
2. THE Contract_Inferrer SHALL record each endpoint path, taken as the URL path of `original`, with the Index entry `host` values that served it and an Evidence_Count of Data_Captures per (host, path) pair.
3. THE Contract_Inferrer SHALL record, for each parameter name except `amp`, using each Data_Capture's first value for that name: the count of Data_Captures carrying the name, the count with an empty value, the count with a Template_Junk value, `required` as true only when every Data_Capture carries a non-empty value, and up to 5 distinct non-empty, non-junk example values ordered by descending frequency then ascending value.
4. THE Contract_Inferrer SHALL type a parameter as `int` with its minimum and maximum when at least one non-empty, non-junk value exists and every such value consists only of ASCII digits, else as `enum` with per-value counts when at most 10 distinct non-empty, non-junk values exist, else as `string` with its distinct-value count.
5. THE Contract_Inferrer SHALL mark every parameter outside the Documented_Parameters as optional and "observed, unexplained", with its presence count, and SHALL record the count of Data_Captures that carry an `amp` name.

### Requirement 3: Month indexing

**User Story:** As the demo presenter, I want Autopsy to prove from the evidence that months are 0-indexed, so that the revenant reproduces the quirk old clients rely on.

#### Acceptance Criteria

1. THE Month_Detector SHALL evaluate H=0 and H=1 for every `full_range` Data_Capture that has at least one Data_Row and whose Row_Dates all parse, treating a capture with a non-integer `a` to `f` value as an Unfit_Capture.
2. IF at least 3 Decisive_Captures fit H and no Decisive_Capture fits the other offset, THEN THE Month_Detector SHALL record month indexing as `0-indexed` for H=0 or `1-indexed` for H=1.
3. IF neither offset has at least 3 fitting Decisive_Captures with none fitting the other offset, THEN THE Month_Detector SHALL record month indexing as `undetermined`.
4. THE Month_Detector SHALL store four counts in the Contract: Decisive_Captures for H=0, Decisive_Captures for H=1, Ambiguous_Captures and Unfit_Captures, with Ambiguous_Captures and Unfit_Captures given no vote.
5. IF month indexing is `undetermined`, THEN THE Autopsy_CLI SHALL write `contract.json`, write no rendered requirements file and exit with a non-zero code.

### Requirement 4: Response variants

**User Story:** As the Reanimate stage, I want each response shape tied to the request that produced it, so that the revenant serves the right CSV for each `g`.

#### Acceptance Criteria

1. THE Contract_Inferrer SHALL record the content types of Data_Captures, taking the lowercased part before any `;` of `content_type` (else `mimetype`), with an Evidence_Count per type.
2. THE Body_Parser SHALL decode the bytes as UTF-8 with no newline conversion, split them into lines at `\n`, take the Header_Line, and classify the remaining lines into Data_Rows and Comment_Lines.
3. IF a Data_Capture body is not valid UTF-8, THEN THE Autopsy_CLI SHALL print an error naming the file, write no output file and exit with a non-zero code.
4. THE Contract_Inferrer SHALL map each Interval to its Response_Variants, each with its column names (the Header_Variant split at `,`), first and last Capture_Year and Evidence_Count, so that `g=v` maps to `Date,Dividends`.
5. THE Contract_Inferrer SHALL record each Header_Variant with its first and last Capture_Year and Evidence_Count, so that `Adj. Close*` and `Adj Close` appear as separate variants (F12).
6. THE Contract_Inferrer SHALL record the Header_Only_Body count, and SHALL include Header_Only_Bodies in Response_Variant and Header_Variant counts while excluding them from the checks of Requirements 3, 5 and 6.

### Requirement 5: Row format

**User Story:** As the Reanimate stage, I want the row-level quirks measured, so that the revenant's bytes match what old parsers expect.

#### Acceptance Criteria

1. THE Contract_Inferrer SHALL record each Row_Date format with its first and last Capture_Year and Evidence_Count.
2. THE Contract_Inferrer SHALL classify each body with at least 2 Data_Rows as `descending` when every Row_Date is strictly earlier than the one before it, `ascending` when every Row_Date is strictly later, else `unordered`, and SHALL record the count per class.
3. IF a Data_Row's Row_Date parses with neither format, THEN THE Contract_Inferrer SHALL count the body as `unparsed_dates` and exclude the body from row-order, month and default checks.
4. THE Contract_Inferrer SHALL record, per Response_Variant and Capture_Year, the distribution of Body_Precision values over bodies with at least 1 Data_Row, with a count per value.
5. THE Contract_Inferrer SHALL record the total Comment_Line count over all Data_Captures, the Capture_Years of bodies carrying Comment_Lines, the first Comment_Line in sorted Index key order as the example, and the counts of Comment_Lines found after and before the last Data_Row (F16).

### Requirement 6: Defaults and error behaviour

**User Story:** As the Reanimate stage, I want to know what the dead API returned for under-specified requests and failures, so that the revenant answers them the same way.

#### Acceptance Criteria

1. THE Contract_Inferrer SHALL record, separately for `s_only` and `empty_range` Data_Captures with at least one Data_Row and no `unparsed_dates` (5.3), the Evidence_Count, the earliest oldest Row_Date and the latest newest Row_Date, recording a count of 0 and null dates for a shape with no such capture.
2. THE Contract_Inferrer SHALL record, for each shape of 6.1, the count of captures whose Capture_Date minus newest Row_Date is from 0 to 7 days inclusive.
3. THE Contract_Inferrer SHALL record, for each shape of 6.1, the default row spacing from the median absolute gap in days between consecutive Row_Dates, pooled over that shape's captures: `d` for at most 4, `w` for 5 to 10, `m` for 25 to 35 (inclusive), else `unknown`, including when no gap exists.
4. IF at least one Error_Capture exists, THEN THE Contract_Inferrer SHALL record, per status code in the Contract's `errors` field, the Evidence_Count, each media type of `content_type` (else `mimetype`) with its count, and the Capture_Shape counts.
5. IF no Error_Capture exists, THEN THE Contract_Inferrer SHALL set `errors` to null.

### Requirement 7: Contract file and determinism

**User Story:** As the Reanimate stage, I want a stable, traceable contract, so that regenerating from the same evidence never produces a diff.

#### Acceptance Criteria

1. THE Contract_Writer SHALL validate the Contract with Pydantic v2 and write `<crypt-dir>/<slug>/contract.json` with an atomic write.
2. IF Contract validation fails, THEN THE Autopsy_CLI SHALL print an error naming the failing field, leave any existing `contract.json` unchanged and exit with a non-zero code.
3. THE Contract_Writer SHALL attach an Evidence_Count to every inferred fact in the Contract.
4. THE Contract_Writer SHALL serialize with sorted keys, 2-space indentation, UTF-8, `\n` line endings and one trailing newline, ordering every list by a fixed sort key that does not depend on Index insertion order or file listing order.
5. THE Contract_Writer SHALL record the Slug, Index entry count and the SHA-256 of the input `index.json` bytes, and SHALL omit wall-clock times and absolute paths.
6. WHEN Autopsy runs twice on byte-identical `index.json` and body files, from any working directory and at any time, THE Contract_Writer SHALL produce byte-identical `contract.json` files.

### Requirement 8: Generated revenant requirements

**User Story:** As the Reanimate stage, I want EARS requirements rendered from the contract, so that Kiro CLI headless builds the revenant from the contract alone.

#### Acceptance Criteria

1. THE Spec_Renderer SHALL read only `contract.json` and write `<specs-dir>/revenant-<slug>/requirements.md` with an atomic write, giving byte-identical output for the same contract.
2. THE Spec_Renderer SHALL emit EARS requirements for the routes (every host alias and path), every parameter with type and requirement status (for every `int` parameter, a requirement that the revenant accepts every value from the observed minimum to the observed maximum, such as `d` up to 12 (F21), and never rejects a value Yahoo accepted), the month indexing, the row-order class with the highest count from 5.2, the default range of each shape from 6.1 and an `X-Revenant-Donor` response header.
3. THE Spec_Renderer SHALL select, per Interval, the served Response_Variant with the latest last Capture_Year, breaking ties by higher Evidence_Count, then by the lowest Header_Variant in code-point order.
4. THE Spec_Renderer SHALL take the served precision as the most frequent Body_Precision of the served Response_Variant in the latest Capture_Year of its precision distribution, breaking ties toward more digits.
5. THE Spec_Renderer SHALL list every Response_Variant not selected by 8.3, every Row_Date format and the Comment_Line example in an informational section, and SHALL state that the revenant ignores "observed, unexplained" parameters.
6. WHERE the Contract's `errors` field is not null, THE Spec_Renderer SHALL emit a requirement that returns the error status with the highest Evidence_Count (ties to the lower code), with that status's most frequent content type (ties to code-point order), when the donor has no rows for the request.

## Correctness Properties

Each property is a Hypothesis test that names its id, using a temporary evidence directory.

- **P1 Month recovery** (Req 3.1 to 3.3): synthetic `full_range` bodies generated with a known
  offset H, at least 3 of them Decisive_Captures, yield H; adding one Decisive_Capture for the
  other offset yields `undetermined`.
- **P2 Byte-identical contract** (Req 7.4, 7.6): the same evidence with Index entries in any
  insertion order yields byte-identical `contract.json`.
- **P3 Unescape fixpoint** (Req 2.1): a query of `[A-Za-z0-9^%.=&]` characters, HTML-escaped 0 to
  3 times, normalizes to the same pairs as the unescaped query.
- **P4 Parsed row order** (Req 5.2): descending dates rendered in either Row_Date format are always
  classified `descending`, including across month and year boundaries where string order fails.

## Deferred

- Inference for slugs outside the Yahoo CSV family, and a per-slug Documented_Parameter list.
- XML, JSON and Yahoo YQL (stretch API) bodies.
- Line-ending, trailing-newline and byte-order-mark quirks of bodies.
- Inferring the meaning of `x`, `y`, `z`, `q` and `j`.
- Using `digest_verified=false` entries differently from verified ones.
- Error trigger inference beyond "no donor rows", and use of `error_page` entries.
- Writing `.config.kiro`, `design.md` or `tasks.md` for the rendered revenant spec.
- Victim `urls_called` as request evidence; LLM-assisted inference.
- Other properties: renderer round-trip, Body_Precision, Header_Variant year ranges.
