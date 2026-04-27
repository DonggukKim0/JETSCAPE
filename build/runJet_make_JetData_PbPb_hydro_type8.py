#!/usr/bin/env python3

from datetime import datetime
from collections import Counter
import argparse
import os
import pathlib
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

os.umask(0)

MAINGENERATOR = "Gen_PbPb_JetData"
wantDir = "hydro_files_PbPb"
HYDRO_CONFIG_DIR = "hydro_files_PbPb_cent_60_80"
CONFIG_FILENAME = "jetscape_user_hydro_files.xml"
TOTAL_EVENTS = 1
RESULTS_BASE = Path(os.environ.get("JETDATA_RESULTS_BASE", "/alice/data/dongguk/results_JetData"))
SHARED_HYDRO_DIR = Path("/alice/data/dongguk/temp")

RUN_EXECUTABLE = "./runJetscape"
TEMP_DIR_NAME = "temp"
STAGED_EVENT_NAME = "event-0"
OUTPUT_DIR_NAME = "out"
PREEQ_OUTPUT = "evolution_all_xyeta_fs.dat"
MUSIC_OUTPUT = "evolution_all_xyeta_MUSIC.dat"
PREEQ_RENAMED = "PreEq_evo.dat"
MUSIC_RENAMED = "MUSIC_evo.dat"


def extract_output_prefix(config_path: Path) -> str:
    """Return the preferred output filename prefix for a configuration."""
    try:
        root = ET.parse(config_path).getroot()
    except (ET.ParseError, FileNotFoundError):
        root = None
    value = None
    if root is not None:
        value = root.findtext('.//outputFilename')
        if value:
            value = value.strip()
    if value:
        return value
    stem = config_path.stem
    if '_' in stem:
        stem = stem.split('_')[-1]
    return stem or str(config_path)



    
