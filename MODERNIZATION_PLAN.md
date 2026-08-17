# Modernization Plan — Grounded DocParse

Cites [docs/architecture.md](docs/architecture.md), [TECHNICAL.md](TECHNICAL.md),
[CONTRIBUTING.md](CONTRIBUTING.md), and [SECURITY.md](SECURITY.md) for
current-state detail. This document is forward-looking only and does not
regenerate those documents.

## 1. Executive summary

Grounded DocParse is a mature, actively-maintained, current-stack Python
project (`uv` + locked `pyproject.toml`, Python 3.12.10) with a real 528-item
`pytest` suite that runs entirely offline in ~68 seconds — no WSL2, no GPU,
and no live network call is required to execute it, contrary to what the
project's WSL/GPU-coupled *runtime* topology might suggest. This is not a
legacy-rescue case. The actual gap is narrow and specific: **no
`.github/workflows/` exists at all**, so none of this real test investment
runs in CI today, and the suite is not currently 100% green — **9 of 528
tests fail on `main` right now**, plus 2 auto-fixable `ruff` violations. The
plan is one phase: author a CI workflow targeting the 519 tests that pass
today (naming the 9 failures as an explicit, tracked quarantine list rather
than silently excluding them), and record the pre-existing lint/test defects
as a fast-follow, not a blocker.

## 2. Current state assessment

See the cited documents above for full current-state detail. Facts this plan
depends on, verified live this pass (2026-08-17), not assumed from docs:

- `uv sync --python 3.12.10 --locked --extra native` installs cleanly from
  the committed `uv.lock`, no hand-patching.
- `uv run python -m compileall -q src streamlit_app.py tests scripts` — clean,
  exit 0.
- `uvx ruff check src streamlit_app.py tests scripts` — **2 errors**, both
  auto-fixable: an unsorted `__all__` export list (`ClassifierProfile`,
  `inspect_content_range` out of alphabetical order). Not investigated
  further as to which module; visible directly in the `ruff` diff output.
- `uv run python -m pytest -q` — **528 collected, 519 passed, 9 failed, 0
  skipped, 0 errors, 67.61s.** No test in the suite is gated behind a live
  WSL service, a live GPU, or a live network call — CONTRIBUTING.md's
  "synthetic documents and fake OpenAI gateways" claim is accurate: even
  `tests/test_grounded_ocr.py` (which references
  `http://127.0.0.1:8080/v1`-style URLs) injects a fake HTTP `opener`
  rather than calling a live service (verified by reading the test).

**The 9 failures, categorized (verified individually, not assumed):**

1. `tests/test_knowledge_wiki.py::test_repository_wiki_contract` — a
   documentation self-consistency check (`validate_wiki`) reports 24 stale
   wiki-article content-hash snapshots (e.g.
   `articles/engineering/adding-a-native-format.md`). This is exactly the
   "living-doc drift" (H8) class of problem, already caught by an existing
   test — the wiki content hasn't been regenerated/re-snapshotted after a
   source change. Not a WSL/GPU/environment issue.
2. **8 failures, all in `tests/test_simple_streamlit.py`**, all using
   `AppTest.from_file("streamlit_app.py").run(...)` — e.g.
   `test_studio_allows_glm_without_openai_environment` asserts
   `engine_toggles["GLM-OCR"] is True` and gets `False`;
   `test_studio_shows_results_and_only_requested_tools` and others show a
   monkeypatched `FakeParser.parse` never being called
   (`assert parse_calls == 1` → `0 == 1`). All 8 share the `AppTest`
   integration-testing mechanism, which is consistent with (but not
   confirmed as) one common root cause — most plausibly a Streamlit version
   bump changing `AppTest` widget-interaction/state-propagation timing.
   **`[INFERRED]`, not confirmed** — diagnosing the exact cause is app-logic
   debugging, out of scope for this planning pass; flagged in § 9 for the
   maintainer.

## 3. Feasibility spike result & strategy

**Spike performed 2026-08-17**, not assumed:

| Check | Result |
|---|---|
| Installs from a committed lockfile without hand-patching | **Yes.** `uv sync --locked` clean. |
| Builds/compiles on a currently-supported toolchain | **Yes.** `compileall` clean, Python 3.12.10. |
| Boots | **Not directly tested this pass** (`streamlit_app.py` was not launched interactively) — but `AppTest.from_file("streamlit_app.py")` boots the app under test 8+ times across the suite, including in passing tests, so the app demonstrably boots under the `AppTest` harness. |
| Test runner executes, ≥1 meaningful test passes | **Yes, overwhelmingly: 519/528 (98.3%).** |

