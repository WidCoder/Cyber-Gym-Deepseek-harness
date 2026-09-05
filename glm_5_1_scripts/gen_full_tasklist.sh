#!/bin/bash
CYBERGYM_DATA_DIR="/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main/cybergym_data/data-heyu/cybergym/data"
OUT="./full_all_tasks.txt"

> "$OUT"
for dataset in arvo oss-fuzz; do
    dataset_dir="${CYBERGYM_DATA_DIR}/${dataset}"
    if [[ ! -d $dataset_dir ]]; then
        echo "WARNING: missing dataset directory: $dataset_dir" >&2
        continue
    fi
    for path in "$dataset_dir"/*; do
      [[ -e $path ]] || continue
      printf '%s:%s\n' "$dataset" "${path##*/}" >> "$OUT"
    done
done
# 排序
sort "$OUT" -o "$OUT"
echo "生成完成：$OUT"