def build_run_script(
        run_script_path: Path,
        initial_rel_paths: list[str],
        output_dir_names: list[str],
        config_rel_paths: list[str],
    ) -> None:
        total_jobs = len(initial_rel_paths)
        initial_lines = "\n".join(f'  "{rel}"' for rel in initial_rel_paths)
        output_lines = "\n".join(f'  "{name}"' for name in output_dir_names)
        config_lines = "\n".join(f'  "{rel}"' for rel in config_rel_paths)
        default_hydro_source = SHARED_HYDRO_DIR.as_posix()

        script_contents = f"""#!/bin/bash
    echo "INIT! $1 $2 $3 $4 $5"
    source alienv_envset.sh
    SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"

    HYDRO_SOURCE_DIR="${{HYDRO_SOURCE_DIR:-{default_hydro_source}}}"
    if [[ -z "$HYDRO_SOURCE_DIR" ]]; then
      echo "ERROR: HYDRO_SOURCE_DIR is not set. Provide a shared hydro_files_PbPb path via the environment." >&2
      exit 1
    fi
    if [[ ! -d "$HYDRO_SOURCE_DIR" ]]; then
      echo "ERROR: HYDRO_SOURCE_DIR '$HYDRO_SOURCE_DIR' does not exist or is not a directory." >&2
      exit 1
    fi
    if [[ -e "{wantDir}" && ! -L "{wantDir}" ]]; then
      echo "ERROR: {wantDir} exists locally and is not a symlink. Remove it so the shared directory can be linked." >&2
      exit 1
    fi
    ln -sfn "$HYDRO_SOURCE_DIR" "{wantDir}"
    
    
    INITIAL_FILES=(
    {initial_lines}
    )

    OUTPUT_LABELS=(
    {output_lines}
    )

    CONFIG_FILES=(
    {config_lines}
    )

    TOTAL_JOBS={total_jobs}

    INDEX_ARG="$2"
    SUBMIT_EPOCH_ARG="$3"
    JOB_SUBMIT_EPOCH=""

    if [[ -z "$INDEX_ARG" ]]; then
      echo "Missing job index argument." >&2
      exit 1
    fi

    if ! [[ "$INDEX_ARG" =~ ^[0-9]+$ ]]; then
      echo "Job index '$INDEX_ARG' is not an integer." >&2
      exit 1
    fi

    JOB_INDEX=$((INDEX_ARG))

    if (( JOB_INDEX < 0 || JOB_INDEX >= TOTAL_JOBS )); then
      echo "Job index $JOB_INDEX out of range (0..$((TOTAL_JOBS-1)))." >&2
      exit 1
    fi

    if [[ -n "$SUBMIT_EPOCH_ARG" ]]; then
      if [[ "$SUBMIT_EPOCH_ARG" =~ ^[0-9]+$ ]]; then
        JOB_SUBMIT_EPOCH="$SUBMIT_EPOCH_ARG"
        if SUBMIT_FMT=$(date -d @"$JOB_SUBMIT_EPOCH" +"%F %T" 2>/dev/null); then
          echo "Job submit time: $SUBMIT_FMT"
        else
          echo "Job submit epoch: $JOB_SUBMIT_EPOCH"
        fi
      else
        echo "Submit epoch '$SUBMIT_EPOCH_ARG' is not an integer." >&2
      fi
    fi

    INITIAL_PATH="${{INITIAL_FILES[$JOB_INDEX]}}"
    OUTPUT_LABEL="${{OUTPUT_LABELS[$JOB_INDEX]}}"
    CONFIG_PATH="${{CONFIG_FILES[$JOB_INDEX]}}"

    echo "Selected initial file: $INITIAL_PATH"
    echo "Output label: $OUTPUT_LABEL"
    echo "Config file: $CONFIG_PATH"

    TEMP_ROOT="{TEMP_DIR_NAME}"
    STAGED_DIR="$TEMP_ROOT/{STAGED_EVENT_NAME}"
    rm -rf "$TEMP_ROOT"
    mkdir -p "$STAGED_DIR"

    EVENT_SOURCE_DIR=$(dirname "$INITIAL_PATH")

    if [[ ! -d "$EVENT_SOURCE_DIR" ]]; then
      echo "ERROR: Event directory $EVENT_SOURCE_DIR not found." >&2
      exit 1
    fi

    cp -a "$EVENT_SOURCE_DIR"/. "$STAGED_DIR"/

    PREEQ_OUTPUT="{PREEQ_OUTPUT}"
    MUSIC_OUTPUT="{MUSIC_OUTPUT}"
    if [[ -f "$MUSIC_OUTPUT" ]]; then
      rm -f "$MUSIC_OUTPUT"
    fi
    if [[ -f "$PREEQ_OUTPUT" ]]; then
      rm -f "$PREEQ_OUTPUT"
    fi
    if [[ -f "{PREEQ_RENAMED}" ]]; then
      rm -f "{PREEQ_RENAMED}"
    fi
    if [[ -f "{MUSIC_RENAMED}" ]]; then
      rm -f "{MUSIC_RENAMED}"
    fi

    JOB_START_FMT=$(date +"%F %T")
    JOB_START_EPOCH=$(date +%s)
    echo "Job start time: $JOB_START_FMT"

    TIME_BIN=/usr/bin/time
    RUN_STATUS=0
    if [[ -x "$TIME_BIN" ]]; then
      TIME_REPORT=$(mktemp 2>/dev/null || true)
      if [[ -n "$TIME_REPORT" ]]; then
        "$TIME_BIN" -f "runJetscape summary: real=%E user=%U sys=%S maxRSS=%MkB" -o "$TIME_REPORT" ./runJetscape "$CONFIG_PATH"
        RUN_STATUS=$?
        cat "$TIME_REPORT"
        rm -f "$TIME_REPORT"
      else
        "$TIME_BIN" -f "runJetscape summary: real=%E user=%U sys=%S maxRSS=%MkB" ./runJetscape "$CONFIG_PATH"
        RUN_STATUS=$?
      fi
    else
      ./runJetscape "$CONFIG_PATH"
      RUN_STATUS=$?
    fi

    if (( RUN_STATUS != 0 )); then
      echo "runJetscape exited with status $RUN_STATUS" >&2
      rm -rf "$TEMP_ROOT"
      exit $RUN_STATUS
    fi

    if [[ -f "$PREEQ_OUTPUT" ]]; then
      echo "Found $PREEQ_OUTPUT after runJetscape"
    else
      echo "ERROR: Expected $PREEQ_OUTPUT was not produced." >&2
      rm -rf "$TEMP_ROOT"
      exit 1
    fi

    if [[ -f "$MUSIC_OUTPUT" ]]; then
      echo "Found $MUSIC_OUTPUT after runJetscape"
    else
      echo "ERROR: Expected $MUSIC_OUTPUT was not produced." >&2
      rm -rf "$TEMP_ROOT"
      exit 1
    fi

    OUTPUT_DIR="out/$OUTPUT_LABEL"
    mkdir -p "$OUTPUT_DIR"
    mv -f "$PREEQ_OUTPUT" "$OUTPUT_DIR/{PREEQ_RENAMED}"
    cp -f "$OUTPUT_DIR/{PREEQ_RENAMED}" "{PREEQ_RENAMED}"
    echo "Stored $OUTPUT_DIR/{PREEQ_RENAMED}"

    mv -f "$MUSIC_OUTPUT" "$OUTPUT_DIR/{MUSIC_RENAMED}"
    cp -f "$OUTPUT_DIR/{MUSIC_RENAMED}" "{MUSIC_RENAMED}"
    echo "Stored $OUTPUT_DIR/{MUSIC_RENAMED}"

    if [[ -n "$JOB_START_EPOCH" ]]; then
      JOB_END_FMT=$(date +"%F %T")
      JOB_END_EPOCH=$(date +%s)
      JOB_WALL=$((JOB_END_EPOCH - JOB_START_EPOCH))
      JOB_WALL_H=$((JOB_WALL / 3600))
      JOB_WALL_M=$(((JOB_WALL % 3600) / 60))
      JOB_WALL_S=$((JOB_WALL % 60))
      printf "Job end time: %s\n" "$JOB_END_FMT"
      printf "Total wall time: %02d:%02d:%02d (h:m:s)\n" "$JOB_WALL_H" "$JOB_WALL_M" "$JOB_WALL_S"
      printf "Total wall time (s): %d\n" "$JOB_WALL"
      if [[ -n "$JOB_SUBMIT_EPOCH" ]]; then
        JOB_WAIT=$((JOB_START_EPOCH - JOB_SUBMIT_EPOCH))
        if (( JOB_WAIT < 0 )); then
          JOB_WAIT=0
        fi
        TOTAL_FROM_SUBMIT=$((JOB_END_EPOCH - JOB_SUBMIT_EPOCH))
        if (( TOTAL_FROM_SUBMIT < 0 )); then
          TOTAL_FROM_SUBMIT=0
        fi
        JOB_WAIT_H=$((JOB_WAIT / 3600))
        JOB_WAIT_M=$(((JOB_WAIT % 3600) / 60))
        JOB_WAIT_S=$((JOB_WAIT % 60))
        TOTAL_SUBMIT_H=$((TOTAL_FROM_SUBMIT / 3600))
        TOTAL_SUBMIT_M=$(((TOTAL_FROM_SUBMIT % 3600) / 60))
        TOTAL_SUBMIT_S=$((TOTAL_FROM_SUBMIT % 60))
        printf "Queue wait time: %02d:%02d:%02d (h:m:s)\n" "$JOB_WAIT_H" "$JOB_WAIT_M" "$JOB_WAIT_S"
        printf "Queue wait time (s): %d\n" "$JOB_WAIT"
        printf "Submit-to-end time: %02d:%02d:%02d (h:m:s)\n" "$TOTAL_SUBMIT_H" "$TOTAL_SUBMIT_M" "$TOTAL_SUBMIT_S"
        printf "Submit-to-end time (s): %d\n" "$TOTAL_FROM_SUBMIT"
      fi
    fi

    rm -rf "$TEMP_ROOT"
    ls -althr
    echo "DONE!"
"""

        run_script_path.write_text(script_contents)
        os.chmod(run_script_path, 0o755)


