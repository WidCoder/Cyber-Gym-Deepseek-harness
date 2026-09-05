import pandas as pd

# 请改成你的csv文件路径
csv_path = "/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/glm_5_1_scripts/data_statistics/jt236-cyber-v0.0.1-ep5_preserve_eval_20260826_v9/data_statistics/detail_tasks.csv"

# 读取csv，兼容中文编码
try:
    df = pd.read_csv(csv_path, encoding="utf-8")
except UnicodeDecodeError:
    df = pd.read_csv(csv_path, encoding="gbk")

# 清洗：过滤耗时为空、非数字
df = df.dropna(subset=["任务耗时(秒)"])
df["任务耗时(秒)"] = pd.to_numeric(df["任务耗时(秒)"], errors="coerce")
df = df.dropna(subset=["任务耗时(秒)"])

# 时间阈值
TWO_H = 2 * 3600   # 7200秒
FOUR_H = 4 * 3600  # 14400秒

# 划分区间
def get_interval(sec):
    if sec < TWO_H:
        return "小于2小时"
    elif TWO_H <= sec <= FOUR_H:
        return "2‑4小时"
    else:
        return "大于4小时"

df["区间"] = df["任务耗时(秒)"].apply(get_interval)

interval_order = ["小于2小时", "2‑4小时", "大于4小时"]

# ========== 1. 全量任务统计 ==========
total_all = len(df)
stat_all = df["区间"].value_counts().reindex(interval_order, fill_value=0)

print("=" * 50)
print("【全量任务耗时分布】总任务数：", total_all)
for name, cnt in stat_all.items():
    ratio = cnt / total_all * 100 if total_all > 0 else 0
    print(f"{name:8s}：{cnt:3d} 道，占比 {ratio:.2f}%")

# ========== 2. 仅分类结果为correct的统计 ==========
df_correct = df[df["分类结果"] == "correct"]
total_correct = len(df_correct)
stat_correct = df_correct["区间"].value_counts().reindex(interval_order, fill_value=0)

print("\n" + "=" * 50)
print("【correct任务耗时分布】总correct数：", total_correct)
for name, cnt in stat_correct.items():
    ratio = cnt / total_correct * 100 if total_correct > 0 else 0
    print(f"{name:8s}：{cnt:3d} 道，占比 {ratio:.2f}%")
print("=" * 50)
