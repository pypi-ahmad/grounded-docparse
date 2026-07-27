# Security best practices report: grounded-docparse

## Executive summary
No Python+Streamlit-specific reference exists in this skill's `references/` (only Django/Flask/FastAPI backend docs, which don't apply — Streamlit isn't a routed web-server framework). This report applies general Python secure-coding practices instead. Most substantive findings for this codebase were already produced this session in `grounded-docparse-threat-model.md` (abuse paths, trust boundaries) and a hardening pass (dependency audit). This report does not re-litigate those; it covers what a general-Python-practices pass adds on top, and confirms nothing new and critical was missed.

**No critical or high findings.** One informational gap (no logging), everything else checked came back clean.

## Medium

None found in this pass beyond what's already tracked in `grounded-docparse-threat-model.md` (TM-001 native-parser risk, TM-002 indirect prompt injection) — see that report for detail; not duplicated here.

## Low / Informational

### F-1: No logging module used anywhere in `src/`
- **Where:** entire `src/grounded_docparse/` package — no `import logging` anywhere.
- **Why it matters:** not a vulnerability by itself, but it means there's no audit trail of parse failures, provider errors, or the exception paths already surfaced to the user in `streamlit_app.py:81,191,215` (`st.error(f"{type(exc).__name__}: ...")`). If something goes wrong, there's nothing durable to look at afterward beyond the Streamlit session.
- **Recommendation:** add a `logging.getLogger(__name__)` at the module boundaries that already catch exceptions (`streamlit_app.py`), log the exception at `warning`/`error` level before showing the user-facing message. Low urgency — this is an observability gap, not an exploitable issue, and the app has no persistence layer to write logs to today (per `docs/spec.md` non-goals: no application caching, no persistence).

### F-2: Sequential, predictable block/region IDs
- **Where:** `src/grounded_docparse/pipeline.py:143` — `block_id = f"p{page_number}-b{index + 1}"`.
- **Why it matters:** the general best-practice guidance is to avoid incrementing public resource IDs since they let an attacker enumerate or guess other resources. Checked whether it applies here: it doesn't. These IDs only ever appear inside one document's own already-fully-returned JSON/Markdown output for a single local session — there's no multi-tenant server exposing them as addressable resources another party could enumerate into. **No action needed**, noted only to record that this was checked rather than skipped.

## Checked and clean
- No `assert`-based validation in production code paths (would silently vanish under Python's `-O` flag) — all validation in `ingest.py`, `extraction.py`, `config.py` uses explicit `if: raise`.
- No weak/predictable randomness used for anything security-relevant (no `random`/`uuid` use in `src/` at all).
- No TLS verification bypass (`verify=False`, unverified SSL contexts) anywhere in the codebase.
- No secrets, API keys, or credentials hardcoded in source (confirmed again this pass; matches the two `/security-review` passes run earlier this session).
- Dependency vulnerabilities: already found and fixed this session — `requests` 2.31.0 → 2.34.2 (3 CVEs), `pip-audit` now clean.

## See also
- `grounded-docparse-threat-model.md` — full trust-boundary/abuse-path analysis (TM-001..TM-005), written earlier this session, is the authoritative source for this repo's real risk surface.
- `ownership-map-out/summary.json` — git-ownership bus-factor analysis (single-author repo, expected bus-factor=1 everywhere).
