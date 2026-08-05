# Agentic Document Extraction: LandingAI ADE and Grounded DocParse

Agentic document extraction is more than OCR followed by a prompt. It is a controlled document-understanding workflow that can perceive visual structure, choose among specialized tasks, reason from user instructions, validate its outputs, preserve uncertainty, and connect results back to source evidence.

LandingAI calls its managed platform **Agentic Document Extraction (ADE)**. Grounded DocParse implements a related pattern with selectable local GLM-OCR or PaddleOCR-VL-1.6, optional bounded Luna reasoning, deterministic validation, and review controls. The products are not connected, and their contracts are not identical, but comparing them helps clarify what “agentic” means in practical document processing.

> **Reference date:** LandingAI product descriptions in this page were verified against its official documentation on 30 July 2026. Product APIs can change; follow the linked LandingAI documentation for current behavior.

## What agentic document extraction means

A basic extraction call looks like this:

```text
Document text + prompt -> model-generated JSON
```

An agentic document workflow has more structure:

```text
Visual document
    -> parse visual and structural evidence
    -> prepare grounded document context
    -> select a goal: classify, split, section, extract, or answer
    -> apply task-specific instructions or schemas
    -> validate structure and source support
    -> repair, fall back, request review, or fail safely
    -> return traceable output
```

The word **agentic** does not automatically mean a fully autonomous general agent. A document system can be agentic because it coordinates goal-directed reasoning and controlled decisions without inventing its own objectives, using arbitrary tools, or acting on external business systems.

## How LandingAI uses the term

