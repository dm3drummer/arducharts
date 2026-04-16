"""Integration tests for arducharts.cli — CLI command functions."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
import yaml

from arducharts.cli import (
    cmd_build,
    cmd_create_chart,
    cmd_describe,
    cmd_diff,
    cmd_diff_planes,
    cmd_lint,
    cmd_list,
    cmd_search,
    cmd_show,
    cmd_update_schema,
    cmd_validate,
)


def ns(**kwargs) -> argparse.Namespace:
    """Build an argparse.Namespace with defaults for testing."""
    defaults = {
        "config_dir": "configs",
        "verbose": False,
        "output": None,
        "limit": 50,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# -- cmd_list --


class TestCmdList:
    def test_prints_charts(self, mini_config_dir: Path, capsys):
        cmd_list(ns(config_dir=str(mini_config_dir)))
        out = capsys.readouterr().out
        assert "alpha" in out
        assert "beta" in out

    def test_empty_charts(self, tmp_path: Path, capsys):
        cmd_list(ns(config_dir=str(tmp_path)))
        out = capsys.readouterr().out
        assert "No charts found" in out


# -- cmd_build --


class TestCmdBuild:
    def test_writes_param_file(self, mini_config_dir: Path, capsys):
        cmd_build(ns(
            config_dir=str(mini_config_dir),
            config="planes/test_plane.yaml",
        ))
        out = capsys.readouterr().out
        assert "Written:" in out
        param_file = mini_config_dir / "build" / "test_plane.param"
        assert param_file.exists()

    def test_custom_output(self, mini_config_dir: Path, tmp_path: Path, capsys):  # pylint: disable=unused-argument
        out_path = tmp_path / "custom.param"
        cmd_build(ns(
            config_dir=str(mini_config_dir),
            config="planes/test_plane.yaml",
            output=str(out_path),
        ))
        assert out_path.exists()

    def test_verbose_shows_overrides(self, mini_config_dir: Path, capsys):
        cmd_build(ns(
            config_dir=str(mini_config_dir),
            config="planes/test_plane.yaml",
            verbose=True,
        ))
        out = capsys.readouterr().out
        assert "Install order" in out or "Overrides" in out


# -- cmd_show --


class TestCmdShow:
    def test_prints_params(self, mini_config_dir: Path, capsys):
        cmd_show(ns(
            config_dir=str(mini_config_dir),
            config="planes/test_plane.yaml",
        ))
        out = capsys.readouterr().out
        assert "PARAM_A" in out
        assert "PARAM_B" in out
        assert "PARAM_C" in out
        assert "PARAM_X" in out


# -- cmd_validate --


class TestCmdValidate:
    def test_valid_config(self, mini_config_dir: Path, capsys):
        cmd_validate(ns(
            config_dir=str(mini_config_dir),
            config="planes/test_plane.yaml",
        ))
        out = capsys.readouterr().out
        assert "Config:" in out

    def test_invalid_config_exits(self, mini_config_dir: Path):
        plane_path = mini_config_dir / "planes" / "bad.yaml"
        plane_path.write_text(yaml.dump({
            "name": "Bad", "charts": ["does_not_exist"],
        }))
        with pytest.raises((FileNotFoundError, SystemExit)):
            cmd_validate(ns(
                config_dir=str(mini_config_dir),
                config="planes/bad.yaml",
            ))


# -- cmd_lint --


class TestCmdLint:
    def test_clean_config(self, mini_config_dir: Path, capsys):
        cmd_lint(ns(
            config_dir=str(mini_config_dir),
            config="planes/test_plane.yaml",
        ))
        out = capsys.readouterr().out
        assert "Linting:" in out

    def test_duplicate_param_warning(self, mini_config_dir: Path, capsys):
        # alpha and beta both set PARAM_A — should produce a lint warning
        cmd_lint(ns(
            config_dir=str(mini_config_dir),
            config="planes/test_plane.yaml",
        ))
        out = capsys.readouterr().out
        assert "PARAM_A" in out


# -- cmd_diff_planes --


class TestCmdDiffPlanes:
    def test_identical_planes(self, mini_config_dir: Path, capsys):
        cmd_diff_planes(ns(
            config_dir=str(mini_config_dir),
            config1="planes/test_plane.yaml",
            config2="planes/test_plane.yaml",
        ))
        out = capsys.readouterr().out
        assert "identical" in out

    def test_different_planes(self, mini_config_dir: Path, capsys):
        cmd_diff_planes(ns(
            config_dir=str(mini_config_dir),
            config1="planes/test_plane.yaml",
            config2="planes/test_plane2.yaml",
        ))
        out = capsys.readouterr().out
        # test_plane has more params than test_plane2
        assert "Only in" in out or "Different" in out


# -- cmd_search --


class TestCmdSearch:
    def test_finds_results(self, pdef_cache_dir: Path, capsys):
        cmd_search(ns(config_dir=str(pdef_cache_dir), query="airspeed"))
        out = capsys.readouterr().out
        assert "ARSPD" in out

    def test_no_results(self, pdef_cache_dir: Path, capsys):
        cmd_search(ns(config_dir=str(pdef_cache_dir), query="zzzzzzz"))
        out = capsys.readouterr().out
        assert "No parameters matching" in out


# -- cmd_describe --


class TestCmdDescribe:
    def test_known_param(self, pdef_cache_dir: Path, capsys):
        cmd_describe(ns(config_dir=str(pdef_cache_dir), params=["ARSPD_TYPE"]))
        out = capsys.readouterr().out
        assert "Airspeed Type" in out

    def test_unknown_param(self, pdef_cache_dir: Path, capsys):
        cmd_describe(ns(config_dir=str(pdef_cache_dir), params=["NOPE"]))
        out = capsys.readouterr().out
        assert "not found" in out


# -- cmd_diff (with param file) --


class TestCmdDiff:
    def test_diff_with_param_file(self, mini_config_dir: Path, capsys):
        # Create a param file that differs from the plane
        param_file = mini_config_dir / "fc.param"
        param_file.write_text("PARAM_A,1\nPARAM_B,2\nPARAM_C,5\n")
        cmd_diff(ns(
            config_dir=str(mini_config_dir),
            config="planes/test_plane.yaml",
            port=None,
            param_file=str(param_file),
            baud=115200,
        ))
        out = capsys.readouterr().out
        assert "Diff:" in out

    def test_no_source_exits(self, mini_config_dir: Path):
        with pytest.raises(SystemExit):
            cmd_diff(ns(
                config_dir=str(mini_config_dir),
                config="planes/test_plane.yaml",
                port=None,
                param_file=None,
                baud=115200,
            ))


# -- cmd_create_chart --


class TestCmdCreateChart:
    def test_basic_creation(self, tmp_path: Path, capsys):
        charts_dir = tmp_path / "charts"
        charts_dir.mkdir()
        cmd_create_chart(ns(
            config_dir=str(tmp_path),
            name="new_chart",
            base=[],
            params=["PARAM_A", "PARAM_B"],
            depends=[],
        ))
        out = capsys.readouterr().out
        assert "Created:" in out
        assert (charts_dir / "new_chart" / "Chart.yaml").exists()
        assert (charts_dir / "new_chart" / "defaults.yaml").exists()

    def test_already_exists_exits(self, tmp_path: Path):
        charts_dir = tmp_path / "charts" / "existing"
        charts_dir.mkdir(parents=True)
        with pytest.raises(SystemExit):
            cmd_create_chart(ns(
                config_dir=str(tmp_path),
                name="existing",
                base=[],
                params=[],
                depends=[],
            ))

    def test_with_base(self, mini_config_dir: Path, capsys):
        cmd_create_chart(ns(
            config_dir=str(mini_config_dir),
            name="based_chart",
            base=["myschema"],
            params=["PARAM_D"],
            depends=[],
        ))
        out = capsys.readouterr().out
        assert "Base:" in out
        chart_yaml = mini_config_dir / "charts" / "based_chart" / "Chart.yaml"
        meta = yaml.safe_load(chart_yaml.read_text())
        assert meta["base"] == ["myschema"]


# -- cmd_update_schema --


class TestCmdUpdateSchema:
    def test_creates_schema_dirs(self, pdef_cache_dir: Path, capsys):
        """Test just the schema chart generation part (mock the download)."""
        from unittest.mock import patch
        # Patch refresh to avoid network call — cache already exists
        with patch.object(
            __import__("arducharts.schema", fromlist=["ParamSchema"]).ParamSchema,
            "refresh",
        ):
            cmd_update_schema(ns(config_dir=str(pdef_cache_dir)))
        out = capsys.readouterr().out
        assert "Done:" in out
        schema_dir = pdef_cache_dir / "schema"
        assert schema_dir.exists()
        families = [d.name for d in schema_dir.iterdir() if d.is_dir()]
        assert "airspeed" in families
        assert "battery" in families
