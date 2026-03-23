"""
Data Pipeline Orchestrator

Coordinates the complete ETL pipeline:
1. Read JSON records from file
2. Validate schema
3. Transform data (normalize fields, calculate derived values)
4. Output to CSV

Handles errors gracefully with configurable policies.
"""

import csv
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .transform import (
    BatchTransformResult,
    BenchmarkTransformer,
    ErrorPolicy,
    TransformResult,
    flatten_record,
    records_to_csv_rows,
)
from .validator import DataValidator, ValidationResult, ValidationSeverity

logger = logging.getLogger(__name__)


# =============================================================================
# Pipeline Configuration
# =============================================================================


@dataclass
class PipelineConfig:
    """Configuration for the data pipeline."""

    # Input settings
    input_path: Path | str

    # Output settings
    output_path: Path | str | None = None
    output_format: str = "csv"  # "csv" or "json"

    # Error handling
    error_policy: ErrorPolicy = ErrorPolicy.COLLECT
    max_errors: int = 100  # Stop after this many errors

    # Validation
    strict_schema: bool = True
    schema_name: str = "benchmark_result"

    # Processing
    batch_size: int = 1000
    include_aggregates: bool = True

    # Logging
    log_level: str = "INFO"
    error_log_path: Path | str | None = None

    def __post_init__(self):
        self.input_path = Path(self.input_path)
        if self.output_path:
            self.output_path = Path(self.output_path)
        if self.error_log_path:
            self.error_log_path = Path(self.error_log_path)


# =============================================================================
# Pipeline Results
# =============================================================================


@dataclass
class PipelineResult:
    """Complete result of a pipeline run."""

    success: bool
    input_path: Path
    output_path: Path | None = None

    # Stats
    records_read: int = 0
    records_valid: int = 0
    records_transformed: int = 0
    records_written: int = 0

    # Timing
    start_time: datetime | None = None
    end_time: datetime | None = None

    # Errors
    validation_errors: list[dict[str, Any]] = field(default_factory=list)
    transform_errors: list[dict[str, Any]] = field(default_factory=list)
    io_errors: list[str] = field(default_factory=list)

    # Aggregates (if computed)
    aggregates: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0

    @property
    def error_count(self) -> int:
        return len(self.validation_errors) + len(self.transform_errors) + len(self.io_errors)

    def summary(self) -> str:
        """Generate a human-readable summary."""
        status = "SUCCESS" if self.success else "FAILED"
        lines = [
            f"Pipeline {status}",
            f"  Input: {self.input_path}",
            f"  Output: {self.output_path or 'None'}",
            f"  Duration: {self.duration_seconds:.2f}s",
            "",
            "Records:",
            f"  Read: {self.records_read}",
            f"  Valid: {self.records_valid}",
            f"  Transformed: {self.records_transformed}",
            f"  Written: {self.records_written}",
        ]

        if self.error_count > 0:
            lines.extend([
                "",
                f"Errors: {self.error_count}",
                f"  Validation: {len(self.validation_errors)}",
                f"  Transform: {len(self.transform_errors)}",
                f"  I/O: {len(self.io_errors)}",
            ])

        return "\n".join(lines)


# =============================================================================
# File I/O
# =============================================================================


def read_json_file(path: Path) -> tuple[Any, str | None]:
    """
    Read and parse a JSON file.

    Returns:
        Tuple of (data, error_message)
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, f"File not found: {path}"
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON at line {e.lineno}: {e.msg}"
    except PermissionError:
        return None, f"Permission denied: {path}"
    except Exception as e:
        return None, f"Error reading file: {e}"


def read_json_lines(path: Path, batch_size: int = 1000) -> Iterator[list[dict]]:
    """
    Read JSON lines format (one JSON object per line) in batches.

    Yields batches of records.
    """
    batch = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    batch.append(record)
                    if len(batch) >= batch_size:
                        yield batch
                        batch = []
                except json.JSONDecodeError as e:
                    logger.warning(f"Skipping invalid JSON at line {line_num}: {e}")

        if batch:
            yield batch
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        raise


def write_csv(path: Path, headers: list[str], rows: list[list[Any]]) -> str | None:
    """
    Write data to CSV file.

    Returns error message if failed, None on success.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        return None
    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Error writing CSV: {e}"


