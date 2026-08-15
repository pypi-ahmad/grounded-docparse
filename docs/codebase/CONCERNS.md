# Codebase Concerns

## Core Sections (Required)

### 1) Top Risks (Prioritized)

1. **Large orchestration hotspots — medium.** `pipeline.py` and `streamlit_app.py` each exceed 3,000 lines. Both are high-churn and combine many control paths, increasing regression and review cost.
2. **No automated repository gate — medium.** There is no checked-in CI workflow or coverage baseline. The local verification suite is strong, but enforcement depends on contributors running it.
3. **Native adapter fidelity — medium.** Docling output is reconciled against a project-built source manifest. This correctly fails closed, but upstream conversion changes can cause valid documents to fail until adapters/tests are updated.
4. **Split result versions — medium.** Streamlit workspace `RESULT_VERSION` is `4.6.1`, OCR full JSON is `4.6.0`, and native JSON is `5.0.0`/`5.1.0`. Compatibility ownership is manual.
5. **Provider preflight inconsistency — medium.** `DocumentAgent.analyze()` and CLI `--schema` validation still check `OPENAI_API_KEY` directly instead of the selected model's `api_key_name`. Region recovery and Markdown refinement are provider-neutral, but Gemini/Agnes classification or TOC can be reported unavailable unless the OpenAI compatibility key is also present.

### 2) Technical Debt

- Product/output versions are split: Streamlit workspace `RESULT_VERSION` is `4.6.1`, OCR full JSON is `4.6.0`, and native JSON is `5.0.0`/`5.1.0`. Compatibility ownership is manual.
- The native extra declares `pywin32`, but no current implementation imports it; its intended feature or removal is undocumented.
- `streamlit_app.py` owns routing UI, persistence coordination, parsing orchestration, analysis, extraction, and downloads in one module.
- Generated graph/wiki/site artifacts are tracked alongside source and inflate repository scans. Analysis metrics must exclude them to avoid misleading size/complexity conclusions.
- There is no central logger; CLI/scripts print and result models carry traces. Operational failures outside saved results have no durable unified log.

### 3) Security Concerns

- The app explicitly targets one trusted local workstation and has no authentication, authorization, tenant isolation, or safe public-network deployment mode.
- Documents, archives, filenames, schemas, and provider output are untrusted. Existing controls include upload/page/pixel limits, signatures, required container parts, ZIP entry/expanded-size limits, `defusedxml`, sanitized HTML, and disabled Docling remote/plugins/enrichments.
- Optional provider features can send recognized content, crops, schema, questions, or full bounded document context to OpenAI or a custom base URL.
- Durable workspaces retain uploaded bytes and generated content beyond process exit until **Clear saved workspace** or database deletion. Operators must treat that as residual sensitive data.
- Native parsers expand complex third-party formats in-process. Dependency patching and adversarial-format regression tests remain important even with current prevalidation.

### 4) Performance and Scaling Concerns

- The Streamlit app and CLI process batch documents sequentially; OCR page work has bounded concurrency, but a long document delays later files.
- Native ingestion holds uploaded bytes, conversion models, manifests, base text, elements, and rendered outputs in memory. Configured uploads can reach 250 MiB and valid archives can expand to 1 GiB.
- GLM-OCR is process-wide and serialized because model loading/GPU ownership is expensive; switching to Paddle coordinates process/service GPU use.
- OpenAI work is bounded by provider concurrency/retry controls, but large document extraction/refinement still carries latency and token-cost risk.
- SQLite is suitable for the trusted single-workstation target, not concurrent multi-user workloads.

### 5) Fragile/High-Churn Areas

Ninety-day commit-path counts identify the main review hotspots:

| Path | Changes |
|---|---:|
| `src/grounded_docparse/pipeline.py` | 24 |
| `src/grounded_docparse/render.py` | 24 |
| `src/grounded_docparse/models.py` | 18 |
| `tests/test_simple_pipeline.py` | 18 |
| `streamlit_app.py` | 17 |
| `README.md` | 16 |
| `CHANGELOG.md` | 15 |
| `docs/architecture.md` | 15 |
| `tests/test_agentic_contract.py` | 15 |
| `src/grounded_docparse/gateways.py` | 14 |

Counts come from `git log --since="90 days ago" --name-only`; they indicate change frequency, not defect density.

### 6) `[ASK USER]` Questions

1. `[ASK USER]` What active Windows-native feature requires `pywin32`? No source module currently imports it.

### 7) Evidence

- `README.md`
- `docs/spec.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `pyproject.toml`
- `streamlit_app.py`
- `src/grounded_docparse/pipeline.py`
- `src/grounded_docparse/render.py`
- `src/grounded_docparse/models.py`
- `src/grounded_docparse/universal.py`
- `src/grounded_docparse/docling_native.py`
- `src/grounded_docparse/native_extraction.py`
- `src/grounded_docparse/workspace_store.py`
