#!/usr/bin/env python3
from datetime import datetime
from collections import Counter
import time
import subprocess
import pathlib
import os
import xml.etree.ElementTree as ET

os.umask(0)

MAINGENERATOR = "run_project_renewal_pp5020_cent_0_100"
wantDir = "project_renewal_pp5020_cent_0_100"
TOTAL_EVENTS = 1000
RESULTS_BASE = pathlib.Path("/alice/data/dongguk/results_JETSCAPE")
SHARED_HYDRO_DIR = None
SHARED_LBT_DIR = pathlib.Path("/alice/home/dongguk/Github/JETSCAPE/build/LBT-tables")
SHARED_EOS_DIR = pathlib.Path("/alice/home/dongguk/Github/JETSCAPE/build/EOS")
SHARED_PYTHIA_DIR = pathlib.Path("/alice/home/dongguk/Github/JETSCAPE/build/Pythia8")
ACCEPTANCE = "JYUAna_configurations.json"


def confirm_setting(label: str, value: object) -> None:
    print(f"{label}: {value}")
    answer = input("Is this correct? (yes/no): ").strip().lower()
    if answer != "yes":
        print("Stop.")
        raise SystemExit(1)


def progress_bar(current: int, total: int, width: int = 24) -> str:
    if total <= 0:
        return "[░░░░░░░░░░░░░░░░░░░░░░] 0/0"
    filled = int(width * current / total)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {current}/{total}"


