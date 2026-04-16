# arducharts — ArduPilot Configuration Manager

<img width="3262" height="1880" alt="CleanShot 2026-04-16 at 16 29 15@2x" src="https://github.com/user-attachments/assets/9162f717-4c76-490c-9c54-8185b3b7b30f" />

## Philosophy

ArduPilot has over 10,000 parameters. Managing them as flat `.param` files is fragile — configs grow stale, differ between airframes for no documented reason, and the knowledge of *why* a parameter was set lives only in someone's head.

**arducharts** treats parameter configuration like infrastructure-as-code. Inspired by Helm charts, it breaks a flight controller's configuration into small, reusable **charts** — each chart owns one logical concern (battery, servos, telemetry, navigation, etc.). A **plane config** declares which charts to install and any per-plane overrides. The tool then compiles, validates, and flashes the merged result.

This means:

- **Modularity** — a battery chart works across airframes. Change it once, rebuild all planes that use it.
- **Traceability** — every parameter has a source: which chart set it, which override changed it.
- **Validation** — parameters are checked against the official ArduPilot schema (types, ranges, enums) before they reach the FC.
- **Reproducibility** — a plane config is a YAML file you can diff, review, and version-control.

### Intended workflow

1. **Import** from an existing FC or `.param` dump — arducharts auto-creates charts grouped by schema family.
2. **Organize** — rename, split, or merge charts into logical groups that make sense for your fleet.
3. **Override** — per-plane values sit in the plane YAML, not buried in chart defaults.
4. **Validate & Build** — catch mistakes before they reach the FC.
5. **Flash & Verify** — write only changed parameters, read them back to confirm.
6. **Share** — export chart packs as `.zip` archives, import on another machine.

### Directory structure

```
configs/
  charts/                        # Reusable parameter charts
    my_plane/                    # Charts grouped by plane or concern
      battery/
        Chart.yaml               # Metadata: name, base family, depends
        defaults.yaml            # Parameter values
      servo/
        Chart.yaml
        defaults.yaml
    shared/                      # Charts shared across planes
      telemetry/
        Chart.yaml
        defaults.yaml
  schema/                        # Auto-generated from ArduPilot param definitions
    battery/
      Chart.yaml                 # schema_params: all params in this family
    servo/
      Chart.yaml
  planes/                        # Per-plane configurations
    my_plane.yaml
  build/                         # Compiled .param files (generated)
    my_plane.param
  exports/                       # Exported .zip chart packs
  .cache/                        # Downloaded ArduPilot param schema
    apm.pdef.json
```

### How charts work

A chart is a directory with two files:

```yaml
# Chart.yaml — metadata
name: battery
description: "6S 5Ah LiPo with voltage and current monitoring"
version: "1.0"
base: [battery]           # schema family (enables validation)
depends: [safety]          # other charts to install first (optional)
```

```yaml
# defaults.yaml — parameter values
params:
  BATT_MONITOR: 4
  BATT_CAPACITY: 5000
  BATT_VOLT_PIN: 14
```

### Composing charts from charts

Charts can depend on other charts via the `depends` field. When a chart is installed, its dependencies are resolved first (depth-first), so their parameters are applied before the chart's own. This lets you build higher-level charts that bundle smaller ones:

```yaml
# Chart.yaml — a "full avionics" bundle chart
name: avionics_standard
description: "Standard avionics stack — GPS, airspeed, AHRS, EKF"
version: "1.0"
depends:
  - shared/gps
  - shared/airspeed_pitot
  - shared/ahrs
  - shared/ekf
```

The bundle chart can have its own `defaults.yaml` to set additional parameters or override what its dependencies set. Or it can have no params of its own — acting purely as a named group.

This means you can compose your configuration at any level of granularity: individual charts for fine control, bundle charts for convenience, or a mix of both.

### Plane configs

A plane config lists charts and overrides:

```yaml
name: "My Plane"
description: "Long-range fixed wing"

charts:
  - my_plane/battery
  - my_plane/servo
  - shared/telemetry

values:
  my_plane/battery:
    BATT_CAPACITY: 12000     # override the chart default

extra_params:
  CUSTOM_PARAM: 42           # params not belonging to any chart
```

**Resolution order** (lowest → highest priority):
1. Chart defaults (depth-first dependency order)
2. Plane `values` (per-chart overrides)
3. Plane `extra_params`

---

## Install

```bash
pip install -r requirements.txt
```

Dependencies: `pyyaml`, `pymavlink` (FC communication), `pyserial` (serial port detection), `textual` (TUI).

---

## TUI

```bash
python -m arducharts tui
```

The TUI is the primary way to interact with arducharts. It provides a full-screen terminal interface for browsing, editing, validating, and flashing configurations.

### Layout

- **Sidebar** (left) — tree view of all planes and charts, grouped by folder.
- **Content area** (right) — tabbed interface with Overview, Validate, Diff, Search, FC Flash, and FC Read.
- **FC Connection Bar** (bottom) — serial port selector, connect/disconnect, status.

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `q` | Quit |
| `o` | Switch to Overview tab |
| `v` | Switch to Validate tab |
| `d` | Switch to Diff tab |
| `/` | Focus search input |
| `c` | Toggle FC connection |
| `f` | Switch to FC Flash tab |

### Overview tab

The main workspace. Shows a table of all charts (name, version, param count, dependencies, description).

