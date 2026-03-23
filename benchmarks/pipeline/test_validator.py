"""
Comprehensive tests for the data validation module.

Tests cover:
- Schema validation (required fields, types, allowed values)
- Field-level validation (range, length, pattern, custom validators)
- Batch validation and error aggregation
- Edge cases and error handling
"""

import pytest
from datetime import datetime
from typing import Any

from .validator import (
    DataValidator,
    FieldSchema,
    Schema,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
    BENCHMARK_RESULT_SCHEMA,
    RUN_RESULT_SCHEMA,
    CORE_BENCHMARK_SCHEMA,
    is_iso_timestamp,
    is_uuid,
    validate_json_structure,
    validate_non_empty,
    validate_cross_field,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def valid_benchmark_result() -> dict[str, Any]:
    """A valid benchmark result record."""
    return {
        "feature": "remember_recall",
        "scale": "small",
        "operation": "write_all",
        "duration_ms": 766.99,
        "success": True,
        "items": 10,
        "tokens_used": 150,
        "details": {"avg_ms": 76.7, "total_writes": 10},
    }


@pytest.fixture
def valid_run_result() -> dict[str, Any]:
    """A valid run result record."""
    return {
        "run_id": "run-001",
        "scenario_id": "sc-benchmark-01",
        "category": "performance",
        "start_time": "2026-03-23T10:00:00+00:00",
        "end_time": "2026-03-23T10:05:00+00:00",
        "config": {"timeout": 300},
        "events": [],
        "result": {"success": True, "metrics": {}},
    }


@pytest.fixture
def valid_core_benchmark() -> dict[str, Any]:
    """A valid core benchmark record."""
    return {
        "timestamp": "2026-03-23T14:16:36+00:00",
        "scales": {"small": 10, "medium": 100, "large": 500},
        "results": [
            {
                "feature": "remember_recall",
                "scale": "small",
                "operation": "write_all",
                "duration_ms": 766.99,
                "success": True,
            },
            {
                "feature": "multi_agent",
                "scale": "medium",
                "operation": "coordinate",
                "duration_ms": 1500.0,
                "success": True,
            },
        ],
    }


@pytest.fixture
def validator() -> DataValidator:
    """A DataValidator instance."""
    return DataValidator()


# =============================================================================
# Test ValidationIssue
# =============================================================================


class TestValidationIssue:
    def test_str_representation(self):
        issue = ValidationIssue(
            message="Field cannot be null",
            severity=ValidationSeverity.ERROR,
            field="feature",
            rule="nullable",
        )
        result = str(issue)
        assert "[ERROR]" in result
        assert "Field 'feature'" in result
        assert "Field cannot be null" in result

    def test_str_with_suggestion(self):
        issue = ValidationIssue(
            message="Invalid type",
            field="duration_ms",
            suggestion="Convert to float",
        )
        result = str(issue)
        assert "Suggestion: Convert to float" in result

    def test_warning_severity(self):
        issue = ValidationIssue(
            message="Unexpected field",
            severity=ValidationSeverity.WARNING,
        )
        assert "[WARNING]" in str(issue)


# =============================================================================
# Test ValidationResult
# =============================================================================


class TestValidationResult:
    def test_valid_result(self):
        result = ValidationResult(valid=True, validated_data={"key": "value"})
        assert result.valid
        assert result.errors == []
        assert result.warnings == []

    def test_invalid_result_with_errors(self):
        issues = [
            ValidationIssue("Error 1", ValidationSeverity.ERROR),
            ValidationIssue("Warning 1", ValidationSeverity.WARNING),
            ValidationIssue("Error 2", ValidationSeverity.ERROR),
        ]
        result = ValidationResult(valid=False, issues=issues)
        assert not result.valid
        assert len(result.errors) == 2
        assert len(result.warnings) == 1

    def test_merge_results(self):
        result1 = ValidationResult(
            valid=True,
            issues=[ValidationIssue("Warning", ValidationSeverity.WARNING)],
        )
        result2 = ValidationResult(
            valid=False,
            issues=[ValidationIssue("Error", ValidationSeverity.ERROR)],
            validated_data={"key": "value"},
        )
        merged = result1.merge(result2)
        assert not merged.valid
        assert len(merged.issues) == 2
        assert merged.validated_data == {"key": "value"}


# =============================================================================
# Test FieldSchema Validation
# =============================================================================


class TestFieldSchema:
    def test_required_field_missing(self):
        schema = FieldSchema(name="feature", types=str, required=True)
        # Note: required check is at Schema level, not FieldSchema.validate
        issues = schema.validate(None)
        assert len(issues) == 1
        assert "null" in issues[0].message.lower()

    def test_type_check_single_type(self):
        schema = FieldSchema(name="count", types=int, required=True)
        # Valid
        assert schema.validate(42) == []
        # Invalid
        issues = schema.validate("not_an_int")
        assert len(issues) == 1
        assert "type" in issues[0].rule

    def test_type_check_union_types(self):
        schema = FieldSchema(name="duration", types=(int, float), required=True)
        assert schema.validate(42) == []
        assert schema.validate(42.5) == []
        issues = schema.validate("not_a_number")
        assert len(issues) == 1

    def test_allowed_values(self):
        schema = FieldSchema(
            name="scale",
            types=str,
            allowed_values=["small", "medium", "large"],
        )
        assert schema.validate("small") == []
        issues = schema.validate("extra_large")
        assert len(issues) == 1
        assert "allowed values" in issues[0].message

    def test_min_max_value(self):
        schema = FieldSchema(
            name="duration_ms",
            types=(int, float),
            min_value=0,
            max_value=60000,
        )
        assert schema.validate(1000) == []
        assert schema.validate(0) == []
        assert schema.validate(60000) == []

        issues = schema.validate(-1)
        assert len(issues) == 1
        assert "below minimum" in issues[0].message

        issues = schema.validate(70000)
        assert len(issues) == 1
        assert "exceeds maximum" in issues[0].message

    def test_string_length(self):
        schema = FieldSchema(
            name="operation",
            types=str,
            min_length=1,
            max_length=100,
        )
        assert schema.validate("write") == []

        issues = schema.validate("")
        assert len(issues) == 1
        assert "below minimum" in issues[0].message

        issues = schema.validate("x" * 150)
        assert len(issues) == 1
        assert "exceeds maximum" in issues[0].message

    def test_pattern_validation(self):
        schema = FieldSchema(
            name="run_id",
            types=str,
            pattern=r"^run-\d{3}$",
        )
        assert schema.validate("run-001") == []
        issues = schema.validate("invalid-id")
        assert len(issues) == 1
        assert "pattern" in issues[0].rule

    def test_custom_validator(self):
        def is_positive(value: int) -> bool:
            return value > 0

        schema = FieldSchema(
            name="items",
            types=int,
            custom_validator=is_positive,
        )
        assert schema.validate(10) == []
        issues = schema.validate(0)
        assert len(issues) == 1
        assert "custom" in issues[0].rule

    def test_custom_validator_exception(self):
        def bad_validator(value: Any) -> bool:
            raise ValueError("Validator crashed")

        schema = FieldSchema(
            name="field",
            types=str,
            custom_validator=bad_validator,
        )
        issues = schema.validate("test")
        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.WARNING
        assert "exception" in issues[0].message.lower()

    def test_nullable_field(self):
        schema = FieldSchema(name="details", types=dict, nullable=True)
        assert schema.validate(None) == []
        assert schema.validate({"key": "value"}) == []


# =============================================================================
# Test Schema Validation
# =============================================================================


class TestSchema:
    def test_missing_required_field(self):
        schema = Schema(
            name="test",
            fields=[
                FieldSchema(name="required_field", types=str, required=True),
                FieldSchema(name="optional_field", types=str, required=False),
            ],
        )
        result = schema.validate({"optional_field": "value"})
        assert not result.valid
        assert any("required_field" in str(i) for i in result.issues)

    def test_extra_fields_allowed(self):
        schema = Schema(
            name="test",
            fields=[FieldSchema(name="known", types=str)],
            allow_extra_fields=True,
        )
        result = schema.validate({"known": "value", "unknown": "extra"})
        assert result.valid

    def test_extra_fields_not_allowed(self):
        schema = Schema(
            name="test",
            fields=[FieldSchema(name="known", types=str)],
            allow_extra_fields=False,
        )
        result = schema.validate({"known": "value", "unknown": "extra"})
        # Extra fields generate warnings, not errors by default
        assert len(result.warnings) == 1
        assert "unexpected" in result.warnings[0].message.lower()

    def test_extra_validators(self):
        def check_consistency(data: dict) -> list[ValidationIssue]:
            if data.get("success") is False and data.get("items", 0) > 0:
                return [
                    ValidationIssue(
                        message="Failed operation should have 0 items",
                        severity=ValidationSeverity.WARNING,
                    )
                ]
            return []

        schema = Schema(
            name="test",
            fields=[
                FieldSchema(name="success", types=bool),
                FieldSchema(name="items", types=int),
            ],
        )
        schema.add_validator(check_consistency)

        result = schema.validate({"success": False, "items": 10})
        assert len(result.warnings) == 1

    def test_add_field_chaining(self):
        schema = Schema(name="test")
        result = schema.add_field(FieldSchema(name="f1", types=str))
        assert result is schema
        assert len(schema.fields) == 1


# =============================================================================
# Test Predefined Schemas
# =============================================================================


class TestBenchmarkResultSchema:
    def test_valid_record(self, validator, valid_benchmark_result):
        result = validator.validate_benchmark_result(valid_benchmark_result)
        assert result.valid, f"Errors: {result.errors}"

    def test_missing_required_fields(self, validator):
        result = validator.validate_benchmark_result({})
        assert not result.valid
        error_fields = [e.field for e in result.errors]
        assert "feature" in error_fields
        assert "scale" in error_fields
        assert "operation" in error_fields
        assert "duration_ms" in error_fields
        assert "success" in error_fields

    def test_invalid_feature_value(self, validator, valid_benchmark_result):
        valid_benchmark_result["feature"] = "unknown_feature"
        result = validator.validate_benchmark_result(valid_benchmark_result)
        assert not result.valid
        assert any("allowed values" in str(e) for e in result.errors)

    def test_invalid_scale_value(self, validator, valid_benchmark_result):
        valid_benchmark_result["scale"] = "tiny"
        result = validator.validate_benchmark_result(valid_benchmark_result)
        assert not result.valid

    def test_negative_duration(self, validator, valid_benchmark_result):
        valid_benchmark_result["duration_ms"] = -100
        result = validator.validate_benchmark_result(valid_benchmark_result)
        assert not result.valid
        assert any("below minimum" in str(e) for e in result.errors)

    def test_invalid_type_for_success(self, validator, valid_benchmark_result):
        valid_benchmark_result["success"] = "yes"  # Should be bool
        result = validator.validate_benchmark_result(valid_benchmark_result)
        assert not result.valid

    def test_optional_fields_missing_ok(self, validator):
        minimal = {
            "feature": "remember_recall",
            "scale": "small",
            "operation": "test",
            "duration_ms": 100,
            "success": True,
        }
        result = validator.validate_benchmark_result(minimal)
        assert result.valid


class TestRunResultSchema:
    def test_valid_record(self, validator, valid_run_result):
        result = validator.validate_run_result(valid_run_result)
        assert result.valid, f"Errors: {result.errors}"

    def test_invalid_timestamp(self, validator, valid_run_result):
        valid_run_result["start_time"] = "not-a-timestamp"
        result = validator.validate_run_result(valid_run_result)
        assert not result.valid

    def test_missing_result_field(self, validator, valid_run_result):
        del valid_run_result["result"]
        result = validator.validate_run_result(valid_run_result)
        assert not result.valid


class TestCoreBenchmarkSchema:
    def test_valid_record(self, validator, valid_core_benchmark):
        result = validator.validate_core_benchmark(valid_core_benchmark)
        assert result.valid, f"Errors: {result.errors}"

    def test_validates_nested_results(self, validator, valid_core_benchmark):
        # Add an invalid nested result
        valid_core_benchmark["results"].append(
            {"feature": "invalid", "scale": "huge"}  # Missing required fields
        )
        result = validator.validate_core_benchmark(valid_core_benchmark)
        assert not result.valid
        # Should have errors with proper path prefixes
        assert any("results[2]" in str(e.field) for e in result.errors)


# =============================================================================
# Test DataValidator Class
# =============================================================================


class TestDataValidator:
    def test_register_custom_schema(self, validator):
        custom_schema = Schema(
            name="custom",
            fields=[FieldSchema(name="custom_field", types=str, required=True)],
        )
        validator.register_schema(custom_schema)

        result = validator.validate({"custom_field": "value"}, "custom")
        assert result.valid

    def test_validate_unknown_schema(self, validator):
        result = validator.validate({}, "nonexistent_schema")
        assert not result.valid
        assert "Unknown schema" in result.issues[0].message

    def test_get_schema(self, validator):
        schema = validator.get_schema("benchmark_result")
        assert schema is not None
        assert schema.name == "benchmark_result"

        assert validator.get_schema("nonexistent") is None

    def test_batch_validation(self, validator, valid_benchmark_result):
        records = [
            valid_benchmark_result,
            valid_benchmark_result.copy(),
            {"feature": "invalid"},  # Invalid
        ]
        results, summary = validator.validate_batch(records, "benchmark_result")

        assert len(results) == 3
        assert summary["total"] == 3
        assert summary["valid"] == 2
        assert summary["invalid"] == 1
        assert summary["validation_rate"] == 2 / 3

    def test_batch_validation_empty(self, validator):
        results, summary = validator.validate_batch([], "benchmark_result")
        assert results == []
        assert summary["total"] == 0
        assert summary["validation_rate"] == 0


# =============================================================================
# Test Helper Functions
# =============================================================================


class TestHelperFunctions:
    def test_is_iso_timestamp_valid(self):
        assert is_iso_timestamp("2026-03-23T14:16:36+00:00")
        assert is_iso_timestamp("2026-03-23T14:16:36Z")
        assert is_iso_timestamp("2026-03-23T14:16:36.123456+00:00")
        assert is_iso_timestamp("2026-03-23")

    def test_is_iso_timestamp_invalid(self):
        assert not is_iso_timestamp("not-a-date")
        assert not is_iso_timestamp("23/03/2026")
        assert not is_iso_timestamp("")
        assert not is_iso_timestamp(None)  # type: ignore

    def test_is_uuid_valid(self):
        assert is_uuid("550e8400-e29b-41d4-a716-446655440000")
        assert is_uuid("550E8400-E29B-41D4-A716-446655440000")  # Uppercase

    def test_is_uuid_invalid(self):
        assert not is_uuid("not-a-uuid")
        assert not is_uuid("550e8400-e29b-41d4-a716")  # Too short
        assert not is_uuid("")

    def test_validate_json_structure_dict(self):
        result = validate_json_structure({"key": "value"}, dict)
        assert result.valid

        result = validate_json_structure([1, 2, 3], dict)
        assert not result.valid

    def test_validate_json_structure_list(self):
        result = validate_json_structure([1, 2, 3], list)
        assert result.valid

    def test_validate_non_empty(self):
        data = {"name": "", "items": [], "config": {}}
        issues = validate_non_empty(data, ["name", "items", "config"])
        assert len(issues) == 3

        data = {"name": "test", "items": [1], "config": {"k": "v"}}
        issues = validate_non_empty(data, ["name", "items", "config"])
        assert len(issues) == 0

    def test_validate_cross_field(self):
        data = {"start_time": 100, "end_time": 50}
        issues = validate_cross_field(
            data,
            "start_time",
            "end_time",
            lambda s, e: s < e,
            "end_time must be after start_time",
        )
        assert len(issues) == 1

        data = {"start_time": 100, "end_time": 200}
        issues = validate_cross_field(
            data,
            "start_time",
            "end_time",
            lambda s, e: s < e,
            "end_time must be after start_time",
        )
        assert len(issues) == 0


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestEdgeCases:
    def test_deeply_nested_path(self, validator):
        """Test that nested validation paths are properly constructed."""
        schema = Schema(
            name="outer",
            fields=[FieldSchema(name="inner", types=dict, required=True)],
        )
        validator.register_schema(schema)

        result = validator.validate({"inner": "not_a_dict"}, "outer")
        assert not result.valid

    def test_special_characters_in_field_names(self):
        schema = FieldSchema(name="field-with-dash", types=str)
        assert schema.validate("value") == []

    def test_unicode_values(self, validator, valid_benchmark_result):
        valid_benchmark_result["operation"] = "测试操作"
        result = validator.validate_benchmark_result(valid_benchmark_result)
        assert result.valid

    def test_very_large_numbers(self, validator, valid_benchmark_result):
        valid_benchmark_result["duration_ms"] = 1e15
        valid_benchmark_result["tokens_used"] = 10**12
        result = validator.validate_benchmark_result(valid_benchmark_result)
        assert result.valid

    def test_float_precision(self, validator, valid_benchmark_result):
        valid_benchmark_result["duration_ms"] = 0.0000001
        result = validator.validate_benchmark_result(valid_benchmark_result)
        assert result.valid

    def test_none_in_details(self, validator, valid_benchmark_result):
        valid_benchmark_result["details"] = None
        result = validator.validate_benchmark_result(valid_benchmark_result)
        assert result.valid  # details is nullable


# =============================================================================
# Test Validation Helper Functions (Extended)
# =============================================================================


class TestValidateNumericRange:
    def test_within_range(self):
        from .validator import validate_numeric_range

        issues = validate_numeric_range(50, min_val=0, max_val=100, field_name="count")
        assert len(issues) == 0

    def test_at_boundaries(self):
        from .validator import validate_numeric_range

        assert len(validate_numeric_range(0, min_val=0, max_val=100)) == 0
        assert len(validate_numeric_range(100, min_val=0, max_val=100)) == 0

    def test_below_minimum(self):
        from .validator import validate_numeric_range

        issues = validate_numeric_range(-5, min_val=0, field_name="items")
        assert len(issues) == 1
        assert "below minimum" in issues[0].message
        assert issues[0].field == "items"

    def test_above_maximum(self):
        from .validator import validate_numeric_range

        issues = validate_numeric_range(150, max_val=100, field_name="score")
        assert len(issues) == 1
        assert "exceeds maximum" in issues[0].message

    def test_float_values(self):
        from .validator import validate_numeric_range

        assert len(validate_numeric_range(0.5, min_val=0.0, max_val=1.0)) == 0
        assert len(validate_numeric_range(1.5, min_val=0.0, max_val=1.0)) == 1


class TestValidateStringFormat:
    def test_valid_pattern(self):
        from .validator import validate_string_format

        issues = validate_string_format(
            "run-001", pattern=r"^run-\d{3}$", field_name="run_id", format_name="run ID"
        )
        assert len(issues) == 0

    def test_invalid_pattern(self):
        from .validator import validate_string_format

        issues = validate_string_format(
            "invalid", pattern=r"^run-\d{3}$", field_name="run_id", format_name="run ID"
        )
        assert len(issues) == 1
        assert "run ID format" in issues[0].message
        assert issues[0].suggestion is not None


class TestValidateListItems:
    def test_all_valid_items(self):
        from .validator import validate_list_items, ValidationIssue

        def int_validator(item: Any, idx: int) -> list[ValidationIssue]:
            if not isinstance(item, int):
                return [ValidationIssue(message=f"Expected int, got {type(item).__name__}")]
            return []

        issues = validate_list_items([1, 2, 3], int_validator, field_name="numbers")
        assert len(issues) == 0

    def test_some_invalid_items(self):
        from .validator import validate_list_items, ValidationIssue

        def positive_validator(item: Any, idx: int) -> list[ValidationIssue]:
            if item <= 0:
                return [ValidationIssue(message="Must be positive", field="value")]
            return []

        issues = validate_list_items([1, -2, 3, -4], positive_validator, field_name="nums")
        assert len(issues) == 2
        assert "nums[1]" in issues[0].field
        assert "nums[3]" in issues[1].field


class TestValidateConsistency:
    def test_all_rules_pass(self):
        from .validator import validate_consistency

        data = {"success": True, "items": 10, "duration_ms": 100}
        rules = [
            ("positive_duration", lambda d: d["duration_ms"] > 0, "Duration must be positive"),
            ("has_items_on_success", lambda d: not d["success"] or d["items"] > 0, "Success requires items"),
        ]
        issues = validate_consistency(data, rules)
        assert len(issues) == 0

    def test_rule_fails(self):
        from .validator import validate_consistency, ValidationSeverity

        data = {"success": True, "items": 0}
        rules = [
            ("has_items_on_success", lambda d: not d["success"] or d["items"] > 0, "Success requires items"),
        ]
        issues = validate_consistency(data, rules)
        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.WARNING

    def test_rule_raises_exception(self):
        from .validator import validate_consistency

        data = {}
        rules = [
            ("bad_rule", lambda d: d["nonexistent"]["key"] > 0, "Should handle exception"),
        ]
        issues = validate_consistency(data, rules)
        assert len(issues) == 1
        assert "failed" in issues[0].message.lower()


class TestBenchmarkConsistencyValidator:
    def test_success_items_consistency(self):
        from .validator import create_benchmark_consistency_validator

        validator = create_benchmark_consistency_validator()

        # Valid: success with items
        issues = validator({"success": True, "items": 10, "duration_ms": 100, "tokens_used": 50})
        # This should pass all consistency checks
        assert all("success_items_consistency" not in (i.rule or "") for i in issues if i.rule)

    def test_negative_duration_warning(self):
        from .validator import create_benchmark_consistency_validator

        validator = create_benchmark_consistency_validator()

        # Invalid: negative duration
        issues = validator({"success": True, "items": 10, "duration_ms": -100})
        duration_issues = [i for i in issues if i.rule == "duration_positive"]
        assert len(duration_issues) == 1

    def test_unreasonable_tokens_warning(self):
        from .validator import create_benchmark_consistency_validator

        validator = create_benchmark_consistency_validator()

        # Invalid: too many tokens
        issues = validator({"success": True, "items": 10, "duration_ms": 100, "tokens_used": 2_000_000})
        token_issues = [i for i in issues if i.rule == "tokens_reasonable"]
        assert len(token_issues) == 1


# =============================================================================
# Integration Tests
# =============================================================================


class TestValidatorIntegration:
    """Integration tests for validator with real data structures."""

    def test_validate_actual_benchmark_file_structure(self, validator):
        """Test validation against actual benchmark file structure."""
        # Simulates the structure in core_benchmark.json
        data = {
            "timestamp": "2026-03-23T14:16:36.318289+00:00",
            "scales": {"small": 10, "medium": 100, "large": 500},
            "results": [
                {
                    "feature": "remember_recall",
                    "scale": "small",
                    "items": 10,
                    "operation": "write_all",
                    "duration_ms": 766.99,
                    "success": True,
                    "tokens_used": 0,
                    "details": {"avg_ms": 76.7, "total_writes": 10},
                },
                {
                    "feature": "multi_agent",
                    "scale": "medium",
                    "items": 100,
                    "operation": "private_write",
                    "duration_ms": 7995.99,
                    "success": True,
                    "tokens_used": 0,
                    "details": {"agents": 100},
                },
            ],
        }

        result = validator.validate_core_benchmark(data)
        assert result.valid, f"Errors: {[str(e) for e in result.errors]}"

    def test_validate_with_null_details(self, validator):
        """Test that null details field is handled correctly."""
        data = {
            "feature": "delta_sync",
            "scale": "small",
            "items": 10,
            "operation": "full_read",
            "duration_ms": 50.78,
            "success": True,
            "tokens_used": 0,
            "details": None,  # Explicitly null
        }

        result = validator.validate_benchmark_result(data)
        assert result.valid

    def test_validate_all_feature_types(self, validator):
        """Test all allowed feature values."""
        features = [
            "remember_recall",
            "multi_agent",
            "semantic_search",
            "token_aware",
            "delta_sync",
            "discovery",
        ]

        for feature in features:
            data = {
                "feature": feature,
                "scale": "small",
                "operation": "test",
                "duration_ms": 100,
                "success": True,
            }
            result = validator.validate_benchmark_result(data)
            assert result.valid, f"Feature '{feature}' should be valid"

    def test_validate_all_scale_types(self, validator):
        """Test all allowed scale values."""
        for scale in ["small", "medium", "large"]:
            data = {
                "feature": "remember_recall",
                "scale": scale,
                "operation": "test",
                "duration_ms": 100,
                "success": True,
            }
            result = validator.validate_benchmark_result(data)
            assert result.valid, f"Scale '{scale}' should be valid"


# =============================================================================
# Error Aggregation Tests
# =============================================================================


class TestErrorAggregation:
    def test_validation_result_merge_preserves_all_issues(self):
        """Test that merging results preserves all issues."""
        result1 = ValidationResult(
            valid=True,
            issues=[
                ValidationIssue("Warning 1", ValidationSeverity.WARNING),
                ValidationIssue("Info 1", ValidationSeverity.INFO),
            ],
        )
        result2 = ValidationResult(
            valid=False,
            issues=[
                ValidationIssue("Error 1", ValidationSeverity.ERROR),
            ],
        )

        merged = result1.merge(result2)
        assert not merged.valid
        assert len(merged.issues) == 3
        assert len(merged.errors) == 1
        assert len(merged.warnings) == 1

    def test_batch_validation_aggregates_errors_correctly(self, validator):
        """Test batch validation aggregates errors from all records."""
        records = [
            # Valid
            {"feature": "remember_recall", "scale": "small", "operation": "test", "duration_ms": 100, "success": True},
            # Invalid feature
            {"feature": "invalid_feature", "scale": "small", "operation": "test", "duration_ms": 100, "success": True},
            # Missing required field
            {"feature": "remember_recall", "scale": "small", "operation": "test", "success": True},
            # Invalid scale
            {"feature": "remember_recall", "scale": "tiny", "operation": "test", "duration_ms": 100, "success": True},
        ]

        results, summary = validator.validate_batch(records, "benchmark_result")

        assert summary["total"] == 4
        assert summary["valid"] == 1
        assert summary["invalid"] == 3
        assert summary["total_issues"] >= 3


# =============================================================================
# Custom Schema Tests
# =============================================================================


class TestCustomSchema:
    def test_create_and_use_custom_schema(self, validator):
        """Test creating and registering a custom schema."""
        from .validator import Schema, FieldSchema

        # Create a custom schema for a new data type
        custom_schema = Schema(
            name="agent_config",
            fields=[
                FieldSchema(name="agent_id", types=str, required=True, pattern=r"^agent-\d+$"),
                FieldSchema(name="model", types=str, required=True),
                FieldSchema(name="temperature", types=float, required=False, min_value=0.0, max_value=2.0),
                FieldSchema(name="max_tokens", types=int, required=False, min_value=1, max_value=100000),
            ],
        )

        validator.register_schema(custom_schema)

        # Valid data
        valid_data = {
            "agent_id": "agent-001",
            "model": "claude-3-opus",
            "temperature": 0.7,
            "max_tokens": 4096,
        }
        result = validator.validate(valid_data, "agent_config")
        assert result.valid

        # Invalid agent_id pattern
        invalid_data = {
            "agent_id": "bad-id",
            "model": "claude-3-opus",
        }
        result = validator.validate(invalid_data, "agent_config")
        assert not result.valid

    def test_schema_with_extra_validator(self, validator):
        """Test schema with custom cross-field validation."""
        from .validator import Schema, FieldSchema, ValidationIssue, ValidationSeverity

        def validate_time_range(data: dict) -> list[ValidationIssue]:
            """Ensure end_time > start_time."""
            if "start_ms" in data and "end_ms" in data:
                if data["end_ms"] <= data["start_ms"]:
                    return [ValidationIssue(
                        message="end_ms must be greater than start_ms",
                        severity=ValidationSeverity.ERROR,
                        rule="time_range",
                    )]
            return []

        schema = Schema(
            name="time_span",
            fields=[
                FieldSchema(name="start_ms", types=(int, float), required=True),
                FieldSchema(name="end_ms", types=(int, float), required=True),
            ],
        )
        schema.add_validator(validate_time_range)

        validator.register_schema(schema)

        # Valid time range
        result = validator.validate({"start_ms": 100, "end_ms": 200}, "time_span")
        assert result.valid

        # Invalid: end before start
        result = validator.validate({"start_ms": 200, "end_ms": 100}, "time_span")
        assert not result.valid
        assert any("time_range" in (i.rule or "") for i in result.issues)


# =============================================================================
# Performance / Stress Tests
# =============================================================================


class TestValidationPerformance:
    def test_batch_validation_large_dataset(self, validator, valid_benchmark_result):
        """Test batch validation handles large datasets."""
        # Create 1000 records
        records = [valid_benchmark_result.copy() for _ in range(1000)]

        results, summary = validator.validate_batch(records, "benchmark_result")

        assert summary["total"] == 1000
        assert summary["valid"] == 1000
        assert summary["validation_rate"] == 1.0

    def test_deeply_nested_details(self, validator, valid_benchmark_result):
        """Test validation handles deeply nested details structures."""
        valid_benchmark_result["details"] = {
            "level1": {
                "level2": {
                    "level3": {
                        "data": [1, 2, 3],
                        "nested_list": [{"a": 1}, {"b": 2}],
                    }
                }
            }
        }

        result = validator.validate_benchmark_result(valid_benchmark_result)
        assert result.valid


# =============================================================================
# Run Tests
# =============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