def build_output_dir_names(config_rel_paths: list[str]) -> list[str]:
    stems = [pathlib.Path(rel).stem for rel in config_rel_paths]
    duplicate_stems = {stem for stem, count in Counter(stems).items() if count > 1}
    assigned: set[str] = set()
    output_dirs: list[str] = []

    for rel, stem in zip(config_rel_paths, stems):
        if stem not in duplicate_stems and stem not in assigned:
            name = stem
        else:
            pure_path = pathlib.PurePosixPath(rel).with_suffix("")
            parts = list(pure_path.parts)
            if parts and parts[0] == wantDir:
                parts = parts[1:]
            sanitized = "__".join(parts) if parts else stem
            name = sanitized or stem

        base_name = name
        suffix = 2
        while name in assigned:
            name = f"{base_name}_{suffix}"
            suffix += 1

        assigned.add(name)
        output_dirs.append(name)

    return output_dirs


def write_condor_submit(
    submit_path: Path,
    work_dir_label: str,
    work_dir_path: Path,
    output_dir: str,
    initial_index: int,
    submit_epoch: int,
) -> None:
    work_dir_posix = work_dir_path.as_posix()
    if not SHARED_HYDRO_DIR.exists():
        raise FileNotFoundError(f"hydro_files_PbPb directory not found at {SHARED_HYDRO_DIR}")
    hydro_source_env = SHARED_HYDRO_DIR.as_posix()
    submit_path.write_text(
        f"""Universe                = vanilla
Executable              = {work_dir_posix}/macro/run.sh
Accounting_Group        = group_alice
JobBatchName            = {work_dir_label}_{output_dir}
Log                     = {work_dir_posix}/logs/{output_dir}_$(InitialIndex).log
Output                  = {work_dir_posix}/{output_dir}_$(InitialIndex).out
Error                   = {work_dir_posix}/{output_dir}_$(InitialIndex).error
request_cpus            = 1
request_memory          = 16GB
request_disk            = 4GB
# Transfer all required executables and scripts
transfer_input_files    = Pythia8,{HYDRO_CONFIG_DIR},nanoDict_rdict.pcm,jcorranDict_rdict.pcm,alienv_envset.sh,runJetscape,jetscape_main.xml,EOS,LBT-tables,run.sh
# Transfer PreEq + MUSIC evolution output
transfer_output_files   = {PREEQ_RENAMED},{MUSIC_RENAMED}
transfer_output_remaps  = "{PREEQ_RENAMED}={work_dir_posix}/out/$(ConfigDir)/{PREEQ_RENAMED};{MUSIC_RENAMED}={work_dir_posix}/out/$(ConfigDir)/{MUSIC_RENAMED}"
Opt                     = {MAINGENERATOR}
ConfigDir               = {output_dir}
InitialIndex            = {initial_index}
SubmitEpoch             = {submit_epoch}
environment            = "HYDRO_SOURCE_DIR={hydro_source_env}"
arguments               = "$(Opt) $(InitialIndex) $(SubmitEpoch)"
should_transfer_files   = YES
when_to_transfer_output = ON_EXIT
periodic_remove         = (CurrentTime - EnteredCurrentStatus) > 604800
Notification            = Never

Queue 1
"""
    )


