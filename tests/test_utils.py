"""Tests for arducharts.utils — pure functions and constants."""

from __future__ import annotations

import math
from arducharts.utils import (
    DEFAULT_BAUD,
    PDEF_URL,
    SENSOR_BITS,
    compute_param_diff,
    norm_value,
    parse_version,
    version_less_than,
)


# -- norm_value --


class TestNormValue:
    def test_bool_true_becomes_1(self):
        assert norm_value(True) == 1
        assert isinstance(norm_value(True), int)

    def test_bool_false_becomes_0(self):
        assert norm_value(False) == 0
        assert isinstance(norm_value(False), int)

    def test_whole_float_becomes_int(self):
        result = norm_value(3.0)
        assert result == 3
        assert isinstance(result, int)

    def test_fractional_float_stays_float(self):
        assert norm_value(3.14) == 3.14

    def test_int_passthrough(self):
        assert norm_value(42) == 42
        assert isinstance(norm_value(42), int)

    def test_string_passthrough(self):
        assert norm_value("hello") == "hello"

    def test_nan_stays_float(self):
        result = norm_value(float("nan"))
        assert isinstance(result, float)
        assert math.isnan(result)

    def test_inf_stays_float(self):
        assert norm_value(float("inf")) == float("inf")

    def test_negative_whole_float(self):
        result = norm_value(-5.0)
        assert result == -5
        assert isinstance(result, int)

    def test_zero_float(self):
        result = norm_value(0.0)
        assert result == 0
        assert isinstance(result, int)

    def test_none_passthrough(self):
        assert norm_value(None) is None


# -- parse_version --


class TestParseVersion:
    def test_simple_version(self):
        assert parse_version("4.5.2") == (4, 5, 2)

    def test_rc_version(self):
        # "rc1" is split as one token — not purely digits, so filtered out
        assert parse_version("4.5.2-rc1") == (4, 5, 2)

    def test_single_digit(self):
        assert parse_version("4") == (4,)

    def test_whitespace_stripped(self):
        assert parse_version("  4.5.2  ") == (4, 5, 2)


# -- version_less_than --


class TestVersionLessThan:
    def test_clearly_less(self):
        assert version_less_than("4.4.0", "4.5.0") is True

    def test_clearly_greater(self):
        assert version_less_than("4.6.0", "4.5.0") is False

    def test_equal_versions(self):
        assert version_less_than("4.5.2", "4.5.2") is False

    def test_different_lengths_less(self):
        assert version_less_than("4.5", "4.5.1") is True

    def test_different_lengths_greater(self):
        assert version_less_than("4.5.1", "4.5") is False


# -- compute_param_diff --


class TestComputeParamDiff:
    def test_all_matching(self):
        d = {"A": 1, "B": 2}
        c = {"A": 1, "B": 2}
        changes, missing, matching = compute_param_diff(d, c)
        assert not changes
        assert not missing
        assert matching == 2

    def test_one_change(self):
        changes, missing, matching = compute_param_diff({"A": 1}, {"A": 2})
        assert len(changes) == 1
        assert changes[0] == ("A", 2, 1)
        assert not missing
        assert matching == 0

    def test_missing_param(self):
        changes, missing, _matching = compute_param_diff({"A": 1}, {})
        assert not changes
        assert len(missing) == 1
        assert missing[0] == ("A", 1)

    def test_mixed_scenario(self):
        desired = {"A": 1, "B": 5, "C": 3}
        current = {"A": 1, "B": 2}
        changes, missing, matching = compute_param_diff(desired, current)
        assert matching == 1
        assert len(changes) == 1
        assert changes[0][0] == "B"
        assert len(missing) == 1
        assert missing[0][0] == "C"

    def test_normalization_applied(self):
        # 3.0 (float) vs 3 (int) should match after normalization
        changes, _missing, matching = compute_param_diff({"A": 3.0}, {"A": 3})
        assert matching == 1
        assert not changes

    def test_empty_dicts(self):
        changes, missing, matching = compute_param_diff({}, {})
        assert not changes
        assert not missing
        assert matching == 0


# -- Constants --


class TestConstants:
    def test_default_baud(self):
        assert DEFAULT_BAUD == 115200

    def test_pdef_url_is_https(self):
        assert PDEF_URL.startswith("https://")

    def test_sensor_bits_values_are_strings(self):
        for bit, name in SENSOR_BITS.items():
            assert isinstance(bit, int)
            assert isinstance(name, str)
