"""
Data Pipeline Package

Complete ETL pipeline for benchmark data:
1. Read JSON records from files
2. Validate schema
3. Transform data (normalize fields, calculate derived values)
4. Output to CSV

Usage:
    from pipeline import run_pipeline, DataPipeline, PipelineConfig

    # Simple usage
    result = run_pipeline("input.json", "output.csv")
    print(result.summary())

    # Advanced usage
    config = PipelineConfig(
        input_path="input.json",
        output_path="output.csv",
        error_policy=ErrorPolicy.SKIP,
    )
    pipeline = DataPipeline(config)
    result = pipeline.run()
"""

from .pipeline import (
    DataPipeline,
    PipelineConfig,
    PipelineResult,
    run_pipeline,
    validate_file,
)
from .transform import (
    BatchTransformResult,
    BenchmarkTransformer,
    ErrorPolicy,
    TransformResult,
    transform_and_export,
    transform_file,
)
from .validator import (
    DataValidator,
    ValidationResult,
    ValidationSeverity,
)

__all__ = [
    # Pipeline
    "DataPipeline",
    "PipelineConfig",
    "PipelineResult",
    "run_pipeline",
    "validate_file",
    # Transform
    "BatchTransformResult",
    "BenchmarkTransformer",
    "ErrorPolicy",
    "TransformResult",
    "transform_and_export",
    "transform_file",
    # Validator
    "DataValidator",
    "ValidationResult",
    "ValidationSeverity",
]