**Navigation:** Click a chart in the sidebar or table to drill into its parameters. Click a plane to see its merged parameter view with sources. The breadcrumb at the top shows where you are.

**Editing parameters:** Click any parameter row in a chart view to open the edit dialog. Schema hints (range, enum values, description) are shown if available.

**Action buttons:**
| Button | What it does |
|--------|-------------|
| Build .param | Compile the selected plane into a `.param` file |
| Import .param | Create a plane config from a Mission Planner / QGC `.param` dump |
| Export .zip | Export the selected plane and its charts as a portable archive |
| Import .zip | Import a `.zip` chart pack |
| Rename | Rename the selected plane, chart, or folder (updates all references) |
| Delete | Delete the selected plane, chart, or folder |
| Update Schema | Download the latest ArduPilot parameter definitions |
| Refresh | Rescan the filesystem and reload all trees |

### Validate tab

Select a plane, then click **Validate**. Runs checks against the ArduPilot schema:

- Unknown parameter names
- Values outside declared ranges
- Invalid enum values
- Multi-chart conflicts (same param set by two charts)
- Unused overrides in `values`

### Diff tab

Compare parameters between any two sources:
- Plane vs plane
- Plane vs live FC
- Plane vs `.param` file

Select two sources from the dropdowns and click **Diff**. The table shows parameters that differ, with values from each side.

### Search tab

Full-text search across all ArduPilot parameter names, display names, and descriptions. Type a query and results update in the table below.

### FC Flash tab

Write parameters to a connected flight controller over MAVLink.

| Option | Description |
|--------|-------------|
| Changed only | Read FC first, only write parameters that differ |
| Verify | Read back each parameter after writing to confirm it took |
| Dry run | Show what would be written without touching the FC |

### FC Read tab

Read all parameters from the connected FC. After reading, you can:
- Export as a `.param` file
- Import as a new plane config (auto-creates charts per schema family)

### FC Connection Bar

The bottom bar shows available serial ports. Select a port and click **Connect** to establish a MAVLink connection. The connection status is displayed, and FC-dependent buttons (Flash, Read) are enabled once connected.

---

## CLI

```bash
python -m arducharts <command> [options]
```

All commands accept `-d / --config-dir` to specify the base config directory (default: `configs`).

### Offline commands

**list** — List all available charts with metadata.
```bash
python -m arducharts list
```

**build** — Compile a plane config into a `.param` file.
```bash
python -m arducharts build planes/my_plane.yaml
python -m arducharts build planes/my_plane.yaml -o output.param
```

**show** — Print merged parameters with descriptions.
```bash
python -m arducharts show planes/my_plane.yaml
```

**validate** — Check parameters against the ArduPilot schema.
```bash
python -m arducharts validate planes/my_plane.yaml
```

**lint** — Static analysis for config mistakes (unused overrides, multi-chart conflicts).
```bash
python -m arducharts lint planes/my_plane.yaml
```

**diff-planes** — Compare two plane configs side by side.
```bash
python -m arducharts diff-planes planes/plane_a.yaml planes/plane_b.yaml
```

**search** — Search parameter names and descriptions.
```bash
python -m arducharts search "battery"
python -m arducharts search "arspd" --limit 20
```

**describe** — Look up detailed information for specific parameters.
```bash
python -m arducharts describe BATT_MONITOR ARSPD_TYPE
```

**create-chart** — Scaffold a new chart directory.
```bash
python -m arducharts create-chart my_plane/gps --base gps --params GPS_TYPE GPS_AUTO_CONFIG
```

**update-schema** — Download latest ArduPilot parameter definitions and rebuild schema charts.
```bash
python -m arducharts update-schema
```

**export-chart** — Export a plane and its charts as a `.zip` archive.
```bash
python -m arducharts export-chart my_plane
python -m arducharts export-chart my_plane -o my_plane_backup.zip
```

**import-chart** — Import a `.zip` chart archive.
```bash
python -m arducharts import-chart my_plane.zip
python -m arducharts import-chart my_plane.zip --force  # overwrite existing
```

### FC commands

These require a MAVLink connection to a flight controller.

**read** — Read all parameters from the FC.
```bash
python -m arducharts read --port /dev/ttyACM0
python -m arducharts read --port /dev/ttyACM0 -o backup.param
```

**import** — Create a plane config from FC or `.param` file. Auto-generates charts per schema family.
```bash
python -m arducharts import --port /dev/ttyACM0 --name "my_plane"
python -m arducharts import --param-file backup.param --name "my_plane"
```

**diff** — Diff a plane config against the FC or a `.param` file.
```bash
python -m arducharts diff planes/my_plane.yaml --port /dev/ttyACM0
python -m arducharts diff planes/my_plane.yaml --param-file backup.param
```

**flash** — Write parameters to the FC.
```bash
python -m arducharts flash planes/my_plane.yaml --port /dev/ttyACM0
python -m arducharts flash planes/my_plane.yaml --port /dev/ttyACM0 --changed-only --verify
python -m arducharts flash planes/my_plane.yaml --port /dev/ttyACM0 --dry-run
```

| Flag | Description |
|------|-------------|
| `--changed-only` | Read current params first, only write differences |
| `--verify` | Read params back after flash and confirm they match |
| `--force` | Skip confirmation prompt |
| `--dry-run` | Show what would be written without writing |

---

## License

This project is licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE) for details.
