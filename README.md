# CardioTrack CT-200 Manual Backend

Backend API for the Tri9T AI Engineering Internship assignment.

The system ingests the CardioTrack CT-200 Home Blood Pressure Monitor manual (PDF), stores it as a hierarchical document tree, supports multiple versions of the same manual, and can generate QA test cases from user-selected sections. When the manual is updated, previously generated test cases can be checked for staleness using content hashes.

This is a FastAPI backend only. There is no frontend.

---

## Problem statement

Medical device manuals change over time. If QA test cases were written against an older version of a requirement, they can quietly become wrong when that section is edited. The assignment asks for a backend that:

1. Turns the manual into a structured, browsable tree
2. Keeps old and new versions side by side
3. Lets a user pick sections and generate QA ideas with an LLM
4. Flags whether those generations still match the current document

The sample manuals are in `data/ct200_manual.pdf` (V1) and `data/ct200_manual_v2.pdf` (V2).

---

## Features implemented

- PDF parsing into a hierarchical node tree (headings, body text, lists, tables kept in body)
- Content hashes per node for change detection
- Document versioning (re-ingest V2 without deleting V1)
- Logical node matching across versions by section path + hash
- Browse, search, and per-node cross-version diff APIs
- Named, version-pinned selections
- Gemini-based QA generation (3–5 validated test cases)
- MongoDB storage for generation payloads; SQLite for structure/metadata
- Staleness detection on retrieval
- HTTP ingest API, CLI ingest helper, and an in-process e2e demo script

---

## Tech stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.10+ |
| API | FastAPI |
| Validation | Pydantic / pydantic-settings |
| Relational DB | SQLAlchemy + SQLite |
| Document store | MongoDB (pymongo) |
| PDF parsing | pypdf |
| LLM | Google Gemini (`google-generativeai`) |
| Tests | pytest + httpx TestClient |

---

## Architecture overview

```
PDF → parser → in-memory tree → SQLite (documents / versions / nodes / selections)
                                      ↓
Selection → reconstruct text → Gemini → Pydantic validate → Mongo (QA payload)
                                      ↓
Retrieval → join SQLite metadata + Mongo payload → hash-based staleness check
```

Routers stay thin. Business logic lives under `app/services/`. The LLM is behind a small provider interface so tests can swap in a scripted fake.

---

## Folder structure

```
app/
  api/          # FastAPI routers (ingest, browse, selections, generation, retrieval)
  core/         # settings + SQLAlchemy engine/session
  db/           # Mongo generation store
  llm/          # Gemini provider + output schemas
  models/       # SQLAlchemy entities
  parsers/      # PDF → tree
  schemas/      # Pydantic request/response models
  services/     # ingestion, browse, versioning, selections, generation, staleness, retrieval
data/           # CT-200 V1 and V2 PDFs
scripts/        # ingest_cli.py, e2e_demo.py
tests/          # unit and API tests
```

---

## Installation

```powershell
cd tri9t-ai-assignment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and set `GEMINI_API_KEY` if you want live QA generation.

You also need a local MongoDB (or Atlas URI) for generation and full retrieval. Browse/selection work with SQLite alone.

---

## Environment variables

| Variable | Required for | Default |
|----------|--------------|---------|
| `APP_NAME` | optional | `ct200-manual-api` |
| `APP_ENV` | optional | `development` |
| `DATABASE_URL` | always | `sqlite:///./ct200.db` |
| `MONGO_URI` | generation + retrieval | `mongodb://localhost:27017` |
| `MONGO_DB_NAME` | generation + retrieval | `ct200_generations` |
| `GEMINI_API_KEY` | generation | empty (must set for live Gemini) |
| `GEMINI_MODEL` | generation | `gemini-flash-latest` |
| `LLM_MAX_RETRIES` | generation | `2` |

---

## Running the application

```powershell
uvicorn app.main:app --reload
```

- API docs: http://127.0.0.1:8000/docs
- Health: `GET /health` → `{"status":"ok"}`

On startup, `init_db()` creates SQLite tables if they do not exist. There is no Alembic migration step.

---

## Database setup

**SQLite** (`ct200.db` in the process working directory by default):

- `documents`, `document_versions`, `nodes`
- `selections`, `selection_nodes`
- `qa_generations` (metadata + hash snapshot + Mongo id)

**MongoDB** database `ct200_generations`, collection `qa_generations`:

- Full generation payload (test cases, reconstructed text, source node snapshot)

If you change the schema during development and hit weird errors, delete `ct200.db` and re-ingest.

---

## API endpoints

### Ingest

| Method | Path | Notes |
|--------|------|-------|
| `POST` | `/documents/ingest` | Body: `pdf_path`, `version_label`, optional `document_title` |

`pdf_path` must point to a `.pdf` inside the project directory (e.g. `data/ct200_manual.pdf`).

