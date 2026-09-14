"""Grounded document parsing pipeline.

Curated public surface: every name re-exported here is the supported contract
for callers outside this package (CLI, Streamlit app, and library users).
Internal helpers that are not re-exported here should stay unexported rather
than being added to this file. Start at native.py (immutable evidence
contracts) or models.py (OCR result contracts) to see what these types
represent, then universal.py for how a file gets routed to a parser.
"""

from .agentic import DocumentAgent, PreparedDocumentContext
from .config import AlternateOcrEngine, OcrEngine, ParserConfig
from .content_range import (
    AppliedContentRange,
    ContentRange,
    ContentRangeInfo,
    ContentUnit,
)
from .extraction import DocumentExtractor
from .models import (
    AgenticAnalysis,
    ChatAnswer,
    ChatSource,
    ClassifierCategory,
    ClassifierProfile,
    Document,
    Element,
    EnhancementMetadata,
    ExtractionResult,
    FormClassificationResult,
    FormSegment,
    ParseMetadata,
    ParseResult,
    RoutedExtractionResult,
    SchemaProposal,
    SegmentExtraction,
    StoredSchema,
    VisualRecoveryResult,
)
from .native import (
    CellSourceAnchor,
    CharacterInterval,
    CsvSourceAnchor,
    NativeAsset,
    NativeDocument,
    NativeElement,
    NativeExtractedValue,
    NativeExtractionEvidence,
    NativeExtractionResult,
    NativeParseResult,
    PageRoute,
    PdfSourceAnchor,
    PreviewArtifact,
    ProcessingType,
    SourceAnchor,
    SourceFormat,
    SourceSpan,
    SourceUnit,
    StructuralSourceAnchor,
    TextSourceAnchor,
    render_native_combined_result,
    render_native_document,
)
from .native_extraction import LangExtractNativeExtractor, translate_stored_schema
from .pipeline import DocumentParser
from .render import render_combined_result
from .universal import (
    MixedNativePageUnusable,
    NativePdfRequiresMixed,
    PdfInspection,
    ProcessingTypeMismatch,
    UniversalDocumentParser,
    inspect_content_range,
)

__all__ = [
    "AgenticAnalysis",
    "AlternateOcrEngine",
    "AppliedContentRange",
    "CellSourceAnchor",
    "CharacterInterval",
    "ChatAnswer",
    "ChatSource",
    "ClassifierCategory",
    "ClassifierProfile",
    "ContentRange",
    "ContentRangeInfo",
    "ContentUnit",
    "CsvSourceAnchor",
    "Document",
    "DocumentAgent",
    "DocumentExtractor",
    "DocumentParser",
    "Element",
    "EnhancementMetadata",
    "ExtractionResult",
    "FormClassificationResult",
    "FormSegment",
    "LangExtractNativeExtractor",
    "MixedNativePageUnusable",
    "NativeAsset",
    "NativeDocument",
    "NativeElement",
    "NativeExtractedValue",
    "NativeExtractionEvidence",
    "NativeExtractionResult",
    "NativeParseResult",
    "NativePdfRequiresMixed",
    "OcrEngine",
    "PageRoute",
    "ParseMetadata",
    "ParseResult",
    "ParserConfig",
    "PdfInspection",
    "PdfSourceAnchor",
    "PreparedDocumentContext",
    "PreviewArtifact",
    "ProcessingType",
    "ProcessingTypeMismatch",
    "RoutedExtractionResult",
    "SchemaProposal",
    "SegmentExtraction",
    "SourceAnchor",
    "SourceFormat",
    "SourceSpan",
    "SourceUnit",
    "StoredSchema",
    "StructuralSourceAnchor",
    "TextSourceAnchor",
    "UniversalDocumentParser",
    "VisualRecoveryResult",
    "inspect_content_range",
    "render_combined_result",
    "render_native_combined_result",
    "render_native_document",
    "translate_stored_schema",
]