def write_json(path: Path, data: Any, pretty: bool = True) -> str | None:
    """
    Write data to JSON file.

    Returns error message if failed, None on success.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            if pretty:
                json.dump(data, f, indent=2, default=str)
            else:
                json.dump(data, f, default=str)
        return None
    except Exception as e:
        return f"Error writing JSON: {e}"


# =============================================================================
# Pipeline Implementation
# =============================================================================


class DataPipeline:
    """
    Main data pipeline that orchestrates the ETL process.

    Usage:
        config = PipelineConfig(
            input_path="data/input.json",
            output_path="data/output.csv"
        )
        pipeline = DataPipeline(config)
        result = pipeline.run()

        if result.success:
            print(f"Processed {result.records_written} records")
        else:
            for error in result.validation_errors:
                print(f"Error: {error}")
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.validator = DataValidator()
        self.transformer = BenchmarkTransformer(error_policy=config.error_policy)

        # Set up logging
        logging.basicConfig(
            level=getattr(logging, config.log_level.upper()),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    def run(self) -> PipelineResult:
        """Execute the complete pipeline."""
        result = PipelineResult(
            success=False,
            input_path=self.config.input_path,
            output_path=self.config.output_path,
            start_time=datetime.now()
        )

        logger.info(f"Starting pipeline: {self.config.input_path}")

        # Step 1: Read input
        data, error = self._read_input()
        if error:
            result.io_errors.append(error)
            result.end_time = datetime.now()
            return result

        # Determine record type and extract records
        records = self._extract_records(data)
        result.records_read = len(records)
        logger.info(f"Read {result.records_read} records")

        # Step 2: Validate
        valid_records, validation_errors = self._validate_records(records)
        result.records_valid = len(valid_records)
        result.validation_errors = validation_errors

        if validation_errors:
            logger.warning(f"Found {len(validation_errors)} validation errors")
            if len(validation_errors) >= self.config.max_errors:
                logger.error("Max errors reached, stopping pipeline")
                result.end_time = datetime.now()
                return result

        # Step 3: Transform
        transformed_records, transform_errors = self._transform_records(valid_records)
        result.records_transformed = len(transformed_records)
        result.transform_errors = transform_errors

        # Calculate aggregates if requested
        if self.config.include_aggregates and transformed_records:
            result.aggregates = self._calculate_aggregates(transformed_records)

        # Step 4: Write output
        if self.config.output_path and transformed_records:
            write_error = self._write_output(transformed_records, result.aggregates)
            if write_error:
                result.io_errors.append(write_error)
            else:
                result.records_written = len(transformed_records)
                logger.info(f"Wrote {result.records_written} records to {self.config.output_path}")

        # Write error log if configured
        if self.config.error_log_path and result.error_count > 0:
            self._write_error_log(result)

        result.success = result.error_count == 0 or (
            result.records_written > 0 and
            self.config.error_policy != ErrorPolicy.FAIL_FAST
        )
        result.end_time = datetime.now()

        logger.info(result.summary())
        return result

    def _read_input(self) -> tuple[Any, str | None]:
        """Read the input file."""
        if not self.config.input_path.exists():
            return None, f"Input file not found: {self.config.input_path}"

        suffix = self.config.input_path.suffix.lower()

        if suffix == ".jsonl":
            # JSON lines format - read all into memory for now
            records = []
            try:
                for batch in read_json_lines(self.config.input_path, self.config.batch_size):
                    records.extend(batch)
                return records, None
            except Exception as e:
                return None, str(e)
        else:
            # Regular JSON
            return read_json_file(self.config.input_path)

    def _extract_records(self, data: Any) -> list[dict[str, Any]]:
        """Extract records from the input data structure."""
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            # Check for common wrapper patterns
            if "results" in data and isinstance(data["results"], list):
                return data["results"]
            elif "data" in data and isinstance(data["data"], list):
                return data["data"]
            elif "records" in data and isinstance(data["records"], list):
                return data["records"]
            else:
                # Single record
                return [data]
        else:
            return []

    def _validate_records(
        self, records: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Validate all records against the schema.

        Returns:
            Tuple of (valid_records, error_details)
        """
        valid_records = []
        errors = []

        for i, record in enumerate(records):
            validation_result = self.validator.validate(record, self.config.schema_name)

            if validation_result.valid:
                valid_records.append(record)
            else:
                for issue in validation_result.errors:
                    errors.append({
                        "record_index": i,
                        "field": issue.field,
                        "message": str(issue.message),
                        "value": str(issue.value) if issue.value is not None else None,
                        "severity": issue.severity.value,
                    })

                    if len(errors) >= self.config.max_errors:
                        break

                # In SKIP mode, continue; otherwise stop
                if self.config.error_policy == ErrorPolicy.FAIL_FAST:
                    break

            if len(errors) >= self.config.max_errors:
                break

        return valid_records, errors

    def _transform_records(
        self, records: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Transform all records.

        Returns:
            Tuple of (transformed_records, error_details)
        """
        batch_result = self.transformer.transform_batch(records, "benchmark")

        errors = []
        for idx, error in batch_result.errors:
            errors.append({
                "record_index": idx,
                "type": type(error).__name__,
                "message": str(error),
                "field": getattr(error, "field", None),
            })

        return batch_result.records, errors

    def _calculate_aggregates(
        self, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Calculate aggregate statistics."""
        from .transform import (
            aggregate_by_feature,
            aggregate_by_scale,
            calculate_success_rate,
        )

        return {
            "total_records": len(records),
            "success_rate": calculate_success_rate(records),
            "by_feature": aggregate_by_feature(records),
            "by_scale": aggregate_by_scale(records),
            "total_duration_ms": sum(r.get("duration_ms", 0) for r in records),
            "total_tokens": sum(r.get("tokens_used", 0) for r in records),
        }

    def _write_output(
        self, records: list[dict[str, Any]], aggregates: dict[str, Any]
    ) -> str | None:
        """Write the output file."""
        output_path = self.config.output_path

        if self.config.output_format == "csv":
            headers, rows = records_to_csv_rows(records)
            return write_csv(output_path, headers, rows)

        elif self.config.output_format == "json":
            output_data = {
                "timestamp": datetime.now().isoformat(),
                "records": records,
            }
            if aggregates:
                output_data["aggregates"] = aggregates
            return write_json(output_path, output_data)

        else:
            return f"Unknown output format: {self.config.output_format}"

    def _write_error_log(self, result: PipelineResult) -> None:
        """Write detailed error log."""
        error_data = {
            "timestamp": datetime.now().isoformat(),
            "input_path": str(result.input_path),
            "validation_errors": result.validation_errors,
            "transform_errors": result.transform_errors,
            "io_errors": result.io_errors,
        }

        error = write_json(self.config.error_log_path, error_data)
        if error:
            logger.error(f"Failed to write error log: {error}")


# =============================================================================
# Convenience Functions
# =============================================================================


def run_pipeline(
    input_path: str | Path,
    output_path: str | Path | None = None,
    output_format: str = "csv",
    error_policy: str = "collect",
) -> PipelineResult:
    """
    Run the data pipeline with sensible defaults.

    Args:
        input_path: Path to input JSON file
        output_path: Path for output file (optional)
        output_format: "csv" or "json"
        error_policy: "fail_fast", "collect", or "skip"

    Returns:
        PipelineResult with processing details

    Example:
        result = run_pipeline(
            "data/benchmark.json",
            "data/output.csv"
        )
        print(result.summary())
    """
    policy_map = {
        "fail_fast": ErrorPolicy.FAIL_FAST,
        "collect": ErrorPolicy.COLLECT,
        "skip": ErrorPolicy.SKIP,
    }

    config = PipelineConfig(
        input_path=input_path,
        output_path=output_path,
        output_format=output_format,
        error_policy=policy_map.get(error_policy, ErrorPolicy.COLLECT),
    )

    pipeline = DataPipeline(config)
    return pipeline.run()


def validate_file(input_path: str | Path) -> ValidationResult:
    """
    Validate a JSON file without transforming.

    Returns validation result with any issues found.
    """
    path = Path(input_path)
    data, error = read_json_file(path)

    if error:
        from .validator import ValidationIssue
        return ValidationResult(
            valid=False,
            issues=[ValidationIssue(message=error, rule="io")]
        )

    validator = DataValidator()

    # Auto-detect schema
    if isinstance(data, dict) and "results" in data:
        return validator.validate_core_benchmark(data)
    elif isinstance(data, dict) and "run_id" in data:
        return validator.validate_run_result(data)
    else:
        return validator.validate_benchmark_result(data)


# =============================================================================
# CLI Entry Point
# =============================================================================


def main():
    """Command-line interface for the pipeline."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Data pipeline for benchmark results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m pipeline.pipeline input.json -o output.csv
  python -m pipeline.pipeline input.json -o output.json --format json
  python -m pipeline.pipeline input.json --validate-only
  python -m pipeline.pipeline input.json -o output.csv --error-policy skip
        """
    )

    parser.add_argument("input", help="Input JSON file path")
    parser.add_argument("-o", "--output", help="Output file path")
    parser.add_argument(
        "--format",
        choices=["csv", "json"],
        default="csv",
        help="Output format (default: csv)"
    )
    parser.add_argument(
        "--error-policy",
        choices=["fail_fast", "collect", "skip"],
        default="collect",
        help="How to handle errors (default: collect)"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate, don't transform or output"
    )
    parser.add_argument(
        "--error-log",
        help="Path to write error log"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()

    if args.validate_only:
        result = validate_file(args.input)
        if result.valid:
            print("Validation: PASSED")
        else:
            print("Validation: FAILED")
            for issue in result.issues:
                print(f"  - {issue}")
        return 0 if result.valid else 1

    config = PipelineConfig(
        input_path=args.input,
        output_path=args.output,
        output_format=args.format,
        error_policy=ErrorPolicy[args.error_policy.upper()],
        error_log_path=args.error_log,
        log_level="DEBUG" if args.verbose else "INFO",
    )

    pipeline = DataPipeline(config)
    result = pipeline.run()

    print(result.summary())
    return 0 if result.success else 1


if __name__ == "__main__":
    exit(main())
