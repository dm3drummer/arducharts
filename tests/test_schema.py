"""Tests for arducharts.schema — ParamSchema loading, search, describe, validate."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from arducharts.schema import ParamSchema


# -- Loading from flat cache --


class TestParamSchemaFromFlatCache:
    def test_get_existing_param(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        defn = schema.get("ARSPD_TYPE")
        assert defn is not None
        assert defn["DisplayName"] == "Airspeed Type"

    def test_get_nonexistent_param(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        assert schema.get("NONEXISTENT") is None

    def test_exists_true(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        assert schema.exists("ARSPD_TYPE") is True

    def test_exists_false(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        assert schema.exists("NOPE") is False

    def test_count(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        # 2 ARSPD + 2 BATT + 1 SIM + 1 INS = 6 params in flat cache
        assert schema.count == 6


# -- Search --


class TestParamSchemaSearch:
    def test_search_by_name(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        results = schema.search("ARSPD")
        names = [name for name, _ in results]
        assert "ARSPD_TYPE" in names
        assert "ARSPD_USE" in names

    def test_search_by_description(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        results = schema.search("airspeed")
        names = [name for name, _ in results]
        assert "ARSPD_TYPE" in names

    def test_search_no_results(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        assert not schema.search("zzzzzzz")

    def test_search_case_insensitive(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        assert len(schema.search("BATTERY")) > 0
        assert len(schema.search("battery")) > 0

    def test_search_results_sorted(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        results = schema.search("BATT")
        names = [name for name, _ in results]
        assert names == sorted(names)


# -- Describe --


class TestParamSchemaDescribe:
    def test_describe_full_param(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        text = schema.describe("BATT_MONITOR")
        assert text is not None
        assert "BATT_MONITOR" in text
        assert "Battery Monitor" in text
        assert "Units: V" in text
        assert "Range: 0..50" in text
        assert "Increment: 1" in text
        assert "Reboot required" in text

    def test_describe_param_with_values(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        text = schema.describe("ARSPD_TYPE")
        assert text is not None
        assert "Values:" in text
        assert "0=None" in text
        assert "2=MS4525" in text

    def test_describe_unknown_param(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        assert schema.describe("NOPE") is None


# -- Validation --


class TestParamSchemaValidation:
    def test_valid_params_no_errors(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        errors, _warnings = schema.validate_params({"ARSPD_TYPE": 1})
        assert not errors

    def test_out_of_range_produces_error(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        errors, _warnings = schema.validate_params({"ARSPD_TYPE": 999})
        assert len(errors) == 1
        assert "out of range" in errors[0]

    def test_unknown_param_produces_warning(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        _errors, warnings = schema.validate_params({"UNKNOWN_XYZ": 5})
        assert any("Unknown param" in w for w in warnings)

    def test_invalid_enum_produces_warning(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        # Value 50 is in range [0..100] but not in the Values enum
        errors, warnings = schema.validate_params({"ARSPD_TYPE": 50})
        assert not errors
        assert any("not in" in w for w in warnings)

    def test_zero_value_skips_range_check(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        # BATT_MONITOR has range [0..50], value 0 should not error
        errors, _ = schema.validate_params({"BATT_MONITOR": 0})
        assert not errors

    def test_dynamic_prefix_skipped(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        _, warnings = schema.validate_params({"SR0_EXTRA1": 5})
        assert not any("SR0_EXTRA1" in w for w in warnings)

    def test_known_deprecated_skipped(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        _, warnings = schema.validate_params({"ARMING_CHECK": 1})
        assert not any("ARMING_CHECK" in w for w in warnings)

    def test_empty_defs_skips_validation(self, tmp_path: Path):
        # No cache at all — _defs will be empty after failed download
        schema = ParamSchema(tmp_path)
        schema._defs = {}
        errors, warnings = schema.validate_params({"ANYTHING": 1})
        assert not errors
        assert len(warnings) == 1
        assert "not available" in warnings[0]


# -- Download --


class TestParamSchemaDownload:
    def test_download_success(self, tmp_path: Path):
        from tests.conftest import MINI_PDEF

        schema = ParamSchema(tmp_path)
        fake_response_data = json.dumps(MINI_PDEF).encode("utf-8")

        class FakeResponse:
            def read(self):
                return fake_response_data
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            schema._download()

        assert schema.cache_path.exists()
        assert schema._flat_cache.exists()
        assert schema._defs is not None
        assert len(schema._defs) > 0

    def test_download_failure_sets_empty_defs(self, tmp_path: Path):
        schema = ParamSchema(tmp_path)

        with patch("urllib.request.urlopen", side_effect=Exception("network error")):
            schema._download()

        assert schema._defs == {}

    def test_refresh_redownloads(self, pdef_cache_dir: Path):
        schema = ParamSchema(pdef_cache_dir)
        # Prime the cache
        schema._ensure_loaded()
        original_count = schema.count

        from tests.conftest import MINI_PDEF
        fake_data = json.dumps(MINI_PDEF).encode("utf-8")

        class FakeResponse:
            def read(self):
                return fake_data
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            schema.refresh()

        assert schema.count == original_count


# -- Flatten from raw cache --


class TestParamSchemaFlatten:
    def test_flatten_creates_flat_cache(self, tmp_path: Path):
        from tests.conftest import MINI_PDEF

        cache_dir = tmp_path / ".cache"
        cache_dir.mkdir()
        (cache_dir / "apm.pdef.json").write_text(json.dumps(MINI_PDEF))
        # No flat cache — force flatten

        schema = ParamSchema(tmp_path)
        schema._ensure_loaded()

        assert (cache_dir / "apm.pdef.flat.json").exists()
        assert schema._defs is not None
        assert "ARSPD_TYPE" in schema._defs