### Browse

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/documents/{document_id}/sections` | Optional `version_id` (default: latest) |
| `GET` | `/nodes/{node_id}` | Optional `include_children` (default true) |
| `GET` | `/versions/{version_id}/nodes/search?q=` | Search heading + body |
| `GET` | `/nodes/{node_id}/changes` | Optional `other_version_id` |

### Selections

| Method | Path | Notes |
|--------|------|-------|
| `POST` | `/selections` | `name`, `version_id`, `node_ids` |
| `GET` | `/selections/{selection_id}` | |
| `GET` | `/selections` | Optional `version_id` filter |

All `node_ids` must belong to the pinned `version_id`.

### Generation

| Method | Path | Notes |
|--------|------|-------|
| `POST` | `/selections/{selection_id}/generations` | Needs Gemini + Mongo |

Submitting the same selection again creates a **new** generation run.

### Retrieval / staleness

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/generations/{generation_id}` | Full cases + staleness |
| `GET` | `/selections/{selection_id}/generations` | Summaries + status |
| `GET` | `/nodes/{node_id}/generations` | Generations that included that node |

Optional query: `target_version_id` (default: latest version of the same document).

---

## Example workflow (V1 → selection → generation → V2 → retrieval)

### Option A — HTTP (with server running)

1. Ingest V1:

```http
POST /documents/ingest
{"pdf_path": "data/ct200_manual.pdf", "version_label": "v1"}
```

Note `document_id` and `version_id`.

2. Find node ids (search or open `/docs` and browse sections).

3. Create a selection pinned to V1:

```http
POST /selections
{"name": "Battery QA", "version_id": 1, "node_ids": [<id of 2.1.1.1>]}
```

4. Generate QA:

```http
POST /selections/{selection_id}/generations
```

5. Ingest V2:

```http
POST /documents/ingest
{"pdf_path": "data/ct200_manual_v2.pdf", "version_label": "v2"}
```

6. Retrieve with staleness:

```http
GET /generations/{generation_id}?target_version_id=2
```

Sections that changed in V2 (for example `2.1.1.1`) should show `staleness_status: "stale"`. Unchanged sections like `1.1` should stay `"up_to_date"` if that was the only selected node.

### Option B — CLI ingest

```powershell
python scripts/ingest_cli.py data/ct200_manual.pdf --version-label v1
python scripts/ingest_cli.py data/ct200_manual_v2.pdf --version-label v2
```

### Option C — automated e2e demo (no live Gemini/Mongo)

```powershell
python scripts/e2e_demo.py
```

This runs the full versioning + staleness path in-process with a scripted LLM and in-memory store.

---

## Testing

```powershell
pytest -v
```

Useful subsets:

```powershell
pytest tests/test_pdf_parser.py -v
pytest tests/test_versioning.py tests/test_staleness.py -v
pytest tests/test_ingest_api.py tests/test_retrieval_api.py -v
python scripts/e2e_demo.py
```

Parser tests cover the irregular cases in the manuals (missing intermediate heading `2.1.1.1`, `3.4` before `3.3`, duplicate “Error Codes” headings).

---

## Design decisions (short)

- **Section path** (`4.2`, `5.3`, …) is the logical identity across versions. Hashes decide unchanged vs modified.
- Each version stores its **own** node rows. Unchanged sections are still separate rows; they are matched logically when comparing.
- Selections pin concrete `node_id`s on a version so re-ingest never retargets old selections.
- LLM output is validated with Pydantic. Bad JSON is retried, then rejected (502). Invalid output is not stored.
- Duplicate generation requests create a new run on purpose (audit trail).

More detail is in `approach.md`.

---

## Assumptions

- The manuals follow a numbered heading pattern similar to the provided PDFs.
- Document identity for re-ingest is the parsed PDF title (same title → same `documents` row).
- “Current document” for staleness means the latest ingested version unless `target_version_id` is passed.
- Tables from PDF text extraction are stored as linear text in the node body, not as structured table objects.

---

## Known limitations

- Hash-based staleness treats a tiny wording change the same as a critical threshold change.
- Renumbering a section looks like remove + add, not rename.
- Search matches heading/body only, not `section_path` itself.
- Listing generations by node scans generation snapshots in SQLite (fine for this assignment size, not ideal at large scale).
- No auth, no multi-tenant isolation, no Alembic migrations.

---

## Future improvements

- Better PDF table extraction (keep cell structure)
- Semantic / embedding-based staleness as a secondary signal
- Index or join table from generations → source nodes for faster lookup
- Optional auto-regeneration of stale cases (explicitly out of scope for the assignment)
- Auth if this were deployed beyond a local demo

---

## License / notes

Built for the Tri9T AI Engineering Internship assignment. The CT-200 manuals are fictional sample documents provided with the assignment.
