#!/usr/bin/env python3

"""
QA helper for MUSIC evolution outputs.

Checks:
  - Event sampling within each centrality (event-to-event metric spread).
  - Centrality differences using event-<index> comparisons.
  - Axis ranges and grid center location from MUSIC headers.

Plots:
  - Per-centrality event sampling (metric vs event index).
  - Centrality trend for event-<index>.
  - Per-centrality heatmaps for event-<index>.
  - Combined heatmap grid for event-<index> across centralities.
"""

from __future__ import annotations

import argparse
import math
import re
import struct
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Sequence, Tuple

try:
    import matplotlib.pyplot as plt  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    plt = None  # type: ignore


MUSIC_FILENAME = "MUSIC_evo.dat"
HEADER_FLOATS = 16
HEADER_SIZE = HEADER_FLOATS * 4
METRIC_INDEX = {
    "temp": 6,
    "ed": 4,
}
METRIC_LABEL = {
    "temp": "Temperature (GeV)",
    "ed": "Energy density (GeV/fm^3)",
}
EVENT_RE = re.compile(r"(\d+)")


@dataclass(frozen=True)
class MusicHeader:
    raw: Tuple[float, ...]
    tau0: float
    dtau: float
    ixmax: int | None
    dx: float
    x_max: float
    iymax: int | None
    dy: float
    y_max: float
    ietamax: int | None
    deta: float
    eta_max: float
    turn_on_rhob: int | None
    turn_on_shear: int | None
    turn_on_bulk: int | None
    turn_on_diff: int | None
    nvar: int | None

    def signature(self, precision: int = 6) -> Tuple[float, ...]:
        return tuple(round(value, precision) for value in self.raw)


@dataclass
class Issue:
    path: Path
    message: str

    def format(self, relative_to: Path | None = None) -> str:
        if relative_to is not None:
            try:
                rel_path = self.path.relative_to(relative_to)
            except ValueError:
                rel_path = self.path
        else:
            rel_path = self.path
        return f"{rel_path}: {self.message}"


@dataclass
class EventMetricResult:
    value: float | None
    count: int
    header: MusicHeader | None
    max_itau: int | None


@dataclass
class GridResult:
    grid: List[List[float]]
    header: MusicHeader
    count: int
    value_sum: float
    value_min: float | None
    value_max: float | None
    max_itau: int | None