def gather_initial_files(base_path: Path) -> List[Path]:
    """Collect every initial.hdf5 file under the hydro directory."""
    hydro_root = base_path / wantDir
    if not hydro_root.exists():
        raise FileNotFoundError(f"Hydro directory not found: {hydro_root}")

    files = sorted(hydro_root.glob("cent_*_*/event-*/initial.hdf5"))
    if not files:
        raise FileNotFoundError(f"No initial.hdf5 files found under {hydro_root}")
    return files


def ensure_hydro_symlink(base_path: Path) -> None:
    """Ensure hydro_files_PbPb points at the shared hydro directory."""
    if not SHARED_HYDRO_DIR.exists():
        raise FileNotFoundError(f"hydro_files_PbPb directory not found at {SHARED_HYDRO_DIR}")

    link_path = base_path / wantDir
    if link_path.exists():
        if link_path.is_symlink():
            if link_path.resolve() != SHARED_HYDRO_DIR.resolve():
                link_path.unlink()
            else:
                return
        else:
            raise RuntimeError(
                f"{link_path} exists locally and is not a symlink. Remove it so the shared directory can be linked."
            )

    link_path.symlink_to(SHARED_HYDRO_DIR)


def config_path_for_centrality(base_path: Path, cent_name: str) -> Path:
    config_path = base_path / HYDRO_CONFIG_DIR / cent_name / CONFIG_FILENAME
    if not config_path.exists():
        raise FileNotFoundError(f"Missing config for {cent_name}: {config_path}")
    return config_path


