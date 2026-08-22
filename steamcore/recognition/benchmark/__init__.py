"""Infrastructure de benchmark offline pour la reconnaissance vision."""

from .corpus import CorpusEntry, CorpusMetadata, discover_corpus
from .metrics import VisionMetric, VisionMetricsAccumulator
from .variants import BenchmarkVariant, get_variants

__all__ = [
    "BenchmarkVariant",
    "CorpusEntry",
    "CorpusMetadata",
    "VisionMetric",
    "VisionMetricsAccumulator",
    "discover_corpus",
    "get_variants",
]