def format_duration(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def render_progress_line(current: int, total: int, elapsed: float) -> str:
    percent = int((current / total) * 100) if total else 0
    if current <= 0:
        eta = "--:--"
    else:
        rate = elapsed / current
        eta = format_duration(rate * (total - current))
    return f"🚀 Submitting jobs... {progress_bar(current, total)}  {percent:3d}%  ⏱ ETA {eta}"


def print_launch_banner() -> None:
    print(f"🚀 Launching JETSCAPE: {MAINGENERATOR}")
    print(f"Config: {wantDir}  Events: {TOTAL_EVENTS}")
    print(f"Hydro: {SHARED_HYDRO_DIR}")
    print(f"LBT tables: {SHARED_LBT_DIR}")
    print(f"EOS: {SHARED_EOS_DIR}")
    print(f"Pythia8: {SHARED_PYTHIA_DIR}")
    print(f"Acceptance: {ACCEPTANCE}")
    print()


def gather_configurations(main_dir: str) -> list[pathlib.Path]:
    base_path = pathlib.Path(main_dir) / wantDir
    if not base_path.exists():
        raise FileNotFoundError(f"Configuration directory not found: {base_path}")

    config_files = sorted(path for path in base_path.rglob("*.xml") if path.is_file())
    if not config_files:
        raise RuntimeError(f"No configuration XML files found under {base_path}")
    return config_files


def extract_output_prefix(config_path: pathlib.Path) -> str:
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
    run_script_path: pathlib.Path, config_rel_paths: list[str], total_events: int
) -> None:
    config_lines = "\n".join(f"  \"{rel}\"" for rel in config_rel_paths)
    default_lbt_source = SHARED_LBT_DIR.as_posix()
    default_eos_source = SHARED_EOS_DIR.as_posix()
    default_pythia_source = SHARED_PYTHIA_DIR.as_posix()
    acceptance_name = pathlib.Path(ACCEPTANCE).name
    script_contents = f"""#!/bin/bash
echo \"INIT! $1 $2 $3 $4 $5\"
source alienv_envset.sh
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"

LBT_SOURCE_DIR="${{LBT_SOURCE_DIR:-{default_lbt_source}}}"
if [[ -z "$LBT_SOURCE_DIR" ]]; then
  echo "ERROR: LBT_SOURCE_DIR is not set. Provide a shared LBT-tables path via the environment." >&2
  exit 1
fi
if [[ ! -d "$LBT_SOURCE_DIR" ]]; then
  echo "ERROR: LBT_SOURCE_DIR '$LBT_SOURCE_DIR' does not exist or is not a directory." >&2
  exit 1
fi
if [[ -e "LBT-tables" && ! -L "LBT-tables" ]]; then
  echo "ERROR: LBT-tables exists locally and is not a symlink. Remove it so the shared directory can be linked." >&2
  exit 1
fi
ln -sfn "$LBT_SOURCE_DIR" LBT-tables

EOS_SOURCE_DIR="${{EOS_SOURCE_DIR:-{default_eos_source}}}"
if [[ -z "$EOS_SOURCE_DIR" ]]; then
  echo "ERROR: EOS_SOURCE_DIR is not set. Provide a shared EOS path via the environment." >&2
  exit 1
fi
if [[ ! -d "$EOS_SOURCE_DIR" ]]; then
  echo "ERROR: EOS_SOURCE_DIR '$EOS_SOURCE_DIR' does not exist or is not a directory." >&2
  exit 1
fi
if [[ -e "EOS" && ! -L "EOS" ]]; then
  echo "ERROR: EOS exists locally and is not a symlink. Remove it so the shared directory can be linked." >&2
  exit 1
fi
ln -sfn "$EOS_SOURCE_DIR" EOS

PYTHIA8_SOURCE_DIR="${{PYTHIA8_SOURCE_DIR:-{default_pythia_source}}}"
if [[ -z "$PYTHIA8_SOURCE_DIR" ]]; then
  echo "ERROR: PYTHIA8_SOURCE_DIR is not set. Provide a shared Pythia8 path via the environment." >&2
  exit 1
fi
if [[ ! -d "$PYTHIA8_SOURCE_DIR" ]]; then
  echo "ERROR: PYTHIA8_SOURCE_DIR '$PYTHIA8_SOURCE_DIR' does not exist or is not a directory." >&2
  exit 1
fi
if [[ -e "Pythia8" && ! -L "Pythia8" ]]; then
  echo "ERROR: Pythia8 exists locally and is not a symlink. Remove it so the shared directory can be linked." >&2
  exit 1
fi
ln -sfn "$PYTHIA8_SOURCE_DIR" Pythia8

ACCEPTANCE_FILE="{acceptance_name}"
if [[ ! -f "$ACCEPTANCE_FILE" ]]; then
  echo "ERROR: Acceptance config '$ACCEPTANCE_FILE' not found." >&2
  exit 1
fi
if [[ "$ACCEPTANCE_FILE" != "JYUAna_configurations.json" ]]; then
  ln -sfn "$ACCEPTANCE_FILE" JYUAna_configurations.json
fi

CONFIG_FILES=(
{config_lines}
)

CONFIG_COUNT=${{#CONFIG_FILES[@]}}
CONFIG_INDEX_ARG=\"$2\"
EVENT_INDEX_ARG=\"$3\"
TOTAL_EVENTS={total_events}

if [[ -z \"$CONFIG_INDEX_ARG\" || -z \"$EVENT_INDEX_ARG\" ]]; then
  echo \"Missing condor arguments (config index / event index).\" >&2
  exit 1
fi

if ! [[ \"$CONFIG_INDEX_ARG\" =~ ^[0-9]+$ ]]; then
  echo \"Config index '$CONFIG_INDEX_ARG' is not an integer.\" >&2
  exit 1
fi

if ! [[ \"$EVENT_INDEX_ARG\" =~ ^[0-9]+$ ]]; then
  echo \"Event index '$EVENT_INDEX_ARG' is not an integer.\" >&2
  exit 1
fi

CONFIG_INDEX=$((CONFIG_INDEX_ARG))
EVENT_INDEX=$((EVENT_INDEX_ARG))

if (( CONFIG_INDEX < 0 || CONFIG_INDEX >= CONFIG_COUNT )); then
  echo \"Config index $CONFIG_INDEX out of range (0..$((CONFIG_COUNT-1))).\" >&2
  exit 1
fi

if (( EVENT_INDEX < 0 || EVENT_INDEX >= TOTAL_EVENTS )); then
  echo \"Event index $EVENT_INDEX out of range (0..$((TOTAL_EVENTS-1))).\" >&2
  exit 1
fi

SUBMIT_EPOCH_ARG=\"$4\"
JOB_SUBMIT_EPOCH=\"\"
if [[ -n \"$SUBMIT_EPOCH_ARG\" ]]; then
  if [[ \"$SUBMIT_EPOCH_ARG\" =~ ^[0-9]+$ ]]; then
    JOB_SUBMIT_EPOCH=\"$SUBMIT_EPOCH_ARG\"
    if SUBMIT_FMT=$(date -d @\"$JOB_SUBMIT_EPOCH\" +\"%F %T\" 2>/dev/null); then
      echo \"Job submit time: $SUBMIT_FMT\"
    else
      echo \"Job submit epoch: $JOB_SUBMIT_EPOCH\"
    fi
  else
    echo \"Submit epoch '$SUBMIT_EPOCH_ARG' is not an integer.\" >&2
  fi
fi

CONFIG_PATH=\"${{CONFIG_FILES[$CONFIG_INDEX]}}\"
echo \"Running configuration: $CONFIG_PATH (event $EVENT_INDEX)\"

if ! RANDOM_SEED=$(python3 - <<'PY' "$CONFIG_PATH"
import pathlib
import random
import re
import sys
import xml.etree.ElementTree as ET

path = pathlib.Path(sys.argv[1])
rng = random.SystemRandom()
# Pythia8 accepts seeds in the range [1, 900000000]; keep values within bounds.
seed_value = rng.randrange(1, 900000001)
seed_text = str(seed_value)

try:
    original_text = path.read_text()
except Exception as exc:
    sys.stderr.write("Failed to read " + str(path) + ": " + str(exc) + "\\n")
    sys.exit(1)

seed_pattern = re.compile(r"(<\s*seed\s*>\s*)(-?\d+)(\s*<\s*/\s*seed\s*>)", re.IGNORECASE)
if seed_pattern.search(original_text):
    updated_text = seed_pattern.sub(lambda m: m.group(1) + seed_text + m.group(3), original_text, count=1)
    try:
        path.write_text(updated_text)
    except Exception as exc:
        sys.stderr.write("Failed to write " + str(path) + ": " + str(exc) + "\\n")
        sys.exit(1)
    print(seed_value)
    sys.exit(0)

try:
    tree = ET.ElementTree(file=path)
except Exception as exc:
    sys.stderr.write("Failed to parse " + str(path) + " when attempting to add seed: " + str(exc) + "\\n")
    sys.exit(1)

root = tree.getroot()
random_node = root.find('.//Random')
if random_node is None:
    random_node = ET.SubElement(root, 'Random')

seed_node = random_node.find('seed')
if seed_node is None:
    seed_node = ET.SubElement(random_node, 'seed')
seed_node.text = seed_text

tree.write(path, encoding='unicode')
print(seed_value)
PY
); then
  echo \"Failed to randomize seed for $CONFIG_PATH\" >&2
  exit 1
fi

if [[ -n \"$RANDOM_SEED\" ]]; then
  echo \"Random seed set to $RANDOM_SEED\"
fi

OUTPUT_PREFIX=$(python3 - <<'PY' "$CONFIG_PATH"
import sys
import xml.etree.ElementTree as ET
path = sys.argv[1]
try:
    root = ET.parse(path).getroot()
    value = root.findtext('.//outputFilename')
    if value:
        value = value.strip()
    if value:
        print(value)
except Exception:
    pass
PY
)
if [[ -z \"$OUTPUT_PREFIX\" ]]; then
  CONFIG_BASE=$(basename \"$CONFIG_PATH\")
  OUTPUT_PREFIX=${{CONFIG_BASE%.xml}}
  OUTPUT_PREFIX=${{OUTPUT_PREFIX##*_}}
fi
if [[ -z \"$OUTPUT_PREFIX\" ]]; then
  OUTPUT_PREFIX=\"$CONFIG_INDEX\"
fi

DATA_BASE=\"${{OUTPUT_PREFIX}}_final_state_hadrons\"
TREE_BASE=\"${{OUTPUT_PREFIX}}_tree\"
FINAL_BASE=\"${{OUTPUT_PREFIX}}_final\"
DATA_FILE=\"${{DATA_BASE}}.dat\"
TREE_FILE=\"${{TREE_BASE}}.root\"
FINAL_FILE=\"${{FINAL_BASE}}.root\"

JOB_START_FMT=$(date +"%F %T")
JOB_START_EPOCH=$(date +%s)
echo \"Job start time: $JOB_START_FMT\"

TIME_BIN=/usr/bin/time
RUN_STATUS=0
if [[ -x \"$TIME_BIN\" ]]; then
  TIME_REPORT=$(mktemp 2>/dev/null || true)
  if [[ -n \"$TIME_REPORT\" ]]; then
    \"$TIME_BIN\" -f \"runJetscape summary: real=%E user=%U sys=%S maxRSS=%MkB\" -o \"$TIME_REPORT\" ./runJetscape \"$CONFIG_PATH\"
    RUN_STATUS=$?
    cat \"$TIME_REPORT\"
    rm -f \"$TIME_REPORT\"
  else
    \"$TIME_BIN\" -f \"runJetscape summary: real=%E user=%U sys=%S maxRSS=%MkB\" ./runJetscape \"$CONFIG_PATH\"
    RUN_STATUS=$?
  fi
else
  ./runJetscape \"$CONFIG_PATH\"
  RUN_STATUS=$?
fi
if (( RUN_STATUS != 0 )); then
  echo \"runJetscape exited with status $RUN_STATUS\" >&2
  exit $RUN_STATUS
fi

# 2) Convert to JTree
if [[ -f \"$DATA_FILE\" ]]; then
  echo \"Converting to JTree...\"
  ./jetscapeToJTree \"$DATA_FILE\" \"$TREE_FILE\"
else
  echo \"ERROR: Expected $DATA_FILE not found after event $EVENT_INDEX!\" >&2
  exit 1
fi

# 3) Generate mylist
LIST_PATH=\"./$TREE_FILE\"
echo \"$LIST_PATH\" > mylist
echo \"Contents of mylist:\"
cat mylist

# 4) Run JYUAna
if [[ -f JYUAna ]]; then
  echo \"Running JYUAna...\"
  ./JYUAna mylist \"$FINAL_FILE\"
else
  echo \"ERROR: JYUAna executable not found!\" >&2
  exit 1
fi

EVENT_SUFFIX=_$EVENT_INDEX

DATA_EVENT_FILE=\"${{DATA_BASE}}${{EVENT_SUFFIX}}.dat\"
TREE_EVENT_FILE=\"${{TREE_BASE}}${{EVENT_SUFFIX}}.root\"
FINAL_EVENT_FILE=\"${{FINAL_BASE}}${{EVENT_SUFFIX}}.root\"

if [[ -f \"$DATA_FILE\" ]]; then
  mv -f \"$DATA_FILE\" \"$DATA_EVENT_FILE\"
fi

if [[ -f \"$TREE_FILE\" ]]; then
  mv -f \"$TREE_FILE\" \"$TREE_EVENT_FILE\"
fi

if [[ -f \"$FINAL_FILE\" ]]; then
  mv -f \"$FINAL_FILE\" \"$FINAL_EVENT_FILE\"
fi

if [[ -n \"$JOB_START_EPOCH\" ]]; then
  JOB_END_FMT=$(date +"%F %T")
  JOB_END_EPOCH=$(date +%s)
  JOB_WALL=$((JOB_END_EPOCH - JOB_START_EPOCH))
  JOB_WALL_H=$((JOB_WALL / 3600))
  JOB_WALL_M=$(((JOB_WALL % 3600) / 60))
  JOB_WALL_S=$((JOB_WALL % 60))
  printf \"Job end time: %s\n\" \"$JOB_END_FMT\"
  printf \"Total wall time: %02d:%02d:%02d (h:m:s)\n\" \"$JOB_WALL_H\" \"$JOB_WALL_M\" \"$JOB_WALL_S\"
  printf \"Total wall time (s): %d\n\" \"$JOB_WALL\"
  if [[ -n \"$JOB_SUBMIT_EPOCH\" ]]; then
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
    printf \"Queue wait time: %02d:%02d:%02d (h:m:s)\n\" \"$JOB_WAIT_H\" \"$JOB_WAIT_M\" \"$JOB_WAIT_S\"
    printf \"Queue wait time (s): %d\n\" \"$JOB_WAIT\"
    printf \"Submit-to-end time: %02d:%02d:%02d (h:m:s)\n\" \"$TOTAL_SUBMIT_H\" \"$TOTAL_SUBMIT_M\" \"$TOTAL_SUBMIT_S\"
    printf \"Submit-to-end time (s): %d\n\" \"$TOTAL_FROM_SUBMIT\"
  fi
fi

ls -althr
echo \"DONE!\"
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
    submit_path: pathlib.Path,
    work_dir_name: str,
    work_dir_path: pathlib.Path,
    config_dir: str,
    config_index: int,
    output_prefix: str,
    total_events: int,
    submit_epoch: int,
    main_dir: str,
) -> None:
    event_lines = "\n".join(str(i) for i in range(total_events))
    transfer_outputs = ",".join(
        [
            # f"{output_prefix}_final_state_hadrons_$(EventIndex).dat",
            # f"{output_prefix}_tree_$(EventIndex).root",
            f"{output_prefix}_final_$(EventIndex).root",
        ]
    )
    main_path = pathlib.Path(main_dir)
    work_dir_posix = work_dir_path.as_posix()
    transfer_sources = [
        main_path / wantDir,
        main_path / ACCEPTANCE,
        main_path / "nanoDict_rdict.pcm",
        main_path / "jcorranDict_rdict.pcm",
        main_path / "alienv_envset.sh",
        main_path / "runJetscape",
        main_path / "jetscapeToJTree",
        main_path / "JYUAna",
        main_path / "jetscape_main.xml",
        main_path / "run.sh",
    ]
    transfer_inputs = ", ".join(path.resolve().as_posix() for path in transfer_sources)
    if not SHARED_LBT_DIR.exists():
        raise FileNotFoundError(f"LBT-tables directory not found at {SHARED_LBT_DIR}")
    if not SHARED_EOS_DIR.exists():
        raise FileNotFoundError(f"EOS directory not found at {SHARED_EOS_DIR}")
    if not SHARED_PYTHIA_DIR.exists():
        raise FileNotFoundError(f"Pythia8 directory not found at {SHARED_PYTHIA_DIR}")
    lbt_source_env = SHARED_LBT_DIR.as_posix()
    eos_source_env = SHARED_EOS_DIR.as_posix()
    pythia_source_env = SHARED_PYTHIA_DIR.as_posix()
    home_env = os.environ.get("HOME", "/alice/home/dongguk")
    submit_path.write_text(
        f"""Universe                = vanilla
