# 🏗️ Architecture Diagram Builder

A Streamlit app that generates and reviews cloud architecture diagrams with
LLMs, exporting to draw.io format.

## Features

- AI-powered infrastructure diagram generation (draw.io XML output)
- Architecture review: security, cost, performance, scalability, compliance
- Multi-cloud service vocabulary (AWS, Azure, GCP)
- A dedicated Review page for uploading an image / PDF / `.drawio` file
- Conversation history and a saved review history per user
- Fully offline operation with free local models, managed from the UI
- User authentication and an admin dashboard

## Pages

Everyone signed in gets:

| Page | What it does |
| --- | --- |
| **Design** | Chat. Describe an architecture, get a draw.io diagram back. |
| **Review** | Upload an existing diagram and get a scored review with per-issue fixes and a downloadable Markdown report. |
| **My diagrams** | Every diagram you generated: search, preview the XML, download, delete. |

Administrators additionally get:

| Page | What it does |
| --- | --- |
| **Admin** | System health and the resolved provider chains; user accounts (create, promote, delete); **Local models** (offline mode, downloads); maintenance (cleanup, backup, runtime settings). |

Accounts are created by an admin - there is no self-service sign-up. The first
run creates one admin from `ADMIN_USERNAME` / `ADMIN_PASSWORD`, after which
credentials live in `user_data/config/credentials.json` (bcrypt hashed) and
`.env` changes to those two values no longer apply.

## Running fully offline

Offline mode restricts both chains to providers that run on this machine, so
no request leaves the network even when API keys are present.