def stage_event_directory(temp_root: Path, source_event_dir: Path) -> Path:
    """Copy the source event directory into temp/event-0 for Jetscape usage."""
    if temp_root.exists():
        shutil.rmtree(temp_root)

    target_dir = temp_root / STAGED_EVENT_NAME
    target_dir.mkdir(parents=True, exist_ok=True)

    for item in source_event_dir.iterdir():
        destination = target_dir / item.name
        if item.is_dir():
            shutil.copytree(item, destination)
        else:
            shutil.copy2(item, destination)

    return target_dir


def ensure_music_output_absent(base_path: Path) -> None:
    """Remove any leftover PreEq/MUSIC output files before starting the next run."""
    for name in (PREEQ_OUTPUT, MUSIC_OUTPUT, PREEQ_RENAMED, MUSIC_RENAMED):
        target = base_path / name
        if target.exists():
            target.unlink()


def run_jetscape_local(base_path: Path, config_path: Path) -> None:
    """Execute Jetscape with the hydro configuration for the staged event."""
    subprocess.run([RUN_EXECUTABLE, str(config_path)], cwd=base_path, check=True)


def store_music_output(base_path: Path, destination_dir: Path) -> tuple[Path, Path]:
    """Move the produced PreEq/MUSIC evolution files into the run-specific output directory."""
    preeq_source = base_path / PREEQ_OUTPUT
    music_source = base_path / MUSIC_OUTPUT
    if not preeq_source.exists():
        raise FileNotFoundError("runJetscape did not produce evolution_all_xyeta_fs.dat")
    if not music_source.exists():
        raise FileNotFoundError("runJetscape did not produce evolution_all_xyeta_MUSIC.dat")

    destination_dir.mkdir(parents=True, exist_ok=True)
    preeq_dest = destination_dir / PREEQ_RENAMED
    music_dest = destination_dir / MUSIC_RENAMED
    if preeq_dest.exists():
        preeq_dest.unlink()
    if music_dest.exists():
        music_dest.unlink()
    shutil.move(str(preeq_source), str(preeq_dest))
    shutil.move(str(music_source), str(music_dest))
    shutil.copy2(str(preeq_dest), str(base_path / PREEQ_RENAMED))
    shutil.copy2(str(music_dest), str(base_path / MUSIC_RENAMED))
    return preeq_dest, music_dest


def build_local_output_dir_name(cent_name: str, event_name: str) -> str:
    sanitized_event = event_name.replace("-", "_")
    return f"{cent_name}_{sanitized_event}"


