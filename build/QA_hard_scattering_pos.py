#!/usr/bin/env python3
"""
Generate QA heatmaps for the energy density stored in JetData HDF5 files.

The script reads a specific frame, renders a logarithmic heatmap of the energy
density on the transverse (x, y) grid, and stores the result both as PNG and
PDF for convenient sharing.
"""
from __future__ import annotations
import argparse
import sys
from dataclasses import dataclass
import math
from pathlib import Path

import h5py
import matplotlib
import numpy as np
from matplotlib import colors

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  (defer until after Agg selection)


def ensure_parent_dir(path: str) -> None:
    """Create parent directory for a target file path if needed."""
    parent = Path(path).parent
    if parent and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)


@dataclass
class CentralityConfig:
    """Configuration container for one centrality selection."""

    label: str
    jetdata: Path
    hard_data: Path | None = None
    output_prefix: str | None = None
    frame: int | None = None
    hard_event: int | None = None
    dataset: str | None = None

    def __post_init__(self) -> None:
        self.jetdata = Path(self.jetdata)
        if self.hard_data is not None:
            self.hard_data = Path(self.hard_data)
        if self.output_prefix is not None:
            self.output_prefix = str(self.output_prefix)


# Fill this list with the centralities you want to draw on a shared canvas.
CENTRALITY_CONFIGS: list[CentralityConfig] = [
    CentralityConfig(
        label="0-2%",
        jetdata="/alice/data/dongguk/hydro_files_OO/cent_0_2/event-0/JetData.h5",
        hard_data="/alice/home/dongguk/Github/JETSCAPE/build/OO_cent_0_2_final_state_hadrons.dat",
        output_prefix="figures/centrality_0_2",
        frame=0,
    ),
    CentralityConfig(
        label="2-5%",
        jetdata="/alice/data/dongguk/hydro_files_OO/cent_2_5/event-0/JetData.h5",
        hard_data="/alice/home/dongguk/Github/JETSCAPE/build/OO_cent_2_5_final_state_hadrons.dat",
        output_prefix="figures/centrality_2_5",
        frame=0,
    ),
    CentralityConfig(
        label="5-10%",
        jetdata="/alice/data/dongguk/hydro_files_OO/cent_5_10/event-0/JetData.h5",
        hard_data="/alice/home/dongguk/Github/JETSCAPE/build/OO_cent_5_10_final_state_hadrons.dat",
        output_prefix="figures/centrality_5_10",
        frame=0,
    ),
    CentralityConfig(
        label="10-20%",
        jetdata="/alice/data/dongguk/hydro_files_OO/cent_10_20/event-0/JetData.h5",
        hard_data="/alice/home/dongguk/Github/JETSCAPE/build/OO_cent_10_20_final_state_hadrons.dat",
        output_prefix="figures/centrality_10_20",
        frame=0,
    ),
    CentralityConfig(
        label="20-30%",
        jetdata="/alice/data/dongguk/hydro_files_OO/cent_20_30/event-0/JetData.h5",
        hard_data="/alice/home/dongguk/Github/JETSCAPE/build/OO_cent_20_30_final_state_hadrons.dat",
        output_prefix="figures/centrality_20_30",
        frame=0,
    ),
    CentralityConfig(
        label="30-40%",
        jetdata="/alice/data/dongguk/hydro_files_OO/cent_30_40/event-0/JetData.h5",
        hard_data="/alice/home/dongguk/Github/JETSCAPE/build/OO_cent_30_40_final_state_hadrons.dat",
        output_prefix="figures/centrality_30_40",
        frame=0,
    ),
    CentralityConfig(
        label="40-50%",
        jetdata="/alice/data/dongguk/hydro_files_OO/cent_40_50/event-0/JetData.h5",
        hard_data="/alice/home/dongguk/Github/JETSCAPE/build/OO_cent_40_50_final_state_hadrons.dat",
        output_prefix="figures/centrality_40_50",
        frame=0,
    ),
    CentralityConfig(
        label="50-60%",
        jetdata="/alice/data/dongguk/hydro_files_OO/cent_50_60/event-0/JetData.h5",
        hard_data="/alice/home/dongguk/Github/JETSCAPE/build/OO_cent_50_60_final_state_hadrons.dat",
        output_prefix="figures/centrality_50_60",
        frame=0,
    ),
    CentralityConfig(
        label="60-70%",
        jetdata="/alice/data/dongguk/hydro_files_OO/cent_60_70/event-0/JetData.h5",
        hard_data="/alice/home/dongguk/Github/JETSCAPE/build/OO_cent_60_70_final_state_hadrons.dat",
        output_prefix="figures/centrality_60_70",
        frame=0,
    ),
    CentralityConfig(
        label="70-100%",
        jetdata="/alice/data/dongguk/hydro_files_OO/cent_70_100/event-0/JetData.h5",
        hard_data="/alice/home/dongguk/Github/JETSCAPE/build/OO_cent_70_100_final_state_hadrons.dat",
        output_prefix="figures/centrality_70_100",
        frame=0,
    ),
]

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QA plots for JetData energy density.")
    parser.add_argument(
        "-i",
        "--input",
        dest="jetdata",
        default="JetData.h5",
        help="Path to JetData HDF5 file (default: %(default)s).",
    )
    parser.add_argument(
        "-f",
        "--frame",
        type=int,
        default=0,
        help="Frame index to visualise (0-based).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="qa_hard_scattering_pos",
        help="Output file prefix for the saved figures.",
    )
    parser.add_argument(
        "--dataset",
        default="e",
        help="Dataset name inside each frame (default: %(default)s for energy density).",
    )
    parser.add_argument(
        "--log-floor",
        type=float,
        default=1.0e-6,
        help="Minimum positive value for the logarithmic color scale.",
    )
    parser.add_argument(
        "--temp-threshold",
        type=float,
        default=0.159,
        help="Ignore cells with Temp below this threshold (GeV). "
        "Use a negative value to disable masking (default: %(default)s).",
    )
    parser.add_argument(
        "--hard-data",
        default="OO_final_state_hadrons.dat",
        help="Path to the final-state hadrons file containing hard-scattering vertices.",
    )
    parser.add_argument(
        "--hard-event",
        type=int,
        help="Event ID inside the hard-data file to pick the vertex from.",
    )
    parser.add_argument(
        "--multi",
        action="store_true",
        help="Draw all entries from CENTRALITY_CONFIGS on a multi-pad canvas.",
    )
    parser.add_argument(
        "--multi-cols",
        type=int,
        default=0,
        help="Number of subplot columns when using --multi (default: auto).",
    )
    parser.add_argument(
        "--save-panels",
        action="store_true",
        help="With --multi, also save each centrality panel as its own PNG/PDF.",
    )
    parser.add_argument(
        "--multi-independent-scale",
        action="store_true",
        help="Allow each panel in --multi mode to use its own color scale (disables shared color bar).",
    )
    parser.add_argument(
        "--swap-axes",
        action="store_true",
        help="Transpose hydro grids so that the first array axis maps to x (useful when the stored data axes are flipped).",
    )
    return parser.parse_args()