Executable              = {work_dir_posix}/macro/run.sh
Accounting_Group        = group_alice
JobBatchName            = {work_dir_name}_{config_dir}
Log                     = {work_dir_posix}/logs/{config_dir}_$(EventIndex).log
Output                  = {work_dir_posix}/{config_dir}_$(EventIndex).out
Error                   = {work_dir_posix}/{config_dir}_$(EventIndex).error
request_cpus            = 1
request_memory          = 4GB
request_disk            = 2GB
# Transfer required executables and lightweight resources
transfer_input_files    = {transfer_inputs}
# Transfer .dat, .root (JTree), and final .root
transfer_output_files   = {transfer_outputs}
Opt                     = {MAINGENERATOR}
ConfigDir               = {config_dir}
ConfigIndex             = {config_index}
SubmitEpoch             = {submit_epoch}
environment            = "LBT_SOURCE_DIR={lbt_source_env} EOS_SOURCE_DIR={eos_source_env} PYTHIA8_SOURCE_DIR={pythia_source_env} HOME={home_env}"
arguments               = "$(Opt) $(ConfigIndex) $(EventIndex) $(SubmitEpoch)"
should_transfer_files   = YES
when_to_transfer_output = ON_EXIT
periodic_remove         = (CurrentTime - EnteredCurrentStatus) > 604800
output_destination      = file://{work_dir_posix}/out/$(ConfigDir)/
Notification            = Never

