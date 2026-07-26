from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from itertools import pairwise

import pymupdf

from .domain import FIELD_PATTERNS, PROFILE_TERMS
from .models import (
    BatchManifest,
    BoundaryDecision,
    DocumentProfile,
    DocumentTree,
    IdentifierEvidence,
    PageClassification,
    ProcessingProfile,
    SubdocumentDescriptor,
)

PRIMARY_IDENTIFIER_PATHS = {
    "invoice.number",
    "purchase_order.number",
    "receipt.number",
    "receipt.transaction_id",
    "claim.number",
    "healthcare.patient_id",
    "healthcare.member_id",
    "paper.doi",
    "contract.number",
    "form.reference_number",
}


def _normalize_identifier(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"\s+", "", normalized)


def _page_nodes(tree: DocumentTree, page_number: int):
    page = next(page for page in tree.pages if page.number == page_number)
    return [tree.nodes[node_id] for node_id in page.content_node_ids]


def classify_pages(
    tree: DocumentTree, requested: DocumentProfile
) -> list[PageClassification]:
    classifications: list[PageClassification] = []
    for page in tree.pages:
        nodes = _page_nodes(tree, page.number)
        scores: dict[DocumentProfile, int] = defaultdict(int)
        evidence: dict[DocumentProfile, list[str]] = defaultdict(list)
        for node in nodes:
            text = (node.text or "").casefold()
            for profile, terms in PROFILE_TERMS.items():
                hits = sum(term in text for term in terms)
                if hits:
                    scores[profile] += hits
                    evidence[profile].append(node.id)
        if requested not in {DocumentProfile.AUTO, DocumentProfile.GENERIC}:
            profile, confidence = requested, 1.0
        elif scores:
            profile, score = max(scores.items(), key=lambda item: (item[1], item[0].value))
            confidence = min(0.95, 0.5 + score * 0.08)
        else:
            profile, confidence = DocumentProfile.ATTACHMENT_UNKNOWN, 0.4
        identifiers: list[IdentifierEvidence] = []
        for node in nodes:
            text = node.text or ""
            for candidate_profile, patterns in FIELD_PATTERNS.items():
                if candidate_profile not in {profile, DocumentProfile.GENERIC_FORM}:
                    continue
                for path, pattern in patterns:
                    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                        value = match.group(1).strip()
                        identifiers.append(
                            IdentifierEvidence(
                                kind=path,
                                value=value,
                                normalized_value=_normalize_identifier(value),
                                page_number=page.number,
                                node_id=node.id,
                                bbox=node.bbox,
                                confidence=node.confidence.score if node.confidence else 0.65,
                                primary=path in PRIMARY_IDENTIFIER_PATHS,
                            )
                        )
        classifications.append(
            PageClassification(
                page_number=page.number,
                profile=profile,
                confidence=confidence,
                source_node_ids=list(dict.fromkeys(evidence.get(profile, []))),
                identifiers=identifiers,
            )
        )
    return classifications


def _primary_values(page: PageClassification) -> dict[str, set[str]]:
    values: dict[str, set[str]] = defaultdict(set)
    for item in page.identifiers:
        if item.primary and item.confidence >= 0.6:
            values[item.kind].add(item.normalized_value)
    return values


def _supporting_values(page: PageClassification) -> dict[str, set[str]]:
    values: dict[str, set[str]] = defaultdict(set)
    for item in page.identifiers:
        if not item.primary and item.confidence >= 0.6:
            values[item.kind].add(item.normalized_value)
    return values