def _attr_float(attrs, name: str) -> float | None:
    if name not in attrs:
        return None
    value = attrs[name]
    try:
        array = np.atleast_1d(value)
        return float(array.flat[0])
    except Exception:
        return None


def load_frame(jetdata_path: Path, frame_index: int, dataset: str):
    """Load the requested frame and dataset, returning data and metadata."""
    if not jetdata_path.exists():
        raise FileNotFoundError(f"JetData file not found: {jetdata_path}")

    with h5py.File(jetdata_path, "r") as jetdata:
        if "Event" not in jetdata:
            raise KeyError("The JetData file does not contain the expected 'Event' group.")

        event_group = jetdata["Event"]
        frames = sorted(event_group.keys())
        if not frames:
            raise ValueError("No frames available inside Event group.")

        if frame_index < 0 or frame_index >= len(frames):
            raise IndexError(f"Frame index {frame_index} out of range (0-{len(frames)-1}).")

        frame = event_group[frames[frame_index]]
        if dataset not in frame:
            available = ", ".join(frame.keys())
            raise KeyError(f"Dataset '{dataset}' not found in frame. Available: {available}")

        data = np.array(frame[dataset])
        temp_grid = np.array(frame["Temp"]) if "Temp" in frame else None

        time = float(frame.attrs.get("Time", [np.nan])[0])

        # Extract grid metadata from Event group attributes (when present).
        x_low = _attr_float(event_group.attrs, "XL")
        x_high = _attr_float(event_group.attrs, "XH")
        y_low = _attr_float(event_group.attrs, "YL")
        y_high = _attr_float(event_group.attrs, "YH")
        dx = _attr_float(event_group.attrs, "DX")
        dy = _attr_float(event_group.attrs, "DY")

    metadata = {
        "x_low": x_low,
        "x_high": x_high,
        "y_low": y_low,
        "y_high": y_high,
        "dx": dx,
        "dy": dy,
        "time": time,
        "frame_name": frames[frame_index],
    }
    return data, temp_grid, metadata


