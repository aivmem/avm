"""
Data Transformation Module for Benchmark Pipeline

Handles:
- Schema validation
- Field normalization (snake_case, date formats, units)
- Derived value calculations (metrics, aggregations)
- Graceful error handling with detailed error reports
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class TransformError(Exception):
    """Base exception for transformation errors."""

    def __init__(self, message: str, field: str | None = None, value: Any = None):
        self.field = field
        self.value = value
        super().__init__(message)


class ValidationError(TransformError):
    """Schema validation failed."""

    pass


class NormalizationError(TransformError):
    """Field normalization failed."""

    pass


class CalculationError(TransformError):
    """Derived value calculation failed."""

    pass


class ErrorPolicy(Enum):
    """How to handle transformation errors."""

    FAIL_FAST = "fail_fast"  # Stop on first error
    COLLECT = "collect"  # Collect all errors, continue processing
    SKIP = "skip"  # Skip invalid records, log warning


@dataclass
class TransformResult:
    """Result of a transformation operation."""

    success: bool
    data: dict[str, Any] | None = None
    errors: list[TransformError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchTransformResult:
    """Result of transforming multiple records."""

    total: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    records: list[dict[str, Any]] = field(default_factory=list)
    errors: list[tuple[int, TransformError]] = field(default_factory=list)
    aggregate_metrics: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Schema Definitions
# =============================================================================

BENCHMARK_RESULT_SCHEMA = {
    "required": ["feature", "scale", "operation", "duration_ms", "success"],
    "types": {
        "feature": str,
        "scale": str,
        "items": int,
        "operation": str,
        "duration_ms": (int, float),
        "success": bool,
        "tokens_used": int,
        "details": (dict, type(None)),
    },
    "allowed_values": {
        "scale": ["small", "medium", "large"],
        "feature": [
            "remember_recall",
            "multi_agent",
            "semantic_search",
            "token_aware",
            "delta_sync",
            "discovery",
        ],
    },
}

RUN_RESULT_SCHEMA = {
    "required": ["run_id", "scenario_id", "start_time", "end_time", "result"],
    "types": {
        "run_id": str,
        "scenario_id": str,
        "category": str,
        "start_time": str,
        "end_time": str,
        "config": dict,
        "events": list,
        "result": dict,
    },
}

CORE_BENCHMARK_SCHEMA = {
    "required": ["timestamp", "results"],
    "types": {
        "timestamp": str,
        "scales": dict,
        "results": list,
    },
}


# =============================================================================
# Schema Validation
# =============================================================================


def validate_schema(
    data: dict[str, Any], schema: dict[str, Any], path: str = ""
) -> list[ValidationError]:
    """
    Validate data against a schema definition.

    Args:
        data: The data to validate
        schema: Schema with 'required', 'types', and 'allowed_values' keys
        path: Current path for nested validation (for error messages)

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    # Check required fields
    for field_name in schema.get("required", []):
        if field_name not in data:
            errors.append(
                ValidationError(
                    f"Missing required field: {path}{field_name}",
                    field=f"{path}{field_name}",
                )
            )

    # Check types
    for field_name, expected_type in schema.get("types", {}).items():
        if field_name in data:
            value = data[field_name]
            if not isinstance(value, expected_type):
                errors.append(
                    ValidationError(
                        f"Invalid type for {path}{field_name}: "
                        f"expected {expected_type}, got {type(value).__name__}",
                        field=f"{path}{field_name}",
                        value=value,
                    )
                )

    # Check allowed values
    for field_name, allowed in schema.get("allowed_values", {}).items():
        if field_name in data and data[field_name] not in allowed:
            errors.append(
                ValidationError(
                    f"Invalid value for {path}{field_name}: "
                    f"'{data[field_name]}' not in {allowed}",
                    field=f"{path}{field_name}",
                    value=data[field_name],
                )
            )

    return errors


# =============================================================================
# Field Normalization
# =============================================================================


