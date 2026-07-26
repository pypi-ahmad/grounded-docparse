"""Grounded document parsing pipeline."""

from .config import ParserConfig
from .evaluation import EvaluationReport, evaluate_tree, load_gold_tree
from .models import (
    DocumentProfile,
    ParseResult,
    ProcessingProfile,
    QualityReport,
    SegmentationMode,
)
from .pipeline import DocumentParser
from .review import build_quality_report, render_annotated_pdf

__all__ = [
    "DocumentParser",
    "DocumentProfile",
    "EvaluationReport",
    "ParseResult",
    "ParserConfig",
    "ProcessingProfile",
    "QualityReport",
    "SegmentationMode",
    "build_quality_report",
    "evaluate_tree",
    "load_gold_tree",
    "render_annotated_pdf",
]