class RunningStats:
    """Welford accumulator for mean/std plus min/max tracking."""

    def __init__(self) -> None:
        self.count = 0
        self.mean = 0.0
        self._m2 = 0.0
        self.minimum: float | None = None
        self.maximum: float | None = None

    def push(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self._m2 += delta * delta2
        if self.minimum is None or value < self.minimum:
            self.minimum = value
        if self.maximum is None or value > self.maximum:
            self.maximum = value

    def summary(self) -> Tuple[float | None, float | None]:
        if self.count == 0:
            return None, None
        if self.count == 1:
            return self.mean, 0.0
        variance = self._m2 / (self.count - 1)
        return self.mean, math.sqrt(variance)


def _centrality_sort_key(name: str) -> Tuple[float, float]:
    parts = name.split("_")
    numbers = [
        float(part.replace("p", "."))
        for part in parts[1:]
        if part.replace("p", ".").replace(".", "", 1).isdigit()
    ]
    if len(numbers) == 1:
        numbers.append(numbers[0])
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    return math.inf, math.inf


def _event_sort_key(path: Path) -> Tuple[int, str]:
    match = EVENT_RE.search(path.name)
    if match:
        return int(match.group(1)), path.name
    return math.inf, path.name


def _format_stat(mean: float | None, std: float | None) -> str:
    if mean is None:
        return "--"
    if std is None or std == 0:
        return f"{mean:.3e}"
    return f"{mean:.3e} +/- {std:.3e}"


def _format_music_header(header: MusicHeader) -> str:
    ixmax = "--" if header.ixmax is None else str(header.ixmax)
    iymax = "--" if header.iymax is None else str(header.iymax)
    ietamax = "--" if header.ietamax is None else str(header.ietamax)
    nvar = "--" if header.nvar is None else str(header.nvar)
    rhob = "--" if header.turn_on_rhob is None else str(header.turn_on_rhob)
    shear = "--" if header.turn_on_shear is None else str(header.turn_on_shear)
    bulk = "--" if header.turn_on_bulk is None else str(header.turn_on_bulk)
    diff = "--" if header.turn_on_diff is None else str(header.turn_on_diff)
    return (
        f"tau0={header.tau0:.3g}, dtau={header.dtau:.3g}, "
        f"ix={ixmax}, iy={iymax}, dx={header.dx:.3g}, "
        f"ieta={ietamax}, deta={header.deta:.3g}, "
        f"nvar={nvar}, shear={shear}, bulk={bulk}, rhob={rhob}, diff={diff}"
    )


def _read_music_header(handle, path: Path) -> Tuple[MusicHeader | None, List[Issue]]:
    issues: List[Issue] = []
    header_bytes = handle.read(HEADER_SIZE)
    if len(header_bytes) < HEADER_SIZE:
        issues.append(
            Issue(
                path,
                f"header too short ({len(header_bytes)} bytes; expected {HEADER_SIZE})",
            )
        )
        return None, issues

    try:
        raw = struct.unpack("<16f", header_bytes)
    except struct.error as exc:
        issues.append(Issue(path, f"header unpack failed: {exc}"))
        return None, issues

    if not all(math.isfinite(value) for value in raw):
        issues.append(Issue(path, "header contains non-finite values"))

    def coerce_int(value: float, label: str) -> int | None:
        if not math.isfinite(value):
            issues.append(Issue(path, f"header {label} not finite: {value}"))
            return None
        rounded = int(round(value))
        if abs(value - rounded) > 1e-3:
            issues.append(Issue(path, f"header {label} not integer-like: {value}"))
            return None
        return rounded

    ixmax = coerce_int(raw[2], "ixmax")
    iymax = coerce_int(raw[5], "iymax")
    ietamax = coerce_int(raw[8], "ietamax")
    turn_on_rhob = coerce_int(raw[11], "turn_on_rhob")
    turn_on_shear = coerce_int(raw[12], "turn_on_shear")
    turn_on_bulk = coerce_int(raw[13], "turn_on_bulk")
    turn_on_diff = coerce_int(raw[14], "turn_on_diff")
    nvar = coerce_int(raw[15], "nvar")

    header = MusicHeader(
        raw=raw,
        tau0=raw[0],
        dtau=raw[1],
        ixmax=ixmax,
        dx=raw[3],
        x_max=raw[4],
        iymax=iymax,
        dy=raw[6],
        y_max=raw[7],
        ietamax=ietamax,
        deta=raw[9],
        eta_max=raw[10],
        turn_on_rhob=turn_on_rhob,
        turn_on_shear=turn_on_shear,
        turn_on_bulk=turn_on_bulk,
        turn_on_diff=turn_on_diff,
        nvar=nvar,
    )

    if header.dtau <= 0:
        issues.append(Issue(path, f"header dtau <= 0 ({header.dtau})"))
    if header.dx <= 0:
        issues.append(Issue(path, f"header dx <= 0 ({header.dx})"))
    if header.dy <= 0:
        issues.append(Issue(path, f"header dy <= 0 ({header.dy})"))
    if header.deta < 0:
        issues.append(Issue(path, f"header deta < 0 ({header.deta})"))
    if header.ixmax is not None and header.ixmax <= 0:
        issues.append(Issue(path, f"header ixmax <= 0 ({header.ixmax})"))
    if header.iymax is not None and header.iymax <= 0:
        issues.append(Issue(path, f"header iymax <= 0 ({header.iymax})"))
    if header.ietamax is not None and header.ietamax <= 0:
        issues.append(Issue(path, f"header ietamax <= 0 ({header.ietamax})"))
    if header.nvar is not None and header.nvar <= 0:
        issues.append(Issue(path, f"header nvar <= 0 ({header.nvar})"))

    return header, issues


def _iter_music_records(handle, nvar: int, chunk_records: int = 50000):
    record_struct = struct.Struct("<" + "f" * nvar)
    record_size = record_struct.size
    chunk_size = record_size * chunk_records
    remainder = b""

    while True:
        data = handle.read(chunk_size)
        if not data:
            break
        data = remainder + data
        n_records = len(data) // record_size
        if n_records == 0:
            remainder = data
            continue
        data_view = memoryview(data)
        for offset in range(0, n_records * record_size, record_size):
            yield record_struct.unpack_from(data_view, offset)
        remainder = data[n_records * record_size :]


def _compute_metric_value(total: float, count: int, stat: str) -> float | None:
    if count == 0:
        return None
    if stat == "sum":
        return total
    return total / count


def collect_event_metric(
    path: Path,
    tau_index: int,
    eta_index: int,
    metric_index: int,
    stat: str,
) -> Tuple[EventMetricResult, List[Issue]]:
    issues: List[Issue] = []
    if not path.exists():
        issues.append(Issue(path, "missing file"))
        return EventMetricResult(None, 0, None, None), issues
    try:
        size = path.stat().st_size
    except OSError as exc:
        issues.append(Issue(path, f"stat failed: {exc}"))
        return EventMetricResult(None, 0, None, None), issues
    if size == 0:
        issues.append(Issue(path, "file has zero size"))
        return EventMetricResult(None, 0, None, None), issues

    with path.open("rb") as handle:
        header, header_issues = _read_music_header(handle, path)
        issues.extend(header_issues)
        if header is None or header.nvar is None:
            return EventMetricResult(None, 0, header, None), issues

        if header.ietamax is not None and eta_index >= header.ietamax:
            issues.append(
                Issue(
                    path,
                    f"eta index {eta_index} out of range for ietamax={header.ietamax}",
                )
            )
            return EventMetricResult(None, 0, header, None), issues

        if metric_index >= header.nvar:
            issues.append(
                Issue(
                    path,
                    f"metric index {metric_index} out of range for nvar={header.nvar}",
                )
            )
            return EventMetricResult(None, 0, header, None), issues

        payload_size = size - HEADER_SIZE
        record_size = header.nvar * 4
        if payload_size < 0:
            issues.append(Issue(path, f"file smaller than header ({size} bytes)"))
        elif payload_size % record_size != 0:
            issues.append(
                Issue(
                    path,
                    "payload size not aligned to record size "
                    f"({payload_size} bytes, record {record_size} bytes)",
                )
            )

        total = 0.0
        count = 0
        max_itau = None
        for record in _iter_music_records(handle, header.nvar):
            itau = int(round(record[0]))
            if max_itau is None or itau > max_itau:
                max_itau = itau
            ieta = int(round(record[3]))
            if itau != tau_index or ieta != eta_index:
                continue
            total += record[metric_index]
            count += 1

        value = _compute_metric_value(total, count, stat)
        if count == 0:
            issues.append(
                Issue(
                    path,
                    f"no cells found for tau={tau_index}, eta={eta_index} "
                    f"(max tau seen: {max_itau})",
                )
            )

        return EventMetricResult(value, count, header, max_itau), issues


def read_event_grid(
    path: Path,
    tau_index: int,
    eta_index: int,
    metric_index: int,
) -> Tuple[GridResult | None, List[Issue]]:
    issues: List[Issue] = []
    if not path.exists():
        issues.append(Issue(path, "missing file"))
        return None, issues
    try:
        size = path.stat().st_size
    except OSError as exc:
        issues.append(Issue(path, f"stat failed: {exc}"))
        return None, issues
    if size == 0:
        issues.append(Issue(path, "file has zero size"))
        return None, issues

    with path.open("rb") as handle:
        header, header_issues = _read_music_header(handle, path)
        issues.extend(header_issues)
        if header is None or header.nvar is None:
            return None, issues
        if header.ixmax is None or header.iymax is None:
            issues.append(Issue(path, "missing ixmax/iymax in header"))
            return None, issues

        if header.ietamax is not None and eta_index >= header.ietamax:
            issues.append(
                Issue(
                    path,
                    f"eta index {eta_index} out of range for ietamax={header.ietamax}",
                )
            )
            return None, issues

        if metric_index >= header.nvar:
            issues.append(
                Issue(
                    path,
                    f"metric index {metric_index} out of range for nvar={header.nvar}",
                )
            )
            return None, issues

        grid = [
            [math.nan for _ in range(header.ixmax)]
            for _ in range(header.iymax)
        ]
        count = 0
        total = 0.0
        value_min = None
        value_max = None
        max_itau = None
        for record in _iter_music_records(handle, header.nvar):
            itau = int(round(record[0]))
            if max_itau is None or itau > max_itau:
                max_itau = itau
            ieta = int(round(record[3]))
            if itau != tau_index or ieta != eta_index:
                continue
            ix = int(round(record[1]))
            iy = int(round(record[2]))
            if ix < 0 or iy < 0 or ix >= header.ixmax or iy >= header.iymax:
                continue
            value = record[metric_index]
            grid[iy][ix] = value
            total += value
            count += 1
            if value_min is None or value < value_min:
                value_min = value
            if value_max is None or value > value_max:
                value_max = value

        if count == 0:
            issues.append(
                Issue(
                    path,
                    f"no cells found for tau={tau_index}, eta={eta_index} "
                    f"(max tau seen: {max_itau})",
                )
            )

        return (
            GridResult(
                grid=grid,
                header=header,
                count=count,
                value_sum=total,
                value_min=value_min,
                value_max=value_max,
                max_itau=max_itau,
            ),
            issues,
        )


def _axis_extent(header: MusicHeader) -> Tuple[float, float, float, float]:
    axis_max = max(abs(header.x_max), abs(header.y_max))
    return -axis_max, axis_max, -axis_max, axis_max


def _grid_center(header: MusicHeader) -> Tuple[float | None, float | None]:
    if header.ixmax is None or header.iymax is None:
        return None, None
    x_max = abs(header.x_max)
    y_max = abs(header.y_max)
    center_x = -x_max + header.dx * (header.ixmax - 1) / 2
    center_y = -y_max + header.dy * (header.iymax - 1) / 2
    return center_x, center_y


def discover_roots(user_roots: Iterable[Path]) -> List[Path]:
    if user_roots:
        roots = []
        for candidate in user_roots:
            if candidate.is_dir() and candidate.name.startswith("hydro_files_"):
                roots.append(candidate.resolve())
            elif candidate.is_dir():
                roots.extend(
                    sorted(
                        child.resolve()
                        for child in candidate.iterdir()
                        if child.is_dir() and child.name.startswith("hydro_files_")
                    )
                )
        return roots

    cwd = Path.cwd()
    return sorted(
        child.resolve()
        for child in cwd.iterdir()
        if child.is_dir() and child.name.startswith("hydro_files_")
    )


def iter_event_dirs(centrality_dir: Path) -> List[Path]:
    return sorted(
        (entry for entry in centrality_dir.iterdir() if entry.is_dir()),
        key=_event_sort_key,
    )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run QA checks on MUSIC evolution files in hydro output directories."
        )
    )
    parser.add_argument(
        "roots",
        nargs="*",
        type=Path,
        help="Paths to hydro_files directories (or their parents).",
    )
    parser.add_argument(
        "-p",
        "--paths",
        dest="paths",
        nargs="+",
        type=Path,
        help=(
            "Explicit hydro_files directories (or parents) to scan. "
            "Can be passed multiple times."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Save the QA report to this file (stdout is still used unless suppressed).",
    )
    parser.add_argument(
        "--centrality",
        nargs="+",
        help="Centrality directory names to scan (e.g. cent_0_10).",
    )
    parser.add_argument(
        "--expected-events",
        type=int,
        help="Expected number of event directories per centrality; warn if mismatched.",
    )
    parser.add_argument(
        "--event-index",
        type=int,
        default=0,
        help="Event index used for centrality comparisons (default: 0).",
    )
    parser.add_argument(
        "--event-limit",
        type=int,
        help="Max number of events per centrality to scan (default: all).",
    )
    parser.add_argument(
        "--event-stride",
        type=int,
        default=1,
        help="Take every Nth event per centrality (default: 1).",
    )
    parser.add_argument(
        "--tau-index",
        type=int,
        default=0,
        help="Tau frame index to analyze (default: 0).",
    )
    parser.add_argument(
        "--eta-index",
        type=int,
        default=0,
        help="Eta index to analyze (default: 0).",
    )
    parser.add_argument(
        "--metric",
        choices=sorted(METRIC_INDEX),
        default="ed",
        help="Metric for QA plots (default: ed).",
    )
    parser.add_argument(
        "--stat",
        choices=("mean", "sum"),
        default="mean",
        help="Aggregation for event metrics (default: mean).",
    )
    parser.add_argument(
        "--plot-dir",
        type=Path,
        help="Directory to store QA plots. If omitted, no plots are generated.",
    )
    parser.add_argument(
        "--plot-format",
        default="png",
        help="Image format for plots (default: png).",
    )
    parser.add_argument(
        "--swap-xy",
        action="store_true",
        help="Transpose heatmap grids before plotting, swapping the x and y axes.",
    )
    parser.add_argument(
        "--mean-trend-only",
        action="store_true",
        help=(
            "Only compute centrality mean trend plots; skip event sampling plots "
            "and event-0 heatmaps."
        ),
    )
    return parser.parse_args(argv)


def _select_event_dirs(
    event_dirs: List[Path],
    stride: int,
    limit: int | None,
) -> List[Path]:
    if stride < 1:
        stride = 1
    selected = event_dirs[::stride]
    if limit is not None:
        selected = selected[:limit]
    return selected


def _format_centrality_label(label: str) -> str:
    if label.startswith("cent_"):
        parts = label.split("_")[1:]
        if len(parts) >= 2:
            return f"{parts[0]}-{parts[1]}%"
    return label


def _plot_event_sampling(
    out_path: Path,
    event_indices: List[int],
    values: List[float],
    mean: float | None,
    std: float | None,
    title: str,
    ylabel: str,
) -> None:
    if plt is None:
        return
    if not event_indices:
        return
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(event_indices, values, marker="o", linewidth=1)
    if mean is not None:
        ax.axhline(mean, color="red", linestyle="--", linewidth=1)
    ax.set_title(title)
    ax.set_xlabel("Event index")
    ax.set_ylabel(ylabel)
    ax.grid(True, linestyle="--", alpha=0.3)
    if mean is not None and std is not None and mean != 0:
        cv = std / mean
        ax.text(
            0.98,
            0.02,
            f"mean={mean:.3e}, std={std:.3e}, cv={cv:.3f}",
            ha="right",
            va="bottom",
            transform=ax.transAxes,
        )
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def _plot_centrality_trend(
    out_path: Path,
    centralities: List[str],
    values: List[float],
    title: str,
    ylabel: str,
) -> None:
    if plt is None:
        return
    if not centralities:
        return
    x_positions = list(range(len(centralities)))
    fig, ax = plt.subplots(figsize=(7.5, 4))
    ax.plot(x_positions, values, marker="o", linewidth=1.5)
    ax.set_xticks(x_positions)
    ax.set_xticklabels([_format_centrality_label(label) for label in centralities], rotation=45, ha="right")
    ax.set_xlabel("Centrality bin")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, linestyle="--", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def _transpose_grid(grid: List[List[float]]) -> List[List[float]]:
    if not grid:
        return grid
    return [list(row) for row in zip(*grid)]


def _plot_heatmap(
    out_path: Path,
    grid: List[List[float]],
    extent: Tuple[float, float, float, float],
    title: str,
    ylabel: str,
    vmin: float | None = None,
    vmax: float | None = None,
) -> None:
    if plt is None:
        return
    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(
        grid,
        origin="lower",
        extent=extent,
        vmin=vmin,
        vmax=vmax,
        aspect="equal",
    )
    ax.axvline(0.0, color="white", linestyle="--", linewidth=0.8)
    ax.axhline(0.0, color="white", linestyle="--", linewidth=0.8)
    ax.set_xlabel("x [fm]")
    ax.set_ylabel("y [fm]")
    ax.set_title(title)
    fig.colorbar(im, ax=ax, label=ylabel)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def _plot_heatmap_grid(
    out_path: Path,
    grids: List[Tuple[str, List[List[float]]]],
    extent: Tuple[float, float, float, float],
    ylabel: str,
    vmin: float | None,
    vmax: float | None,
) -> None:
    if plt is None:
        return
    if not grids:
        return
    ncols = len(grids)
    nrows = 1
    fig, axes = plt.subplots(
        nrows=nrows,
        ncols=ncols,
        figsize=(3.2 * ncols + 0.8, 3.8),
        sharey=True,
        squeeze=False,
        gridspec_kw={"wspace": 0.0},
    )
    for idx, (label, grid) in enumerate(grids):
        ax = axes[0][idx]
        im = ax.imshow(
            grid,
            origin="lower",
            extent=extent,
            vmin=vmin,
            vmax=vmax,
            aspect="equal",
        )
        ax.axvline(0.0, color="white", linestyle="--", linewidth=0.8)
        ax.axhline(0.0, color="white", linestyle="--", linewidth=0.8)
        ax.set_title(_format_centrality_label(label))
        ax.set_xlabel("x [fm]")
        if idx == 0:
            ax.set_ylabel("y [fm]")
        else:
            ax.tick_params(labelleft=False)
    fig.subplots_adjust(left=0.045, right=0.91, bottom=0.14, top=0.88, wspace=0.0, hspace=0.0)
    cax = fig.add_axes([0.925, 0.18, 0.014, 0.64])
    fig.colorbar(im, cax=cax, label=ylabel)
    fig.savefig(out_path)
    plt.close(fig)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    start_time = time.perf_counter()

    user_roots: List[Path] = []
    if args.paths:
        user_roots.extend(args.paths)
    if args.roots:
        user_roots.extend(args.roots)

    roots = discover_roots(user_roots)
    if not roots:
        print(
            "No hydro_files_* directories found. Provide paths explicitly if they "
            "are located elsewhere.",
            file=sys.stderr,
        )
        return 1

    output_stream = None
    if args.output is not None:
        output_path = args.output
        if output_path.parent and not output_path.parent.exists():
            output_path.parent.mkdir(parents=True, exist_ok=True)
        output_stream = output_path.open("w", encoding="utf-8")

    def log(message: str = "", *, end: str = "\n") -> None:
        if message:
            print(message, end=end)
        else:
            print(end=end)
        if output_stream is not None:
            output_stream.write(f"{message}{end}")
            output_stream.flush()

    if args.plot_dir and plt is None:
        log("Warning: matplotlib is not available; plot generation skipped.")

    metric_index = METRIC_INDEX[args.metric]
    metric_label = METRIC_LABEL[args.metric]
    stat_label = args.stat
    eta_index = args.eta_index
    tau_index = args.tau_index
    mean_trend_only = args.mean_trend_only
    swap_xy = args.swap_xy

    total_events = 0
    all_issues: List[Issue] = []
    header_registry: Dict[Tuple[float, ...], set[Tuple[Path, str, str]]] = defaultdict(
        set
    )
    header_examples: Dict[Tuple[float, ...], MusicHeader] = {}

    plot_dir = args.plot_dir
    if plot_dir is not None:
        plot_dir.mkdir(parents=True, exist_ok=True)

    event0_grids: List[Tuple[str, List[List[float]], MusicHeader]] = []
    event0_values: List[Tuple[str, float]] = []
    centrality_mean_values: List[Tuple[str, float]] = []

    for root in roots:
        log(str(root))
        centrality_dirs = sorted(
            (
                child
                for child in root.iterdir()
                if child.is_dir() and not child.name.startswith(".")
            ),
            key=lambda p: _centrality_sort_key(p.name),
        )
        if args.centrality:
            centrality_dirs = [
                c for c in centrality_dirs if c.name in set(args.centrality)
            ]
        if not centrality_dirs:
            log("  no centrality directories found")
            all_issues.append(Issue(root, "no centrality directories found"))
            continue

        for cent_dir in centrality_dirs:
            event_dirs = iter_event_dirs(cent_dir)
            if not event_dirs:
                issues = [Issue(cent_dir, "no event directories found")]
                all_issues.extend(issues)
                log(f"  {cent_dir.name}: 0 events checked, 1 issue(s) detected")
                for issue in issues:
                    log(f"    - {issue.format(relative_to=root)}")
                continue

            if args.expected_events is not None and len(event_dirs) != args.expected_events:
                issue = Issue(
                    cent_dir,
                    f"expected {args.expected_events} events, found {len(event_dirs)}",
                )
                all_issues.append(issue)
                log(f"  {cent_dir.name}: {len(event_dirs)} events found (count mismatch)")
                log(f"    - {issue.format(relative_to=root)}")

            selected_event_dirs = _select_event_dirs(
                event_dirs, args.event_stride, args.event_limit
            )
            if not selected_event_dirs:
                issue = Issue(cent_dir, "no events selected after stride/limit")
                all_issues.append(issue)
                log(f"  {cent_dir.name}: 0 events selected")
                log(f"    - {issue.format(relative_to=root)}")
                continue

            stats = RunningStats()
            track_event_series = plot_dir is not None and not mean_trend_only
            event_metrics: List[Tuple[int, float]] = []
            issues: List[Issue] = []

            for event_dir in selected_event_dirs:
                total_events += 1
                event_path = event_dir / MUSIC_FILENAME
                result, event_issues = collect_event_metric(
                    event_path,
                    tau_index=tau_index,
                    eta_index=eta_index,
                    metric_index=metric_index,
                    stat=stat_label,
                )
                issues.extend(event_issues)
                if result.value is not None:
                    event_idx = _event_sort_key(event_dir)[0]
                    if track_event_series:
                        event_metrics.append((event_idx, result.value))
                    stats.push(result.value)
                if result.header:
                    signature = result.header.signature()
                    header_registry[signature].add(
                        (root, cent_dir.name, event_dir.name)
                    )
                    header_examples.setdefault(signature, result.header)

            if issues:
                log(
                    f"  {cent_dir.name}: {len(selected_event_dirs)} events checked, "
                    f"{len(issues)} issue(s) detected"
                )
                for issue in issues:
                    log(f"    - {issue.format(relative_to=root)}")
                all_issues.extend(issues)
            else:
                log(
                    f"  {cent_dir.name}: {len(selected_event_dirs)} events checked, OK"
                )

            mean, std = stats.summary()
            log(
                f"    metric ({args.metric}, {stat_label}) = "
                f"{_format_stat(mean, std)}"
            )
            if mean is not None:
                centrality_mean_values.append((cent_dir.name, mean))

            if event_metrics and plot_dir is not None and plt is not None:
                event_metrics.sort(key=lambda item: item[0])
                event_indices = [idx for idx, _ in event_metrics]
                values = [val for _, val in event_metrics]
                plot_path = (
                    plot_dir
                    / f"{cent_dir.name}_event_sampling_tau{tau_index:04d}.{args.plot_format}"
                )
                _plot_event_sampling(
                    plot_path,
                    event_indices,
                    values,
                    mean,
                    std,
                    title=(
                        f"{_format_centrality_label(cent_dir.name)}: {metric_label} ({stat_label}), "
                        f"tau={tau_index}, eta={eta_index}"
                    ),
                    ylabel=f"{metric_label} ({stat_label})",
                )

            # Event-index heatmap and centrality comparison
            if mean_trend_only:
                continue

            target_event_name = f"event-{args.event_index}"
            event_index_dir = next(
                (event_dir for event_dir in event_dirs if event_dir.name == target_event_name),
                None,
            )
            if event_index_dir is None:
                issue = Issue(
                    cent_dir, f"event directory not found: {target_event_name}"
                )
                all_issues.append(issue)
                log(f"    - {issue.format(relative_to=root)}")
                continue

            grid_result, grid_issues = read_event_grid(
                event_index_dir / MUSIC_FILENAME,
                tau_index=tau_index,
                eta_index=eta_index,
                metric_index=metric_index,
            )
            if grid_issues:
                for issue in grid_issues:
                    log(f"    - {issue.format(relative_to=root)}")
                all_issues.extend(grid_issues)
            if grid_result is None:
                continue

            header = grid_result.header
            signature = header.signature()
            header_registry[signature].add((root, cent_dir.name, target_event_name))
            header_examples.setdefault(signature, header)

            x_min, x_max, y_min, y_max = _axis_extent(header)
            center_x, center_y = _grid_center(header)
            expected_cells = header.ixmax * header.iymax
            coverage = grid_result.count / expected_cells if expected_cells else 0.0
            log(
                "    grid: "
                f"x=[{x_min:.3g}, {x_max:.3g}], "
                f"y=[{y_min:.3g}, {y_max:.3g}], "
                f"center=({center_x:.3g}, {center_y:.3g}), "
                f"cells={grid_result.count}/{expected_cells} "
                f"({coverage:.1%})"
            )

            value = _compute_metric_value(
                grid_result.value_sum, grid_result.count, stat_label
            )
            if value is not None:
                event0_values.append((cent_dir.name, value))

            if plot_dir is not None and plt is not None:
                heatmap_path = (
                    plot_dir
                    / f"{cent_dir.name}_event-{args.event_index}_tau{tau_index:04d}.{args.plot_format}"
                )
                _plot_heatmap(
                    heatmap_path,
                    _transpose_grid(grid_result.grid) if swap_xy else grid_result.grid,
                    extent=(x_min, x_max, y_min, y_max),
                    title=(
                        f"{_format_centrality_label(cent_dir.name)} {target_event_name}: "
                        f"{metric_label} (tau={tau_index}, eta={eta_index})"
                    ),
                    ylabel=metric_label,
                )
                event0_grids.append((cent_dir.name, _transpose_grid(grid_result.grid) if swap_xy else grid_result.grid, header))

        log()

    if header_registry:
        variants = sorted(
            header_registry.items(), key=lambda item: len(item[1]), reverse=True
        )
        if len(variants) == 1:
            signature, entries = variants[0]
            header = header_examples.get(signature)
            if header is not None:
                log("MUSIC header consistency: OK (single header variant)")
                log(f"  {len(entries)} event(s): {_format_music_header(header)}")
                log()
        else:
            log(f"MUSIC header variants detected: {len(variants)}")
            for signature, entries in variants[:5]:
                header = header_examples.get(signature)
                if header is None:
                    continue
                log(f"  {len(entries)} event(s): {_format_music_header(header)}")
                root, cent, event = next(iter(entries))
                log(f"    sample: {root}/{cent}/{event}")
            log()

    if plot_dir is not None and plt is not None and event0_values and not mean_trend_only:
        ordered = sorted(event0_values, key=lambda item: _centrality_sort_key(item[0]))
        cent_labels = [name for name, _ in ordered]
        values = [val for _, val in ordered]
        trend_path = plot_dir / f"centrality_event-{args.event_index}_trend.{args.plot_format}"
        _plot_centrality_trend(
            trend_path,
            cent_labels,
            values,
            title=(
                f"Event-{args.event_index}: {metric_label} ({stat_label}) "
                f"tau={tau_index}, eta={eta_index}"
            ),
            ylabel=f"{metric_label} ({stat_label})",
        )

    if plot_dir is not None and plt is not None and centrality_mean_values:
        ordered = sorted(
            centrality_mean_values, key=lambda item: _centrality_sort_key(item[0])
        )
        cent_labels = [name for name, _ in ordered]
        values = [val for _, val in ordered]
        trend_path = plot_dir / f"centrality_mean_trend.{args.plot_format}"
        _plot_centrality_trend(
            trend_path,
            cent_labels,
            values,
            title=(
                f"Centrality mean: {metric_label} ({stat_label}) "
                f"tau={tau_index}, eta={eta_index}"
            ),
            ylabel=f"{metric_label} ({stat_label})",
        )

    if plot_dir is not None and plt is not None and event0_grids and not mean_trend_only:
        ordered_grids = sorted(event0_grids, key=lambda item: _centrality_sort_key(item[0]))
        vmin = None
        vmax = None
        for _, grid, _ in ordered_grids:
            for row in grid:
                for value in row:
                    if not math.isfinite(value):
                        continue
                    if vmin is None or value < vmin:
                        vmin = value
                    if vmax is None or value > vmax:
                        vmax = value
        extent = _axis_extent(ordered_grids[0][2])
        grid_path = plot_dir / f"centrality_event-{args.event_index}_heatmaps.{args.plot_format}"
        _plot_heatmap_grid(
            grid_path,
            [(name, grid) for name, grid, _ in ordered_grids],
            extent=extent,
            ylabel=metric_label,
            vmin=vmin,
            vmax=vmax,
        )

    elapsed = time.perf_counter() - start_time
    log(
        f"Summary: {total_events} event directories checked across {len(roots)} "
        f"hydro file set(s)."
    )
    if all_issues:
        log(f"Issues detected: {len(all_issues)}")
    else:
        log("Issues detected: 0")
    log(f"Total runtime: {elapsed:.2f} s")

    if output_stream is not None:
        output_stream.close()

    return 1 if all_issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