def to_snake_case(name: str) -> str:
    """Convert camelCase or PascalCase to snake_case."""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def normalize_keys(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively normalize all dictionary keys to snake_case."""
    result = {}
    for key, value in data.items():
        new_key = to_snake_case(key)
        if isinstance(value, dict):
            result[new_key] = normalize_keys(value)
        elif isinstance(value, list):
            result[new_key] = [
                normalize_keys(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[new_key] = value
    return result


def parse_iso_timestamp(ts: str) -> datetime | None:
    """Parse ISO 8601 timestamp to datetime."""
    if not ts:
        return None
    try:
        # Handle various ISO formats
        ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def normalize_timestamp(data: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    """
    Normalize timestamp fields to ISO 8601 format.

    Adds '_parsed' suffix fields with datetime objects.
    """
    result = data.copy()
    for field_name in fields:
        if field_name in result and result[field_name]:
            parsed = parse_iso_timestamp(str(result[field_name]))
            if parsed:
                result[f"{field_name}_parsed"] = parsed
                result[field_name] = parsed.isoformat()
    return result


def normalize_duration(
    value: int | float, from_unit: str = "ms", to_unit: str = "s"
) -> float:
    """Convert duration between units."""
    conversions = {
        ("ms", "s"): lambda x: x / 1000,
        ("s", "ms"): lambda x: x * 1000,
        ("ms", "ms"): lambda x: x,
        ("s", "s"): lambda x: x,
    }
    key = (from_unit, to_unit)
    if key not in conversions:
        raise NormalizationError(f"Unknown unit conversion: {from_unit} -> {to_unit}")
    return conversions[key](value)


def normalize_benchmark_result(record: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize a single benchmark result record.

    - Converts keys to snake_case
    - Normalizes duration to seconds
    - Adds normalized scale factor
    """
    result = normalize_keys(record)

    # Add duration in seconds
    if "duration_ms" in result:
        result["duration_s"] = normalize_duration(result["duration_ms"], "ms", "s")

    # Add scale factor
    scale_factors = {"small": 1, "medium": 10, "large": 50}
    if "scale" in result:
        result["scale_factor"] = scale_factors.get(result["scale"], 1)

    return result


def normalize_run_result(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize a run result record."""
    result = normalize_keys(record)
    result = normalize_timestamp(result, ["start_time", "end_time"])

    # Calculate duration if both timestamps present
    if "start_time_parsed" in result and "end_time_parsed" in result:
        delta = result["end_time_parsed"] - result["start_time_parsed"]
        result["total_duration_s"] = delta.total_seconds()

    return result


# =============================================================================
# Derived Value Calculations
# =============================================================================


def calculate_throughput(duration_ms: float, items: int) -> float:
    """Calculate items per second."""
    if duration_ms <= 0:
        return 0.0
    return items / (duration_ms / 1000)


def calculate_latency_stats(durations: list[float]) -> dict[str, float]:
    """Calculate latency statistics from a list of durations."""
    if not durations:
        return {"min": 0, "max": 0, "avg": 0, "p50": 0, "p95": 0, "p99": 0}

    sorted_d = sorted(durations)
    n = len(sorted_d)

    def percentile(p: float) -> float:
        k = (n - 1) * p
        f = int(k)
        c = f + 1 if f + 1 < n else f
        return sorted_d[f] + (k - f) * (sorted_d[c] - sorted_d[f])

    return {
        "min": sorted_d[0],
        "max": sorted_d[-1],
        "avg": sum(sorted_d) / n,
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
    }


def calculate_success_rate(results: list[dict[str, Any]]) -> float:
    """Calculate success rate from a list of results."""
    if not results:
        return 0.0
    successes = sum(1 for r in results if r.get("success", False))
    return successes / len(results)


def calculate_derived_metrics(record: dict[str, Any]) -> dict[str, Any]:
    """
    Calculate derived metrics for a benchmark result.

    Adds:
    - throughput_per_s: items processed per second
    - efficiency_score: composite efficiency metric
    - cost_estimate: estimated token cost
    """
    result = record.copy()

    # Throughput
    duration_ms = result.get("duration_ms", 0)
    items = result.get("items", 1)
    result["throughput_per_s"] = calculate_throughput(duration_ms, items)

    # Efficiency score (higher is better)
    tokens = result.get("tokens_used", 0)
    if duration_ms > 0:
        # Penalize high token usage and slow operations
        time_factor = 1000 / max(duration_ms, 1)
        token_factor = 1 / max(tokens + 1, 1)
        result["efficiency_score"] = round(time_factor * token_factor * 100, 2)
    else:
        result["efficiency_score"] = 0

    # Cost estimate (rough estimate: $0.00001 per token)
    result["cost_estimate_usd"] = tokens * 0.00001

    return result


def aggregate_by_feature(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Aggregate results by feature.

    Returns summary statistics per feature.
    """
    by_feature: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        feature = r.get("feature", "unknown")
        by_feature.setdefault(feature, []).append(r)

    aggregated = {}
    for feature, records in by_feature.items():
        durations = [r["duration_ms"] for r in records if "duration_ms" in r]
        tokens = [r.get("tokens_used", 0) for r in records]

        aggregated[feature] = {
            "count": len(records),
            "success_rate": calculate_success_rate(records),
            "latency_stats_ms": calculate_latency_stats(durations),
            "total_tokens": sum(tokens),
            "avg_tokens": sum(tokens) / len(tokens) if tokens else 0,
        }

    return aggregated


def aggregate_by_scale(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate results by scale."""
    by_scale: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        scale = r.get("scale", "unknown")
        by_scale.setdefault(scale, []).append(r)

    aggregated = {}
    for scale, records in by_scale.items():
        durations = [r["duration_ms"] for r in records if "duration_ms" in r]
        items = [r.get("items", 0) for r in records]

        aggregated[scale] = {
            "count": len(records),
            "success_rate": calculate_success_rate(records),
            "latency_stats_ms": calculate_latency_stats(durations),
            "total_items": sum(items),
            "throughput_per_s": calculate_throughput(sum(durations), sum(items))
            if durations
            else 0,
        }

    return aggregated


# =============================================================================
# Main Transformation Pipeline
# =============================================================================


class BenchmarkTransformer:
    """
    Main transformer class for benchmark data.

    Usage:
        transformer = BenchmarkTransformer(error_policy=ErrorPolicy.COLLECT)
        result = transformer.transform_core_benchmark(data)
        if result.success:
            print(result.data)
        else:
            for error in result.errors:
                print(f"Error: {error}")
    """

    def __init__(self, error_policy: ErrorPolicy = ErrorPolicy.COLLECT):
        self.error_policy = error_policy
        self._custom_validators: list[Callable[[dict], list[ValidationError]]] = []
        self._custom_transformers: list[Callable[[dict], dict]] = []

    def add_validator(
        self, validator: Callable[[dict[str, Any]], list[ValidationError]]
    ) -> "BenchmarkTransformer":
        """Add a custom validation function."""
        self._custom_validators.append(validator)
        return self

    def add_transformer(
        self, transformer: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> "BenchmarkTransformer":
        """Add a custom transformation function."""
        self._custom_transformers.append(transformer)
        return self

    def _handle_error(
        self, error: TransformError, errors: list[TransformError]
    ) -> bool:
        """
        Handle an error according to policy.

        Returns True if processing should continue, False if it should stop.
        """
        if self.error_policy == ErrorPolicy.FAIL_FAST:
            raise error
        errors.append(error)
        return self.error_policy != ErrorPolicy.SKIP

    def transform_benchmark_result(
        self, record: dict[str, Any]
    ) -> TransformResult:
        """Transform a single benchmark result record."""
        errors: list[TransformError] = []
        warnings: list[str] = []

        # Validate schema
        schema_errors = validate_schema(record, BENCHMARK_RESULT_SCHEMA)
        for err in schema_errors:
            if not self._handle_error(err, errors):
                return TransformResult(success=False, errors=errors)

        # Custom validators
        for validator in self._custom_validators:
            try:
                custom_errors = validator(record)
                for err in custom_errors:
                    if not self._handle_error(err, errors):
                        return TransformResult(success=False, errors=errors)
            except Exception as e:
                warnings.append(f"Custom validator failed: {e}")

        # Normalize
        try:
            data = normalize_benchmark_result(record)
        except Exception as e:
            err = NormalizationError(f"Normalization failed: {e}")
            if not self._handle_error(err, errors):
                return TransformResult(success=False, errors=errors)
            data = record

        # Calculate derived metrics
        try:
            data = calculate_derived_metrics(data)
        except Exception as e:
            err = CalculationError(f"Metric calculation failed: {e}")
            if not self._handle_error(err, errors):
                return TransformResult(success=False, errors=errors)

        # Custom transformers
        for transformer in self._custom_transformers:
            try:
                data = transformer(data)
            except Exception as e:
                warnings.append(f"Custom transformer failed: {e}")

        return TransformResult(
            success=len(errors) == 0,
            data=data,
            errors=errors,
            warnings=warnings,
            metrics={
                "duration_ms": data.get("duration_ms"),
                "tokens_used": data.get("tokens_used", 0),
            },
        )

    def transform_core_benchmark(self, data: dict[str, Any]) -> TransformResult:
        """Transform a complete core benchmark file."""
        errors: list[TransformError] = []
        warnings: list[str] = []

        # Validate top-level schema
        schema_errors = validate_schema(data, CORE_BENCHMARK_SCHEMA)
        for err in schema_errors:
            if not self._handle_error(err, errors):
                return TransformResult(success=False, errors=errors)

        # Transform metadata
        result = normalize_keys(data)
        result = normalize_timestamp(result, ["timestamp"])

        # Transform each result record
        transformed_results = []
        for i, record in enumerate(data.get("results", [])):
            record_result = self.transform_benchmark_result(record)
            if record_result.data:
                transformed_results.append(record_result.data)
            errors.extend(record_result.errors)
            warnings.extend(record_result.warnings)

        result["results"] = transformed_results

        # Add aggregate metrics
        result["aggregates"] = {
            "by_feature": aggregate_by_feature(transformed_results),
            "by_scale": aggregate_by_scale(transformed_results),
            "overall": {
                "total_records": len(transformed_results),
                "success_rate": calculate_success_rate(transformed_results),
                "total_tokens": sum(
                    r.get("tokens_used", 0) for r in transformed_results
                ),
            },
        }

        return TransformResult(
            success=len(errors) == 0,
            data=result,
            errors=errors,
            warnings=warnings,
            metrics=result["aggregates"]["overall"],
        )

    def transform_run_result(self, data: dict[str, Any]) -> TransformResult:
        """Transform a run result record."""
        errors: list[TransformError] = []

        # Validate schema
        schema_errors = validate_schema(data, RUN_RESULT_SCHEMA)
        for err in schema_errors:
            if not self._handle_error(err, errors):
                return TransformResult(success=False, errors=errors)

        # Normalize
        result = normalize_run_result(data)

        # Transform events
        if "events" in result:
            result["events"] = [normalize_keys(e) for e in result["events"]]
            result["event_summary"] = {
                "count": len(result["events"]),
                "agents": list({e.get("agent") for e in result["events"]}),
                "actions": list({e.get("action") for e in result["events"]}),
            }

        return TransformResult(
            success=len(errors) == 0,
            data=result,
            errors=errors,
        )

    def transform_batch(
        self, records: list[dict[str, Any]], record_type: str = "benchmark"
    ) -> BatchTransformResult:
        """
        Transform a batch of records.

        Args:
            records: List of records to transform
            record_type: Type of record ('benchmark' or 'run')
        """
        batch_result = BatchTransformResult(total=len(records))

        transform_fn = (
            self.transform_benchmark_result
            if record_type == "benchmark"
            else self.transform_run_result
        )

        for i, record in enumerate(records):
            try:
                result = transform_fn(record)
                if result.success and result.data:
                    batch_result.records.append(result.data)
                    batch_result.successful += 1
                elif self.error_policy == ErrorPolicy.SKIP:
                    batch_result.skipped += 1
                else:
                    batch_result.failed += 1
                    for err in result.errors:
                        batch_result.errors.append((i, err))
            except TransformError as e:
                batch_result.failed += 1
                batch_result.errors.append((i, e))

        # Calculate aggregate metrics
        if batch_result.records:
            batch_result.aggregate_metrics = {
                "success_rate": batch_result.successful / batch_result.total,
                "by_feature": aggregate_by_feature(batch_result.records),
                "by_scale": aggregate_by_scale(batch_result.records),
            }

        return batch_result


# =============================================================================
# CSV Output Helpers
# =============================================================================


def flatten_record(record: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested dictionary for CSV output."""
    flat = {}
    for key, value in record.items():
        full_key = f"{prefix}{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(flatten_record(value, f"{full_key}_"))
        elif isinstance(value, list):
            flat[full_key] = json.dumps(value)
        elif isinstance(value, datetime):
            flat[full_key] = value.isoformat()
        else:
            flat[full_key] = value
    return flat


def records_to_csv_rows(records: list[dict[str, Any]]) -> tuple[list[str], list[list]]:
    """
    Convert records to CSV-ready format.

    Returns:
        Tuple of (headers, rows)
    """
    if not records:
        return [], []

    # Flatten all records
    flat_records = [flatten_record(r) for r in records]

    # Collect all unique keys
    all_keys = set()
    for r in flat_records:
        all_keys.update(r.keys())

    # Sort keys for consistent column order
    headers = sorted(all_keys)

    # Build rows
    rows = []
    for r in flat_records:
        row = [r.get(h, "") for h in headers]
        rows.append(row)

    return headers, rows


# =============================================================================
# Convenience Functions
# =============================================================================


def transform_file(
    input_path: str | Path,
    error_policy: ErrorPolicy = ErrorPolicy.COLLECT,
) -> TransformResult:
    """
    Transform a JSON benchmark file.

    Auto-detects file type based on content structure.
    """
    path = Path(input_path)
    if not path.exists():
        return TransformResult(
            success=False,
            errors=[ValidationError(f"File not found: {path}")],
        )

    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return TransformResult(
            success=False,
            errors=[ValidationError(f"Invalid JSON: {e}")],
        )

    transformer = BenchmarkTransformer(error_policy=error_policy)

    # Auto-detect type
    if "results" in data and isinstance(data.get("results"), list):
        # Core benchmark format
        return transformer.transform_core_benchmark(data)
    elif "run_id" in data:
        # Run result format
        return transformer.transform_run_result(data)
    else:
        # Try as single benchmark result
        return transformer.transform_benchmark_result(data)


def transform_and_export(
    input_path: str | Path,
    output_csv_path: str | Path | None = None,
    error_policy: ErrorPolicy = ErrorPolicy.COLLECT,
) -> TransformResult:
    """
    Transform a JSON file and optionally export to CSV.

    Args:
        input_path: Path to input JSON file
        output_csv_path: Optional path for CSV output
        error_policy: How to handle errors

    Returns:
        TransformResult with transformed data
    """
    import csv

    result = transform_file(input_path, error_policy)

    if result.success and result.data and output_csv_path:
        # Get records to export
        records = result.data.get("results", [result.data])

        headers, rows = records_to_csv_rows(records)

        output_path = Path(output_csv_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)

    return result
