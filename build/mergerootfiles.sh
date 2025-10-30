#!/bin/bash

start_time=$(date +%s)

# Check arguments
if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <directory_to_search> <target_filename>"
  exit 1
fi

SEARCH_DIR="$1"
TARGET_FILENAME="$2"
OUTPUT_FILENAME="merged_AnalysisResults.root"

FILE_COUNT=$(find "$SEARCH_DIR" -type f -name "$TARGET_FILENAME" | wc -l)
echo "Number of files to merge: $FILE_COUNT"

# Collect files to merge
files=( $(find "$SEARCH_DIR" -type f -name "$TARGET_FILENAME") )
total=${#files[@]}
echo "Merging $total files with progress bar..."

# Iteratively merge and update progress
for idx in "${!files[@]}"; do
  file="${files[$idx]}"
  if [ "$idx" -eq 0 ]; then
    cp "$file" "$OUTPUT_FILENAME"
  else
    hadd -f temp.root "$OUTPUT_FILENAME" "$file" >/dev/null 2>&1
    mv temp.root "$OUTPUT_FILENAME"
  fi
  done_count=$((idx + 1))
  percent=$(( done_count * 100 / total ))
  bar_width=40
  filled=$(( percent * bar_width / 100 ))
  empty=$(( bar_width - filled ))
  bar=$(printf "\e[1;32m%0.s#\e[0m" $(seq 1 $filled))
  dash=$(printf "\e[1;30m%0.s-\e[0m" $(seq 1 $empty))
  printf "\r\e[1m[%s%s] %3d%% (%d/%d)\e[0m" "$bar" "$dash" "$percent" "$done_count" "$total"
done

end_time=$(date +%s)
elapsed=$((end_time - start_time))
hours=$((elapsed / 3600))
minutes=$(( (elapsed % 3600) / 60 ))
seconds=$((elapsed % 60))

echo -e "\n\e[1;32m✅ Merge complete!\e[0m"
echo -e "\e[1;36m🕒 Time taken: ${hours}h ${minutes}m ${seconds}s\e[0m"
echo -e "\e[1;35m📁 Output saved to: \e[1;33m$OUTPUT_FILENAME\e[0m"