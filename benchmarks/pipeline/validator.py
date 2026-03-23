"""
Data Validation Module for Benchmark Pipeline

Provides comprehensive validation for benchmark data including:
- Schema validation with detailed error reporting
- Type checking with support for union types
- Range and constraint validation
- Custom validator registration
- Batch validation with configurable error policies
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, TypeVar

T = TypeVar("T")


# =============================================================================
# Validation Errors
# =============================================================================


class ValidationSeverity(Enum):
    """Severity level for validation issues."""
    ERROR = "error"      # Must be fixed, blocks processing
    WARNING = "warning"  # Should be fixed, allows processing
    INFO = "info"        # Informational, no action needed


@dataclass
class ValidationIssue:
    """A single validation issue."""
    message: str
    severity: ValidationSeverity = ValidationSeverity.ERROR
    field: str | None = None
    value: Any = None
    rule: str | None = None
    suggestion: str | None = None

    def __str__(self) -> str:
        parts = [f"[{self.severity.value.upper()}]"]
        if self.field:
            parts.append(f"Field '{self.field}':")
        parts.append(self.message)
        if self.suggestion:
            parts.append(f"(Suggestion: {self.suggestion})")
        return " ".join(parts)


@dataclass
class ValidationResult:
    """Result of validation operations."""
    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    validated_data: dict[str, Any] | None = None

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.WARNING]

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        """Merge another result into this one."""
        return ValidationResult(
            valid=self.valid and other.valid,
            issues=self.issues + other.issues,
            validated_data=other.validated_data if other.validated_data else self.validated_data,
        )


# =============================================================================
# Schema Definitions
# =============================================================================


@dataclass
class FieldSchema:
    """Schema definition for a single field."""
    name: str
    types: tuple[type, ...] | type
    required: bool = False
    nullable: bool = False
    allowed_values: list[Any] | None = None
    min_value: float | None = None
    max_value: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None
    custom_validator: Callable[[Any], bool] | None = None

    def validate(self, value: Any, path: str = "") -> list[ValidationIssue]:
        """Validate a value against this field schema."""
        issues = []
        full_path = f"{path}.{self.name}" if path else self.name

        # Handle None values
        if value is None:
            if not self.nullable and self.required:
                issues.append(ValidationIssue(
                    message=f"Field cannot be null",
                    field=full_path,
                    rule="nullable",
                ))
            return issues

        # Type check
        expected_types = self.types if isinstance(self.types, tuple) else (self.types,)
        if not isinstance(value, expected_types):
            type_names = ", ".join(t.__name__ for t in expected_types)
            issues.append(ValidationIssue(
                message=f"Expected type {type_names}, got {type(value).__name__}",
                field=full_path,
                value=value,
                rule="type",
                suggestion=f"Convert to {expected_types[0].__name__}",
            ))
            return issues  # Skip further checks if type is wrong

        # Allowed values
        if self.allowed_values is not None and value not in self.allowed_values:
            issues.append(ValidationIssue(
                message=f"Value '{value}' not in allowed values: {self.allowed_values}",
                field=full_path,
                value=value,
                rule="allowed_values",
            ))

        # Numeric range
        if isinstance(value, (int, float)):
            if self.min_value is not None and value < self.min_value:
                issues.append(ValidationIssue(
                    message=f"Value {value} is below minimum {self.min_value}",
                    field=full_path,
                    value=value,
                    rule="min_value",
                ))
            if self.max_value is not None and value > self.max_value:
                issues.append(ValidationIssue(
                    message=f"Value {value} exceeds maximum {self.max_value}",
                    field=full_path,
                    value=value,
                    rule="max_value",
                ))

        # String length
        if isinstance(value, str):
            if self.min_length is not None and len(value) < self.min_length:
                issues.append(ValidationIssue(
                    message=f"String length {len(value)} is below minimum {self.min_length}",
                    field=full_path,
                    value=value,
                    rule="min_length",
                ))
            if self.max_length is not None and len(value) > self.max_length:
                issues.append(ValidationIssue(
                    message=f"String length {len(value)} exceeds maximum {self.max_length}",
                    field=full_path,
                    value=value,
                    rule="max_length",
                ))
            if self.pattern is not None and not re.match(self.pattern, value):
                issues.append(ValidationIssue(
                    message=f"String does not match pattern '{self.pattern}'",
                    field=full_path,
                    value=value,
                    rule="pattern",
                ))

        # Custom validator
        if self.custom_validator is not None:
            try:
                if not self.custom_validator(value):
                    issues.append(ValidationIssue(
                        message="Custom validation failed",
                        field=full_path,
                        value=value,
                        rule="custom",
                    ))
            except Exception as e:
                issues.append(ValidationIssue(
                    message=f"Custom validator raised exception: {e}",
                    field=full_path,
                    value=value,
                    rule="custom",
                    severity=ValidationSeverity.WARNING,
                ))

        return issues


@dataclass
class Schema:
    """Complete schema for validating records."""
    name: str
    fields: list[FieldSchema] = field(default_factory=list)
    allow_extra_fields: bool = True
    extra_validators: list[Callable[[dict[str, Any]], list[ValidationIssue]]] = field(
        default_factory=list
    )

    def add_field(self, field_schema: FieldSchema) -> "Schema":
        """Add a field to the schema."""
        self.fields.append(field_schema)
        return self

    def add_validator(
        self, validator: Callable[[dict[str, Any]], list[ValidationIssue]]
    ) -> "Schema":
        """Add a custom validator."""
        self.extra_validators.append(validator)
        return self

    def validate(self, data: dict[str, Any], path: str = "") -> ValidationResult:
        """Validate data against this schema."""
        issues = []
        field_names = {f.name for f in self.fields}

        # Check required fields
        for field_schema in self.fields:
            if field_schema.required and field_schema.name not in data:
                issues.append(ValidationIssue(
                    message=f"Missing required field",
                    field=f"{path}.{field_schema.name}" if path else field_schema.name,
                    rule="required",
                ))

        # Validate each field
        for field_schema in self.fields:
            if field_schema.name in data:
                issues.extend(field_schema.validate(data[field_schema.name], path))

        # Check for extra fields
        if not self.allow_extra_fields:
            extra = set(data.keys()) - field_names
            for extra_field in extra:
                issues.append(ValidationIssue(
                    message=f"Unexpected field '{extra_field}'",
                    field=f"{path}.{extra_field}" if path else extra_field,
                    rule="extra_field",
                    severity=ValidationSeverity.WARNING,
                ))

        # Run extra validators
        for validator in self.extra_validators:
            try:
                issues.extend(validator(data))
            except Exception as e:
                issues.append(ValidationIssue(
                    message=f"Extra validator raised exception: {e}",
                    rule="extra_validator",
                    severity=ValidationSeverity.WARNING,
                ))

        has_errors = any(i.severity == ValidationSeverity.ERROR for i in issues)
        return ValidationResult(
            valid=not has_errors,
            issues=issues,
            validated_data=data if not has_errors else None,
        )


# =============================================================================
# Pre-defined Schemas
# =============================================================================


def is_iso_timestamp(value: str) -> bool:
    """Check if string is a valid ISO 8601 timestamp."""
    try:
        value = value.replace("Z", "+00:00")
        datetime.fromisoformat(value)
        return True
    except (ValueError, AttributeError):
        return False


def is_uuid(value: str) -> bool:
    """Check if string is a valid UUID format."""
    uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    return bool(re.match(uuid_pattern, value.lower()))


BENCHMARK_RESULT_SCHEMA = Schema(
    name="benchmark_result",
    fields=[
        FieldSchema(
            name="feature",
            types=str,
            required=True,
            allowed_values=[
                "remember_recall",
                "multi_agent",
                "semantic_search",
                "token_aware",
                "delta_sync",
                "discovery",
            ],
        ),
        FieldSchema(
            name="scale",
            types=str,
            required=True,
            allowed_values=["small", "medium", "large"],
        ),
        FieldSchema(
            name="operation",
            types=str,
            required=True,
            min_length=1,
            max_length=100,
        ),
        FieldSchema(
            name="duration_ms",
            types=(int, float),
            required=True,
            min_value=0,
        ),
        FieldSchema(
            name="success",
            types=bool,
            required=True,
        ),
        FieldSchema(
            name="items",
            types=int,
            required=False,
            min_value=0,
        ),
        FieldSchema(
            name="tokens_used",
            types=int,
            required=False,
            min_value=0,
        ),
        FieldSchema(
            name="details",
            types=(dict, type(None)),
            required=False,
            nullable=True,
        ),
    ],
)


RUN_RESULT_SCHEMA = Schema(
    name="run_result",
    fields=[
        FieldSchema(
            name="run_id",
            types=str,
            required=True,
            min_length=1,
        ),
        FieldSchema(
            name="scenario_id",
            types=str,
            required=True,
            min_length=1,
        ),
        FieldSchema(
            name="category",
            types=str,
            required=False,
        ),
        FieldSchema(
            name="start_time",
            types=str,
            required=True,
            custom_validator=is_iso_timestamp,
        ),
        FieldSchema(
            name="end_time",
            types=str,
            required=True,
            custom_validator=is_iso_timestamp,
        ),
        FieldSchema(
            name="config",
            types=dict,
            required=False,
        ),
        FieldSchema(
            name="events",
            types=list,
            required=False,
        ),
        FieldSchema(
            name="result",
            types=dict,
            required=True,
        ),
    ],
)


CORE_BENCHMARK_SCHEMA = Schema(
    name="core_benchmark",
    fields=[
        FieldSchema(
            name="timestamp",
            types=str,
            required=True,
            custom_validator=is_iso_timestamp,
        ),
        FieldSchema(
            name="scales",
            types=dict,
            required=False,
        ),
        FieldSchema(
            name="results",
            types=list,
            required=True,
        ),
    ],
)


# =============================================================================
# Validator Class
# =============================================================================


class DataValidator:
    """
    Main validator class for benchmark data.

    Usage:
        validator = DataValidator()
        result = validator.validate_benchmark_result(record)
        if result.valid:
            print("Valid!")
        else:
            for issue in result.errors:
                print(issue)
    """

    def __init__(self):
        self._schemas: dict[str, Schema] = {
            "benchmark_result": BENCHMARK_RESULT_SCHEMA,
            "run_result": RUN_RESULT_SCHEMA,
            "core_benchmark": CORE_BENCHMARK_SCHEMA,
        }

    def register_schema(self, schema: Schema) -> None:
        """Register a custom schema."""
        self._schemas[schema.name] = schema

    def get_schema(self, name: str) -> Schema | None:
        """Get a schema by name."""
        return self._schemas.get(name)

    def validate(self, data: dict[str, Any], schema_name: str) -> ValidationResult:
        """Validate data against a named schema."""
        schema = self._schemas.get(schema_name)
        if not schema:
            return ValidationResult(
                valid=False,
                issues=[ValidationIssue(
                    message=f"Unknown schema: {schema_name}",
                    rule="schema_lookup",
                )],
            )
        return schema.validate(data)

    def validate_benchmark_result(self, data: dict[str, Any]) -> ValidationResult:
        """Validate a single benchmark result."""
        return self.validate(data, "benchmark_result")

    def validate_run_result(self, data: dict[str, Any]) -> ValidationResult:
        """Validate a run result record."""
        return self.validate(data, "run_result")

    def validate_core_benchmark(self, data: dict[str, Any]) -> ValidationResult:
        """Validate a core benchmark file."""
        result = self.validate(data, "core_benchmark")

        # Also validate nested results
        if "results" in data and isinstance(data["results"], list):
            for i, record in enumerate(data["results"]):
                nested_result = self.validate_benchmark_result(record)
                for issue in nested_result.issues:
                    issue.field = f"results[{i}].{issue.field}" if issue.field else f"results[{i}]"
                result = result.merge(nested_result)

        return result

    def validate_batch(
        self,
        records: list[dict[str, Any]],
        schema_name: str
    ) -> tuple[list[ValidationResult], dict[str, Any]]:
        """
        Validate a batch of records.

        Returns:
            Tuple of (list of results, summary stats)
        """
        results = []
        valid_count = 0
        invalid_count = 0
        total_issues = 0

        for record in records:
            result = self.validate(record, schema_name)
            results.append(result)
            if result.valid:
                valid_count += 1
            else:
                invalid_count += 1
            total_issues += len(result.issues)

        summary = {
            "total": len(records),
            "valid": valid_count,
            "invalid": invalid_count,
            "total_issues": total_issues,
            "validation_rate": valid_count / len(records) if records else 0,
        }

        return results, summary


# =============================================================================
# Validation Helpers
# =============================================================================


def validate_json_structure(data: Any, expected_type: type = dict) -> ValidationResult:
    """Validate that data has the expected JSON structure."""
    if not isinstance(data, expected_type):
        return ValidationResult(
            valid=False,
            issues=[ValidationIssue(
                message=f"Expected {expected_type.__name__}, got {type(data).__name__}",
                rule="structure",
            )],
        )
    return ValidationResult(valid=True)


def validate_non_empty(data: dict[str, Any], fields: list[str]) -> list[ValidationIssue]:
    """Validate that specified fields are non-empty."""
    issues = []
    for field_name in fields:
        value = data.get(field_name)
        if value is not None and not value:  # Empty string, list, dict, etc.
            issues.append(ValidationIssue(
                message=f"Field cannot be empty",
                field=field_name,
                value=value,
                rule="non_empty",
            ))
    return issues


def validate_cross_field(
    data: dict[str, Any],
    field1: str,
    field2: str,
    comparator: Callable[[Any, Any], bool],
    error_message: str,
) -> list[ValidationIssue]:
    """Validate a relationship between two fields."""
    if field1 in data and field2 in data:
        if not comparator(data[field1], data[field2]):
            return [ValidationIssue(
                message=error_message,
                rule="cross_field",
            )]
    return []


def validate_numeric_range(
    value: int | float,
    min_val: float | None = None,
    max_val: float | None = None,
    field_name: str = "value",
) -> list[ValidationIssue]:
    """Validate that a numeric value is within a specified range."""
    issues = []
    if min_val is not None and value < min_val:
        issues.append(ValidationIssue(
            message=f"Value {value} is below minimum {min_val}",
            field=field_name,
            value=value,
            rule="range",
        ))
    if max_val is not None and value > max_val:
        issues.append(ValidationIssue(
            message=f"Value {value} exceeds maximum {max_val}",
            field=field_name,
            value=value,
            rule="range",
        ))
    return issues


def validate_string_format(
    value: str,
    pattern: str,
    field_name: str = "value",
    format_name: str = "pattern",
) -> list[ValidationIssue]:
    """Validate that a string matches a specific format pattern."""
    if not re.match(pattern, value):
        return [ValidationIssue(
            message=f"Value does not match expected {format_name} format",
            field=field_name,
            value=value,
            rule="format",
            suggestion=f"Value should match pattern: {pattern}",
        )]
    return []


def validate_list_items(
    items: list[Any],
    item_validator: Callable[[Any, int], list[ValidationIssue]],
    field_name: str = "items",
) -> list[ValidationIssue]:
    """Validate each item in a list using a custom validator."""
    issues = []
    for i, item in enumerate(items):
        item_issues = item_validator(item, i)
        for issue in item_issues:
            issue.field = f"{field_name}[{i}].{issue.field}" if issue.field else f"{field_name}[{i}]"
        issues.extend(item_issues)
    return issues


def validate_consistency(
    data: dict[str, Any],
    rules: list[tuple[str, Callable[[dict[str, Any]], bool], str]],
) -> list[ValidationIssue]:
    """
    Validate data consistency using multiple rules.

    Args:
        data: The data to validate
        rules: List of (rule_name, check_function, error_message) tuples

    Returns:
        List of validation issues for failed rules
    """
    issues = []
    for rule_name, check_fn, error_msg in rules:
        try:
            if not check_fn(data):
                issues.append(ValidationIssue(
                    message=error_msg,
                    rule=rule_name,
                    severity=ValidationSeverity.WARNING,
                ))
        except Exception as e:
            issues.append(ValidationIssue(
                message=f"Consistency check '{rule_name}' failed: {e}",
                rule=rule_name,
                severity=ValidationSeverity.WARNING,
            ))
    return issues


def create_benchmark_consistency_validator() -> Callable[[dict[str, Any]], list[ValidationIssue]]:
    """Create a validator for benchmark result consistency checks."""
    def validator(data: dict[str, Any]) -> list[ValidationIssue]:
        rules = [
            (
                "success_items_consistency",
                lambda d: d.get("success", True) or d.get("items", 0) == 0,
                "Failed operations should have 0 items processed",
            ),
            (
                "duration_positive",
                lambda d: d.get("duration_ms", 0) >= 0,
                "Duration cannot be negative",
            ),
            (
                "tokens_reasonable",
                lambda d: d.get("tokens_used", 0) <= 1_000_000,
                "Token usage seems unreasonably high (>1M)",
            ),
            (
                "throughput_reasonable",
                lambda d: (d.get("duration_ms", 1) == 0 or
                          d.get("items", 0) / (d.get("duration_ms", 1) / 1000) <= 100_000),
                "Throughput seems unreasonably high (>100K items/sec)",
            ),
        ]
        return validate_consistency(data, rules)
    return validator