1. Install [Ollama](https://ollama.com/download) - free, runs locally.
2. Sign in as an admin and open **Admin → Local models**.
3. Download a model from the catalogue (`llama3.2:3b` is the lightest useful
   starting point; add `llava:7b` if you want to review screenshots).
   Progress is shown as it downloads.
4. Turn on **Offline mode**.

The toggle and the chosen models are stored in
`user_data/config/runtime.json` and survive a restart; `OFFLINE_MODE` in
`.env` only sets the startup default. "Reset to .env defaults" on the
Maintenance tab clears them.

Local models are smaller than the hosted ones - expect simpler blueprints and
slower responses, especially without a GPU.

## How model selection works

Providers are tried in a **cheap-first** order. The first one that answers
serves the request; paid Claude is the last resort.

```
LLM     : Groq  ->  Ollama (local)  ->  Gemini  ->  Claude
Vision  : Gemini  ->  LLaVA (local)  ->  Tesseract OCR  ->  Claude
```

Three things make this reliable:

- **Startup probes are free.** Availability is decided by key presence, a
  local Ollama `/api/tags` lookup, and a Tesseract binary check. No test
  completions are sent, so starting the app costs nothing.
- **Transient errors retry in place.** A 429 or 503 (common on free tiers)
  retries the same provider up to 3 times with backoff before falling
  through. Permanent errors (bad key, unknown model) fall through immediately.
- **Success is remembered.** The provider that last answered moves to the
  front of the chain for the rest of the process.

Every model name is set in `.env` - see below. The chains in
`config/settings.py` read those values, so `.env` is the single place to
change models.

## Setup

### 1. Install

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

pip install -r requirements.txt
```

No provider SDKs are needed - LiteLLM talks to Groq, Gemini, Anthropic and
Ollama over plain HTTP.

### 2. Configure `.env`

```bash
# ---- API keys (set at least one) ----
GROQ_API_KEY=gsk_...            # https://console.groq.com
GOOGLE_API_KEY=AIza...          # https://aistudio.google.com/apikey
ANTHROPIC_API_KEY=sk-ant-...    # https://console.anthropic.com

# ---- Models (override any of these) ----
GROQ_LLM_MODEL=llama-3.3-70b-versatile
GOOGLE_LLM_MODEL=gemini-3.7-flash
GOOGLE_VISION_MODEL=gemini-3.7-flash
ANTHROPIC_LLM_MODEL=claude-opus-5
ANTHROPIC_VISION_MODEL=claude-opus-5
OLLAMA_LLM_MODEL=mistral
OLLAMA_VISION_MODEL=llava
OLLAMA_BASE_URL=http://localhost:11434

# ---- Generation tuning ----
LLM_TEMPERATURE=0.4
LLM_MAX_TOKENS=16000

# ---- Corporate networks (see TLS note below) ----
# CA_BUNDLE=C:\Users\<you>\.certs\corp-ca-bundle.pem

# ---- Auth ----
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-me
```

### 3. Optional: local models via Ollama

Install Ollama, then either download models from **Admin → Local models** in
the app, or from a terminal:

```bash
ollama pull llama3.2:3b
ollama pull llava
ollama serve
```

### 4. Optional: Tesseract OCR

Needed only as the last-ditch vision fallback. Install the binary, then set
`TESSERACT_PATH` if it isn't on your `PATH`.

### 5. Run

```bash
streamlit run app.py
```

Opens at http://localhost:8501. Default login is `admin` / `admin123` -
**change it via `ADMIN_PASSWORD` before first run.**

## Corporate networks and TLS

On a network that does TLS inspection, every HTTPS call from Python fails with
`CERTIFICATE_VERIFY_FAILED` even though browsers work. Python does not read
the OS certificate store, so it never sees your corporate root CA.

Build a bundle that combines certifi with your OS CA store, then point
`CA_BUNDLE` at it. On Windows:

```powershell
$out = "$env:USERPROFILE\.certs"
New-Item -ItemType Directory -Force -Path $out | Out-Null
$bundle = Join-Path $out "corp-ca-bundle.pem"
$certifi = python -c "import certifi; print(certifi.where())"

$sb = New-Object System.Text.StringBuilder
[void]$sb.AppendLine((Get-Content -Raw $certifi))
foreach ($store in @("Cert:\LocalMachine\Root","Cert:\LocalMachine\CA",
                     "Cert:\CurrentUser\Root","Cert:\CurrentUser\CA")) {
  foreach ($c in (Get-ChildItem $store -ErrorAction SilentlyContinue)) {
    [void]$sb.AppendLine("-----BEGIN CERTIFICATE-----")
    [void]$sb.AppendLine([Convert]::ToBase64String($c.RawData,'InsertLineBreaks'))
    [void]$sb.AppendLine("-----END CERTIFICATE-----")
  }
}
[IO.File]::WriteAllText($bundle, $sb.ToString())
```

Then add `CA_BUNDLE=C:\Users\<you>\.certs\corp-ca-bundle.pem` to `.env`.
Certificate verification stays enabled - never disable it to work around this.

## Project structure

```
app.py                          Routing, session and the sidebar
ui/
  styles.py                     App-wide CSS and small render helpers
  login.py                      Sign-in screen
  chat.py                       Design page
  review.py                     Upload-and-review page
  diagrams.py                   Diagram library
  admin.py                      Admin dashboard incl. local model manager
config/
  settings.py                   All configuration + fallback chains + prompts
  models.py                     Pydantic data models
  model_fallback.py             Provider availability probing, offline mode
  runtime_config.py             Admin-editable settings (JSON backed)
auth/
  auth_manager.py               Login, registration, bcrypt hashing
  admin_manager.py              Admin operations, stats, backup
agents/
  orchestration_agent.py        Classifies the request
  generation_agent.py           Description -> architecture blueprint
  review_agent.py               Architecture -> issue list
  workflow.py                   Runs the pipeline
services/
  llm_service.py                Text generation + provider fallback
  vision_service.py             Image reading + provider fallback
  ollama_service.py             Local model status, download, delete
  drawio_service.py             Blueprint -> draw.io XML
  file_processor.py             Upload type detection
  json_utils.py                 Tolerant JSON extraction from LLM output
storage/
  conversation_store.py         Chat history (JSON per conversation)
  diagram_store.py              Diagram XML + metadata
  review_store.py               Saved reviews (JSON per review)
  user_activity_log.py          Append-only JSONL audit log
```

Data is stored on the local filesystem under `user_data/`, partitioned by
user id. No database required.

## Troubleshooting

**"No AI provider is configured"**
No API key is set and Ollama isn't reachable. Set a key in `.env`, or download
a local model from Admin → Local models. The app still starts so an admin can
fix it from the UI.

**"Offline mode is on but no local model is available"**
Ollama isn't running, or nothing is downloaded yet. Admin → Local models shows
which of the two it is.

**`CERTIFICATE_VERIFY_FAILED`**
See the TLS section above - set `CA_BUNDLE`.

**"model does not exist or you do not have access to it"**
The model name is wrong for that key, or the key lacks access. Check the
provider console and update the matching `*_MODEL` variable in `.env`.

**503 "high demand" from Gemini**
Free-tier capacity. The app retries automatically; if a model is persistently
unavailable, switch `GOOGLE_LLM_MODEL` to another (e.g. `gemini-3.6-flash`).

**Which provider is actually serving requests?**
Admin Dashboard → System Health → Model Availability. It shows the resolved
chain, the active provider, and why each unavailable one was skipped.

## Known limitations

- Session timeout is configured but not enforced; sessions last as long as the
  browser tab.
- There is no self-service registration UI - the admin creates users.
- No login rate limiting.
- A model download blocks the admin's browser tab until it finishes; other
  users are unaffected.
- `datetime.utcnow()` is used throughout storage; it emits a DeprecationWarning
  on Python 3.12+. Changing it needs a migration for already-stored naive
  timestamps.
- Phase 2 diagram types (C4, DFD, Sequence) are defined in `DIAGRAM_TYPES` but
  only Infrastructure is implemented.