def run_local_mode(main_path: Path) -> None:
    initial_files = gather_initial_files(main_path)
    total = len(initial_files)

    out_root = main_path / OUTPUT_DIR_NAME
    out_root.mkdir(parents=True, exist_ok=True)
    temp_root = main_path / TEMP_DIR_NAME

    print(f"Found {total} initial.hdf5 files under {wantDir}.")

    for index, initial_file in enumerate(initial_files, start=1):
        event_dir = initial_file.parent
        cent_dir_name = event_dir.parent.name
        event_dir_name = event_dir.name
        output_dir_name = build_local_output_dir_name(cent_dir_name, event_dir_name)
        destination_dir = out_root / output_dir_name

        relative_initial = initial_file.relative_to(main_path)
        print(f"[{index}/{total}] Processing {relative_initial}")

        config_path = config_path_for_centrality(main_path, cent_dir_name)
        config_rel = config_path.relative_to(main_path)

        try:
            stage_event_directory(temp_root, event_dir)
            ensure_music_output_absent(main_path)
            run_jetscape_local(main_path, config_rel)
            preeq_path, music_path = store_music_output(main_path, destination_dir)
            print(f"    Stored {preeq_path.relative_to(main_path)}")
            print(f"    Stored {music_path.relative_to(main_path)}")
        except subprocess.CalledProcessError as exc:
            print(f"    ERROR: runJetscape exited with status {exc.returncode}")
            raise
        except Exception as exc:
            print(f"    ERROR: {exc}")
            raise
        finally:
            if temp_root.exists():
                shutil.rmtree(temp_root)


def run_condor_mode(main_path: Path) -> None:
    main_dir = str(main_path)
    results_root = RESULTS_BASE
    results_root.mkdir(parents=True, exist_ok=True)

    initial_files = gather_initial_files(main_path)
    total_jobs = len(initial_files)
    print(f"Initial hydrodynamic profiles detected: {total_jobs}")

    initial_rel = [path.relative_to(main_path).as_posix() for path in initial_files]
    output_dir_names: list[str] = []
    config_rel: list[str] = []
    for initial_file in initial_files:
        event_dir = initial_file.parent
        cent_dir_name = event_dir.parent.name
        event_dir_name = event_dir.name
        output_dir_names.append(build_local_output_dir_name(cent_dir_name, event_dir_name))
        config_path = config_path_for_centrality(main_path, cent_dir_name)
        config_rel.append(config_path.relative_to(main_path).as_posix())

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    work_dir = f"{now}_{MAINGENERATOR}"
    work_dir_path = results_root / work_dir

    for sub in ["macro", "out", "logs"]:
        (work_dir_path / sub).mkdir(parents=True, exist_ok=True)
    for out_dir in output_dir_names:
        (work_dir_path / "out" / out_dir).mkdir(parents=True, exist_ok=True)

    run_sh_path = work_dir_path / "macro" / "run.sh"
    build_run_script(run_sh_path, initial_rel, output_dir_names, config_rel)

    submit_paths: list[Path] = []
    for job_index, out_dir in enumerate(output_dir_names):
        submit_path = work_dir_path / "macro" / f"condor_{job_index}.sub"
        submit_epoch = int(datetime.now().timestamp())
        write_condor_submit(
            submit_path,
            work_dir,
            work_dir_path,
            out_dir,
            job_index,
            submit_epoch,
        )
        submit_paths.append(submit_path)

    main_path_abs = pathlib.Path(main_dir)

    for idx, submit_path in enumerate(submit_paths, start=1):
        print(f"Submitting job {idx}/{total_jobs}")
        submit_rel = submit_path.as_posix()
        proc = subprocess.Popen(
            ['condor_submit', submit_rel],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=main_path_abs,
            text=True,
        )
        out, err = proc.communicate()
        if out:
            print(out.strip())
        if err:
            print(err.strip())
        if proc.returncode != 0:
            raise RuntimeError(f"condor_submit failed for {submit_path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare and submit Jetscape jobs.")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Run Jetscape sequentially for each initial.hdf5 instead of submitting to Condor.",
    )
    args = parser.parse_args()

    main_path = pathlib.Path(os.path.realpath(__file__)).parent

    ensure_hydro_symlink(main_path)

    if args.local:
        run_local_mode(main_path)
    else:
        run_condor_mode(main_path)


if __name__ == "__main__":
    main()