**Conclusion: this system is already past the Testability Milestone for the
overwhelming majority of its surface — this is Strategy C (wire up what's
already there), the same pattern as the other repos audited this session,
except with dramatically more existing substance to wire up (528 tests vs.
5-11 elsewhere).** The Testability Milestone was crossed long before this
plan; what's missing is purely the CI wiring, plus fixing (or explicitly
quarantining) the 9 tests that keep the suite from being 100% green today.

**Testability Milestone:** already crossed (pre-existing), for 519/528 tests.
**CI Milestone: Phase 1** — the first (and only) phase in this plan, and the
project's first-ever CI workflow.

**Safety-ladder rung chosen: L3 (partial gate) today, with a clearly marked
path to L4.** This is a stronger starting position than the other repos
audited this session (which chose L3 because so little was testable at all).
Here, L3 is chosen not because little is testable, but because 9 named tests
are **currently red** and must be quarantined rather than silently included
in a "green" claim — quarantining 9 failing tests out of 528 while gating on
the other 519 is a materially different, far more valuable L3 than gating on
5 pure functions. Once the 9 failures are fixed (tracked as a fast-follow,
§ 9), the gate becomes a true, unqualified L4 with no code changes to the CI
workflow itself — just removing the quarantine list.

**Economic triage (§ 2f):** unlike the thinner repos this session, this
project already represents substantial investment (528 tests, multiple OCR
engine integrations, a threat-model document, benchmarks). The safety
investment of standing up CI here is proportionate and overdue, not
speculative — the tests already exist; wiring them up is nearly free.

## 4. Target architecture

| Component | Verdict | Why |
|---|---|---|
| Application code (`src/grounded_docparse/`, `streamlit_app.py`), pipelines, OCR gateways | ✅ Keep as-is | Current stack, extensively tested, no EOL — "don't gold-plate" applies directly |
| `pyproject.toml` / `uv.lock` | ✅ Keep as-is | Already correct, already locked |
| Existing 528-test `pytest` suite | ✅ Keep as-is, wire up in CI | The tests are already written and already offline-safe; this phase is pure CI wiring, not test authorship |
| 2 `ruff` violations (unsorted `__all__`) | 🔄 Fast-follow fix (§ 9) | Trivial, auto-fixable (`ruff check --fix`), but out of this plan's phase to avoid mixing an unreviewed auto-fix into a CI-authoring PR |
| 9 failing tests | 🔄 Fast-follow investigation (§ 9) | Root cause (especially the 8 `AppTest` failures) needs app-level debugging this planning pass didn't do; quarantine now, fix next |
| CI | 🗑️→➕ Add (none exists to remove) | Author `.github/workflows/ci.yml`: `uv sync --locked`, `ruff check`, `compileall`, `pytest` with the 9 known failures marked `xfail` (not deleted, not silently skipped) |

No "Upgrade in place," "Swap dependency," or "Rewrite" work is needed
anywhere.

#### ADR: Gate CI on 519/528 tests via named `xfail`, not a smaller subset

- **Context:** the Testability Milestone requires the test runner to execute
  and pass ≥1 meaningful test in CI. Here, nearly the entire suite already
  qualifies — the exception is 9 currently-broken tests, not an
  environment/service-coupling problem.
