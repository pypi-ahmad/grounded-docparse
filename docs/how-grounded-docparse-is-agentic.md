# How Grounded DocParse Is Agentic

Grounded DocParse is a **bounded, evidence-grounded agentic document system**. It does more than send one prompt to a language model: it prepares structured document context, assigns specialized reasoning tasks, validates the responses, performs limited repair when necessary, and routes uncertain results through human review gates.

It is deliberately not a fully autonomous general-purpose agent. The application does not invent its own goals, execute arbitrary tools, take external business actions, or run an open-ended planning loop. Deterministic application code remains in control of what an AI model can see, what it may propose, what is accepted, and when the workflow stops.

## Agentic in plain language

An ordinary model call follows a simple pattern:

```text
Prompt + document text -> model response
```

Grounded DocParse follows a controlled workflow:

```text
Source document
    -> deterministic validation and rasterization
    -> selected extraction-engine document perception
    -> grounded Markdown, layout, element IDs, and bounding boxes
    -> optional specialized reasoning tasks
    -> schema and evidence validation
    -> limited repair or deterministic fallback
    -> human review where required
    -> cited result, warning, or safe failure
```

This is agentic because the system coordinates several goal-oriented reasoning roles over shared document state. It is bounded because every role has a narrow job, controlled input, structured output, validation rules, and a stopping condition.

## The deterministic foundation comes first

The selected grounded local engine owns the document's observable structure:

- recognized text;
- page and reading order;
- element type;
- stable element and atomic-evidence IDs;
- normalized bounding boxes; and
- OCR confidence.

These values become the evidence layer used by later reasoning. Optional selected-provider features may interpret or propose changes around this evidence, but do not gain authority to rebuild the document.

This separation matters. The language model is used for judgment where judgment is useful, while deterministic code preserves identity, geometry, ordering, contracts, and auditability.

## The specialized agentic roles

| Capability | Goal | Controlled input | Accepted result and boundary |
|---|---|---|---|
| Visual recovery | Recover difficult text from suspicious regions | Selected image crops from existing local OCR regions | Text replacement is accepted only for the original region and only above the confidence threshold; geometry, type, order, additions, and deletions remain local-OCR-owned |
| Markdown refinement | Improve presentation without changing evidence | Recognized Markdown and compact layout records | Rendering directives may change presentation, but cannot replace canonical text or alter source geometry |
| Document classification | Describe the overall document | Grounded context from the first two pages | A structured classification result; failure does not invalidate the parse |
| Table of contents | Organize document sections | Bounded Markdown/layout contexts | Sections must reference known elements and pages; grounded headings provide a fallback |
| Custom form routing | Divide a mixed packet into business categories | User-defined categories plus grounded Markdown/layout | Contiguous, complete page segments with valid categories and evidence; uncertain segments require review |
| Extraction | Populate a user-approved schema | Refined Markdown plus the local-OCR-owned layout tree and evidence IDs | Values must satisfy the schema and resolve to accepted source evidence; unsupported values are repaired once or downgraded |
| Document chat | Answer questions about the parsed document | Relevant bounded document context and recent conversation | Only citations to known element IDs become clickable sources; uncited answers receive low confidence |

These are roles within one orchestrated application, not independent services that act without supervision.

## How the application observes and prepares context

`DocumentAgent.prepare` converts the successful parse into reusable agentic context. Rejected elements are removed, but active elements retain their local-OCR-owned identity. Each compact layout record includes its element ID, type, page, reading order, and text.

Long documents are divided into bounded contexts rather than being placed into one unlimited prompt. A context is limited to eight pages and approximately 48,000 characters. Oversized pages and elements are split further. This gives the reasoning stages enough local evidence while limiting cost, latency, and uncontrolled context growth.

Different tasks then use the prepared state differently:

- overall classification examines the first two pages;
- table-of-contents generation traverses every context;
- scalar extraction can process contexts and reconcile grounded candidates;
- form routing uses bounded windows with boundary-page overlap; and
- chat uses the complete context when it fits, otherwise deterministic retrieval selects relevant elements and neighbors.

The system, rather than the model, decides what context is available for each task.

## How the system reasons, checks, and repairs

The model does not receive permission to return arbitrary prose for workflow decisions. Agentic calls use structured response models appropriate to their task. Application code then validates both the shape and the meaning of the response.

Examples include:

- a routed form category must exist in the user-supplied profile;
- classified form segments must cover every supplied page exactly once and in order;
- routing evidence must refer to known elements inside the segment's page range;
- extracted values must conform to the approved JSON Schema;
- extraction citations must refer to active blocks or atoms;
- cited source text must support the extracted value; and
- chat citations must refer to known document elements.

