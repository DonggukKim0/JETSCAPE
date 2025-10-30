#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: merge_jetscape.sh -i <root_dir> -o <output_dir> [-p <parallel_jobs>]

Options:
  -i  Directory whose tree contains out/jetscape_user_* folders.
  -o  Directory where merged ROOT files will be written.
  -p  Number of parallel hadd jobs to run (default: number of CPU cores).
  -h  Show this help message.

Every jetscape_user_<index> directory located under any "out" folder below
<root_dir> is processed by combining <index>_final_*.root into
jetscape_user_<index>_merged.root inside <output_dir>.
USAGE
}

err() {
  echo "[ERROR] $*" >&2
}

info() {
  echo "[INFO] $*" >&2
}

format_duration() {
  local total_seconds="${1}"
  local hours=$(( total_seconds / 3600 ))
  local minutes=$(( (total_seconds % 3600) / 60 ))
  local seconds=$(( total_seconds % 60 ))

  if (( hours > 0 )); then
    printf '%dh %02dm %02ds' "${hours}" "${minutes}" "${seconds}"
  elif (( minutes > 0 )); then
    printf '%dm %02ds' "${minutes}" "${seconds}"
  else
    printf '%ds' "${seconds}"
  fi
}

input_dir=""
output_dir=""
parallelism=""

while getopts ":i:o:p:h" opt; do
  case "${opt}" in
    i) input_dir="${OPTARG}" ;;
    o) output_dir="${OPTARG}" ;;
    p) parallelism="${OPTARG}" ;;
    h)
      usage
      exit 0
      ;;
    :) err "Option -${OPTARG} requires an argument"; usage; exit 1 ;;
    \?) err "Unknown option -${OPTARG}"; usage; exit 1 ;;
  esac
done

if [[ -z "${input_dir}" || -z "${output_dir}" ]]; then
  err "Both -i and -o are required"
  usage
  exit 1
fi

if ! command -v hadd >/dev/null 2>&1; then
  err "hadd not found in PATH"
  exit 1
fi

if [[ ! -d "${input_dir}" ]]; then
  err "Input directory not found: ${input_dir}"
  exit 1
fi

mkdir -p "${output_dir}"

if [[ -z "${parallelism}" ]]; then
  if command -v nproc >/dev/null 2>&1; then
    parallelism="$(nproc)"
  else
    parallelism=1
  fi
fi

if ! [[ "${parallelism}" =~ ^[0-9]+$ ]] || (( parallelism < 1 )); then
  err "Parallel jobs must be a positive integer"
  exit 1
fi

search_root="${input_dir%/}"
mapfile -d '' -t jetscape_dirs < <(find "${search_root}" -type d -path '*/out/jetscape_user_*' -print0 | sort -z)

if (( ${#jetscape_dirs[@]} == 0 )); then
  err "No out/jetscape_user_* directories found under ${search_root}"
  exit 1
fi

info "Found ${#jetscape_dirs[@]} directories to merge"

SECONDS=0

pids=()
declare -A job_labels

take_slot() {
  while (( ${#pids[@]} >= parallelism )); do
    release_oldest
  done
}

release_oldest() {
  local pid="${pids[0]}"
  pids=("${pids[@]:1}")
  local label="${job_labels[$pid]}"
  unset "job_labels[$pid]"
  if ! wait "${pid}"; then
    err "hadd failed for ${label}"
    exit 1
  fi
}

cleanup() {
  local pid
  for pid in "${pids[@]}"; do
    local label="${job_labels[$pid]}"
    if ! wait "${pid}"; then
      err "hadd failed for ${label}"
      exit 1
    fi
    unset "job_labels[$pid]"
  done
}

trap cleanup EXIT

for dir in "${jetscape_dirs[@]}"; do
  dir_basename="$(basename "${dir}")"

  if [[ ${dir_basename} =~ ([0-9]+)$ ]]; then
    dir_index="${BASH_REMATCH[1]}"
  else
    info "Skipping ${dir}: cannot determine numeric index"
    continue
  fi

  output_file="${output_dir%/}/tree_${dir_index}_merged.root"
  # output_file="${output_dir%/}/jetscape_user_${dir_index}_merged.root"
  pattern="${dir_index}_tree_*.root"
  # pattern="${dir_index}_final_*.root"

  readarray -d '' -t root_files < <(find "${dir}" -maxdepth 1 -type f -name "${pattern}" -print0 | sort -z)

  if (( ${#root_files[@]} == 0 )); then
    info "Skipping ${dir}: no ${pattern} files"
    continue
  fi

  take_slot

  info "Merging ${#root_files[@]} files from ${dir} -> ${output_file}"

  (
    if hadd -f "${output_file}" "${root_files[@]}"; then
      info "Finished ${output_file}"
    else
      err "hadd failed for ${dir}"
      exit 1
    fi
  ) &

  pid=$!
  pids+=("${pid}")
  job_labels[${pid}]="${dir}"

done

cleanup
trap - EXIT

elapsed="${SECONDS}"
duration=$(format_duration "${elapsed}")
info "All merges completed in ${duration}"