def decide_boundaries(pages: list[PageClassification]) -> list[BoundaryDecision]:
    boundaries: list[BoundaryDecision] = []
    for previous, current in pairwise(pages):
        previous_ids, current_ids = _primary_values(previous), _primary_values(current)
        previous_support = _supporting_values(previous)
        current_support = _supporting_values(current)
        common_kinds = previous_ids.keys() & current_ids.keys()
        same_id = any(previous_ids[kind] & current_ids[kind] for kind in common_kinds)
        changed_id = any(
            previous_ids[kind].isdisjoint(current_ids[kind]) for kind in common_kinds
        )
        supporting_kinds = previous_support.keys() & current_support.keys()
        same_support = any(
            previous_support[kind] & current_support[kind] for kind in supporting_kinds
        )
        changed_support = any(
            previous_support[kind].isdisjoint(current_support[kind])
            for kind in supporting_kinds
        )
        reasons: list[str] = []
        if same_id:
            score = 0.0
            reasons.append("same_primary_identifier")
        elif changed_id:
            score = 1.0
            reasons.append("changed_primary_identifier")
        elif current_ids and not previous_ids:
            score = 0.82
            reasons.append("new_primary_identifier")
        elif (
            previous.profile != current.profile
            and previous.confidence >= 0.65
            and current.confidence >= 0.65
        ):
            score = 0.85
            reasons.append("high_confidence_type_change")
        elif previous.profile != current.profile:
            score = 0.65
            reasons.append("uncertain_type_change")
        elif changed_support:
            score = 0.6
            reasons.append("changed_supporting_identifier")
        elif same_support:
            score = 0.1
            reasons.append("same_supporting_identifier")
        else:
            score = 0.15
            reasons.append("same_document_type")
        decision = "split" if score >= 0.8 else "keep" if score <= 0.5 else "uncertain"
        boundaries.append(
            BoundaryDecision(
                before_page=current.page_number,
                score=score,
                decision=decision,
                confidence=abs(score - 0.5) * 2,
                reasons=reasons,
            )
        )
    return boundaries


def build_batch_manifest(
    tree: DocumentTree,
    processing_profile: ProcessingProfile,
    requested: DocumentProfile,
    *,
    enabled: bool = True,
    boundary_overrides: dict[int, tuple[str, float, str, str]] | None = None,
) -> BatchManifest:
    pages = classify_pages(tree, requested)
    boundaries = decide_boundaries(pages)
    if not enabled:
        for boundary in boundaries:
            boundary.decision = "keep"
            boundary.score = 0
            boundary.confidence = 1
            boundary.reasons = ["segmentation_disabled"]
    for boundary in boundaries:
        override = (boundary_overrides or {}).get(boundary.before_page)
        if override is None:
            continue
        decision, confidence, adjudication, reason = override
        boundary.decision = decision
        boundary.confidence = confidence
        boundary.adjudication = adjudication
        boundary.reasons.append(reason[:2_000])
    starts = [pages[0].page_number]
    starts.extend(item.before_page for item in boundaries if item.decision == "split")
    ranges = [
        (start, starts[index + 1] - 1 if index + 1 < len(starts) else pages[-1].page_number)
        for index, start in enumerate(starts)
    ]
    descriptors: list[SubdocumentDescriptor] = []
    for index, (start, end) in enumerate(ranges, start=1):
        selected = [page for page in pages if start <= page.page_number <= end]
        profile_scores: dict[DocumentProfile, float] = defaultdict(float)
        for page in selected:
            profile_scores[page.profile] += page.confidence
        profile = max(profile_scores, key=lambda item: (profile_scores[item], item.value))
        identifiers = [item for page in selected for item in page.identifiers]
        primary = next((item for item in identifiers if item.primary), None)
        segment_id = f"seg-{hashlib.sha256(f'{tree.source_sha256}:{start}:{end}'.encode()).hexdigest()[:16]}"
        descriptors.append(
            SubdocumentDescriptor(
                id=segment_id,
                index=index,
                start_page=start,
                end_page=end,
                profile=profile,
                confidence=sum(page.confidence for page in selected) / len(selected),
                instance_key=(
                    f"{primary.kind}:{primary.normalized_value}" if primary else None
                ),
                identifiers=identifiers,
                warnings=(
                    ["Uncertain boundary was retained with the preceding document."]
                    if any(
                        item.decision == "uncertain" and start < item.before_page <= end
                        for item in boundaries
                    )
                    else []
                ),
            )
        )
    by_key: dict[str, list[SubdocumentDescriptor]] = defaultdict(list)
    for descriptor in descriptors:
        if descriptor.instance_key:
            by_key[descriptor.instance_key].append(descriptor)
    for matches in by_key.values():
        if len(matches) > 1:
            for descriptor in matches:
                descriptor.related_segment_ids = [
                    item.id for item in matches if item.id != descriptor.id
                ]
    return BatchManifest(
        batch_id=f"batch-{tree.source_sha256[:16]}",
        source_name=tree.source_name,
        source_sha256=tree.source_sha256,
        page_count=len(tree.pages),
        processing_profile=processing_profile,
        page_classifications=pages,
        boundaries=boundaries,
        subdocuments=descriptors,
    )


