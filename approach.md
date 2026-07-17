# Approach Document

This note explains how I built the CT-200 manual backend and why I made certain choices. It matches the code in this repo.

---

## 1. Overall architecture

The app is a FastAPI service with three main layers:

1. **Routers** (`app/api/`) — HTTP only
2. **Services** (`app/services/`) — ingest, browse, version compare, selections, generation, staleness, retrieval
3. **Storage** — SQLite for the document tree / selections / generation metadata; MongoDB for the full LLM payload

PDF parsing sits in `app/parsers/` and returns an in-memory tree. Persistence and APIs consume that tree.

I kept the LLM behind a small provider interface (`LLMProvider`). Production uses Gemini. Tests and `scripts/e2e_demo.py` inject a scripted provider so the versioning/staleness flow can run without calling Google.

---

## 2. Why SQLite

The assignment asks for SQLAlchemy + SQLite for the tree, versions, and selections. That fit the project well:

- Zero server setup for structure data
- Easy to wipe and re-ingest during development (`ct200.db`)
- Enough for a single-machine demo and pytest

I used SQLAlchemy 2.x mapped models and `create_all` on startup. There is no Alembic. For this assignment that was intentional — fewer moving parts. For production I would add migrations.

---

## 3. Why MongoDB

Generated QA output is nested JSON (test cases, reconstructed text, source snapshot). The assignment allows MongoDB or a justified JSON store.

I used MongoDB because:

- The payload shape can grow without ALTER TABLE
- SQLite still holds a thin `qa_generations` row (`mongo_id`, hash snapshot, counts) for joins and staleness
- Retrieval can load metadata from SQLite and the body from Mongo

Tests use an in-memory store that implements the same `insert` / `get` interface, so CI does not need a live Mongo process.

---

## 4. Why Gemini

Any LLM provider was allowed. I picked Gemini (free tier) via `google-generativeai`. The default model in config is `gemini-flash-latest`.

I did not try to build a custom model. The interesting part for the assignment is structured validation and failure handling, not the vendor.

---

## 5. How the parser works

Pipeline:

1. `pypdf` extracts text page by page
2. Drop empty lines and page markers like `-- 3 of 6 --`
3. Detect numbered headings
4. Build a parent/child tree with a stack
5. Hash each node

Heading detection had to handle two formats in these PDFs:

- Top-level: `1. Device Overview` (dot after the number)
- Nested: `1.1 Intended Use` (no trailing dot after the full path)

A first regex attempt treated top-level headings incorrectly and folded section 1 into the title. I fixed that with separate patterns. Numbered list lines inside a body (e.g. `1. Normal: ...`) are excluded using a colon heuristic so they do not become section nodes.

Hierarchy quirks in the manuals:

- `2.1.1.1` has no `2.1.1` parent → attach under deepest existing prefix (`2.1`)
- `3.4` appears before `3.3` in the PDF → keep document order, do not sort by number
- Two headings both named “Error Codes” (`4.2` and `7.1`) → two distinct nodes

Tables and lists stay inside the section `body` as text. I did not rebuild a formal table grid from PDF layout.

Content hash:

```text
sha256(section_path + "\n" + heading + "\n" + normalized_body)
```

Normalization uses NFKC (PDF ligatures) and collapses trivial whitespace. Children are not included in the hash.

---

## 6. How document versioning works

`ingest_pdf` / `POST /documents/ingest`:

1. Parse the PDF
2. Find or create a `Document` by title
3. Always insert a **new** `DocumentVersion`
4. Persist a full node tree for that version

V1 rows are never updated or deleted when V2 arrives. That is what makes version-pinned selections safe.

---

## 7. How node matching works

Across versions, logical identity is **`section_path`** (`1.1`, `4.2`, `5.3`, …). The root title node is keyed as `__root__` in compare logic.

Then:

| Situation | Status |
|-----------|--------|
| Same path, same content hash | unchanged |
| Same path, different hash | modified |
| Path only in newer version | added |
| Path only in older version | removed |

Storage still creates separate node rows per version (different IDs). “Same logical node” means matching during compare/staleness, not sharing one database row. Sharing one row would break version-pinned selections.

Where this breaks:

- If a section is renumbered (`4.2` → `4.3`), it looks like remove + add
- If a path is reused for unrelated content, it looks like a normal modify
- Fuzzy title matching is not used (on purpose — too easy to merge the two “Error Codes” sections)

---

## 8. How staleness detection works

When a generation is created, I snapshot each selected node’s `section_path` + `content_hash` into `qa_generations.source_snapshot_json` (and again inside the Mongo document).

On retrieval:

1. Load the snapshot
2. Pick a target version (default: latest for that document)
3. For each snapshot path, find the node with the same path in the target version
4. Compare hashes

Per-node statuses: `up_to_date`, `stale_modified`, `stale_removed`.  
Overall generation status is `stale` if **any** source node is stale.

I am honest about the limits in the API response: hash equality cannot tell a wording tweak from a safety-threshold change, and renumbers look like removals. There is no semantic check of whether the generated test case text still makes sense.

---

## 9. Generation pipeline

1. Load the version-pinned selection
2. Reconstruct text from selected nodes in order
3. Send a prompt that asks for JSON only, 3–5 concrete QA cases, based only on the excerpts
4. Parse JSON (tolerate optional markdown fences)
5. Validate with Pydantic (`QAGenerationOutput`)
6. On failure, retry up to `LLM_MAX_RETRIES` (default 2 → 3 attempts total)
7. If still invalid → HTTP 502; nothing written
8. If valid → write Mongo payload, then SQLite metadata with the snapshot

