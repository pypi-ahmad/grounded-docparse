from __future__ import annotations

import re
from collections import defaultdict

from .models import (
    DocumentClassification,
    DocumentNode,
    DocumentProfile,
    DocumentTree,
    FieldSource,
    GroundedField,
    NodeType,
    ValidationFinding,
)

PROFILE_TERMS: dict[DocumentProfile, tuple[str, ...]] = {
    DocumentProfile.TECHNICAL_DOCUMENTATION: (
        "prerequisite",
        "installation",
        "configuration",
        "api",
        "warning",
        "troubleshooting",
    ),
    DocumentProfile.SCIENTIFIC_PAPER: (
        "abstract",
        "method",
        "results",
        "references",
        "doi",
        "conclusion",
    ),
    DocumentProfile.INVOICE: (
        "invoice",
        "bill to",
        "subtotal",
        "tax",
        "amount due",
        "payment terms",
    ),
    DocumentProfile.INSURANCE_CLAIM: (
        "claim number",
        "policy number",
        "claimant",
        "date of loss",
        "insured",
        "claim status",
    ),
    DocumentProfile.HEALTHCARE_FORM: (
        "patient",
        "provider",
        "diagnosis",
        "medication",
        "member id",
        "signature",
    ),
    DocumentProfile.PURCHASE_ORDER: (
        "purchase order",
        "po number",
        "order id",
        "ship to",
        "delivery date",
    ),
    DocumentProfile.RECEIPT: (
        "receipt",
        "transaction id",
        "cashier",
        "change",
        "thank you",
    ),
    DocumentProfile.CONTRACT: (
        "agreement",
        "contract number",
        "effective date",
        "party",
        "terms and conditions",
    ),
    DocumentProfile.CORRESPONDENCE: (
        "dear",
        "subject",
        "sincerely",
        "from",
        "to",
    ),
    DocumentProfile.GENERIC_FORM: (
        "application",
        "form number",
        "reference number",
        "please complete",
        "signature",
    ),
}

PROFILE_DOMAIN = {
    DocumentProfile.TECHNICAL_DOCUMENTATION: "technology",
    DocumentProfile.SCIENTIFIC_PAPER: "research",
    DocumentProfile.INVOICE: "financial-services",
    DocumentProfile.INSURANCE_CLAIM: "insurance",
    DocumentProfile.HEALTHCARE_FORM: "healthcare",
    DocumentProfile.PURCHASE_ORDER: "logistics",
    DocumentProfile.RECEIPT: "financial-services",
    DocumentProfile.CONTRACT: "legal",
    DocumentProfile.CORRESPONDENCE: "correspondence",
    DocumentProfile.GENERIC_FORM: "generic",
    DocumentProfile.ATTACHMENT_UNKNOWN: "generic",
    DocumentProfile.MIXED_BATCH: "mixed",
    DocumentProfile.GENERIC: "generic",
}