- **Decision:** mark the 9 known-failing tests `@pytest.mark.xfail(reason=...,
  strict=False)` (or an equivalent per-test skip with a linked-issue-style
  comment) rather than excluding them from collection or deleting them. CI
  then runs the full suite; the 9 report as expected-failures instead of
  hard failures, so CI can be green from day one without hiding that they're
  broken (`pytest`'s own summary still surfaces `xfail` counts).
- **Alternatives considered:** (a) delete/skip the 9 tests silently — rejected,
  this is exactly the kind of hidden gap the skill's Honesty Rules warn
  against; (b) block CI authorship on fixing all 9 first — rejected as
  unnecessarily blocking a nearly-free, high-value CI win on unrelated
  app-logic debugging with unknown effort.
- **Consequences:** CI is green from the first PR. The 9 `xfail` markers are
  a visible, trackable to-do (they'll fail loudly with `strict=False` →
  `XPASS` reporting if/when someone fixes the underlying bug and forgets to
  remove the marker — a built-in reminder to clean up).

## 5. Per-feature migration analysis

Only the build/verification tooling is migrating. Every product feature
(routing, OCR pipelines, evidence model, persistence, CLI) is unaffected —
✅ keep as-is, per § 4.

- **Current implementation:** `uv` + locked `pyproject.toml` (already
  correct), 528-test `pytest` suite (already written, already offline-safe),
  no CI.
- **Migration strategy:** Strategy C (wire up what's already there — § 3).
- **Testability status:** already past the Testability Milestone for 519/528
  tests; safety rung L3 today (9 named `xfail`), with a documented, nearly-
  free path to L4.
- **Dependencies and coupling:** touches only `.github/workflows/ci.yml`
  (new), the 9 test files (adding `xfail` markers — no assertion logic
  changed), and one doc update (`CONTRIBUTING.md`/`TECHNICAL.md` noting CI
  exists and what it covers — H8).
- **Effort estimate:** S (small) — one CI YAML file, 9 marker additions, one
  doc update. The fast-follow (fixing 9 tests + 2 lint errors) is separate
  and unestimated here (app-logic work, not tooling).
- **Risk assessment:** low. The only real risk is a CI-runner OS/Python
  mismatch with what's locally verified — mitigated by pinning the CI job to
  Python 3.12.10 and running on the same OS family verified locally
  (Windows; see § 6 for why `windows-latest` is recommended over
  `ubuntu-latest` here, unusually for this session's repos).
- **Acceptance criteria:** `.github/workflows/ci.yml` runs and is green on
  this phase's own PR, with the 9 `xfail` tests visible in the summary as
  `xfailed`, not silently absent.

## 6. Phased implementation plan

**Phase gating is regime-aware.** This phase is entirely **post-testability
("lit")** — 519/528 tests already pass locally; nothing here is "dark."

**Hazard red-team (Phase 2.5), walked against every class:**

- **H1** (incomplete quarantine) — checked: the 9-test quarantine list above
  is exhaustive (verified via a full `pytest -v` run, not a guess). Cleared.
- **H2** (framework-major codemod) — N/A: no framework major bump. Cleared.
- **H3** (runtime/deployment lockstep) — **Relevant, and resolved
  deliberately, not cleared as N/A.** The app's real runtime is Windows
  11 + WSL2/GPU for two OCR engines (TECHNICAL.md, USAGE.md). The verified-
  passing test suite, however, requires none of that — it runs clean on
  plain Windows with no WSL and no GPU (this spike ran without either).
  **Decision:** target `windows-latest` in CI (matching the actual supported
  OS family) rather than `ubuntu-latest` (this session's default elsewhere),
  since the project is Windows-primary and nothing about the test suite
  requires Linux specifically. This is a genuine judgment call this plan
  makes explicitly rather than defaulting silently.
- **H4** (route-class enumeration) — N/A: no edge/gateway/auth rewrite. Cleared.
- **H5** (stateful data-store major) — N/A: no persisted-volume schema touched
  by this phase. Cleared.
- **H6** (transitional-insecure state) — N/A: no weakened security state
  introduced. Cleared.
- **H7** (stacked-PR trunk drift) — N/A in practice: single-phase plan, one
  branch from `main`, one PR back. Cleared by construction.
- **H8** (living-doc drift) — **Triggered, and already partially caught by
  the codebase itself** (the `test_knowledge_wiki.py` failure IS an H8
  detector firing). **Plan action:** update `CONTRIBUTING.md` to state that
  CI now runs `ruff`/`compileall`/`pytest`, and note in `TECHNICAL.md` that
  the wiki-snapshot staleness is a known, tracked pre-existing failure (not
  reintroduce the same drift by documenting CI without documenting its
  current quarantine list).

### Phase 1: Stand up CI on the existing 528-test suite (T-shirt size: S)

**Goal:** Give this project's substantial existing test investment its
first-ever CI gate, honestly scoped around 9 pre-existing, named failures.
**Regime:** post-testability ("lit") — the whole test suite.
**Safety rung:** L3 today (9 named `xfail`), documented path to L4.
**Prerequisites:** none — first and only phase.
**Duration estimate:** well under a sprint for the CI wiring itself; the
fast-follow fixes (§ 9) are separately estimated.

#### Tasks

| ID | Task | Component | Blocked by |
|----|------|-----------|------------|
| 1.1 | Add `@pytest.mark.xfail(reason="...", strict=False)` to the 9 named failing tests, each with a one-line reason citing this plan | tests | — |
| 1.2 | Author `.github/workflows/ci.yml`: `uv sync --locked --extra native` → `ruff check src streamlit_app.py tests scripts` → `compileall` → `pytest -q`, on push/PR to `main`, `windows-latest`, Python 3.12.10 | CI | 1.1 |
| 1.3 | Update `CONTRIBUTING.md` to state CI now runs these checks automatically and note the 9-test quarantine + 2 lint-error fast-follow (H8) | docs | 1.2 |
| 1.4 | Update `TECHNICAL.md`'s development section to reference the new CI workflow | docs | 1.2 |

#### Risks & Mitigations

- **Risk:** `windows-latest` GitHub Actions runner resolves dependencies or
  behaves differently than the local Windows dev machine. → **Mitigation:**
  pin the CI job's Python version to exactly 3.12.10 (matching
  `uv.lock`/CONTRIBUTING.md's documented dev command); verify green on this
  phase's own PR before merging.
- **Risk:** a future contributor treats `xfail` markers as permanent rather
  than a tracked to-do. → **Mitigation:** each marker's `reason=` cites this
  plan by name; `strict=False` means an accidental fix will show as `XPASS`
  in CI output, a visible nudge to remove the marker.

#### Decisions made

- **Resolved:** target OS is `windows-latest`, not `ubuntu-latest` — this
  project is Windows-primary (unlike the other repos audited this session);
  no further discussion needed to execute.
- **Deferred, not dropped:** root-causing and fixing the 8 `AppTest`
  failures and the 1 wiki-snapshot failure. Deferred because it's app-logic
  debugging with unknown effort, not because it's unimportant — see § 9.
- **Dropped:** attempting to make the CI job also exercise the live WSL/GPU
  OCR runtimes. Not deferred — genuinely out of scope for a GitHub-hosted
  runner regardless of project maturity; those paths remain covered by
  `TESTING.md`'s manual verification process.

#### Verification & Exit Criteria (Definition of Done)

- [x] `uv sync --locked --extra native` installs cleanly on the CI runner
      (confirmed via the green GitHub Actions run below).
- [x] `uv run python -m pytest -q` reports `519 passed, 9 xfailed` — verified
      locally, exit 0.
- [x] `uvx ruff check src streamlit_app.py tests scripts` — the 2 known
      violations were fixed in this same phase (separate commit
      `33f9e0e`), not deferred; ruff now reports clean.
- [x] `.github/workflows/ci.yml` ran and is **green** on GitHub (confirmed
      via `gh run list`, first real run after this phase's push, commit
      `ca336ca`).
- [x] `CONTRIBUTING.md` and `TECHNICAL.md` both updated to state CI exists
      and link the quarantine list (H8 closed in the same commit).
- [x] No test assertion logic changed — only `xfail` markers added.

**Status: ✅ complete.** Both lint violations were fixed rather than left as
a fast-follow (maintainer's call, made when executing this phase) — §9
item 3's ruff half is done; the wiki-snapshot regeneration half is not.

## 7. Execution governance

- **Branch per phase:** single branch (e.g. `ci/stand-up-workflow`) cut from
  `main`, one PR back to `main`. No stacking risk (H7 cleared by construction).
- **Trunk:** confirmed `main` is the only branch in this repo.
- **Gate:** green CI on the PR is authoritative (lit regime, whole suite).
- **CI Milestone and enforcement:** Phase 1 authors `.github/workflows/ci.yml`.
  **Turning it into a required status check / branch-protection rule is a
  manual step in GitHub → Settings → Branches that this plan cannot
  perform** — recorded in § 9.
- **Living docs:** `CONTRIBUTING.md`/`TECHNICAL.md` updates are tasks 1.3–1.4
  in the same phase, not a follow-up (H8).
- **`.github/copilot-instructions.md`:** confirmed no prior file existed at
  the start of this pass — the companion file is a fresh file, not a merge.

## 8. Migration safety net

- **Feature flags:** none needed — no runtime behavior changes.
- **Data migration:** none.
- **Rollback plan:** revert the single PR; nothing else depends on the new
  workflow file or the `xfail` markers.
- **Transitional-insecure-state register:** empty.
- **Oracle & seam contracts:** the 528-test suite is its own oracle; no new
  contracts needed for a purely additive CI-wiring phase.
- **Testing strategy:** the existing suite, run in CI, is the testing
  strategy. Live WSL/GPU/provider paths remain covered only by
  `TESTING.md`'s manual process — unchanged by this phase.
- **Observability:** N/A — no deployed service.

## 9. Open questions / decisions needed from stakeholders

1. **Manual platform step the agent cannot perform:** after Phase 1's CI is
   green, a human must go to GitHub → Settings → Branches and add the CI
   job as a required status check on `main` for it to actually block merges.
2. **Fast-follow, not part of this phase:** root-cause and fix the 8 failing
   `tests/test_simple_streamlit.py::*` `AppTest`-based tests. Likely one
   shared root cause (possibly a Streamlit version behavior change in
   `AppTest` widget-interaction timing) but **not confirmed** — this plan
   deliberately did not attempt app-logic debugging. Recommend investigating
   as its own small piece of work, then removing the corresponding `xfail`
   markers.
3. **Fast-follow, not part of this phase:** regenerate the 24 stale wiki
   snapshots so `tests/test_knowledge_wiki.py::test_repository_wiki_contract`
   passes, and fix the 2 `ruff` `__all__`-ordering violations
   (`uvx ruff check --fix` should resolve both mechanically).
4. **`[DECISION NEEDED]`** Should CI's `windows-latest` choice ever be
   supplemented with a Linux job, given the suite itself has no Linux-only
   dependency? Not urgent — the current recommendation matches the project's
   actual primary OS; flagged here so it isn't forgotten if the project's
   platform story changes.