Duplicate `POST` on the same selection always creates a **new** run. I chose that so history is not silently overwritten. Returning the previous run would also be defensible; I preferred an audit trail for this assignment.

Missing `GEMINI_API_KEY` fails early with HTTP 503.

---

## 10. Database schema overview

**SQLite**

- `documents` — logical manual
- `document_versions` — each ingest
- `nodes` — tree for one version (`parent_id`, `position`, `section_path`, `content_hash`)
- `selections` — name + pinned `version_id`
- `selection_nodes` — ordered membership
- `qa_generations` — `mongo_id`, `source_snapshot_json`, counts

**MongoDB** collection `qa_generations`

- `test_cases`, `reconstructed_text`, `source_nodes`, `attempts_used`, ids/timestamps

Unique constraint: `(version_id, section_path)` on nodes so a version cannot contain two nodes with the same path.

---

## 11. Error handling strategy

| Case | Behavior |
|------|----------|
| Missing document / node / selection / generation | 404 |
| Selection nodes from wrong version, bad ingest path | 400 |
| Empty / missing Gemini key | 503 |
| LLM output still invalid after retries | 502 with attempt count + last error |
| PDF not found on ingest | 404 |

Invalid LLM JSON is never persisted. That was a hard requirement for me — better a loud failure than a bad test case sitting in Mongo.

---

## 12. API design decisions

- Ingest is an HTTP endpoint (`POST /documents/ingest`) plus a CLI script. The assignment does not require HTTP ingest, but it makes the Swagger/demo flow usable.
- Browse defaults to the latest version when `version_id` is omitted.
- Generation has no request body; the selection already carries the source nodes.
- Retrieval always recomputes staleness instead of storing a stale flag that could go out of date.
- List-by-node finds generations by scanning snapshots for that `node_id`. Fine for this dataset; I would index it properly if the table grew.

---

## 13. Trade-offs

| Choice | Trade-off |
|--------|-----------|
| Path + hash matching | Simple and explainable; weak on renames |
| Linearized tables in body | No lost text; no real grid structure |
| Sync SQLAlchemy | Simpler than async for this scope |
| No Alembic | Fast to start; painful if schema evolves in production |
| Always-new generation runs | More storage; clearer history |
| Hash-only staleness | Honest but coarse |

I also spent more time getting the parser hierarchy right than polishing edge-case HTTP errors. That matched how the assignment weights irregularities and process.

---

## 14. Limitations

- PDF layout extraction is still flat text for tables
- Staleness is binary at the generation level if any selected section changed
- Search does not query `section_path` directly
- No authentication
- Node→generation lookup is not optimized
- Relies on the CT-200 numbered-heading style; a totally different PDF layout would need parser work

---

## 15. Possible future improvements

- Structured table parsing
- Optional embedding similarity for “soft” staleness
- A `generation_nodes` join table for indexed retrieval by node
- Alembic migrations
- Rate limiting / auth if exposed publicly
- A small admin CLI to list versions and diffs without opening Swagger

---

## Decision log (assignment questions)

### 1. What’s the one part of this system most likely to silently give wrong results without erroring? How would you catch it?

The parser. A clean-looking tree can still mis-parent a section or swallow a heading, and the API will happily return it. I caught issues with unit tests aimed at the known irregularities, manual hierarchy dumps, and comparing heading paths to the PDF. In production I would also add a checksum of section paths after ingest and fail the ingest if expected paths are missing.

### 2. Where did you choose simplicity over correctness because of time, and what would break first if this went to production as-is?

Hash-only staleness and linearized tables. In production, teams would either get noisy “stale” flags on harmless wording edits, or miss that a test case’s expected result no longer matches a rewritten requirement even when hashes somehow aligned after a bad match. Listing generations by node by scanning all snapshots would also degrade first under load.

### 3. Name one input you did not handle, and what the system does when it sees it.

A PDF with no numbered headings (or a path outside the project tree on ingest). The parser raises if there is no extractable text; ingest rejects paths outside the project or non-`.pdf` files with 400/404. I also did not handle section renumbering as a rename — the matcher reports remove + add.

---

## Extra assignment questions

### How would you improve parser accuracy if document formatting becomes more complex?

I would stop relying only on regex over plain text. Next step would be layout-aware extraction (bounding boxes / fonts from a library like pdfplumber) so heading level can come from style, not just numbering. I would still keep document-order traversal. For tables I would detect grid structure and store a markdown or JSON table in the body. OCR would only be added when text extraction returns empty pages. Golden-file tests per document family would matter more than a fully generic parser.

### How would you reduce hallucinations in generated test cases?

The current prompt already says to use only the excerpts. I would tighten that further: require every `expected_result` to quote or paraphrase a concrete sentence from the selection, reject cases whose `source_section_paths` are not in the selection, and optionally run a second cheap check that steps mention values present in the text (thresholds, error codes). Lower temperature and smaller excerpts help more than a bigger model here.

### What would you change if this system had to support millions of documents?

SQLite would go first — move structure data to Postgres. Add Alembic, connection pooling, and async workers for ingest/generation. Index generation↔node relationships instead of scanning snapshots. Store large payloads in object storage or sharded Mongo with retention policies. Partition by document/tenant. Caching browse responses and running staleness checks lazily or on ingest events would matter. The matching strategy could stay path+hash per document family, but I would not assume one global numbering scheme across all manuals.