FIELD_PATTERNS: dict[DocumentProfile, tuple[tuple[str, str], ...]] = {
    DocumentProfile.TECHNICAL_DOCUMENTATION: (
        ("technical.version", r"\bversion\s*[:#]?\s*([\w.-]+)"),
        ("technical.component", r"\b(?:component|product)\s*[:#]?\s*([^\n;]+)"),
        ("technical.warning", r"\b(warning\s*[:!-]?\s*.+)"),
        ("technical.api_identifier", r"\b(?:api|endpoint)\s*[:#]?\s*([^\n;]+)"),
        ("technical.prerequisite", r"\bprerequisites?\s*[:#]?\s*([^\n;]+)"),
        ("technical.procedure", r"\b(?:procedure|step)\s*[:#]?\s*([^\n;]+)"),
    ),
    DocumentProfile.SCIENTIFIC_PAPER: (
        ("paper.doi", r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)"),
        ("paper.keywords", r"\bkeywords?\s*[:—-]\s*(.+)"),
        ("paper.dataset", r"\b(?:dataset|data set)\s*[:—-]?\s*([^\n;]+)"),
        ("paper.author", r"\bauthors?\s*[:—-]\s*(.+)"),
        ("paper.affiliation", r"\baffiliations?\s*[:—-]\s*(.+)"),
    ),
    DocumentProfile.INVOICE: (
        ("invoice.number", r"\binvoice\s*(?:number|no\.?|#)\s*[:#]?\s*([\w/-]+)"),
        ("invoice.po_number", r"\b(?:purchase order|po)\s*(?:number|no\.?|#)?\s*[:#]?\s*([\w/-]+)"),
        ("invoice.date", r"\binvoice\s+date\s*[:#]?\s*([^\n;]+)"),
        ("invoice.due_date", r"\bdue\s+date\s*[:#]?\s*([^\n;]+)"),
        ("invoice.subtotal", r"\bsubtotal\s*[:#]?\s*([$€£]?\s*[\d,.]+)"),
        ("invoice.tax", r"\b(?:tax|vat)\s*[:#]?\s*([$€£]?\s*[\d,.]+)"),
        ("invoice.total", r"\b(?:grand\s+total|total|amount\s+due)\s*[:#]?\s*([$€£]?\s*[\d,.]+)"),
        ("invoice.payment_terms", r"\bpayment\s+terms?\s*[:#]?\s*([^\n;]+)"),
        ("invoice.vendor", r"\b(?:vendor|seller|from)\s*[:#]?\s*([^\n;]+)"),
        ("invoice.customer", r"\b(?:customer|bill\s+to)\s*[:#]?\s*([^\n;]+)"),
    ),
    DocumentProfile.INSURANCE_CLAIM: (
        ("claim.number", r"\bclaim\s*(?:number|no\.?|#)\s*[:#]?\s*([\w/-]+)"),
        ("claim.policy_number", r"\bpolicy\s*(?:number|no\.?|#)\s*[:#]?\s*([\w/-]+)"),
        ("claim.claimant", r"\bclaimant\s*[:#]?\s*([^\n;]+)"),
        ("claim.loss_date", r"\bdate\s+of\s+loss\s*[:#]?\s*([^\n;]+)"),
        ("claim.status", r"\bclaim\s+status\s*[:#]?\s*([^\n;]+)"),
        ("claim.amount", r"\b(?:claim|covered)\s+amount\s*[:#]?\s*([$€£]?\s*[\d,.]+)"),
        ("claim.provider", r"\bprovider\s*[:#]?\s*([^\n;]+)"),
        ("claim.service_date", r"\bdate\s+of\s+service\s*[:#]?\s*([^\n;]+)"),
        ("claim.type", r"\bclaim\s+type\s*[:#]?\s*([^\n;]+)"),
    ),
    DocumentProfile.HEALTHCARE_FORM: (
        ("healthcare.form_type", r"\bform\s+type\s*[:#]?\s*([^\n;]+)"),
        ("healthcare.patient_id", r"\bpatient\s*(?:id|number|no\.?)\s*[:#]?\s*([\w/-]+)"),
        ("healthcare.member_id", r"\bmember\s*(?:id|number|no\.?)\s*[:#]?\s*([\w/-]+)"),
        ("healthcare.provider", r"\bprovider\s*[:#]?\s*([^\n;]+)"),
        ("healthcare.diagnosis", r"\bdiagnos(?:is|es)\s*[:#]?\s*([^\n;]+)"),
        ("healthcare.medication", r"\bmedications?\s*[:#]?\s*([^\n;]+)"),
        ("healthcare.signature", r"\bsignature\s*[:#]?\s*([^\n;]+)"),
        ("healthcare.procedure", r"\bprocedures?\s*[:#]?\s*([^\n;]+)"),
        ("healthcare.date", r"\b(?:service|visit)\s+date\s*[:#]?\s*([^\n;]+)"),
    ),
    DocumentProfile.PURCHASE_ORDER: (
        ("purchase_order.number", r"\b(?:purchase\s+order|po|order)\s*(?:number|no\.?|id|#)?\s*[:#]?\s*([\w/-]+)"),
        ("purchase_order.date", r"\b(?:order|purchase)\s+date\s*[:#]?\s*([^\n;]+)"),
        ("purchase_order.vendor", r"\b(?:vendor|supplier)\s*[:#]?\s*([^\n;]+)"),
        ("purchase_order.total", r"\b(?:grand\s+total|total)\s*[:#]?\s*([$€£]?\s*[\d,.]+)"),
    ),
    DocumentProfile.RECEIPT: (
        ("receipt.number", r"\breceipt\s*(?:number|no\.?|#)\s*[:#]?\s*([\w/-]+)"),
        ("receipt.transaction_id", r"\btransaction\s*(?:id|number|no\.?)\s*[:#]?\s*([\w/-]+)"),
        ("receipt.date", r"\bdate\s*[:#]?\s*([^\n;]+)"),
        ("receipt.total", r"\btotal\s*[:#]?\s*([$€£]?\s*[\d,.]+)"),
    ),
    DocumentProfile.CONTRACT: (
        ("contract.number", r"\b(?:contract|agreement)\s*(?:number|no\.?|#)\s*[:#]?\s*([\w/-]+)"),
        ("contract.effective_date", r"\beffective\s+date\s*[:#]?\s*([^\n;]+)"),
    ),
    DocumentProfile.CORRESPONDENCE: (
        ("correspondence.subject", r"\bsubject\s*[:#]?\s*([^\n;]+)"),
        ("correspondence.date", r"\bdate\s*[:#]?\s*([^\n;]+)"),
    ),
    DocumentProfile.GENERIC_FORM: (
        ("form.reference_number", r"\b(?:reference|application|form)\s*(?:number|no\.?|id|#)\s*[:#]?\s*([\w/-]+)"),
        ("form.date", r"\bdate\s*[:#]?\s*([^\n;]+)"),
    ),
}