When a structured response is invalid, the gateway permits one schema-repair attempt. Form routing similarly makes one validation-informed retry. Extraction adds one semantic evidence-repair request when a value is not properly grounded.

The loops are intentionally finite. If repair still fails, the application stops that feature, records a warning, uses a deterministic fallback where one exists, or returns `null`/`not_found` rather than repeatedly prompting until a plausible-looking answer appears. An on-demand extraction may expose a nearby candidate as `inferred`, but that state is distinguished from verified evidence.

## Human control is part of the design

The optional agentic features do not run as one unavoidable chain.

- Grounded parsing remains usable without a cloud AI model or API key.
- Visual recovery, refinement, classification, TOC generation, extraction, routing, and chat are separately controlled.
- Extraction runs only after parsing and only when a user explicitly requests it with a schema.
- Chat sends no request until it is enabled and a question is submitted.
- Users define the categories and extraction eligibility for custom routing.
- Low-confidence and boundary-merged form segments require review.
- Every routed segment must have an approved status before extraction can begin. High-confidence segments may receive that status automatically; low-confidence and boundary-merged decisions require user review.
- Only categories marked as extractable are sent to their assigned schemas.

The routing profile is fingerprinted at classification time. If it changes afterward, extraction is blocked until classification runs again. This prevents an old decision from being silently reused under new business rules.

## Example: a mixed-form business packet

Consider a 20-page packet containing a cover sheet, a new request, an update form, and supporting records. The business wants structured data only from new requests.

1. The selected grounded engine parses every page and creates the evidence layer; **AI ADE** is the explicit alternative path.
2. The user loads a routing profile defining `new_request`, `update`, `records`, and the automatic `other` fallback.
3. The routing agent proposes contiguous page segments and cites the elements supporting each category.
4. Deterministic validation checks complete page coverage, category names, ranges, and cited evidence.
5. High-confidence segments may be auto-approved; uncertain or window-boundary decisions are held for review.
6. The user reviews and corrects any held segments. Extraction remains blocked until every segment has an approved status, whether automatic or user-confirmed.
7. The application extracts only approved `new_request` segments because only that category is marked eligible.
8. Each extracted field is resolved back to existing evidence and its local-OCR-owned page and bounding box.
9. A failed segment remains visible without deleting successful results from other eligible segments.

The model contributes classification and extraction judgment, but the application controls routing rules, validation, eligibility, approval, evidence resolution, and failure handling. That combination is the core of the app's agentic design.

## Grounding is the control plane

The most important agentic constraint is that downstream reasoning must remain connected to the original parse.

For extraction, the model receives document Markdown and an identifier-rich layout tree. It proposes values and evidence references, but the application resolves those references against the parse result. Page numbers and bounding boxes are copied from the local-OCR-owned source records; provider-supplied geometry is not trusted as a new source of truth.

For chat, only citations that map to known element IDs are exposed. The UI can then open the cited annotated page and highlight the stored source box. The answer is therefore reviewable against the same evidence used by extraction and routing.

Grounding turns a model response from an unsupported assertion into a claim that can be inspected, accepted, corrected, or rejected.

## Failure isolation and deterministic fallbacks

Agentic features are optional enhancements around a completed parse. Their failures are isolated:

- classification and TOC generation run concurrently and can fail independently;
- TOC failure can fall back to grounded local OCR headings;
- an unavailable key marks optional features unavailable without destroying the parse;
- invalid routing blocks routed extraction rather than guessing;
- an extraction failure for one eligible form does not remove successful form results; and
- unsupported extracted leaves become explicit warnings and empty or inferred states.

The application exposes feature status, duration, warnings, model usage, and trace events in its results. This provides an operational record of which reasoning stages ran and what they consumed, without treating a model response as unquestionable truth.

## What the app does not do

Grounded DocParse should not be described as a fully autonomous agent. It has no:

- open-ended observe-plan-act loop;
- general task planner that creates new objectives;
- arbitrary tool execution;
- permission to modify source files or external systems;
- durable cross-session agent memory;
- autonomous approval of low-confidence business decisions; or
- authority to invent new source elements, page geometry, or evidence.

The Streamlit process synchronously orchestrates a known set of capabilities. Parse and feature results are session state unless the user downloads them; SQLite persists reusable schemas and routing profiles, not autonomous agent memory.

## The precise description

The most accurate description is:

> Grounded DocParse is a user-configured, bounded agentic workflow for document understanding. Specialized AI reasoning stages operate over a deterministic OCR evidence layer, while application code enforces context limits, structured contracts, finite repair, source grounding, automatic and human review gates, and safe failure behavior.

That design provides useful model-driven judgment without surrendering control of document identity, evidence, or downstream business actions.