def maybe_swap_axes(
    data: np.ndarray,
    temp_grid: np.ndarray | None,
    metadata: dict,
    swap_axes: bool,
) -> tuple[np.ndarray, np.ndarray | None, dict]:
    """Optional transpose for cases where HDF5 stores x and y axes swapped."""
    if not swap_axes:
        return data, temp_grid, metadata

    swapped_metadata = metadata.copy()
    swapped_metadata["dx"], swapped_metadata["dy"] = metadata.get("dy"), metadata.get("dx")
    swapped_metadata["x_low"], swapped_metadata["y_low"] = metadata.get("y_low"), metadata.get("x_low")
    swapped_metadata["x_high"], swapped_metadata["y_high"] = metadata.get("y_high"), metadata.get("x_high")
    return data.T, None if temp_grid is None else temp_grid.T, swapped_metadata


def load_hard_scatter_vertices(path: Path, event_id: int | None):
    """Extract vertex coordinates for all (or a specific) events."""
    if not path.exists():
        return []

    vertices: list[tuple[float, float]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.lstrip().startswith("#"):
                    continue
                tokens = line.lstrip("# \t").split()
                if len(tokens) < 2:
                    continue
                data = {}
                i = 0
                while i + 1 < len(tokens):
                    key = tokens[i]
                    value = tokens[i + 1]
                    data[key] = value
                    i += 2

                event_value = data.get("Event")
                if event_value is None:
                    continue
                try:
                    event_value = int(float(event_value))
                except ValueError:
                    continue
                if event_id is not None and event_value != event_id:
                    continue

                vx = data.get("vertex_x")
                vy = data.get("vertex_y")
                if vx is None or vy is None:
                    continue
                try:
                    vertices.append((float(vx), float(vy)))
                except ValueError:
                    continue
    except OSError:
        return []
    return vertices


def prepare_heatmap_inputs(
    data: np.ndarray,
    temp_grid: np.ndarray | None,
    metadata: dict,
    log_floor: float,
    temp_threshold: float,
):
    """Mask the raw arrays and derive plotting metadata."""
    masked_data = data
    if temp_grid is not None and temp_threshold is not None and temp_threshold >= 0.0:
        mask = temp_grid >= temp_threshold
        masked_data = np.where(mask, data, np.nan)

    finite_positive = masked_data[np.isfinite(masked_data) & (masked_data > 0)]
    if finite_positive.size == 0:
        vmin = log_floor
        vmax = max(log_floor * 10.0, log_floor + 1e-6)
    else:
        vmin = max(log_floor, float(finite_positive.min()))
        vmax = float(finite_positive.max())

    if not np.isfinite(vmin) or vmin <= 0:
        vmin = log_floor
    if not np.isfinite(vmax) or vmax <= vmin:
        vmax = vmin * 1.5

    extent = None
    dx = metadata.get("dx")
    dy = metadata.get("dy")
    if isinstance(dx, float) and isinstance(dy, float) and dx > 0 and dy > 0:
        ny, nx = data.shape
        half_x = dx * nx / 2.0
        half_y = dy * ny / 2.0
        extent = (-half_x, half_x, -half_y, half_y)
    else:
        x_low = metadata.get("x_low")
        x_high = metadata.get("x_high")
        y_low = metadata.get("y_low")
        y_high = metadata.get("y_high")
        if None not in (x_low, x_high, y_low, y_high):
            extent = (x_low, x_high, y_low, y_high)

    if extent is None:
        raise ValueError("Grid metadata missing: cannot infer spatial extent.")

    plot_array = np.ma.masked_invalid(masked_data)
    plot_array = np.ma.masked_less_equal(plot_array, 0.0)
    return plot_array, extent, vmin, vmax


def add_hard_vertex_markers(ax, hard_vertices: list[tuple[float, float]]):
    if not hard_vertices:
        return None
    xs, ys = zip(*hard_vertices)
    return ax.scatter(
        xs,
        ys,
        marker="*",
        s=60,
        color="black",
        edgecolor="white",
        linewidth=0.3,
        zorder=5,
    )


def plot_energy_density(
    data: np.ndarray,
    temp_grid: np.ndarray | None,
    metadata: dict,
    log_floor: float,
    temp_threshold: float,
    output_prefix: str,
    hard_vertices: list[tuple[float, float]],
    title_override: str | None = None,
    norm: colors.Normalize | None = None,
):
    """Render and save the logarithmic energy-density heatmap."""
    plot_array, extent, vmin, vmax = prepare_heatmap_inputs(
        data=data,
        temp_grid=temp_grid,
        metadata=metadata,
        log_floor=log_floor,
        temp_threshold=temp_threshold,
    )

    fig, ax = plt.subplots(figsize=(6, 5), constrained_layout=True)
    log_norm = norm or colors.LogNorm(vmin=vmin, vmax=vmax)
    im = ax.imshow(
        plot_array,
        origin="lower",
        extent=extent,
        cmap="magma",
        norm=log_norm,
        aspect="equal",
    )
    ax.axhline(0.0, color="black", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.axvline(0.0, color="black", linestyle="--", linewidth=0.8, alpha=0.6)
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Energy density e")
    ax.set_xlabel("x [fm]")
    ax.set_ylabel("y [fm]")
    time = metadata["time"]
    title = title_override or f"{metadata['frame_name']} energy density"
    if not np.isnan(time):
        title += f" (tau = {time:.3f} fm/c)"
    ax.set_title(title)

    scatter_artist = add_hard_vertex_markers(ax, hard_vertices)
    if scatter_artist is not None:
        ax.legend(
            [scatter_artist],
            ["hard scattering point"],
            loc="upper right",
            frameon=True,
            framealpha=0.8,
        )

    png_path = f"{output_prefix}.png"
    pdf_path = f"{output_prefix}.pdf"
    ensure_parent_dir(png_path)
    fig.savefig(png_path, dpi=300)
    ensure_parent_dir(pdf_path)
    fig.savefig(pdf_path)
    plt.close(fig)
    return png_path, pdf_path


def plot_multiple_centralities(
    configs: list[CentralityConfig],
    dataset_default: str,
    frame_default: int,
    log_floor: float,
    temp_threshold: float,
    output_prefix: str,
    columns: int,
    save_individual: bool,
    hard_event_override: int | None,
    shared_scale: bool,
    swap_axes: bool,
):
    """Draw every entry from configs on a shared canvas with multiple pads."""
    if not configs:
        raise ValueError("CENTRALITY_CONFIGS is empty; add entries to enable --multi.")

    panels: list[dict] = []
    global_vmin: float | None = None
    global_vmax: float | None = None

    for config in configs:
        dataset_name = config.dataset or dataset_default
        frame_index = config.frame if config.frame is not None else frame_default
        data, temp_grid, metadata = load_frame(config.jetdata, frame_index, dataset_name)
        data, temp_grid, metadata = maybe_swap_axes(data, temp_grid, metadata, swap_axes)
        hard_vertices: list[tuple[float, float]] = []
        hard_event = hard_event_override if hard_event_override is not None else config.hard_event
        if config.hard_data:
            hard_vertices = load_hard_scatter_vertices(config.hard_data, hard_event)

        plot_array, extent, vmin, vmax = prepare_heatmap_inputs(
            data=data,
            temp_grid=temp_grid,
            metadata=metadata,
            log_floor=log_floor,
            temp_threshold=temp_threshold,
        )
        if shared_scale:
            global_vmin = vmin if global_vmin is None else min(global_vmin, vmin)
            global_vmax = vmax if global_vmax is None else max(global_vmax, vmax)
        panels.append(
            {
                "config": config,
                "data": data,
                "temp_grid": temp_grid,
                "metadata": metadata,
                "hard_vertices": hard_vertices,
                "plot_array": plot_array,
                "extent": extent,
                "vmin": vmin,
                "vmax": vmax,
            }
        )

    if shared_scale and (global_vmin is None or global_vmax is None):
        raise ValueError("Unable to determine global color scale for multi-plot.")

    count = len(panels)
    cols = columns if columns and columns > 0 else int(math.ceil(math.sqrt(count)))
    cols = max(cols, 1)
    rows = int(math.ceil(count / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(6 * cols, 5 * rows), constrained_layout=True)
    axes_flat = np.atleast_1d(axes).flatten()

    # Hide unused pads when grid > number of panels.
    for ax in axes_flat[count:]:
        ax.axis("off")

    saved_individual: list[tuple[str | None, str, str]] = []
    shared_norm = colors.LogNorm(vmin=global_vmin, vmax=global_vmax) if shared_scale else None
    last_image = None

    for ax, panel in zip(axes_flat, panels):
        config = panel["config"]
        metadata = panel["metadata"]
        hard_vertices = panel["hard_vertices"]
        plot_array = panel["plot_array"]
        extent = panel["extent"]
        local_norm = shared_norm or colors.LogNorm(vmin=panel["vmin"], vmax=panel["vmax"])
        im = ax.imshow(
            plot_array,
            origin="lower",
            extent=extent,
            cmap="magma",
            norm=local_norm,
            aspect="equal",
        )
        ax.axhline(0.0, color="black", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.axvline(0.0, color="black", linestyle="--", linewidth=0.8, alpha=0.6)
        if shared_scale:
            last_image = im
        else:
            cbar = fig.colorbar(im, ax=ax)
            cbar.set_label("Energy density e")
        ax.set_xlabel("x [fm]")
        ax.set_ylabel("y [fm]")
        title_components = [config.label or metadata["frame_name"]]
        time = metadata["time"]
        if not np.isnan(time):
            title_components.append(f"tau = {time:.3f} fm/c")
        ax.set_title("\n".join(title_components))

        scatter_artist = add_hard_vertex_markers(ax, hard_vertices)
        if scatter_artist is not None:
            ax.legend(
                [scatter_artist],
                ["hard scattering point"],
                loc="upper right",
                frameon=True,
                framealpha=0.8,
                fontsize="small",
            )

        if save_individual and config.output_prefix:
            png_path, pdf_path = plot_energy_density(
                data=panel["data"],
                temp_grid=panel["temp_grid"],
                metadata=metadata,
                log_floor=log_floor,
                temp_threshold=temp_threshold,
                output_prefix=config.output_prefix,
                hard_vertices=hard_vertices,
                title_override=config.label or metadata["frame_name"],
                norm=shared_norm,
            )
            saved_individual.append((config.label, png_path, pdf_path))

    if shared_scale and last_image is not None:
        cbar = fig.colorbar(
            last_image,
            ax=axes_flat[:count],
            location="right",
            fraction=0.035,
            pad=0.04,
        )
        cbar.set_label("Energy density e")

    png_path = f"{output_prefix}.png"
    pdf_path = f"{output_prefix}.pdf"
    ensure_parent_dir(png_path)
    fig.savefig(png_path, dpi=300)
    ensure_parent_dir(pdf_path)
    fig.savefig(pdf_path)
    plt.close(fig)
    return png_path, pdf_path, saved_individual


def main() -> int:
    args = parse_args()
    per_panel_outputs: list[tuple[str | None, str, str]] = []

    try:
        if args.multi:
            png_path, pdf_path, per_panel_outputs = plot_multiple_centralities(
                configs=CENTRALITY_CONFIGS,
                dataset_default=args.dataset,
                frame_default=args.frame,
                log_floor=args.log_floor,
                temp_threshold=args.temp_threshold,
                output_prefix=args.output,
                columns=args.multi_cols,
                save_individual=args.save_panels,
                hard_event_override=args.hard_event,
                shared_scale=not args.multi_independent_scale,
                swap_axes=args.swap_axes,
            )
        else:
            jetdata_path = Path(args.jetdata)
            data, temp_grid, metadata = load_frame(jetdata_path, args.frame, args.dataset)
            data, temp_grid, metadata = maybe_swap_axes(data, temp_grid, metadata, args.swap_axes)
            hard_vertices: list[tuple[float, float]] = []
            if args.hard_data:
                hard_vertices = load_hard_scatter_vertices(Path(args.hard_data), args.hard_event)
            png_path, pdf_path = plot_energy_density(
                data=data,
                temp_grid=temp_grid,
                metadata=metadata,
                log_floor=args.log_floor,
                temp_threshold=args.temp_threshold,
                output_prefix=args.output,
                hard_vertices=hard_vertices,
            )
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if args.multi:
        print(f"Wrote multi-centrality canvas: {png_path} and {pdf_path}")
        if per_panel_outputs:
            print("Saved individual panels:")
            for label, panel_png, panel_pdf in per_panel_outputs:
                label_text = label or "frame"
                print(f"  - {label_text}: {panel_png}, {panel_pdf}")
    else:
        print(f"Wrote {png_path} and {pdf_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
