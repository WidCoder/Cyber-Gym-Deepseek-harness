from pathlib import Path
import sys

# 方式1：命令行传多个包含 CORRECT.txt 的目录或文件
#   python stat_correct.py /path/to/out1 /path/to/out2 ...
# 方式2：直接改这里的路径列表
PATHS = sys.argv[1:] or [
    # "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/glm_5_1_scripts/data_statistics/dsv4_eval_20260805_v10/data_statistics", 
    # "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/glm_5_1_scripts/data_statistics/glm51_eval_20260805_v9/data_statistics", 
    # "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/glm_5_1_scripts/data_statistics/glm51_eval_20260808_v9.2/data_statistics", 
    # "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/glm_5_1_scripts/data_statistics/glm51_eval_20260809_v9.1/data_statistics", 
    # "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/glm_5_1_scripts/data_statistics/glm51_eval_20260813_v9/data_statistics", 
    # "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/glm_5_1_scripts/data_statistics/glm52_eval_20260807_v9/data_statistics", 
    "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/output/glm-5.3-flash/glm-5.3-flash-eval-20260828-v9/data_statistics", 
    "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/output/glm-5.3-flash/glm-5.3-flash-eval-20260831-v0/data_statistics", 
    "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/output/glm-5.3-flash/glm-5.3-flash-eval-20260901-v9/round1/data_statistics", 
    "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/output/glm-5.3-flash/glm-5.3-flash-eval-20260901-v9/round2/data_statistics", 
    "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/output/glm-5.3-flash/glm-5.3-flash-eval-20260902-v9/round1/data_statistics", 
    "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/output/glm-5.3-flash/glm-5.3-flash-eval-20260903-v9/round1/data_statistics", 
    "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/output/glm-5.3-flash/glm-5.3-flash-eval-20260903-2-v9/round1/data_statistics", 

    "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/glm_5_1_scripts/data_statistics/jt236-cyber-v0.0.2-ep3_preserve_eval_20260826_v9", 
    "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/output/jt236/jt236b-eval-cyber-v0.0.3-ep3-preserve-20260828-v9/data_statistics", 
    "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/output/jt236/jt236b-eval-cyber-v0.0.4-ep5-preserve-20260831-v9/round1/data_statistics", 
    "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/output/jt236/jt236b-eval-cyber-v0.0.5-ep5-preserve-20260901-v9/round1/data_statistics", 
    "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/output/jt236/jt236b-eval-cyber-v0.0.6-ep3-preserve-20260902-v9/data_statistics", 
    "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/output/jt236/jt236b-eval-cyber-v0.0.7-iter_0002350-preserve-20260904-v9/round1/data_statistics",
]

file_task_sets = {}
for p in PATHS:
    p = Path(p)
    files = [p] if p.is_file() else sorted(p.rglob("CORRECT.txt"))
    for f in files:
        tasks = {l.strip() for l in f.read_text().splitlines() if l.strip()}
        file_task_sets[str(f)] = tasks

total_with_dup = sum(len(s) for s in file_task_sets.values())
union = set().union(*file_task_sets.values()) if file_task_sets else set()

print(f"{'文件':<80}{'题数':>6}")
for name, s in file_task_sets.items():
    print(f"{name:<80}{len(s):>6}")

print(f"\n结果文件数: {len(file_task_sets)}")
print(f"总答对数(含重复): {total_with_dup}")
print(f"去重后答对数: {len(union)}")
print(f"去重占比(1507): {len(union)/1507*100:.2f}%")

# # 每对文件的重叠题数（文件多时可注释掉）
# names = list(file_task_sets)
# if 2 <= len(names) <= 10:
#     print("\n两两重叠:")
#     for i in range(len(names)):
#         for j in range(i+1, len(names)):
#             inter = file_task_sets[names[i]] & file_task_sets[names[j]]
#             print(f"  {Path(names[i]).parent.parent.name} ∩ {Path(names[j]).parent.parent.name}: {len(inter)}")

# 哪些题所有实验都没做对
full = {l.strip() for l in Path("/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/glm_5_1_scripts/full_all_tasks.txt").read_text().splitlines() if l.strip()}
never = sorted(full - union)
Path("never_correct.txt").write_text("\n".join(never) + "\n")
print(f"从未答对: {len(never)} 题，已写入 never_correct.txt")