def slice_document_tree(
    tree: DocumentTree, descriptor: SubdocumentDescriptor
) -> DocumentTree:
    selected_pages = [
        page
        for page in tree.pages
        if descriptor.start_page <= page.number <= descriptor.end_page
    ]
    included = {tree.root_id}
    for page in selected_pages:
        included.add(page.id)
        included.update(page.content_node_ids)
    pending = list(included)
    while pending:
        node = tree.nodes.get(pending.pop())
        if node is None:
            continue
        if node.parent_id and node.parent_id not in included:
            included.add(node.parent_id)
            pending.append(node.parent_id)
        for node_id in node.children_ids:
            candidate = tree.nodes.get(node_id)
            if candidate is None or node_id in included:
                continue
            if candidate.page_number is None or (
                descriptor.start_page <= candidate.page_number <= descriptor.end_page
            ):
                included.add(node_id)
                pending.append(node_id)
    segment = tree.model_copy(deep=True)
    segment.document_id = descriptor.id
    segment.source_name = f"part-{descriptor.index:04d}-{descriptor.profile.value}.pdf"
    segment.nodes = {
        node_id: node for node_id, node in segment.nodes.items() if node_id in included
    }
    for node in segment.nodes.values():
        node.children_ids = [item for item in node.children_ids if item in included]
        node.relationships = [
            item for item in node.relationships if item.target_id in included
        ]
    segment.pages = [page for page in segment.pages if page.id in included]
    for local_number, page in enumerate(segment.pages, start=1):
        page.segment_page_number = local_number
        for node_id in page.content_node_ids:
            node = segment.nodes[node_id]
            for citation in node.citations:
                citation.segment_page_number = local_number
    referenced_assets = {
        str(node.attributes.get("asset_path"))
        for node in segment.nodes.values()
        if node.attributes.get("asset_path")
    }
    segment.assets = [asset for asset in segment.assets if asset in referenced_assets]
    segment.model_runs = [
        run
        for run in segment.model_runs
        if run.page_number is None
        or descriptor.start_page <= run.page_number <= descriptor.end_page
    ]
    segment.adaptive_retries = [
        retry
        for retry in segment.adaptive_retries
        if descriptor.start_page <= retry.page_number <= descriptor.end_page
    ]
    segment_page_numbers = {
        page.number: page.segment_page_number for page in segment.pages
    }
    filtered_failures = []
    for failure in segment.failure_cases:
        if (
            failure.page_number is not None
            and failure.page_number not in segment_page_numbers
        ):
            continue
        had_node_ids = bool(failure.node_ids)
        failure.node_ids = [item for item in failure.node_ids if item in included]
        if had_node_ids and not failure.node_ids:
            continue
        failure.segment_page_number = segment_page_numbers.get(failure.page_number)
        filtered_failures.append(failure)
    segment.failure_cases = filtered_failures
    segment.grounded_fields = []
    segment.logical_tables = []
    segment.schema_extractions = []
    segment.validation_findings = []
    segment.document_classification = None
    segment.batch_manifest = None
    return segment


def extract_pdf_range(data: bytes, start_page: int, end_page: int) -> bytes:
    with pymupdf.open(stream=data, filetype="pdf") as source:
        output = pymupdf.open()
        try:
            output.insert_pdf(source, from_page=start_page - 1, to_page=end_page - 1)
            return output.tobytes(garbage=3, deflate=True)
        finally:
            output.close()