LandingAI ADE is a managed document-intelligence platform. Its current public surface separates document work into five APIs: Parse, Extract, Classify, Section, and Split. Most workflows begin with Parse, while Classify can operate independently to label pages before or without parsing. [LandingAI ADE overview](https://docs.landing.ai/ade/ade-overview)

| LandingAI capability | Official purpose |
|---|---|
| Parse | Convert a document into structured Markdown and hierarchical JSON with chunks, page references, and coordinates |
| Classify | Assign user-defined categories to individual pages |
| Split | Classify and separate parsed multi-document files into logical sub-documents |
| Section | Generate a hierarchical table of contents with section levels and chunk references |
| Extract | Populate schema-defined fields from parsed content |

LandingAI Parse identifies elements such as text, tables, and form fields. Its output contains chunk IDs and grounding information, including the source page and coordinates. That representation can then be used by the other ADE operations. [LandingAI Parse documentation](https://docs.landing.ai/ade/parse)

This public API design is agentic in a practical sense: a user can give the platform different document goals and definitions, and the platform applies specialized document reasoning to each goal. The public documentation does not establish that ADE uses an open-ended autonomous observe-plan-act loop internally, so this page does not assume one.

## How Grounded DocParse is agentic

Grounded DocParse uses a parse-then-reason architecture:

```text
PDF or image
    -> local rasterization and GLM-OCR
    -> grounded Markdown + hierarchical JSON + layout elements
    -> optional bounded Luna reasoning
    -> deterministic validation and evidence resolution
    -> conditional review
    -> cited result, warning, or safe failure
```

The selected local OCR engine owns the canonical document evidence: text regions, element IDs, types, pages, reading order, confidence, and normalized bounding boxes. Optional Luna stages can interpret that evidence, but they cannot freely redefine its identity or geometry.

The application coordinates several specialized goals:

- recovering difficult text from selected existing regions;
- improving Markdown presentation through bounded directives;
- classifying the whole document;
- generating a hierarchical table of contents;
- classifying and segmenting mixed-form packets from user-defined categories;
- extracting schema-defined fields from the whole document or eligible segments; and
- answering document questions with known-element citations.

For the implementation details and control boundaries, see [How Grounded DocParse Is Agentic](how-grounded-docparse-is-agentic.md).

## Capability comparison

| Area | LandingAI ADE | Grounded DocParse |
|---|---|---|
| Primary delivery model | Managed platform with APIs and client libraries | Workstation-oriented Streamlit application and Python package |
| Visual parser | LandingAI parsing models exposed through ADE Parse | Selectable local GLM-OCR or PaddleOCR-VL-1.6 service |
| Parse representation | Markdown, hierarchical JSON, chunks, pages, and coordinates | Base/refined Markdown, hierarchical JSON, blocks, atoms, elements, pages, and normalized boxes |
| Classification | User-defined page classification can run independently of Parse | Whole-document classification and user-defined form segmentation run after the local parse |
| Mixed packets | Split returns classified sub-documents and their Markdown | Form routing produces contiguous logical segments and runs assigned schemas against in-memory subsets |
| Sectioning | Section API generates a hierarchical TOC with chunk references | Optional TOC generation produces nested sections with pages and known element references |
| Extraction | Schema-based extraction from parsed or split content | Schema-based extraction from grounded Markdown/layout with deterministic evidence validation |
| Chat | Playground chat is an example application rather than an ADE API | Optional document chat is built into the Streamlit application |
| Grounding identity | LandingAI chunk ID, page, and coordinates | Local-OCR-owned block/atom/element ID, page, source text, and normalized box |
| Control model | Operations and validation are managed by the ADE platform | Explicit context limits, finite retries, confidence gates, review states, and failure isolation are visible in application code |

The two systems use related concepts, but their nouns are not interchangeable. A LandingAI **chunk** and a Grounded DocParse **element** both identify grounded document content, yet they have different schemas and ownership rules.

## Do we have Parse, Classify, Split, Section, and Extract?

### Parse — yes

Grounded DocParse converts supported PDFs and images into:

- grounded and refined Markdown;
- hierarchical document/page/block JSON;
- normalized elements and atomic evidence;
- page references and reading order;
- element types and confidence;
- normalized bounding boxes; and
- an annotated PDF for visual review.

Our elements serve a purpose comparable to LandingAI chunks, but they are not API-compatible representations.

### Classify — yes, with a different execution point

Grounded DocParse provides two classification modes:

1. optional whole-document classification based on the first two parsed pages; and
2. custom form classification based on categories and descriptions supplied by the user.

Custom classification assigns categories to contiguous page ranges rather than returning unrelated independent labels for every page. The ranges collectively cover the packet, so every page belongs to one effective segment.

Unlike LandingAI Classify, our classification requires a completed local OCR parse because it reasons over the resulting Markdown and layout elements.

### Split — partial: logical segmentation, not file splitting

Custom form routing can separate a mixed packet into logical segments such as `new_request`, `update`, `records`, and `other`. Each segment has a page range, category, confidence, reasoning, evidence IDs, review status, extraction eligibility, and optional assigned schema.

For eligible segments, the application creates an in-memory `ParseResult` subset containing the original pages and elements, then runs the assigned extraction schema. This is sufficient for selective extraction and per-form result reporting.

The current application does **not** export each segment as a new PDF or standalone Markdown sub-document. It therefore has LandingAI-like logical splitting for routing, but not full separate-document output. LandingAI Split explicitly returns classified sub-documents with Markdown content. [LandingAI Split API](https://docs.landing.ai/api-reference/tools/ade-split)

### Section — yes

Optional TOC generation creates hierarchical sections with titles, levels, pages, child sections, and grounded element references. Returned page and element references are validated. If the optional model call fails, the application can build a deterministic fallback from accepted GLM headings.

### Extract — yes

Users can define fields and descriptions in the UI or import schema definitions from JSON or Markdown. The extraction stage receives refined document Markdown plus an identifier-rich layout tree.

Every returned value must satisfy the schema. A verified value must resolve to supporting source evidence. When exact support cannot be confirmed, the on-demand extraction path may retain a candidate as `inferred` with a grounded location and warning; that state is kept distinct from verified evidence. The application copies page and bounding-box data from a local-OCR-owned block or atom rather than accepting newly invented provider geometry as the source of truth.

For mixed packets, only segments that have an approved status, are marked eligible, and have an assigned saved schema are extracted. Non-eligible categories remain classified but are not sent to extraction.

## Do we meet the characteristics of agentic extraction?

### 1. Visual and structural understanding — yes, with a boundary

The parser represents text, headings, lists, tables, form fields, checkboxes, figures, captions, reading order, hierarchy, page location, and geometry. It also preserves multi-page order and supplies bounded cross-page context to later stages.

It does not build an unrestricted semantic knowledge graph connecting every concept across every page. Its page relationships are the explicit document hierarchy, reading order, context windows, sections, and contiguous form segments.

### 2. Goal-directed behavior — yes

The system selects specialized behavior from the user’s requested outcome: recover weak text, refine presentation, classify, section, route forms, extract fields, or answer a question. These capabilities share prepared evidence but have independent controls and failure states.

### 3. Adaptive processing — yes

Extraction uses user-defined field names, descriptions, and types rather than a hard-coded template. Routing uses user-defined category descriptions and extraction eligibility. The same logic can therefore operate across varying document layouts without training a new template model for every form.

This does not guarantee that every unseen layout will be interpreted correctly; representative evaluation and human review remain necessary.

### 4. Grounding — yes, strongly enforced

Accepted results can resolve to known source records containing:

- a block, atom, or element ID;
- page number;
- source text or source span;
- normalized bounding box; and
- confidence or review state.

Before marking an extracted value verified, the application validates that its citations exist and that the cited text supports the proposed value. An inferred value may retain a candidate source location without literal support, but it remains labeled and warned accordingly. Chat exposes only citations that map to known element IDs.

### 5. Validation and self-correction — yes, bounded

The application validates structured model responses, extraction schemas, extracted instances, evidence pointers, cited content, categories, page ranges, complete segmentation coverage, and TOC references.

Invalid structured output receives one repair opportunity. Form routing makes one validation-informed retry. Extraction can make one semantic evidence-repair request. These loops stop after their defined attempt; the application does not keep prompting until it receives a plausible result.

### 6. Uncertainty handling — yes

The system can distinguish verified, inferred, not-found, and null extraction outcomes. Routing carries confidence and review status. Visual states include checked, unchecked, indeterminate, and unknown. Optional feature failures and partial fallbacks are exposed as statuses and warnings.

An inferred value is not presented as verified evidence. An unresolved value is cleared or reported as missing rather than being silently invented.

### 7. Orchestration — yes

The application coordinates a known workflow:

```text
input validation
    -> rasterization
    -> GLM layout and recognition
    -> quality analysis
    -> optional visual recovery
    -> document assembly and rendering
    -> optional classification and TOC
    -> optional routing and review
    -> optional extraction
    -> optional cited chat
    -> downloads and metadata
```

Optional failures remain isolated where possible. A failed classification, TOC, extraction, or chat operation does not retroactively erase a successful local OCR parse.

### 8. Controlled autonomy — yes

The model may make bounded classification, organization, extraction, and question-answering decisions. Application code retains authority over available context, structured contracts, source identity, geometry, confidence thresholds, repair limits, routing eligibility, and stopping conditions.

High-confidence routing segments may be auto-approved. Low-confidence and boundary-merged segments require user review. Extraction does not run automatically after parsing, and chat sends no request until the user enables it and submits a question.

The application has no open-ended planner, arbitrary tool execution, durable agent memory, self-created business objectives, or permission to act on downstream systems.

## What this comparison does not claim

- Grounded DocParse does not call, embed, or reproduce LandingAI ADE.
- The **ADE mode** label in Grounded DocParse is only a preset for optional Luna features; it is not a LandingAI integration.
- Similar functions do not imply identical model architecture, output contracts, accuracy, scale, or production maturity.
- The current logical form router does not replace a separate-document export feature.
- Public LandingAI API behavior does not reveal or prove an undocumented internal autonomous-agent architecture.

## Bottom line

LandingAI ADE and Grounded DocParse both implement practical agentic document intelligence: they establish a structured document representation and support goal-directed operations such as classification, organization, splitting or routing, and schema extraction.

Grounded DocParse fully provides Parse, Classify, Section, and Extract equivalents. It partially provides Split through grounded logical segmentation and selective extraction, but it does not currently emit separate sub-document files.

Across the broader agentic criteria, Grounded DocParse provides visual and structural understanding, adaptive task definitions, source grounding, bounded repair, explicit uncertainty, workflow orchestration, and controlled autonomy. Its design deliberately favors finite, inspectable decisions over open-ended autonomous behavior.

## References

- [LandingAI ADE overview](https://docs.landing.ai/ade/ade-overview)
- [LandingAI Parse documentation](https://docs.landing.ai/ade/parse)
- [LandingAI Split API](https://docs.landing.ai/api-reference/tools/ade-split)
- [LandingAI ADE Playground](https://docs.landing.ai/ade/ade-playground)
- [How Grounded DocParse Is Agentic](how-grounded-docparse-is-agentic.md)
- [Grounded DocParse architecture](architecture.md)
- [Grounded DocParse design basis](research.md)
