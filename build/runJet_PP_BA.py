#!/usr/bin/env python3
import shutil
from datetime import datetime
import subprocess
import pathlib
import os 
os.umask(0)

MAINGENERATOR = "JETSCAPE_PP_BA_1000000"  # name of optns file, must be placed in the same folder of this script
USER_MAIL      = "dongguk.kim@cern.ch"

## Default values
totalEvents = 2
print(f"Total events: {totalEvents}")

# Paths
now     = datetime.now().strftime("%Y%m%d_%H%M%S")
workDir = f"{now}_{MAINGENERATOR}"
mainDir = os.path.dirname(os.path.realpath(__file__))
main_path = pathlib.Path(mainDir)

# Prepare directories
for sub in ["macro", "out", "logs"]:
    pathlib.Path(f"{mainDir}/{workDir}/{sub}").mkdir(parents=True, exist_ok=True)
for i in range(totalEvents):
    pathlib.Path(f"{mainDir}/{workDir}/out/{i}").mkdir(parents=True, exist_ok=True)

# Prepare JCORRAN include directory so ROOT can find Ali* headers on worker nodes
default_jcorran_root = main_path.resolve().parents[1] / "JCORRAN"
jcorran_root = pathlib.Path(os.environ.get("JCORRAN_DIR", default_jcorran_root))
include_source = pathlib.Path(
    os.environ.get("JCORRAN_INCLUDE_DIR", jcorran_root / "include")
).expanduser().resolve()
if not include_source.is_dir():
    raise FileNotFoundError(f"JCORRAN include directory not found: {include_source}")

include_dest = pathlib.Path(f"{mainDir}/{workDir}/JCORRAN_include")
if include_dest.exists():
    shutil.rmtree(include_dest)
shutil.copytree(include_source, include_dest)

# 1) run.sh: runJetscape → jetscapeToJTree → JYUAna
run_sh = f"{mainDir}/{workDir}/macro/run.sh"
with open(run_sh, "w") as fRun:
    fRun.write(f"""#!/bin/bash
echo "INIT! $1 $2 $3 $4 $5"
source alienv_envset.sh

JCORRAN_INCLUDE_DIR="$PWD/JCORRAN_include"
JCORRAN_RUNTIME="$PWD/JCORRAN_runtime"
if [[ -d "$JCORRAN_INCLUDE_DIR" ]]; then
  mkdir -p "$JCORRAN_RUNTIME/bin"
  rm -rf "$JCORRAN_RUNTIME/include"
  cp -a "$JCORRAN_INCLUDE_DIR" "$JCORRAN_RUNTIME/include"
  ln -sfn "$JCORRAN_RUNTIME/include" "$PWD/include"
  cp -f JYUAna "$JCORRAN_RUNTIME/bin/JYUAna"
  cp -f jcorranDict_rdict.pcm "$JCORRAN_RUNTIME/bin/jcorranDict_rdict.pcm"
  cp -f nanoDict_rdict.pcm "$JCORRAN_RUNTIME/bin/nanoDict_rdict.pcm"
  if [[ -z "$ROOT_INCLUDE_PATH" ]]; then
    ROOT_INCLUDE_PATH="$JCORRAN_RUNTIME/include"
  else
    ROOT_INCLUDE_PATH="$JCORRAN_RUNTIME/include:$ROOT_INCLUDE_PATH"
  fi
  export ROOT_INCLUDE_PATH
  echo "ROOT_INCLUDE_PATH=$ROOT_INCLUDE_PATH"
else
  echo "ERROR: $JCORRAN_INCLUDE_DIR is missing; cannot set up ALICE analysis headers." >&2
  exit 1
fi

# Set random seed
RANDOM_SEED=$(od -vAn -N4 -tu4 < /dev/urandom | tr -d " ")
RANDOM_SEED=$(( RANDOM_SEED % 10001 ))
echo "RANDOM_SEED: $RANDOM_SEED"
sed -i "s|<seed>[0-9]*</seed>|<seed>${{RANDOM_SEED}}</seed>|" jetscape_user_PP.xml

# 1) JETSCAPE 실행
./runJetscape jetscape_user_PP.xml

# 2) Convert to JTree
if [[ -f test_out_final_state_hadrons.dat ]]; then
  echo "Converting to JTree..."
  ./jetscapeToJTree test_out_final_state_hadrons.dat test_out_tree.root
else
  echo "ERROR: .dat file not found!"
  exit 1
fi

# 3) Generate mylist with absolute path so JYUAna can read it even after changing directories
LIST_PATH="$PWD/test_out_tree.root"
echo "$LIST_PATH" > mylist
echo "Contents of mylist:"
cat mylist

# 4) Run JYUAna
MYLIST_ABS="$PWD/mylist"
FINAL_ABS="$PWD/test_out_final.root"
JCORRAN_BIN="$JCORRAN_RUNTIME/bin"
if [[ -x "$JCORRAN_BIN/JYUAna" ]]; then
  echo "Running JYUAna from $JCORRAN_BIN..."
  (cd "$JCORRAN_BIN" && ./JYUAna "$MYLIST_ABS" "$FINAL_ABS")
else
  echo "ERROR: JYUAna executable not prepared at $JCORRAN_BIN!" >&2
  exit 1
fi

ls -althr
echo "DONE!"
""")
os.chmod(run_sh, 0o755)

