from __future__ import annotations

import json
from collections import Counter

from .models import DocumentTree


def build_audit_json(tree: DocumentTree) -> str:
    citations = [citation for node in tree.nodes.values() for citation in node.citations]
    scopes = Counter(str(citation.grounding_scope) for citation in citations)
    unresolved_nodes = [
        node.id
        for node in tree.nodes.values()
        if not node.citations
        or any(str(item.grounding_scope) == "unresolved" for item in node.citations)
    ]
    content_nodes = [
        tree.nodes[node_id] for page in tree.pages for node_id in page.content_node_ids
    ]
    grounded_content = sum(bool(node.citations) for node in content_nodes)
    extraction_values = [
        item
        for extraction in tree.schema_extractions
        for item in extraction.provenance.values()
    ]
    cited_extraction_values = sum(bool(item.citations) for item in extraction_values)
    failure_codes = Counter(item.code for item in tree.failure_cases)
    failure_stages = Counter(item.stage for item in tree.failure_cases)
    failure_severities = Counter(item.severity for item in tree.failure_cases)
    failure_outcomes = Counter(item.outcome for item in tree.failure_cases)
    payload = {
        "schema_version": "1.2.0",
        "document_id": tree.document_id,
        "source_sha256": tree.source_sha256,
        "document_schema_version": tree.schema_version,
        "processing_profile": tree.processing_profile,
        "document_profile": tree.document_classification.profile
        if tree.document_classification
        else None,
        "citation_coverage": {
            "content_nodes": len(content_nodes),
            "grounded_content_nodes": grounded_content,
            "coverage": grounded_content / len(content_nodes) if content_nodes else 1.0,
            "by_scope": dict(sorted(scopes.items())),
            "unresolved_node_ids": unresolved_nodes,
        },
        "model_runs": [item.model_dump(mode="json") for item in tree.model_runs],
        "window_runs": [item.model_dump(mode="json") for item in tree.window_runs],
        "adaptive_retries": [
            item.model_dump(mode="json") for item in tree.adaptive_retries
        ],
        "failure_cases": {
            "count": len(tree.failure_cases),
            "by_code": dict(sorted(failure_codes.items())),
            "by_stage": dict(sorted(failure_stages.items())),
            "by_severity": dict(sorted(failure_severities.items())),
            "by_outcome": dict(sorted(failure_outcomes.items())),
            "items": [item.model_dump(mode="json") for item in tree.failure_cases],
        },
        "validation_findings": [
            item.model_dump(mode="json") for item in tree.validation_findings
        ],
        "schema_extraction": {
            "document_count": len(tree.schema_extractions),
            "status_counts": dict(
                sorted(Counter(item.status for item in tree.schema_extractions).items())
            ),
            "leaf_values": len(extraction_values),
            "cited_leaf_values": cited_extraction_values,
            "citation_coverage": (
                cited_extraction_values / len(extraction_values)
                if extraction_values
                else 1.0
            ),
            "validation_error_count": sum(
                len(item.validation_errors) for item in tree.schema_extractions
            ),
            "logical_tables": [
                {
                    "id": table.id,
                    "row_count": table.row_count,
                    "column_count": table.column_count,
                    "source_table_count": len(table.source_table_node_ids),
                    "status": table.status,
                }
                for table in tree.logical_tables
            ],
        },
        "warnings": list(tree.warnings),
        "segmentation": {
            "subdocument_count": len(tree.batch_manifest.subdocuments),
            "split_boundaries": [
                item.before_page
                for item in tree.batch_manifest.boundaries
                if item.decision == "split"
            ],
            "uncertain_boundaries": [
                item.before_page
                for item in tree.batch_manifest.boundaries
                if item.decision == "uncertain"
            ],
        }
        if tree.batch_manifest
        else None,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
