#!/usr/bin/env python3
"""Textual TUI for arducharts — ArduPilot Configuration Manager."""

import os
import shutil
from pathlib import Path

import yaml
from textual.app import App, ComposeResult
from textual.screen import ModalScreen
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Header,
    Footer,
    Static,
    Select,
    Tree,
    TabbedContent,
    TabPane,
    DataTable,
    Button,
    Log,
    Input,
    Checkbox,
    ProgressBar,
)
from textual import work

from arducharts import (
    ParamCompositor,
    ParamSchema,
    norm_value,
    compute_param_diff,
    collect_export_files,
    lint_plane_config,
    rebuild_schema_charts,
    write_export_zip,
    HAS_MAVLINK,
    DEFAULT_BAUD,
)
from arducharts.schema_map import build_schema_charts_data

if HAS_MAVLINK:
    from arducharts import MAVLinkConnection


# ---------------------------------------------------------------------------
# Filename dialog
# ---------------------------------------------------------------------------

class FilenameDialog(ModalScreen[str | None]):
    """Modal dialog that asks for a filename."""

    DEFAULT_CSS = """
    FilenameDialog {
        align: center middle;
    }
    #fn-dialog {
        width: 50;
        height: auto;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #fn-dialog #fn-title {
        text-align: center;
        width: 100%;
        margin-bottom: 1;
        text-style: bold;
    }
    #fn-dialog Input {
        width: 100%;
        margin-bottom: 1;
    }
    #fn-dialog #fn-buttons {
        height: auto;
        width: 100%;
        align-horizontal: right;
    }
    #fn-dialog #fn-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, title: str, default: str = "fc_read", raw: bool = False) -> None:
        super().__init__()
        self._title = title
        self._default = default
        self._raw = raw

    def compose(self) -> ComposeResult:
        with Vertical(id="fn-dialog"):
            yield Static(self._title, id="fn-title")
            yield Input(
                value=self._default,
                placeholder="file name",
                id="fn-input",
            )
            with Horizontal(id="fn-buttons"):
                yield Button("Cancel", id="fn-cancel")
                yield Button("OK", id="fn-ok", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#fn-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "fn-ok":
            self._submit()
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "fn-input":
            self._submit()

    def _submit(self) -> None:
        raw = self.query_one("#fn-input", Input).value.strip()
        if self._raw:
            self.dismiss(raw or self._default)
        else:
            name = "".join(c for c in raw if c.isalnum() or c in "_-") or self._default
            self.dismiss(name)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Confirm dialog
# ---------------------------------------------------------------------------

class ConfirmDialog(ModalScreen[bool]):
    """Modal dialog that asks for Yes / No confirmation."""

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }
    #confirm-dialog {
        width: 50;
        height: auto;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #confirm-dialog #confirm-title {
        text-align: center;
        width: 100%;
        margin-bottom: 1;
        text-style: bold;
    }
    #confirm-dialog #confirm-buttons {
        height: auto;
        width: 100%;
        align-horizontal: right;
    }
    #confirm-dialog #confirm-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(self._message, id="confirm-title")
            with Horizontal(id="confirm-buttons"):
                yield Button("No", id="confirm-no")
                yield Button("Yes", id="confirm-yes", variant="error")

    def on_mount(self) -> None:
        self.query_one("#confirm-no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-yes":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


# ---------------------------------------------------------------------------
# Action choice dialog
# ---------------------------------------------------------------------------

class ActionDialog(ModalScreen[str | None]):
    """Modal dialog with multiple action buttons. Returns the chosen action id."""

    DEFAULT_CSS = """
    ActionDialog {
        align: center middle;
    }
    #act-dialog {
        width: 50;
        height: auto;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #act-dialog #act-title {
        text-align: center;
        width: 100%;
        margin-bottom: 1;
        text-style: bold;
    }
    #act-dialog Button {
        width: 100%;
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, title: str, actions: list[tuple[str, str, str]]) -> None:
        """actions: list of (label, action_id, variant)."""
        super().__init__()
        self._title = title
        self._actions = actions

    def compose(self) -> ComposeResult:
        with Vertical(id="act-dialog"):
            yield Static(self._title, id="act-title")
            for label, action_id, variant in self._actions:
                yield Button(label, id=f"act-{action_id}", variant=variant)
            yield Button("Done", id="act-done")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "act-done":
            self.dismiss(None)
        elif btn_id.startswith("act-"):
            self.dismiss(btn_id.removeprefix("act-"))

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Edit param dialog
# ---------------------------------------------------------------------------