# 2) condor.sub: transfer_input_files 에 JYUAna 추가, transfer_output_files 에 test_out_final.root 추가
transfer_inputs = [
    "Pythia8",
    "lib_hdf5",
    "lib_boost",
    "lib",
    "src",
    "nanoDict_rdict.pcm",
    "jcorranDict_rdict.pcm",
    "alienv_envset.sh",
    "runJetscape",
    "jetscapeToJTree",
    "JYUAna",
    "jetscape_main.xml",
    "jetscape_user_PP.xml",
    f"{workDir}/JCORRAN_include",
]
transfer_input_str = ",".join(transfer_inputs)

sub_sh = f"{mainDir}/{workDir}/macro/condor.sub"
with open(sub_sh, "w") as fSub:
    fSub.write(f"""Universe                = vanilla
Executable              = {workDir}/macro/run.sh
Accounting_Group        = group_alice
JobBatchName            = {workDir}_$(process)
Log                     = {workDir}/logs/$(process).log
Output                  = {workDir}/$(process).out
Error                   = {workDir}/$(process).error

request_memory          = 4GB
request_disk            = 4GB
# Transfer all required executables and scripts
transfer_input_files    = {transfer_input_str}
# Transfer .dat, .root (JTree), and final .root
transfer_output_files   = test_out_final_state_hadrons.dat,test_out_tree.root,test_out_final.root
arguments               = "$(Opt) $(process)"
should_transfer_files   = YES
when_to_transfer_output = ON_EXIT
periodic_remove         = (CurrentTime - EnteredCurrentStatus) > 259200
output_destination      = file://{mainDir}/{workDir}/out/$(process)/
Notification            = Always
Notify_user             = {USER_MAIL}

Queue {totalEvents} Opt in ({MAINGENERATOR})
""")

# 3) condor.dag: 변경 없음
dag = f"{mainDir}/{workDir}/macro/condor.dag"
with open(dag, "w") as fDag:
    fDag.write(f"JOB A {workDir}/macro/condor.sub\n")

# 4) DAG 제출
cmd = (
    f'condor_submit_dag -batch-name {MAINGENERATOR}_{totalEvents} '
    f'-force -notification Always '
    f'-append "Accounting_Group=group_alice" '
    f'-append "notify_user={USER_MAIL}" '
    f'{workDir}/macro/condor.dag'
)
proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
out, err = proc.communicate()
print(out.decode("utf-8"))
