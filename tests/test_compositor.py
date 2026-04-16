"""Tests for arducharts.compositor — chart resolution, merging, and file I/O."""

from __future__ import annotations

from pathlib import Path

import pytest

from arducharts.compositor import ParamCompositor, _merge_params


# -- YAML loading --


class TestLoadYaml:
    def test_caching(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        path = mini_config_dir / "charts" / "alpha" / "Chart.yaml"
        first = compositor.load_yaml(path)
        second = compositor.load_yaml(path)
        assert first is second

    def test_empty_yaml_returns_empty_dict(self, tmp_path: Path):
        path = tmp_path / "empty.yaml"
        path.write_text("")
        compositor = ParamCompositor(tmp_path)
        assert compositor.load_yaml(path) == {}

    def test_nonexistent_file_raises(self, tmp_path: Path):
        compositor = ParamCompositor(tmp_path)
        with pytest.raises(FileNotFoundError):
            compositor.load_yaml(tmp_path / "nope.yaml")


# -- load_plane --


class TestLoadPlane:
    def test_basic_loading(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        result = compositor.load_plane("planes/test_plane.yaml")
        assert result["name"] == "Test Plane"
        assert "params" in result
        assert "installed" in result
        assert "meta" in result

    def test_chart_defaults_applied(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        result = compositor.load_plane("planes/test_plane.yaml")
        assert result["params"]["PARAM_B"] == 2  # from alpha

    def test_dependency_resolution_order(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        result = compositor.load_plane("planes/test_plane.yaml")
        installed = result["installed"]
        # beta depends on alpha, so alpha first
        assert installed.index("alpha") < installed.index("beta")

    def test_override_in_values_applied(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        result = compositor.load_plane("planes/test_plane.yaml")
        # plane values override beta's PARAM_C from 10 to 20
        assert result["params"]["PARAM_C"] == 20

    def test_extra_params_highest_priority(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        result = compositor.load_plane("planes/test_plane.yaml")
        assert result["params"]["PARAM_X"] == 42

    def test_meta_tracks_source(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        result = compositor.load_plane("planes/test_plane.yaml")
        # PARAM_A overridden by beta
        assert "beta" in result["meta"]["PARAM_A"]

    def test_missing_chart_raises(self, mini_config_dir: Path):
        import yaml
        plane_path = mini_config_dir / "planes" / "bad.yaml"
        plane_path.write_text(yaml.dump({
            "name": "Bad", "charts": ["does_not_exist"],
        }))
        compositor = ParamCompositor(mini_config_dir)
        with pytest.raises(FileNotFoundError, match="Chart not found"):
            compositor.load_plane("planes/bad.yaml")

    def test_chart_without_chart_yaml_raises(self, mini_config_dir: Path):
        import yaml
        # Create chart dir without Chart.yaml
        (mini_config_dir / "charts" / "broken").mkdir()
        plane_path = mini_config_dir / "planes" / "bad2.yaml"
        plane_path.write_text(yaml.dump({
            "name": "Bad2", "charts": ["broken"],
        }))
        compositor = ParamCompositor(mini_config_dir)
        with pytest.raises(FileNotFoundError, match="Missing Chart.yaml"):
            compositor.load_plane("planes/bad2.yaml")

    def test_no_mission_rally_fence_in_result(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        result = compositor.load_plane("planes/test_plane.yaml")
        assert "mission" not in result
        assert "rally" not in result
        assert "fence" not in result


# -- Dedup --


class TestInstallChartDedup:
    def test_chart_installed_once(self, mini_config_dir: Path):
        """Alpha is both directly listed and a dep of beta — installed once."""
        compositor = ParamCompositor(mini_config_dir)
        result = compositor.load_plane("planes/test_plane.yaml")
        assert result["installed"].count("alpha") == 1


# -- list_charts --


class TestListCharts:
    def test_returns_all_charts(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        charts = compositor.list_charts()
        names = [c["name"] for c in charts]
        assert "alpha" in names
        assert "beta" in names
        assert "gamma" in names

    def test_chart_metadata_fields(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        charts = compositor.list_charts()
        for chart in charts:
            assert "name" in chart
            assert "description" in chart
            assert "version" in chart
            assert "depends" in chart
            assert "params" in chart

    def test_param_count(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        charts = compositor.list_charts()
        alpha = next(c for c in charts if c["name"] == "alpha")
        gamma = next(c for c in charts if c["name"] == "gamma")
        assert alpha["params"] == 2
        assert gamma["params"] == 0

    def test_empty_charts_dir(self, tmp_path: Path):
        compositor = ParamCompositor(tmp_path)
        assert not compositor.list_charts()


# -- list_schema_charts --


class TestListSchemaCharts:
    def test_returns_schema_charts(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        charts = compositor.list_schema_charts()
        assert len(charts) == 1
        assert charts[0]["name"] == "myschema"
        assert charts[0]["schema_params"] == 4

    def test_empty_schema_dir(self, tmp_path: Path):
        compositor = ParamCompositor(tmp_path)
        assert not compositor.list_schema_charts()


# -- get_schema_params --


class TestGetSchemaParams:
    def test_existing_family(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        params = compositor.get_schema_params("myschema")
        assert "PARAM_A" in params
        assert "PARAM_B" in params
        assert len(params) == 4

    def test_nonexistent_family(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        assert compositor.get_schema_params("nope") == []


# -- validate_chart_bases --


class TestValidateChartBases:
    def test_no_warnings_when_params_in_schema(self, mini_config_dir: Path):
        """Delta has base [myschema] and params PARAM_A, PARAM_B — both in schema."""
        compositor = ParamCompositor(mini_config_dir)
        warnings = compositor.validate_chart_bases()
        delta_warnings = [w for w in warnings if "delta" in w]
        assert delta_warnings == []

    def test_warning_for_param_not_in_base(self, mini_config_dir: Path):
        """Add a param to delta that's not in the schema."""
        import yaml
        defaults_path = mini_config_dir / "charts" / "delta" / "defaults.yaml"
        defaults_path.write_text(yaml.dump({
            "params": {"PARAM_A": 1, "PARAM_B": 2, "PARAM_Z": 99},
        }))
        compositor = ParamCompositor(mini_config_dir)
        warnings = compositor.validate_chart_bases()
        assert any("PARAM_Z" in w and "delta" in w for w in warnings)


# -- match_charts --


class TestMatchCharts:
    def test_match_returns_matching_charts(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        fc_params = {"PARAM_A": 1, "PARAM_B": 2, "PARAM_C": 10}
        matched, _values, _unmatched = compositor.match_charts(fc_params)
        assert "alpha" in matched

    def test_override_values_for_differing_params(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        fc_params = {"PARAM_A": 5, "PARAM_B": 2}
        matched, values, _unmatched = compositor.match_charts(fc_params)
        assert "alpha" in matched
        assert "alpha" in values
        assert values["alpha"]["PARAM_A"] == 5

    def test_unmatched_params_returned(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        fc_params = {"PARAM_A": 1, "PARAM_B": 2, "UNKNOWN_Z": 7}
        _, _, unmatched = compositor.match_charts(fc_params)
        assert "UNKNOWN_Z" in unmatched

    def test_schema_chart_claims_remaining(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        # FC has PARAM_D which is in myschema but not in any user chart
        fc_params = {"PARAM_A": 1, "PARAM_B": 2, "PARAM_D": 50}
        matched, _values, unmatched = compositor.match_charts(fc_params)
        assert "myschema" in matched
        assert "PARAM_D" not in unmatched

    def test_bundle_matched_when_all_deps_matched(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        # FC has all params for alpha and beta
        fc_params = {"PARAM_A": 1, "PARAM_B": 2, "PARAM_C": 10}
        matched, _, _ = compositor.match_charts(fc_params)
        # gamma is a bundle of alpha+beta, both matched
        assert "gamma" in matched


# -- Param file I/O --


class TestParamFileIO:
    def test_to_param_file_basic(self, tmp_path: Path):
        output = tmp_path / "test.param"
        ParamCompositor.to_param_file({"A": 1, "B": 2.5}, output)
        content = output.read_text()
        assert "A,1\n" in content
        assert "B,2.500000\n" in content

    def test_to_param_file_with_header(self, tmp_path: Path):
        output = tmp_path / "test.param"
        ParamCompositor.to_param_file({"A": 1}, output, header="My Plane\nv1.0")
        lines = output.read_text().splitlines()
        assert lines[0] == "# My Plane"
        assert lines[1] == "# v1.0"
        assert lines[2] == "#"

    def test_to_param_file_int_no_decimals(self, tmp_path: Path):
        output = tmp_path / "test.param"
        ParamCompositor.to_param_file({"A": 42}, output)
        content = output.read_text()
        assert "A,42\n" in content
        assert "42.0" not in content

    def test_read_param_file_comma_separated(self, sample_param_file: Path):
        params = ParamCompositor.read_param_file(sample_param_file)
        assert params["PARAM_A"] == 1
        assert params["PARAM_B"] == 2.5
        assert params["PARAM_C"] == 10

    def test_read_param_file_skips_comments_and_blanks(self, tmp_path: Path):
        path = tmp_path / "test.param"
        path.write_text("# comment\n\nA,1\n   \n# another\nB,2\n")
        params = ParamCompositor.read_param_file(path)
        assert len(params) == 2

    def test_read_param_file_space_separated(self, tmp_path: Path):
        path = tmp_path / "test.param"
        path.write_text("A 1\nB 2.5\n")
        params = ParamCompositor.read_param_file(path)
        assert params["A"] == 1
        assert params["B"] == 2.5

    def test_roundtrip(self, tmp_path: Path):
        original = {"X": 1, "Y": 3.14, "Z": 0}
        output = tmp_path / "rt.param"
        ParamCompositor.to_param_file(original, output)
        readback = ParamCompositor.read_param_file(output)
        for key, value in original.items():
            assert readback[key] == pytest.approx(value, abs=1e-5)


# -- _merge_params --


class TestMergeParams:
    def test_new_params_added(self):
        merged: dict = {}
        meta: dict = {}
        _merge_params(merged, meta, {"A": 1, "B": 2}, "source1")
        assert merged == {"A": 1, "B": 2}
        assert meta == {"A": "source1", "B": "source1"}

    def test_override_applied(self):
        merged = {"A": 1}
        meta = {"A": "old"}
        _merge_params(merged, meta, {"A": 99}, "new")
        assert merged["A"] == 99
        assert meta["A"] == "new"

    def test_same_value_updates_meta(self):
        merged = {"A": 1}
        meta = {"A": "old"}
        _merge_params(merged, meta, {"A": 1}, "new")
        assert meta["A"] == "new"


# -- import_as_charts --


class TestImportAsCharts:
    def test_creates_charts_per_family(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        fc_params = {"PARAM_A": 1, "PARAM_B": 2, "PARAM_D": 50}
        charts, _unmatched = compositor.import_as_charts(fc_params, "test_import")
        # PARAM_A, PARAM_B, PARAM_D are all in myschema
        assert "test_import/myschema" in charts
        chart_dir = mini_config_dir / "charts" / "test_import" / "myschema"
        assert (chart_dir / "Chart.yaml").exists()
        assert (chart_dir / "defaults.yaml").exists()

    def test_defaults_contain_fc_values(self, mini_config_dir: Path):
        import yaml
        compositor = ParamCompositor(mini_config_dir)
        fc_params = {"PARAM_A": 77, "PARAM_B": 88}
        compositor.import_as_charts(fc_params, "val_test")
        defaults = yaml.safe_load(
            (mini_config_dir / "charts" / "val_test" / "myschema" / "defaults.yaml").read_text()
        )
        assert defaults["params"]["PARAM_A"] == 77
        assert defaults["params"]["PARAM_B"] == 88

    def test_unmatched_params_returned(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        fc_params = {"PARAM_A": 1, "UNKNOWN_Z": 99}
        _, unmatched = compositor.import_as_charts(fc_params, "unk_test")
        assert "UNKNOWN_Z" in unmatched

    def test_no_schema_returns_all_unmatched(self, tmp_path: Path):
        compositor = ParamCompositor(tmp_path)
        fc_params = {"A": 1, "B": 2}
        charts, unmatched = compositor.import_as_charts(fc_params, "empty")
        assert not charts
        assert len(unmatched) == 2

    def test_chart_yaml_has_base(self, mini_config_dir: Path):
        import yaml
        compositor = ParamCompositor(mini_config_dir)
        fc_params = {"PARAM_A": 1}
        compositor.import_as_charts(fc_params, "base_test")
        meta = yaml.safe_load(
            (mini_config_dir / "charts" / "base_test" / "myschema" / "Chart.yaml").read_text()
        )
        assert meta["base"] == ["myschema"]


# -- list_charts with nested dirs --


class TestListChartsNested:
    def test_nested_charts_discovered(self, mini_config_dir: Path):
        """Charts created by import_as_charts should appear in list_charts."""
        compositor = ParamCompositor(mini_config_dir)
        compositor.import_as_charts({"PARAM_A": 1}, "nested_test")
        charts = compositor.list_charts()
        names = [c["name"] for c in charts]
        assert "nested_test/myschema" in names

    def test_nested_and_flat_coexist(self, mini_config_dir: Path):
        compositor = ParamCompositor(mini_config_dir)
        compositor.import_as_charts({"PARAM_A": 1}, "sub")
        charts = compositor.list_charts()
        names = [c["name"] for c in charts]
        # Flat charts still found
        assert "alpha" in names
        assert "beta" in names
        # Nested chart also found
        assert "sub/myschema" in names

    def test_load_plane_with_nested_charts(self, mini_config_dir: Path):
        """A plane referencing nested charts should load correctly."""
        import yaml
        compositor = ParamCompositor(mini_config_dir)
        compositor.import_as_charts({"PARAM_A": 5, "PARAM_B": 10}, "myplane")
        plane_path = mini_config_dir / "planes" / "myplane.yaml"
        plane_path.write_text(yaml.dump({
            "name": "My Plane",
            "charts": ["myplane/myschema"],
        }))
        result = compositor.load_plane("planes/myplane.yaml")
        assert result["params"]["PARAM_A"] == 5
        assert result["params"]["PARAM_B"] == 10


# -- export/import chart zip --


class TestChartZipIO:
    def test_export_and_import_roundtrip(self, mini_config_dir: Path):
        import yaml
        import zipfile

        compositor = ParamCompositor(mini_config_dir)
        # Create a plane with nested charts
        compositor.import_as_charts(
            {"PARAM_A": 42, "PARAM_B": 7}, "export_plane"
        )
        plane_data = {
            "name": "export_plane",
            "charts": ["export_plane/myschema"],
        }
        plane_path = mini_config_dir / "planes" / "export_plane.yaml"
        plane_path.write_text(yaml.dump(plane_data))

        # Export
        exports_dir = mini_config_dir / "exports"
        exports_dir.mkdir()
        zip_path = exports_dir / "export_plane.zip"
        charts_dir = mini_config_dir / "charts" / "export_plane"

        files = []
        files.append((plane_path, "plane.yaml"))
        for f in sorted(charts_dir.rglob("*")):
            if f.is_file():
                rel = f.relative_to(charts_dir)
                files.append((f, f"charts/{rel}"))

        with zipfile.ZipFile(str(zip_path), "w") as zf:
            for filepath, arcname in files:
                zf.write(filepath, arcname)

        # Import into a different name
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            members = zf.namelist()
            for arcname in members:
                if arcname == "plane.yaml":
                    target = mini_config_dir / "planes" / "imported.yaml"
                else:
                    family_rel = arcname.removeprefix("charts/")
                    target = mini_config_dir / "charts" / "imported" / family_rel
                target.parent.mkdir(parents=True, exist_ok=True)
                data = zf.read(arcname)
                if arcname == "plane.yaml":
                    pd = yaml.safe_load(data.decode()) or {}
                    pd["name"] = "imported"
                    pd["charts"] = [
                        f"imported/{c.split('/')[-1]}" if "/" in c else f"imported/{c}"
                        for c in pd.get("charts", [])
                    ]
                    with open(target, "w", encoding="utf-8") as f:
                        yaml.dump(pd, f)
                else:
                    target.write_bytes(data)

        # Verify imported plane loads correctly
        compositor2 = ParamCompositor(mini_config_dir)
        result = compositor2.load_plane("planes/imported.yaml")
        assert result["name"] == "imported"
        assert result["params"]["PARAM_A"] == 42
        assert result["params"]["PARAM_B"] == 7

    def test_zip_contains_correct_structure(self, mini_config_dir: Path):
        import yaml
        import zipfile

        compositor = ParamCompositor(mini_config_dir)
        compositor.import_as_charts({"PARAM_A": 1}, "ziptest")
        plane_path = mini_config_dir / "planes" / "ziptest.yaml"
        plane_path.write_text(yaml.dump({
            "name": "ziptest", "charts": ["ziptest/myschema"],
        }))

        zip_path = mini_config_dir / "test.zip"
        charts_dir = mini_config_dir / "charts" / "ziptest"
        with zipfile.ZipFile(str(zip_path), "w") as zf:
            zf.write(plane_path, "plane.yaml")
            for f in sorted(charts_dir.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(charts_dir)
                    zf.write(f, f"charts/{rel}")

        with zipfile.ZipFile(str(zip_path), "r") as zf:
            names = zf.namelist()
            assert "plane.yaml" in names
            assert "charts/myschema/Chart.yaml" in names
            assert "charts/myschema/defaults.yaml" in names