REQUIRED_FIELDS: dict[DocumentProfile, tuple[str, ...]] = {
    DocumentProfile.INVOICE: ("invoice.number", "invoice.total"),
    DocumentProfile.INSURANCE_CLAIM: ("claim.number", "claim.policy_number"),
    DocumentProfile.HEALTHCARE_FORM: ("healthcare.patient_id", "healthcare.provider"),
    DocumentProfile.SCIENTIFIC_PAPER: ("document.title",),
    DocumentProfile.TECHNICAL_DOCUMENTATION: ("document.title",),
    DocumentProfile.PURCHASE_ORDER: ("purchase_order.number",),
    DocumentProfile.RECEIPT: ("receipt.total",),
    DocumentProfile.CONTRACT: ("contract.number",),
}


def _content_nodes(tree: DocumentTree) -> list[DocumentNode]:
    return [
        tree.nodes[node_id]
        for page in tree.pages
        for node_id in page.content_node_ids
        if tree.nodes[node_id].text
    ]


def _source(node: DocumentNode) -> FieldSource:
    return FieldSource(
        node_id=node.id,
        page_number=node.page_number,
        bbox=node.bbox,
        source_bbox=node.source_bbox,
    )


def classify_document(
    tree: DocumentTree, requested: DocumentProfile
) -> DocumentClassification:
    nodes = _content_nodes(tree)
    if requested not in {DocumentProfile.AUTO, DocumentProfile.GENERIC}:
        return DocumentClassification(
            profile=requested,
            domain=PROFILE_DOMAIN[requested],
            confidence=1,
            method="user_override",
        )
    scores: dict[DocumentProfile, int] = defaultdict(int)
    evidence: dict[DocumentProfile, list[str]] = defaultdict(list)
    for node in nodes:
        text = (node.text or "").casefold()
        for profile, terms in PROFILE_TERMS.items():
            hits = sum(term in text for term in terms)
            if hits:
                scores[profile] += hits
                evidence[profile].append(node.id)
    if not scores or requested == DocumentProfile.GENERIC:
        return DocumentClassification(
            profile=DocumentProfile.GENERIC,
            domain="generic",
            confidence=1 if requested == DocumentProfile.GENERIC else 0.4,
            method="user_override" if requested == DocumentProfile.GENERIC else "heuristic",
        )
    profile, score = max(scores.items(), key=lambda item: (item[1], item[0].value))
    return DocumentClassification(
        profile=profile,
        domain=PROFILE_DOMAIN[profile],
        confidence=min(0.95, 0.5 + score * 0.08),
        method="heuristic",
        source_node_ids=list(dict.fromkeys(evidence[profile]))[:1_000],
    )


def _normalized_value(path: str, value: str) -> str:
    value = " ".join(value.split()).strip(" .")
    if path.endswith(("subtotal", "tax", "total", "amount")):
        numeric = re.sub(r"[^\d,.-]", "", value).replace(",", "")
        try:
            return f"{float(numeric):.2f}"
        except ValueError:
            pass
    return value