Queue EventIndex from (
{event_lines}
)
"""
    )


def main() -> None:
    main_dir = os.path.dirname(os.path.realpath(__file__))
    main_path = pathlib.Path(main_dir)

    confirm_setting("wantDir", wantDir)
    confirm_setting("TOTAL_EVENTS", TOTAL_EVENTS)
    confirm_setting("RESULTS_BASE", RESULTS_BASE)
    confirm_setting("SHARED_HYDRO_DIR", SHARED_HYDRO_DIR)
    confirm_setting("SHARED_LBT_DIR", SHARED_LBT_DIR)
    confirm_setting("SHARED_EOS_DIR", SHARED_EOS_DIR)
    confirm_setting("SHARED_PYTHIA_DIR", SHARED_PYTHIA_DIR)
    confirm_setting("ACCEPTANCE", ACCEPTANCE)

    print_launch_banner()

    config_paths = gather_configurations(main_dir)
    config_rel = [path.relative_to(main_dir).as_posix() for path in config_paths]
    output_prefixes = [extract_output_prefix(path) for path in config_paths]
    out_dir_names = build_output_dir_names(config_rel)
    config_count = len(config_rel)

    total_jobs = config_count * TOTAL_EVENTS
    print(f"Configurations detected: {config_count}")
    print(f"Events per configuration: {TOTAL_EVENTS}")
    print(f"Total HTCondor jobs: {total_jobs}")

    RESULTS_BASE.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    work_dir = f"{now}_{MAINGENERATOR}"
    work_dir_path = RESULTS_BASE / work_dir

    for sub in ["macro", "out", "logs"]:
        (work_dir_path / sub).mkdir(parents=True, exist_ok=True)
    for out_dir in out_dir_names:
        (work_dir_path / "out" / out_dir).mkdir(parents=True, exist_ok=True)

    run_sh_path = work_dir_path / "macro" / "run.sh"
    build_run_script(run_sh_path, config_rel, TOTAL_EVENTS)

    submit_paths: list[pathlib.Path] = []
    for config_index, out_dir in enumerate(out_dir_names):
        submit_path = work_dir_path / "macro" / f"condor_{config_index}.sub"
        submit_epoch = int(datetime.now().timestamp())
        write_condor_submit(
            submit_path,
            work_dir,
            work_dir_path,
            out_dir,
            config_index,
            output_prefixes[config_index],
            TOTAL_EVENTS,
            submit_epoch,
            main_dir,
        )
        submit_paths.append(submit_path)

    total_submits = len(submit_paths)
    start_submit = time.monotonic()
    if total_submits:
        print(render_progress_line(0, total_submits, 0), end="\r", flush=True)
    for idx, submit_path in enumerate(submit_paths, start=1):
        proc = subprocess.Popen(
            ['condor_submit', submit_path.as_posix()],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=main_path,
            text=True,
        )
        out, err = proc.communicate()
        if proc.returncode != 0:
            print()
            if out:
                print(out.strip())
            if err:
                print(err.strip())
            raise RuntimeError(f"condor_submit failed for {submit_path.name}")
        if total_submits:
            elapsed = time.monotonic() - start_submit
            line = render_progress_line(idx, total_submits, elapsed)
            end_char = "\n" if idx == total_submits else "\r"
            print(line, end=end_char, flush=True)

if __name__ == "__main__":
    main()