class EditParamDialog(ModalScreen[str | None]):
    """Modal dialog for editing a parameter value with schema hints."""

    DEFAULT_CSS = """
    EditParamDialog {
        align: center middle;
    }
    #ep-dialog {
        width: 70;
        height: auto;
        max-height: 80%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #ep-dialog #ep-title {
        text-align: center;
        width: 100%;
        margin-bottom: 1;
        text-style: bold;
    }
    #ep-dialog .ep-info {
        color: $text-muted;
        width: 100%;
    }
    #ep-dialog Input {
        width: 100%;
        margin-bottom: 1;
    }
    #ep-dialog Select {
        width: 100%;
        margin-bottom: 1;
    }
    #ep-dialog #ep-buttons {
        height: auto;
        width: 100%;
        align-horizontal: right;
    }
    #ep-dialog #ep-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        param_name: str,
        current_value: str,
        schema_def: dict | None = None,
    ) -> None:
        super().__init__()
        self._param_name = param_name
        self._current_value = current_value
        self._schema = schema_def or {}
        # Pre-build full enum options list for filtering
        vals = self._schema.get("Values")
        if vals:
            self._all_enum_options: list[tuple[str, str]] = [
                (f"{k} = {v}", str(k))
                for k, v in sorted(vals.items(), key=lambda x: float(x[0]))
            ]
        else:
            self._all_enum_options = []

    def compose(self) -> ComposeResult:
        display = self._schema.get("DisplayName", "")
        title = f"{self._param_name} — {display}" if display else self._param_name

        with Vertical(id="ep-dialog"):
            yield Static(title, id="ep-title")

            # Description
            desc = self._schema.get("Description", "")
            if desc:
                yield Static(desc, classes="ep-info")

            # Range / Units / Increment
            hints: list[str] = []
            rng = self._schema.get("Range")
            if rng:
                hints.append(f"Range: {rng.get('low', '?')} .. {rng.get('high', '?')}")
            if self._schema.get("Units"):
                hints.append(f"Units: {self._schema['Units']}")
            if self._schema.get("Increment"):
                hints.append(f"Increment: {self._schema['Increment']}")
            if self._schema.get("RebootRequired"):
                hints.append("Reboot required")
            if hints:
                yield Static("  ".join(hints), classes="ep-info")

            # Bitmask info
            bits = self._schema.get("Bitmask")
            if bits:
                bit_strs = [
                    f"{k}: {v}"
                    for k, v in sorted(bits.items(), key=lambda x: int(x[0]))
                ]
                yield Static(f"Bitmask: {', '.join(bit_strs)}", classes="ep-info")

            # Enum values → filter input + Select dropdown + Input for custom
            vals = self._schema.get("Values")
            if vals:
                yield Input(
                    placeholder="Filter values...",
                    id="ep-filter",
                )
                yield Select(
                    self._all_enum_options,
                    id="ep-select",
                    prompt="Pick a value...",
                    value=(self._current_value
                           if self._current_value in dict(vals)
                           else Select.BLANK),
                )

            yield Input(
                value=self._current_value,
                placeholder="value",
                id="ep-input",
            )
            with Horizontal(id="ep-buttons"):
                yield Button("Cancel", id="ep-cancel")
                yield Button("Save", id="ep-save", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#ep-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter the enum Select options when the filter input changes."""
        if event.input.id == "ep-filter":
            query = event.value.strip().lower()
            try:
                select = self.query_one("#ep-select", Select)
            except Exception:
                return
            if not query:
                select.set_options(self._all_enum_options)
            else:
                filtered = [
                    (label, val)
                    for label, val in self._all_enum_options
                    if query in label.lower()
                ]
                select.set_options(filtered)

    def on_select_changed(self, event: Select.Changed) -> None:
        """When enum value is picked, update the input field."""
        if event.select.id == "ep-select" and event.value != Select.BLANK:
            self.query_one("#ep-input", Input).value = str(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ep-save":
            self.dismiss(self.query_one("#ep-input", Input).value)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "ep-input":
            self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# FC Connection Bar widget
# ---------------------------------------------------------------------------

class FCConnectionBar(Static):
    """Horizontal bar for managing the FC serial connection."""

    DEFAULT_CSS = """
    FCConnectionBar {
        height: auto;
        border-top: solid $primary-darken-2;
        background: $surface-darken-2;
        padding: 0 1;
        layout: horizontal;
    }
    FCConnectionBar #fc-port {
        width: 30;
        margin-right: 1;
    }
    FCConnectionBar #fc-baud {
        width: 16;
        margin-right: 1;
    }
    FCConnectionBar Button {
        min-width: 14;
        margin-right: 1;
    }
    FCConnectionBar #fc-status {
        width: auto;
        margin-right: 2;
        content-align-vertical: middle;
        color: $text-muted;
    }
    FCConnectionBar #fc-battery {
        width: auto;
        content-align-vertical: middle;
        color: $success;
    }
    """

    def compose(self) -> ComposeResult:
        ports = self._scan_ports()
        port_kwargs: dict = {
            "id": "fc-port",
            "allow_blank": True,
            "prompt": "No ports found" if not ports else "Select port",
        }
        if ports:
            port_kwargs["value"] = ports[0][1]
        yield Select(ports, **port_kwargs)
        yield Select(
            [("115200", 115200), ("57600", 57600), ("921600", 921600)],
            value=115200,
            allow_blank=False,
            id="fc-baud",
        )
        yield Button("Refresh", id="fc-refresh-btn", variant="default")
        yield Button("Connect", id="fc-connect-btn", variant="primary")
        yield Static("Disconnected", id="fc-status")
        yield Static("", id="fc-battery")

    @staticmethod
    def _scan_ports() -> list[tuple[str, str]]:
        """Return available serial ports as (label, path) tuples via pyserial."""
        try:
            from serial.tools.list_ports import comports
        except ImportError:
            return []
        ports = []
        for p in sorted(comports(), key=lambda x: x.device):
            desc = p.description if p.description and p.description != "n/a" else ""
            label = f"{p.device}  ({desc})" if desc else p.device
            ports.append((label, p.device))
        return ports

    def _refresh_ports(self) -> None:
        """Re-scan serial ports and update the dropdown."""
        select = self.query_one("#fc-port", Select)
        ports = self._scan_ports()
        select.set_options(ports)
        if ports:
            select.value = ports[0][1]
        else:
            select.clear()


# ---------------------------------------------------------------------------
# Sidebar (unchanged)
# ---------------------------------------------------------------------------

class Sidebar(Static):
    """Left sidebar with plane tree and chart tree."""

    DEFAULT_CSS = """
    Sidebar {
        width: 32;
        border-right: solid $primary-darken-2;
        background: $surface-darken-2;
        padding: 1 1;
    }
    Sidebar #planes-label,
    Sidebar #charts-label {
        text-style: bold;
        color: $accent;
        margin-top: 1;
        margin-bottom: 0;
        text-align: center;
        width: 100%;
    }
    Sidebar Tree {
        min-height: 4;
        scrollbar-size: 1 1;
    }
    """

    def __init__(self, config_dir: str = "configs") -> None:
        super().__init__()
        self.config_dir = Path(config_dir)

    def compose(self) -> ComposeResult:
        # --- Planes tree ---
        yield Static("Planes", id="planes-label")
        yield self._build_planes_tree()

        # --- Charts tree ---
        yield Static("Charts", id="charts-label")
        yield self._build_charts_tree()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_planes_tree(self) -> Tree[str]:
        """Build a Tree widget listing planes/*.yaml."""
        tree: Tree[str] = Tree("planes", id="planes-tree")
        tree.root.expand()
        planes_dir = self.config_dir / "planes"
        if planes_dir.is_dir():
            for p in sorted(planes_dir.glob("*.yaml")):
                rel = str(p.relative_to(self.config_dir))
                tree.root.add_leaf(p.stem, data=rel)
        return tree

    def _build_charts_tree(self) -> Tree[str]:
        """Build a Tree widget listing charts grouped by subfolder."""
        tree: Tree[str] = Tree("charts", id="charts-tree")
        tree.root.expand()
        compositor = ParamCompositor(str(self.config_dir))

        # Group charts by top-level folder
        folders: dict[str, list[dict]] = {}
        top_level: list[dict] = []
        for chart in compositor.list_charts():
            name = chart["name"]
            if "/" in name:
                folder = name.split("/", 1)[0]
                folders.setdefault(folder, []).append(chart)
            else:
                top_level.append(chart)

        # Render folder groups
        for folder in sorted(folders):
            branch = tree.root.add(folder, data=f"folder:{folder}")
            branch.expand()
            for chart in folders[folder]:
                # Show only the part after the folder prefix
                label = chart["name"].split("/", 1)[1]
                branch.add_leaf(label, data=chart["name"])

        # Render top-level charts
        for chart in top_level:
            tree.root.add_leaf(chart["name"], data=chart["name"])

        return tree

    def refresh_trees(self) -> None:
        """Rebuild the planes and charts trees in place."""
        # Rebuild planes tree
        planes_tree = self.query_one("#planes-tree", Tree)
        planes_tree.root.remove_children()
        planes_dir = self.config_dir / "planes"
        if planes_dir.is_dir():
            for p in sorted(planes_dir.glob("*.yaml")):
                rel = str(p.relative_to(self.config_dir))
                planes_tree.root.add_leaf(p.stem, data=rel)

        # Rebuild charts tree
        charts_tree = self.query_one("#charts-tree", Tree)
        charts_tree.root.remove_children()
        compositor = ParamCompositor(str(self.config_dir))
        folders: dict[str, list[dict]] = {}
        top_level: list[dict] = []
        for chart in compositor.list_charts():
            name = chart["name"]
            if "/" in name:
                folder = name.split("/", 1)[0]
                folders.setdefault(folder, []).append(chart)
            else:
                top_level.append(chart)
        for folder in sorted(folders):
            branch = charts_tree.root.add(folder, data=f"folder:{folder}")
            branch.expand()
            for chart in folders[folder]:
                label = chart["name"].split("/", 1)[1]
                branch.add_leaf(label, data=chart["name"])
        for chart in top_level:
            charts_tree.root.add_leaf(chart["name"], data=chart["name"])


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------

class APConfigApp(App):
    """Interactive TUI for ArduPilot parameter configuration."""

    TITLE = "arducharts"
    SUB_TITLE = "ArduPilot Configuration Manager"
    CSS = """
    Screen {
        background: $surface;
    }
    Header {
        background: $primary-darken-2;
    }
    Footer {
        background: $primary-darken-3;
    }
    DataTable {
        scrollbar-size: 1 1;
    }
    DataTable > .datatable--cursor {
        background: $accent 30%;
    }
    Log {
        scrollbar-size: 1 1;
    }
    ProgressBar Bar > .bar--bar {
        color: $success;
    }
    """

    DEFAULT_CSS = """
    #content-area {
        width: 1fr;
        height: 100%;
    }
    #content-area TabbedContent {
        width: 1fr;
        height: 100%;
    }
    #content-area TabPane {
        overflow-y: auto;
        padding: 1 1;
    }
    #overview-header {
        height: auto;
        margin-bottom: 1;
    }
    #breadcrumb {
        width: 1fr;
        text-style: bold;
        color: $accent;
    }
    #overview-legend {
        color: $text-muted;
        text-align: right;
        width: auto;
    }
    #overview-search {
        width: 40;
    }
    #overview-table {
        width: 100%;
        height: 1fr;
    }
    .tab-desc {
        color: $text-muted;
        margin-bottom: 1;
    }
    .action-row {
        height: auto;
        margin-bottom: 1;
    }
    .action-row Button {
        margin-right: 1;
    }
    .copy-btn {
        min-width: 8;
    }
    #validate-log {
        height: 1fr;
        border: solid $primary-darken-3;
    }
    #diff-selects-row {
        height: auto;
        margin-bottom: 1;
    }
    #diff-selects-row Select {
        width: 1fr;
        margin-right: 1;
    }
    #diff-selects-row Button {
        min-width: 12;
    }
    #diff-progress-row {
        height: auto;
        margin-top: 1;
        display: none;
    }
    #diff-progress {
        width: 1fr;
    }
    #diff-pct {
        width: 8;
        content-align: right middle;
    }
    #diff-table {
        width: 100%;
        height: 1fr;
    }
    #search-input {
        margin-bottom: 1;
    }
    #search-table {
        width: 100%;
        height: 1fr;
    }
    #fc-read-table {
        width: 100%;
        height: 1fr;
    }
    #fc-read-progress-row {
        height: auto;
        margin-top: 1;
        display: none;
    }
    #fc-read-progress {
        width: 1fr;
    }
    #fc-read-pct {
        width: 8;
        content-align: right middle;
    }
    #flash-options {
        height: auto;
        margin-bottom: 1;
        layout: horizontal;
    }
    #flash-options Checkbox {
        margin-right: 2;
    }
    #flash-log {
        height: 1fr;
        border: solid $primary-darken-3;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("o", "tab_overview", "Overview", show=False),
        Binding("v", "tab_validate", "Validate", show=False),
        Binding("d", "tab_diff", "Diff Planes", show=False),
        Binding("slash", "focus_search", "Search", show=False),
        Binding("c", "toggle_fc", "FC Connect", show=False),
        Binding("f", "tab_flash", "Flash", show=False),
    ]

    active_plane: str | None = None
    active_plane_rel: str | None = None

    def __init__(self, config_dir: str = "configs"):
        super().__init__()
        self.config_dir = config_dir
        self.mav_connection = None
        self._fc_params: dict | None = None
        self._overview_columns: tuple[str, ...] = ()
        self._overview_rows: list[tuple[str, ...]] = []
        self._active_chart: str | None = None  # chart being viewed in overview
        self._active_folder: str | None = None  # folder being viewed in overview

    def _scan_planes(self) -> list[tuple[str, str]]:
        """Return (display_name, relative_path) for every plane YAML."""
        planes_dir = Path(self.config_dir) / "planes"
        if not planes_dir.is_dir():
            return []
        results = []
        for p in sorted(planes_dir.glob("*.yaml")):
            rel = str(p.relative_to(Path(self.config_dir)))
            results.append((p.stem, rel))
        return results

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield Sidebar(config_dir=self.config_dir)
            with Vertical(id="content-area"):
                with TabbedContent():
                    with TabPane("Overview", id="tab-overview"):
                        with Horizontal(id="overview-header"):
                            yield Static("Charts", id="breadcrumb")
                            yield Static(
                                "Build: compile plane → .param\n"
                                "Import .param: create plane from dump\n"
                                "Export/Import .zip: share chart packs\n"
                                "Delete: remove selected item\n"
                                "Update Schema: download latest defs",
                                id="overview-legend",
                            )
                        with Horizontal(classes="action-row"):
                            yield Input(
                                placeholder="Filter...",
                                id="overview-search",
                            )
                            yield Button(
                                "Copy", id="copy-overview-table",
                                classes="copy-btn", disabled=True,
                            )
                            yield Button(
                                "Refresh", id="refresh-btn",
                                classes="copy-btn",
                            )
                        with Horizontal(classes="action-row"):
                            yield Button(
                                "Build .param", id="build-btn",
                                variant="primary", disabled=True,
                                classes="copy-btn",
                            )
                            yield Button(
                                "Import .param",
                                id="import-param-file-btn",
                                variant="success", classes="copy-btn",
                            )
                            yield Button(
                                "Export .zip", id="export-chart-btn",
                                classes="copy-btn",
                            )
                            yield Button(
                                "Import .zip", id="import-chart-btn",
                                classes="copy-btn",
                            )
                            yield Button(
                                "Rename", id="rename-btn",
                                classes="copy-btn",
                            )
                            yield Button(
                                "Delete", id="delete-btn",
                                variant="error", classes="copy-btn",
                            )
                            yield Button(
                                "Update Schema",
                                id="update-schema-btn",
                                classes="copy-btn",
                            )
                        yield DataTable(id="overview-table", cursor_type="row")
                    with TabPane("Validate", id="tab-validate"):
                        yield Static(
                            "Check param names, ranges, enums against "
                            "ArduPilot schema. Lint for config mistakes "
                            "(unused overrides, multi-chart conflicts).",
                            classes="tab-desc",
                        )
                        with Horizontal(classes="action-row"):
                            yield Button(
                                "Validate", id="validate-btn",
                                variant="primary", disabled=True,
                            )
                            yield Button(
                                "Copy", id="copy-validate-log",
                                classes="copy-btn", disabled=True,
                            )
                        yield Log(id="validate-log")
                    with TabPane("Diff", id="tab-diff-planes"):
                        yield Static(
                            "Compare params between plane configs "
                            "or a live FC.",
                            classes="tab-desc",
                        )
                        diff_sources = [("FC (live)", "__fc__")] + self._scan_planes()
                        with Horizontal(id="diff-selects-row"):
                            yield Select(
                                diff_sources,
                                id="diff-plane1",
                            )
                            yield Select(
                                diff_sources,
                                id="diff-plane2",
                            )
                            yield Button(
                                "Diff",
                                id="diff-btn",
                                variant="primary",
                            )
                            yield Button(
                                "Copy", id="copy-diff-table",
                                classes="copy-btn", disabled=True,
                            )
                            yield Button(
                                "Diff vs .param",
                                id="diff-param-file-btn",
                                classes="copy-btn",
                            )
                        with Horizontal(id="diff-progress-row"):
                            yield ProgressBar(
                                id="diff-progress",
                                total=100,
                                show_eta=False,
                            )
                            yield Static("", id="diff-pct")
                        yield DataTable(id="diff-table")
                    with TabPane("Search", id="tab-search"):
                        yield Static(
                            "Full-text search across all ArduPilot "
                            "param names, display names, and "
                            "descriptions.",
                            classes="tab-desc",
                        )
                        yield Input(
                            placeholder="Search params...",
                            id="search-input",
                        )
                        yield DataTable(id="search-table")
                    # --- FC Tabs ---
                    with TabPane("FC Flash", id="tab-fc-flash"):
                        yield Static("Write params to FC over MAVLink.", classes="tab-desc")
                        with Horizontal(id="flash-options"):
                            yield Checkbox(
                                "Changed only",
                                id="flash-changed-only",
                                value=True,
                            )
                            yield Checkbox("Verify", id="flash-verify", value=True)
                            yield Checkbox("Dry run", id="flash-dry-run")
                        with Vertical(id="flash-legend"):
                            yield Static(
                                "Changed only — read FC first, "
                                "write only params that differ",
                                classes="tab-desc",
                            )
                            yield Static(
                                "Verify — read back each param "
                                "after writing to confirm",
                                classes="tab-desc",
                            )
                            yield Static(
                                "Dry run — show what would be "
                                "written without touching the FC",
                                classes="tab-desc",
                            )
                        with Horizontal(classes="action-row"):
                            yield Button(
                                "Flash", id="flash-btn",
                                variant="warning", disabled=True,
                            )
                            yield Button(
                                "Copy", id="copy-flash-log",
                                classes="copy-btn", disabled=True,
                            )
                        yield Log(id="flash-log")
                    with TabPane("FC Read", id="tab-fc-read"):
                        yield Static(
                            "Read all parameters from the "
                            "connected FC via MAVLink.",
                            classes="tab-desc",
                        )
                        yield Button(
                            "Read Params",
                            id="fc-read-btn",
                            variant="primary",
                            disabled=True,
                        )
                        with Horizontal(id="fc-read-progress-row"):
                            yield ProgressBar(
                                id="fc-read-progress",
                                total=100,
                                show_eta=False,
                            )
                            yield Static("", id="fc-read-pct")
                        yield DataTable(id="fc-read-table")
        yield FCConnectionBar()
        yield Footer()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        """Populate the Overview DataTable with chart information on startup."""
        self._show_charts_overview()

        # Pre-select second plane in diff-plane2 dropdown if available
        planes = self._scan_planes()
        if len(planes) >= 2:
            self.query_one("#diff-plane2", Select).value = planes[1][1]

        # If pymavlink is not available, hide the FC connection bar
        if not HAS_MAVLINK:
            self.query_one(FCConnectionBar).display = False

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle clicks on tree nodes."""
        tree = event.node.tree
        if tree.id == "planes-tree" and event.node.data is not None:
            abs_path = str(Path(self.config_dir) / event.node.data)
            self.active_plane = abs_path
            self.active_plane_rel = event.node.data
            # Mark selected plane in the tree
            for node in tree.root.children:
                stem = Path(node.data).stem if node.data else ""
                if node is event.node:
                    node.set_label(f">> {stem}")
                else:
                    node.set_label(stem)
            # Enable the Build button now that a plane is selected
            self.query_one("#build-btn", Button).disabled = False
            # Enable the Validate button now that a plane is selected
            self.query_one("#validate-btn", Button).disabled = False
# Enable FC buttons that require plane + connection
            self._update_fc_button_states()
            # Refresh Overview data; only switch tab if already on Overview
            current_tab = self.query_one(TabbedContent).active
            self._show_plane_overview(switch_tab=current_tab == "tab-overview")
            self.notify(f"Plane selected: {event.node.data}")
        elif tree.id == "charts-tree" and event.node.data is not None:
            data = str(event.node.data)
            if data.startswith("folder:"):
                # Clicked a folder — show only that folder's charts
                folder = data.removeprefix("folder:")
                self._show_folder_charts(folder)
            else:
                self._show_chart_params(data)
        elif tree.id == "charts-tree" and event.node.data is None:
            # Clicked "charts" root — reset to chart listing
            self._show_charts_overview()
        elif tree.id == "planes-tree" and event.node.data is None:
            # Clicked "planes" root — deselect plane, clear markers
            self.active_plane = None
            self.active_plane_rel = None
            for node in tree.root.children:
                stem = Path(node.data).stem if node.data else ""
                node.set_label(stem)
            self.query_one("#build-btn", Button).disabled = True
            self.query_one("#validate-btn", Button).disabled = True
            self._show_charts_overview()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        btn_id = event.button.id
        if btn_id == "refresh-btn":
            self._refresh_all()
        elif btn_id == "build-btn":
            self._run_build()
        elif btn_id == "validate-btn":
            self._run_validate()
        elif btn_id == "diff-btn":
            self._run_diff_planes()
        elif btn_id == "fc-refresh-btn":
            self.query_one(FCConnectionBar)._refresh_ports()
        elif btn_id == "fc-connect-btn":
            self._handle_fc_connect()
        elif btn_id == "fc-read-btn":
            self._run_fc_read()
        elif btn_id == "import-param-file-btn":
            self._import_param_file()
        elif btn_id == "flash-btn":
            self._run_flash()

        elif btn_id == "export-chart-btn":
            self._export_chart_zip()
        elif btn_id == "import-chart-btn":
            self._import_chart_zip()
        elif btn_id == "rename-btn":
            self._rename_active()
        elif btn_id == "delete-btn":
            self._delete_active()
        elif btn_id == "update-schema-btn":
            self._run_update_schema()
        elif btn_id == "diff-param-file-btn":
            self._diff_vs_param_file()
        elif btn_id and btn_id.startswith("copy-"):
            self._copy_widget_text(btn_id.removeprefix("copy-"))

    def _set_copy_enabled(self, copy_btn_id: str, enabled: bool) -> None:
        """Enable or disable a copy button."""
        try:
            self.query_one(f"#{copy_btn_id}", Button).disabled = not enabled
        except Exception:
            pass

    def _copy_widget_text(self, widget_id: str) -> None:
        """Copy text content of a Log or DataTable to clipboard and file."""
        try:
            widget = self.query_one(f"#{widget_id}")
        except Exception:
            self.notify("Nothing to copy", severity="warning")
            return

        if isinstance(widget, Log):
            text = "\n".join(widget.lines)
        elif isinstance(widget, DataTable):
            lines: list[str] = []
            # Header
            col_labels = [
                col.label.plain if hasattr(col.label, "plain") else str(col.label)
                for col in widget.columns.values()
            ]
            if col_labels:
                lines.append("\t".join(col_labels))
            # Rows
            for row_key in widget.rows:
                row_data = widget.get_row(row_key)
                cells = [
                    c.plain if hasattr(c, "plain") else str(c)
                    for c in row_data
                ]
                lines.append("\t".join(cells))
            text = "\n".join(lines)
        else:
            self.notify("Cannot copy this widget", severity="warning")
            return

        if not text.strip():
            self.notify("Nothing to copy", severity="warning")
            return

        self.copy_to_clipboard(text)
        self.notify("Copied to clipboard")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes."""
        if event.input.id == "overview-search":
            self._apply_overview_filter()
            return
        if event.input.id != "search-input":
            return
        try:
            _search_input = self.query_one("#search-input", Input)
        except Exception:
            return
        query = event.value.strip()
        if len(query) >= 2:
            self._run_search(query)
        else:
            # Clear the table when query is too short
            table = self.query_one("#search-table", DataTable)
            table.clear(columns=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in overview table."""
        if event.data_table.id != "overview-table":
            return

        row_data = event.data_table.get_row(event.row_key)

        # Charts list view — click opens that chart's params
        if self._overview_columns and self._overview_columns[0] == "Chart":
            chart_name = str(row_data[0])
            # If viewing a folder, prepend the folder prefix
            if self._active_folder:
                chart_name = f"{self._active_folder}/{chart_name}"
            self._show_chart_params(chart_name)
            return

        # Plane overview — click navigates to the chart in the Source column
        if (
            self._overview_columns
            and self._overview_columns[0] == "Param"
            and not self._active_chart
        ):
            if len(row_data) >= 3 and len(self._overview_columns) >= 3:
                source = str(row_data[2])
                # Source looks like "chart 'my_plane/battery' defaults"
                if "'" in source:
                    chart_name = source.split("'")[1]
                    chart_dir = Path(self.config_dir) / "charts" / chart_name
                    if chart_dir.exists():
                        self._show_chart_params(chart_name)
            return

        # Chart params view — click edits the value
        if not self._active_chart:
            return

        param_name = str(row_data[0])
        current_value = str(row_data[1])

        if current_value == "(available)":
            current_value = ""

        self._edit_chart_param(param_name, current_value)

    def _edit_chart_param(self, param_name: str, current_value: str) -> None:
        """Open dialog to edit a chart param value and save to defaults.yaml."""
        chart_name = self._active_chart
        schema = ParamSchema(self.config_dir)
        schema_def = schema.get(param_name)

        def _do_save(new_value: str | None) -> None:
            if new_value is None:
                return

            compositor = ParamCompositor(self.config_dir)
            defaults_path = compositor.charts_dir / chart_name / "defaults.yaml"

            # Load current defaults
            data = {}
            if defaults_path.exists():
                data = compositor.load_yaml(defaults_path)
            params = data.get("params", {})

            # Parse value
            try:
                parsed = int(new_value)
            except (ValueError, OverflowError):
                try:
                    parsed = float(new_value)
                except (ValueError, OverflowError):
                    parsed = new_value

            params[param_name] = parsed
            data["params"] = params

            with open(defaults_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)

            self.notify(f"{param_name} = {parsed}")
            self._show_chart_params(chart_name)

        self.push_screen(
            EditParamDialog(param_name, current_value, schema_def),
            _do_save,
        )

    # ------------------------------------------------------------------
    # Key-binding actions
    # ------------------------------------------------------------------

    def action_tab_overview(self) -> None:
        """Switch to the Overview tab."""
        self.query_one(TabbedContent).active = "tab-overview"

    def action_tab_validate(self) -> None:
        """Switch to the Validate tab."""
        self.query_one(TabbedContent).active = "tab-validate"

    def action_tab_diff(self) -> None:
        """Switch to the Diff Planes tab."""
        self.query_one(TabbedContent).active = "tab-diff-planes"

    def action_focus_search(self) -> None:
        """Focus the Search input and switch to the Search tab."""
        self.query_one(TabbedContent).active = "tab-search"
        try:
            self.query_one("#search-input", Input).focus()
        except Exception:
            pass

    def action_toggle_fc(self) -> None:
        """Toggle FC connection."""
        self._handle_fc_connect()

    def action_tab_flash(self) -> None:
        """Switch to the FC Flash tab."""
        self.query_one(TabbedContent).active = "tab-fc-flash"


    # ------------------------------------------------------------------
    # FC Connection management
    # ------------------------------------------------------------------

    def _handle_fc_connect(self) -> None:
        """Toggle FC connection state or abort a pending connection."""
        btn = self.query_one("#fc-connect-btn", Button)
        if str(btn.label) == "Abort":
            # Cancel the running connect worker and reset
            self.workers.cancel_group(self, "fc-connect")
            self._abort_fc_connect()
        elif self.mav_connection is not None:
            self._disconnect_fc()
        else:
            self._connect_fc()

    def _abort_fc_connect(self) -> None:
        """Clean up after aborting a connection attempt."""
        if self.mav_connection is not None:
            try:
                self.mav_connection.close()
            except Exception:
                pass
            self.mav_connection = None
        status = self.query_one("#fc-status", Static)
        status.update("Disconnected")
        btn = self.query_one("#fc-connect-btn", Button)
        btn.label = "Connect"
        btn.variant = "primary"
        btn.disabled = False
        self.notify("Connection aborted", severity="warning")

    @work(thread=True, exclusive=True, group="fc-connect")
    def _connect_fc(self) -> None:
        """Connect to FC in a background thread."""
        if not HAS_MAVLINK:
            self.notify("pymavlink not installed", severity="error")
            return

        port_select = self.query_one("#fc-port", Select)
        baud_select = self.query_one("#fc-baud", Select)
        port = str(port_select.value) if port_select.value != Select.BLANK else ""
        baud = int(baud_select.value) if baud_select.value != Select.BLANK else DEFAULT_BAUD

        if not port:
            self.notify("Select a serial port", severity="warning")
            return

        status = self.query_one("#fc-status", Static)
        status.update("Connecting...")
        btn = self.query_one("#fc-connect-btn", Button)
        btn.label = "Abort"
        btn.variant = "warning"

        try:
            mav = MAVLinkConnection(port, baud)  # pylint: disable=possibly-used-before-assignment
            self.mav_connection = mav
            sys_id = mav.conn.target_system
            comp_id = mav.conn.target_component
            status.update(f"Connected (sys {sys_id}, comp {comp_id})")
            btn.label = "Disconnect"
            btn.variant = "error"
            self._update_fc_button_states()
            self._refresh_battery()
            self.notify(f"Connected to {port}", severity="information")
        except Exception as exc:
            if self.mav_connection is not None:
                try:
                    self.mav_connection.close()
                except Exception:
                    pass
                self.mav_connection = None
            status.update("Disconnected")
            btn.label = "Connect"
            btn.variant = "primary"
            self.notify(f"Connection failed: {exc}", severity="error")

    def _disconnect_fc(self) -> None:
        """Disconnect from FC (runs on main thread — close() is fast)."""
        if self.mav_connection is not None:
            try:
                self.mav_connection.close()
            except Exception:
                pass
            self.mav_connection = None

        status = self.query_one("#fc-status", Static)
        status.update("Disconnected")
        battery = self.query_one("#fc-battery", Static)
        battery.update("")
        btn = self.query_one("#fc-connect-btn", Button)
        btn.label = "Connect"
        btn.variant = "primary"
        self._update_fc_button_states()
        self.notify("Disconnected from FC")

    @work(thread=True, exclusive=True, group="fc-battery")
    def _refresh_battery(self) -> None:
        """Read battery info from FC and update the label."""
        if self.mav_connection is None:
            return
        try:
            sys_status = self.mav_connection.get_sys_status()
            if sys_status:
                voltage = sys_status["voltage"] / 1000.0
                remaining = sys_status["remaining"]
                label = self.query_one("#fc-battery", Static)
                label.update(f"{voltage:.1f}V  {remaining}%")
        except Exception:
            pass

    def _update_fc_button_states(self) -> None:
        """Enable/disable FC-related buttons based on connection + plane state."""
        connected = self.mav_connection is not None
        has_plane = self.active_plane_rel is not None

        # Buttons that need connection only
        self.query_one("#fc-read-btn", Button).disabled = not connected

        # Buttons that need connection + plane
        self.query_one("#flash-btn", Button).disabled = not (connected and has_plane)

    # ------------------------------------------------------------------
    # Existing workers (Build, Show, Validate, Diff, Search)
    # ------------------------------------------------------------------

    def _refresh_all(self) -> None:
        """Refresh sidebar trees, diff dropdowns, and overview."""
        self.query_one(Sidebar).refresh_trees()
        # Refresh diff source dropdowns
        diff_sources = [("FC (live)", "__fc__")] + self._scan_planes()
        self.query_one("#diff-plane1", Select).set_options(diff_sources)
        self.query_one("#diff-plane2", Select).set_options(diff_sources)
        self._show_charts_overview()
        self.notify("Refreshed")

    def _run_build(self) -> None:
        """Build the active plane into a .param file."""
        if not self.active_plane_rel:
            self.notify("No plane selected.", severity="warning")
            return

        try:
            compositor = ParamCompositor(self.config_dir)
            result = compositor.load_plane(self.active_plane_rel)

            build_dir = Path(self.config_dir) / "build"
            build_dir.mkdir(parents=True, exist_ok=True)
            plane_stem = Path(self.active_plane_rel).stem
            output_path = build_dir / f"{plane_stem}.param"

            header = f"{result['name']} -- built by arducharts"
            ParamCompositor.to_param_file(
                result["params"], str(output_path), header=header
            )

            self.notify(
                f"Built {len(result['params'])} params → {output_path}",
                severity="information",
            )

        except Exception as exc:
            self.notify(f"Build failed: {exc}", severity="error")

    def _show_folder_charts(self, folder: str) -> None:
        """Show charts belonging to a specific folder."""
        self._active_chart = None
        self._active_folder = folder
        columns = ("Chart", "Version", "Params", "Base", "Description")
        rows: list[tuple[str, ...]] = []
        compositor = ParamCompositor(self.config_dir)
        for chart in compositor.list_charts():
            name = chart["name"]
            if not name.startswith(f"{folder}/"):
                continue
            label = name.split("/", 1)[1]
            rows.append((
                label,
                str(chart.get("version", "")),
                str(chart.get("params", 0)),
                ", ".join(chart.get("base", [])),
                chart.get("description", ""),
            ))
        self._overview_columns = columns
        self._overview_rows = rows
        self._apply_overview_filter()
        self.query_one(TabbedContent).active = "tab-overview"
        self.query_one("#breadcrumb", Static).update(f"Charts > {folder}")

    def _show_charts_overview(self) -> None:
        """Reset Overview table to the chart listing (startup view)."""
        self._active_chart = None
        self._active_folder = None
        columns = ("Chart", "Version", "Params", "Depends", "Description")
        rows: list[tuple[str, ...]] = []
        compositor = ParamCompositor(self.config_dir)
        for chart in compositor.list_charts():
            rows.append((
                chart["name"],
                str(chart.get("version", "")),
                str(chart.get("params", 0)),
                ", ".join(chart.get("depends", [])),
                chart.get("description", ""),
            ))
        self._overview_columns = columns
        self._overview_rows = rows
        self._apply_overview_filter()
        self.query_one(TabbedContent).active = "tab-overview"
        self.query_one("#breadcrumb", Static).update("Charts")

    def _show_plane_overview(self, switch_tab: bool = True) -> None:
        """Show the active plane's merged params in the Overview table."""
        if not self.active_plane_rel:
            return

        try:
            compositor = ParamCompositor(self.config_dir)
            result = compositor.load_plane(self.active_plane_rel)
            schema = ParamSchema(self.config_dir)

            columns = ("Param", "Value", "Source", "Description")
            rows: list[tuple[str, ...]] = []
            for key, value in result["params"].items():
                source = result["meta"].get(key, "")
                defn = schema.get(key)
                display = defn.get("DisplayName", "") if defn else ""
                rows.append((key, str(norm_value(value)), source, display))

            name = result["name"]

            self._active_chart = None
            self._overview_columns = columns
            self._overview_rows = rows
            self._apply_overview_filter()
            if switch_tab:
                self.query_one(TabbedContent).active = "tab-overview"
            self.query_one("#breadcrumb", Static).update(f"Planes > {name}")
        except Exception as exc:
            self.notify(f"Load failed: {exc}", severity="error")

    def _show_chart_params(self, chart_name: str) -> None:
        """Show a chart's params in the Overview table when clicked in sidebar."""
        compositor = ParamCompositor(self.config_dir)
        schema = ParamSchema(self.config_dir)
        chart_yaml = compositor.charts_dir / chart_name / "Chart.yaml"
        defaults_yaml = compositor.charts_dir / chart_name / "defaults.yaml"

        # Load chart meta for base info
        bases = []
        if chart_yaml.exists():
            meta = compositor.load_yaml(chart_yaml)
            bases = meta.get("base", [])

        # Active params (from defaults.yaml)
        active_params = {}
        if defaults_yaml.exists():
            data = compositor.load_yaml(defaults_yaml)
            active_params = data.get("params", {})

        # Collect available params from base schema
        base_params = set()
        for base_name in bases:
            base_params.update(compositor.get_schema_params(base_name))

        rows: list[tuple[str, ...]] = []
        # Show active params first
        for key, value in active_params.items():
            defn = schema.get(key)
            display = defn.get("DisplayName", "") if defn else ""
            in_base = key in base_params
            status = "" if not bases else ("" if in_base else "not in base")
            rows.append((key, str(norm_value(value)), status, display))

        # Show available (unused) base params
        available = sorted(base_params - set(active_params.keys()))
        for key in available:
            defn = schema.get(key)
            display = defn.get("DisplayName", "") if defn else ""
            rows.append((key, "(available)", "base", display))

        subtitle = f"chart: {chart_name}"
        if bases:
            subtitle += f" (base: {', '.join(bases)})"
            columns = ("Param", "Value", "Status", "Description")
            final_rows = rows
        else:
            columns = ("Param", "Value", "Description")
            final_rows = [(r[0], r[1], r[3]) for r in rows]

        self._active_chart = chart_name
        self._overview_columns = columns
        self._overview_rows = final_rows
        self._apply_overview_filter()
        self.query_one(TabbedContent).active = "tab-overview"
        if "/" in chart_name:
            folder, family = chart_name.split("/", 1)
            self.query_one("#breadcrumb", Static).update(f"Charts > {folder} > {family}")
        else:
            self.query_one("#breadcrumb", Static).update(f"Charts > {chart_name}")

    def _apply_overview_filter(self) -> None:
        """Repopulate the overview table, keeping only rows that match the filter."""
        table = self.query_one("#overview-table", DataTable)
        table.clear(columns=True)
        if not self._overview_columns:
            self._set_copy_enabled("copy-overview-table", False)
            return
        table.add_columns(*self._overview_columns)

        try:
            query = self.query_one("#overview-search", Input).value.strip().lower()
        except Exception:
            query = ""

        count = 0
        for row in self._overview_rows:
            if query and not any(query in cell.lower() for cell in row):
                continue
            table.add_row(*row)
            count += 1

        self._set_copy_enabled("copy-overview-table", count > 0)

    @work(thread=True, exclusive=True, group="validate")
    def _run_validate(self) -> None:
        """Run validation and lint checks on the active plane."""
        log = self.query_one("#validate-log", Log)
        log.clear()
        log.write_line("Running validation...")

        if not self.active_plane_rel:
            log.write_line("[ERROR] No plane selected.")
            return

        try:
            compositor = ParamCompositor(self.config_dir)
            result = compositor.load_plane(self.active_plane_rel)

            log.write_line(f"Config:    {result['name']}")
            log.write_line(f"Charts:    {', '.join(result['charts'])}")
            log.write_line(f"Installed: {len(result['installed'])} (with deps)")
            log.write_line(f"Params:    {len(result['params'])}")

            params = result["params"]
            errors: list[str] = []
            warnings: list[str] = []

            # -- Schema validation --
            schema = ParamSchema(self.config_dir)
            schema_errors, schema_warnings = schema.validate_params(params)
            errors.extend(schema_errors)
            warnings.extend(schema_warnings)

            # -- Lint checks --
            lint_warnings: list[str] = []

            # Run lint checks
            plane_path = Path(self.active_plane_rel)
            if not plane_path.is_absolute():
                plane_path = compositor.config_dir / plane_path
            lint_warnings.extend(
                lint_plane_config(compositor, plane_path, result)
            )

            # -- Output results --
            log.write_line("")

            if errors:
                log.write_line(f"Errors ({len(errors)}):")
                for e in errors:
                    log.write_line(f"  [ERROR] {e}")

            if warnings:
                log.write_line(f"Warnings ({len(warnings)}):")
                for w in warnings:
                    log.write_line(f"  [WARN] {w}")

            if lint_warnings:
                log.write_line(f"Lint ({len(lint_warnings)}):")
                for lw in lint_warnings:
                    log.write_line(f"  [LINT] {lw}")

            self._set_copy_enabled("copy-validate-log", True)

            if not errors and not warnings and not lint_warnings:
                log.write_line("All checks passed.")
                self.notify("Validation OK", severity="information")
            elif errors:
                self.notify(
                    f"Validation: {len(errors)} error(s)", severity="error"
                )
            else:
                self.notify(
                    f"Validation: {len(warnings) + len(lint_warnings)} warning(s)",
                    severity="warning",
                )

        except Exception as exc:
            log.write_line(f"[ERROR] {exc}")
            self._set_copy_enabled("copy-validate-log", True)
            self.notify(f"Validation failed: {exc}", severity="error")

    @work(thread=True, exclusive=True, group="search")
    def _run_search(self, query: str) -> None:
        """Search parameters and populate the search table."""
        table = self.query_one("#search-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Param", "DisplayName", "Units", "Range", "Description")

        try:
            schema = ParamSchema(self.config_dir)
            results = schema.search(query)
            for name, defn in results:
                display_name = defn.get("DisplayName", "")
                units = defn.get("Units", "")
                rng = defn.get("Range", {})
                if isinstance(rng, dict) and rng:
                    range_str = f"{rng.get('low', '')}..{rng.get('high', '')}"
                else:
                    range_str = ""
                description = defn.get("Description", "")
                table.add_row(name, display_name, units, range_str, description)
        except Exception as exc:
            self.notify(f"Search failed: {exc}", severity="error")

    def _resolve_diff_source(self, value: str) -> dict:
        """Load params from a plane config or live FC."""
        if value == "__fc__":
            if self.mav_connection is None:
                raise RuntimeError("Not connected to FC")

            progress_row = self.query_one("#diff-progress-row")
            progress_bar = self.query_one("#diff-progress", ProgressBar)
            pct_label = self.query_one("#diff-pct", Static)

            self.call_from_thread(setattr, progress_row, "display", True)
            self.call_from_thread(progress_bar.update, total=100, progress=0)
            self.call_from_thread(pct_label.update, "0%")

            def _on_progress(received: int, total: int | None) -> None:
                if total and total > 0:
                    pct = int(received * 100 / total)
                    self.call_from_thread(progress_bar.update, total=100, progress=pct)
                    self.call_from_thread(pct_label.update, f"{pct}%")

            fc_params = self.mav_connection.read_all_params(
                on_progress=_on_progress,
            )
            self.call_from_thread(progress_bar.update, total=100, progress=100)
            self.call_from_thread(pct_label.update, "100%")
            self.call_from_thread(setattr, progress_row, "display", False)
            return {
                "params": {k: norm_value(v) for k, v in fc_params.items()},
            }

        compositor = ParamCompositor(self.config_dir)
        return compositor.load_plane(value)

    @work(thread=True, exclusive=True, group="diff-planes")
    def _run_diff_planes(self) -> None:
        """Compare two param sources (planes or FC) and populate the diff table."""
        table = self.query_one("#diff-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Param", "Source 1", "Source 2", "Status")

        select1 = self.query_one("#diff-plane1", Select)
        select2 = self.query_one("#diff-plane2", Select)

        if Select.BLANK in (select1.value, select2.value):
            self.notify("Select two sources to diff.", severity="warning")
            return

        src1 = str(select1.value)
        src2 = str(select2.value)

        try:
            result1 = self._resolve_diff_source(src1)
            result2 = self._resolve_diff_source(src2)

            all_keys = set(result1["params"].keys()) | set(result2["params"].keys())

            for key in sorted(all_keys):
                in1 = key in result1["params"]
                in2 = key in result2["params"]
                if in1 and not in2:
                    table.add_row(
                        key,
                        str(norm_value(result1["params"][key])),
                        "",
                        "Only in 1",
                    )
                elif in2 and not in1:
                    table.add_row(
                        key,
                        "",
                        str(norm_value(result2["params"][key])),
                        "Only in 2",
                    )
                else:
                    v1 = norm_value(result1["params"][key])
                    v2 = norm_value(result2["params"][key])
                    if v1 != v2:
                        table.add_row(key, str(v1), str(v2), "Different")

            self._set_copy_enabled("copy-diff-table", True)
            self.notify("Diff complete.", severity="information")

        except Exception as exc:
            self.notify(f"Diff failed: {exc}", severity="error")
        finally:
            progress_row = self.query_one("#diff-progress-row")
            self.call_from_thread(setattr, progress_row, "display", False)

    # ------------------------------------------------------------------
    # Task 7: FC Read
    # ------------------------------------------------------------------

    @work(thread=True, exclusive=True, group="fc-read")
    def _run_fc_read(self) -> None:
        """Read all params from FC, show in table, then offer next actions."""
        table = self.query_one("#fc-read-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Param", "Value")

        if self.mav_connection is None:
            self.notify("Not connected to FC.", severity="error")
            return

        progress_row = self.query_one("#fc-read-progress-row")
        progress_bar = self.query_one("#fc-read-progress", ProgressBar)
        pct_label = self.query_one("#fc-read-pct", Static)

        progress_row.display = True
        progress_bar.update(total=100, progress=0)
        pct_label.update("0%")

        def _on_progress(received: int, total: int | None) -> None:
            if total and total > 0:
                pct = int(received * 100 / total)
                self.call_from_thread(progress_bar.update, total=100, progress=pct)
                self.call_from_thread(pct_label.update, f"{pct}%")

        try:
            self.notify("Reading params from FC...")
            fc_params = self.mav_connection.read_all_params(
                on_progress=_on_progress,
            )
            self._fc_params = fc_params

            self.call_from_thread(progress_bar.update, total=100, progress=100)
            self.call_from_thread(pct_label.update, "100%")

            for key in sorted(fc_params.keys()):
                table.add_row(key, str(fc_params[key]))

            # Show wizard dialog
            self.call_from_thread(
                self._show_fc_read_actions, len(fc_params),
            )
        except Exception as exc:
            self.notify(f"FC Read failed: {exc}", severity="error")
        finally:
            progress_row.display = False

    def _show_fc_read_actions(self, param_count: int) -> None:
        """Show action dialog after successful FC read."""

        def _on_action(action: str | None) -> None:
            if action == "export":
                self._export_fc_param()
            elif action == "import":
                self._import_fc_as_plane()

        self.push_screen(
            ActionDialog(
                f"Read {param_count} params. What next?",
                [
                    ("Export as .param file", "export", "primary"),
                    ("Import as Plane (create charts)", "import", "success"),
                ],
            ),
            _on_action,
        )

    def _export_fc_param(self) -> None:
        """Ask for filename, then export FC params to .param file."""
        if not self._fc_params:
            self.notify("No params to export. Read first.", severity="warning")
            return

        def _do_export(name: str | None) -> None:
            if name is None:
                return
            build_dir = Path(self.config_dir) / "build"
            build_dir.mkdir(parents=True, exist_ok=True)
            output = build_dir / f"{name}.param"
            ParamCompositor.to_param_file(
                dict(sorted(self._fc_params.items())),
                str(output),
                header="Read from FC",
            )
            self.notify(f"Exported: {output}", severity="information")

        self.push_screen(
            FilenameDialog("Export .param", default="fc_read"), _do_export
        )

    def _import_param_file(self) -> None:
        """Import a .param file → ask for plane name → create charts."""

        def _ask_path(filepath: str | None) -> None:
            if filepath is None:
                return
            if not filepath.endswith(".param"):
                self.notify("File must be a .param", severity="error")
                return

            path = Path(filepath)
            if not path.exists():
                self.notify(f"Not found: {path}", severity="error")
                return

            try:
                fc_params = ParamCompositor.read_param_file(path)
            except Exception as exc:
                self.notify(f"Failed to read: {exc}", severity="error")
                return

            default_name = path.stem

            def _do_create(name: str | None) -> None:
                if name is None:
                    return

                compositor = ParamCompositor(self.config_dir)
                charts, unmatched = compositor.import_as_charts(fc_params, name)

                plane: dict = {
                    "name": name,
                    "description": f"Imported from {path.name} ({len(fc_params)} params)",
                    "charts": charts,
                }
                if unmatched:
                    plane["extra_params"] = unmatched

                planes_dir = Path(self.config_dir) / "planes"
                planes_dir.mkdir(parents=True, exist_ok=True)
                output = planes_dir / f"{name}.yaml"
                with open(output, "w", encoding="utf-8") as f:
                    yaml.dump(plane, f, default_flow_style=False, sort_keys=False)

                self.notify(
                    f"Created {len(charts)} charts, {len(unmatched)} extra → {output}",
                )
                self._refresh_all()

            self.push_screen(
                FilenameDialog("Plane name", default=default_name), _do_create,
            )

        self.push_screen(
            FilenameDialog("Path to .param file", default="", raw=True),
            _ask_path,
        )

    def _import_fc_as_plane(self) -> None:
        """Ask for plane name, then create per-schema-family charts + plane config."""
        if not self._fc_params:
            self.notify("No params to import. Read first.", severity="warning")
            return

        def _do_import(name: str | None) -> None:
            if name is None:
                return

            compositor = ParamCompositor(self.config_dir)
            charts, unmatched = compositor.import_as_charts(
                self._fc_params, name,
            )

            # Create plane config referencing the new charts
            plane: dict = {
                "name": name,
                "description": f"Imported from FC ({len(self._fc_params)} params)",
                "charts": charts,
            }
            if unmatched:
                plane["extra_params"] = unmatched

            planes_dir = Path(self.config_dir) / "planes"
            planes_dir.mkdir(parents=True, exist_ok=True)
            output = planes_dir / f"{name}.yaml"
            with open(output, "w", encoding="utf-8") as f:
                yaml.dump(plane, f, default_flow_style=False, sort_keys=False)

            self.notify(
                f"Created {len(charts)} charts, {len(unmatched)} extra → {output}",
                severity="information",
            )

        self.push_screen(
            FilenameDialog("Import as Plane", default="my_plane"),
            _do_import,
        )

    # ------------------------------------------------------------------
    # Export / Import chart archives
    # ------------------------------------------------------------------


    def _export_chart_zip(self) -> None:
        """Export the active plane + its charts as a portable .zip."""
        name = None
        if self.active_plane_rel:
            name = Path(self.active_plane_rel).stem
        elif self._active_chart and "/" in self._active_chart:
            name = self._active_chart.split("/", 1)[0]

        if not name:
            self.notify("Select a plane first", severity="warning")
            return

        def _do_export(filename: str | None) -> None:
            if filename is None:
                return

            config_dir = Path(self.config_dir)
            files = collect_export_files(config_dir, name)

            if not files:
                self.notify(f"Nothing to export for '{name}'", severity="warning")
                return

            export_dir = config_dir / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            output = export_dir / f"{filename}.zip"
            write_export_zip(files, output)
            self.notify(f"Exported {len(files)} files → {output}")

        self.push_screen(
            FilenameDialog("Export as .zip", default=name), _do_export,
        )

    def _import_chart_zip(self) -> None:
        """Import a .zip chart archive — extract directly to config_dir."""
        import zipfile

        def _do_import(filepath: str | None) -> None:
            if filepath is None:
                return

            config_dir = Path(self.config_dir)
            if not filepath.endswith(".zip"):
                self.notify("File must be a .zip", severity="error")
                return
            archive = Path(filepath)
            if not archive.exists():
                self.notify(f"Not found: {archive}", severity="error")
                return

            try:
                with zipfile.ZipFile(str(archive), "r") as zf:
                    members = zf.namelist()

                    # Validate: only allow charts/ and planes/ entries
                    for m in members:
                        if not (m.startswith("charts/") or m.startswith("planes/")):
                            self.notify(
                                f"Invalid entry: {m}", severity="error",
                            )
                            return

                    # Warn if files already exist
                    existing = [
                        m for m in members if (config_dir / m).exists()
                    ]
                    if existing:
                        self.notify(
                            f"Overwriting {len(existing)} existing file(s)",
                            severity="warning",
                        )

                    # Extract directly to config_dir
                    for arcname in members:
                        target = config_dir / arcname
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(zf.read(arcname))

                    self.notify(
                        f"Imported {len(members)} files from {archive.name}"
                    )
                    self._refresh_all()
            except Exception as exc:
                self.notify(f"Import failed: {exc}", severity="error")

        exports_dir = str(Path(self.config_dir) / "exports") + "/"
        self.push_screen(
            FilenameDialog("Path to .zip", default=exports_dir, raw=True), _do_import,
        )

    # ------------------------------------------------------------------
    # Task 8: FC Flash
    # ------------------------------------------------------------------

    @work(thread=True, exclusive=True, group="fc-flash")
    def _run_flash(self) -> None:
        """Flash params to FC."""
        log = self.query_one("#flash-log", Log)
        log.clear()

        if self.mav_connection is None:
            log.write_line("[ERROR] Not connected to FC.")
            return
        if not self.active_plane_rel:
            log.write_line("[ERROR] No plane selected.")
            return

        changed_only = self.query_one("#flash-changed-only", Checkbox).value
        verify = self.query_one("#flash-verify", Checkbox).value
        dry_run = self.query_one("#flash-dry-run", Checkbox).value

        try:
            compositor = ParamCompositor(self.config_dir)
            result = compositor.load_plane(self.active_plane_rel)
            desired = result["params"]

            if changed_only:
                log.write_line("Reading current params to find differences...")
                current = self.mav_connection.read_all_params()
                changes, missing, _ = compute_param_diff(desired, current)
                params_to_write = {}
                for key, _, desired_val in changes:
                    params_to_write[key] = desired_val
                for key, val in missing:
                    params_to_write[key] = val

                if not params_to_write:
                    log.write_line("All parameters already match. Nothing to flash.")
                    self.notify("Nothing to flash — all match", severity="information")
                    return
                log.write_line(
                    f"{len(params_to_write)} params differ "
                    f"(out of {len(desired)} total)"
                )
            else:
                params_to_write = desired

            log.write_line(
                f"{'[DRY RUN] ' if dry_run else ''}"
                f"Flashing {len(params_to_write)} params to FC..."
            )
            log.write_line("")

            total = len(params_to_write)
            success = 0
            failed_list: list[str] = []

            for i, (key, value) in enumerate(params_to_write.items(), 1):
                if dry_run:
                    log.write_line(f"  [{i}/{total}] Would set {key} = {value}")
                    success += 1
                    continue
                ok = self.mav_connection.write_param(key, value)
                if ok:
                    log.write_line(f"  [{i}/{total}] {key} = {value}  OK")
                    success += 1
                else:
                    log.write_line(f"  [{i}/{total}] {key} = {value}  FAILED")
                    failed_list.append(key)

            log.write_line("")
            log.write_line(f"{success}/{total} parameters written")
            if failed_list:
                log.write_line(f"Failed: {', '.join(failed_list)}")

            # Verify
            if verify and not dry_run:
                log.write_line("")
                log.write_line("Verifying -- reading back params from FC...")
                readback = self.mav_connection.read_all_params()
                v_changes, v_missing, _ = compute_param_diff(
                    params_to_write, readback
                )
                if v_changes or v_missing:
                    log.write_line(
                        f"Verify FAILED -- "
                        f"{len(v_changes) + len(v_missing)} mismatch(es):"
                    )
                    for key, cur, exp in v_changes[:20]:
                        log.write_line(f"  {key}: expected {exp}, got {cur}")
                    for key, _ in v_missing[:20]:
                        log.write_line(f"  {key}: NOT FOUND on FC")
                else:
                    log.write_line(
                        f"Verify OK -- all {len(params_to_write)} params confirmed."
                    )

            self._set_copy_enabled("copy-flash-log", True)
            severity = "information" if not failed_list else "warning"
            self.notify(
                f"Flash {'(dry run) ' if dry_run else ''}complete: "
                f"{success}/{total}",
                severity=severity,
            )

        except Exception as exc:
            log.write_line(f"[ERROR] {exc}")
            self._set_copy_enabled("copy-flash-log", True)
            self.notify(f"Flash failed: {exc}", severity="error")

    # ------------------------------------------------------------------
    # Delete plane / chart / folder
    # ------------------------------------------------------------------

    def _delete_active(self) -> None:
        """Delete the currently active chart, folder, or plane."""
        config_dir = Path(self.config_dir)

        if self._active_chart:
            target = self._active_chart
            kind = "chart"
            msg = f"Delete chart '{target}' and all its files?"
        elif self._active_folder:
            target = self._active_folder
            kind = "folder"
            msg = f"Delete chart folder '{target}' and all its charts?"
        elif self.active_plane_rel:
            target = self.active_plane_rel
            kind = "plane"
            plane_stem = Path(target).stem
            msg = f"Delete plane '{plane_stem}'?"
        else:
            self.notify("Nothing selected to delete.", severity="warning")
            return

        def _on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                if kind == "chart":
                    chart_path = config_dir / "charts" / target
                    if chart_path.exists():
                        shutil.rmtree(chart_path)
                    self._active_chart = None
                elif kind == "folder":
                    folder_path = config_dir / "charts" / target
                    if folder_path.exists():
                        shutil.rmtree(folder_path)
                    self._active_folder = None
                elif kind == "plane":
                    plane_path = config_dir / target
                    if plane_path.exists():
                        os.remove(plane_path)
                    self.active_plane = None
                    self.active_plane_rel = None

                self.notify(f"Deleted {kind}: {target}")
                self._refresh_all()
            except Exception as exc:
                self.notify(f"Delete failed: {exc}", severity="error")

        self.push_screen(ConfirmDialog(msg), _on_confirm)

    # ------------------------------------------------------------------
    # Rename plane / chart / folder
    # ------------------------------------------------------------------

    def _rename_active(self) -> None:
        """Rename the currently active chart, folder, or plane."""
        config_dir = Path(self.config_dir)

        if self._active_chart:
            target = self._active_chart
            kind = "chart"
            old_name = Path(target).name
            title = f"Rename chart '{old_name}'"
        elif self._active_folder:
            target = self._active_folder
            kind = "folder"
            old_name = target
            title = f"Rename folder '{old_name}'"
        elif self.active_plane_rel:
            target = self.active_plane_rel
            kind = "plane"
            old_name = Path(target).stem
            title = f"Rename plane '{old_name}'"
        else:
            self.notify("Nothing selected to rename.", severity="warning")
            return

        def _on_name(new_name: str | None) -> None:
            if not new_name or new_name == old_name:
                return
            try:
                if kind == "plane":
                    old_path = config_dir / target
                    new_path = old_path.with_name(f"{new_name}.yaml")
                    if new_path.exists():
                        self.notify(f"Plane '{new_name}' already exists.", severity="error")
                        return
                    # Update the name field inside the YAML
                    with open(old_path, encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                    data["name"] = new_name
                    with open(old_path, "w", encoding="utf-8") as f:
                        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
                    old_path.rename(new_path)
                    self.active_plane = str(new_path)
                    self.active_plane_rel = str(new_path.relative_to(config_dir))

                elif kind == "chart":
                    old_chart_dir = config_dir / "charts" / target
                    # Preserve parent folder if chart is nested (e.g. folder/chart)
                    parent = Path(target).parent
                    new_target = str(parent / new_name) if str(parent) != "." else new_name
                    new_chart_dir = config_dir / "charts" / new_target
                    if new_chart_dir.exists():
                        self.notify(f"Chart '{new_name}' already exists.", severity="error")
                        return
                    # Update name in Chart.yaml
                    chart_yaml = old_chart_dir / "Chart.yaml"
                    if chart_yaml.exists():
                        with open(chart_yaml, encoding="utf-8") as f:
                            meta = yaml.safe_load(f) or {}
                        meta["name"] = new_name
                        with open(chart_yaml, "w", encoding="utf-8") as f:
                            yaml.dump(meta, f, default_flow_style=False, sort_keys=False)
                    old_chart_dir.rename(new_chart_dir)
                    # Update references in all plane configs
                    self._update_chart_refs(target, new_target)
                    self._active_chart = new_target

                elif kind == "folder":
                    old_folder = config_dir / "charts" / target
                    new_folder = config_dir / "charts" / new_name
                    if new_folder.exists():
                        self.notify(f"Folder '{new_name}' already exists.", severity="error")
                        return
                    # Collect old chart names before rename
                    old_charts = []
                    for chart_yaml in old_folder.rglob("Chart.yaml"):
                        rel = str(chart_yaml.parent.relative_to(config_dir / "charts"))
                        old_charts.append(rel)
                    old_folder.rename(new_folder)
                    # Update references for each chart that was in the folder
                    for old_ref in old_charts:
                        new_ref = new_name + old_ref[len(target):]
                        self._update_chart_refs(old_ref, new_ref)
                    self._active_folder = new_name

                self.notify(f"Renamed {kind}: {old_name} → {new_name}")
                self._refresh_all()
            except Exception as exc:
                self.notify(f"Rename failed: {exc}", severity="error")

        self.push_screen(FilenameDialog(title, default=old_name), _on_name)

    def _update_chart_refs(self, old_name: str, new_name: str) -> None:
        """Update all plane and chart files that reference a renamed chart."""
        config_dir = Path(self.config_dir)

        # Update plane configs: charts list and values keys
        planes_dir = config_dir / "planes"
        if planes_dir.exists():
            for plane_file in planes_dir.glob("*.yaml"):
                try:
                    with open(plane_file, encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                    changed = False
                    charts = data.get("charts", [])
                    for i, c in enumerate(charts):
                        if c == old_name:
                            charts[i] = new_name
                            changed = True
                    values = data.get("values", {})
                    if old_name in values:
                        values[new_name] = values.pop(old_name)
                        changed = True
                    if changed:
                        with open(plane_file, "w", encoding="utf-8") as f:
                            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
                except Exception:
                    pass

        # Update chart-to-chart depends references
        charts_dir = config_dir / "charts"
        if charts_dir.exists():
            for chart_yaml in charts_dir.rglob("Chart.yaml"):
                try:
                    with open(chart_yaml, encoding="utf-8") as f:
                        meta = yaml.safe_load(f) or {}
                    depends = meta.get("depends", [])
                    changed = False
                    for i, dep in enumerate(depends):
                        if dep == old_name:
                            depends[i] = new_name
                            changed = True
                    if changed:
                        with open(chart_yaml, "w", encoding="utf-8") as f:
                            yaml.dump(meta, f, default_flow_style=False, sort_keys=False)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Update Schema from TUI
    # ------------------------------------------------------------------

    @work(thread=True, exclusive=True, group="update-schema")
    def _run_update_schema(self) -> None:
        """Download latest param definitions and rebuild schema charts."""
        config_dir = Path(self.config_dir)

        self.app.call_from_thread(
            self.notify, "Downloading latest param definitions..."
        )

        try:
            schema = ParamSchema(self.config_dir)
            schema.refresh()

            families = build_schema_charts_data(config_dir)
            created, updated = rebuild_schema_charts(config_dir, families)

            total_families = len(families) - (1 if "_unmapped" in families else 0)
            self.app.call_from_thread(
                self.notify,
                f"Schema updated: {schema.count} params, "
                f"{created} created, {updated} updated, "
                f"{total_families} families",
                severity="information",
            )
        except Exception as exc:
            self.app.call_from_thread(
                self.notify, f"Schema update failed: {exc}", severity="error"
            )

    # ------------------------------------------------------------------
    # Diff vs .param file
    # ------------------------------------------------------------------

    def _diff_vs_param_file(self) -> None:
        """Open a dialog for a .param file path, then diff against active plane."""

        def _ask_path(filepath: str | None) -> None:
            if filepath is None:
                return
            if not filepath.strip():
                self.notify("No file path provided.", severity="warning")
                return

            path = Path(filepath.strip())
            if not path.exists():
                self.notify(f"Not found: {path}", severity="error")
                return

            if not self.active_plane_rel:
                self.notify("Select a plane first to diff against.", severity="warning")
                return

            try:
                param_file_params = ParamCompositor.read_param_file(path)
            except Exception as exc:
                self.notify(f"Failed to read .param file: {exc}", severity="error")
                return

            # Perform the diff
            try:
                compositor = ParamCompositor(self.config_dir)
                result = compositor.load_plane(self.active_plane_rel)
                plane_params = {k: norm_value(v) for k, v in result["params"].items()}
                file_params = {k: norm_value(v) for k, v in param_file_params.items()}

                table = self.query_one("#diff-table", DataTable)
                table.clear(columns=True)
                table.add_columns("Param", "Plane", ".param file", "Status")

                all_keys = set(plane_params.keys()) | set(file_params.keys())
                for key in sorted(all_keys):
                    in_plane = key in plane_params
                    in_file = key in file_params
                    if in_plane and not in_file:
                        table.add_row(key, str(plane_params[key]), "", "Only in plane")
                    elif in_file and not in_plane:
                        table.add_row(key, "", str(file_params[key]), "Only in .param")
                    else:
                        v1 = plane_params[key]
                        v2 = file_params[key]
                        if v1 != v2:
                            table.add_row(key, str(v1), str(v2), "Different")

                self._set_copy_enabled("copy-diff-table", True)
                self.query_one(TabbedContent).active = "tab-diff-planes"
                self.notify(f"Diff vs {path.name} complete.", severity="information")
            except Exception as exc:
                self.notify(f"Diff failed: {exc}", severity="error")

        self.push_screen(
            FilenameDialog("Path to .param file", default="", raw=True),
            _ask_path,
        )

def run_tui(config_dir: str = "configs"):
    """Create and run the APConfig TUI app."""
    app = APConfigApp(config_dir=config_dir)
    app.run()


if __name__ == "__main__":
    run_tui()