def extract_grounded_fields(
    tree: DocumentTree, classification: DocumentClassification
) -> list[GroundedField]:
    nodes = _content_nodes(tree)
    fields: list[GroundedField] = []
    title = next(
        (node for node in nodes if node.type == NodeType.HEADING.value and node.text),
        None,
    )
    if title:
        fields.append(
            GroundedField(
                path="document.title",
                raw_value=title.text or "",
                normalized_value=" ".join((title.text or "").split()),
                source_node_ids=[title.id],
                sources=[_source(title)],
                confidence=title.confidence.score if title.confidence else 0.7,
            )
        )
    patterns = FIELD_PATTERNS.get(classification.profile, ())
    seen: set[str] = {field.path for field in fields}
    for node in nodes:
        text = node.text or ""
        for path, pattern in patterns:
            if path in seen:
                continue
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            raw = match.group(1).strip()
            normalized = _normalized_value(path, raw)
            fields.append(
                GroundedField(
                    path=path,
                    raw_value=raw,
                    normalized_value=normalized,
                    source_node_ids=[node.id],
                    sources=[_source(node)],
                    confidence=node.confidence.score if node.confidence else 0.65,
                    status="normalized" if normalized != raw else "literal",
                )
            )
            seen.add(path)
    section_paths = {
        DocumentProfile.SCIENTIFIC_PAPER: {
            "abstract": "paper.abstract",
            "method": "paper.methods",
            "result": "paper.results",
            "reference": "paper.references",
        },
        DocumentProfile.TECHNICAL_DOCUMENTATION: {
            "prerequisite": "technical.prerequisite",
            "procedure": "technical.procedure",
            "warning": "technical.warning",
        },
    }.get(classification.profile, {})
    for index, node in enumerate(nodes[:-1]):
        if node.type != NodeType.HEADING.value:
            continue
        heading = (node.text or "").casefold()
        path = next(
            (value for key, value in section_paths.items() if key in heading), None
        )
        if not path or path in seen:
            continue
        value_node = next(
            (
                item
                for item in nodes[index + 1 :]
                if item.type != NodeType.HEADING.value and item.text
            ),
            None,
        )
        if value_node:
            raw = value_node.text or ""
            fields.append(
                GroundedField(
                    path=path,
                    raw_value=raw,
                    normalized_value=" ".join(raw.split()),
                    source_node_ids=[value_node.id],
                    sources=[_source(value_node)],
                    confidence=value_node.confidence.score
                    if value_node.confidence
                    else 0.65,
                )
            )
            seen.add(path)
    if classification.profile == DocumentProfile.INVOICE:
        table = next((node for node in nodes if node.type == NodeType.TABLE.value), None)
        if table and "invoice.line_items" not in seen:
            fields.append(
                GroundedField(
                    path="invoice.line_items",
                    raw_value=table.text or "",
                    normalized_value=table.text or "",
                    source_node_ids=[table.id],
                    sources=[_source(table)],
                    confidence=table.confidence.score if table.confidence else 0.65,
                )
            )
    return fields


def validate_fields(
    classification: DocumentClassification, fields: list[GroundedField]
) -> list[ValidationFinding]:
    by_path = {field.path: field for field in fields}
    findings = [
        ValidationFinding(
            code="missing_expected_field",
            severity="warning",
            message=f"Expected field was not found: {path}",
            field_paths=[path],
        )
        for path in REQUIRED_FIELDS.get(classification.profile, ())
        if path not in by_path
    ]
    if classification.profile == DocumentProfile.INVOICE:
        try:
            subtotal = float(by_path["invoice.subtotal"].normalized_value or "")
            tax = float(by_path["invoice.tax"].normalized_value or "")
            total = float(by_path["invoice.total"].normalized_value or "")
        except (KeyError, TypeError, ValueError):
            pass
        else:
            if abs((subtotal + tax) - total) > 0.01:
                sources = list(
                    dict.fromkeys(
                        node_id
                        for path in ("invoice.subtotal", "invoice.tax", "invoice.total")
                        for node_id in by_path[path].source_node_ids
                    )
                )
                findings.append(
                    ValidationFinding(
                        code="invoice_total_mismatch",
                        severity="warning",
                        message="Invoice subtotal plus tax does not equal total.",
                        field_paths=["invoice.subtotal", "invoice.tax", "invoice.total"],
                        source_node_ids=sources,
                    )
                )
    return findings


def apply_document_profile(tree: DocumentTree, requested: DocumentProfile) -> None:
    classification = classify_document(tree, requested)
    fields = extract_grounded_fields(tree, classification)
    tree.document_classification = classification
    tree.grounded_fields = fields
    tree.validation_findings = validate_fields(classification, fields)
