#!/usr/bin/env python3
"""
三份detail_tasks.csv对比合并工具
输入：glm52、jt236b、jt236_fp8三份detail csv
按task_id全外连接，字段交错排列；csv末尾追加统计汇总表：耗时、轮次的均值/最大/最小
"""
import argparse
import pandas as pd

def main():
    parser = argparse.ArgumentParser(description="三份detail_tasks.csv按task_id合并，字段交错排列，末尾附带统计汇总")
    parser.add_argument("--csv-glm52", type=str, required=True, help="glm52 detail_tasks.csv路径")
    parser.add_argument("--csv-jt236b", type=str, required=True, help="jt236b detail_tasks.csv路径")
    parser.add_argument("--csv-jt236-fp8", type=str, required=True, help="jt236_fp8 detail_tasks.csv路径")
    parser.add_argument("--out-csv", type=str, default="compare_three_models.csv", help="输出csv路径")
    args = parser.parse_args()

    df_glm52 = pd.read_csv(args.csv_glm52, encoding="utf-8-sig")
    df_jt236b = pd.read_csv(args.csv_jt236b, encoding="utf-8-sig")
    df_jt236_fp8 = pd.read_csv(args.csv_jt236_fp8, encoding="utf-8-sig")

    base_cols = [c for c in df_glm52.columns if c != "task_id"]

    # 方案：预先手动重命名第三个df所有列，task_id不动，其余全部加上 _jt236_fp8
    rename_fp8 = {}
    for col in df_jt236_fp8.columns:
        if col != "task_id":
            rename_fp8[col] = f"{col}_jt236_fp8"
    df_jt236_fp8 = df_jt236_fp8.rename(columns=rename_fp8)

    # 第一步合并 glm52 + jt236b
    df_merge = pd.merge(
        df_glm52,
        df_jt236b,
        on="task_id",
        how="outer",
        suffixes=("_glm52", "_jt236b")
    )
    # 第二步合并预已经加好后缀的jt236_fp8，不再传suffixes
    df_merge = pd.merge(
        df_merge,
        df_jt236_fp8,
        on="task_id",
        how="outer"
    )

    # 列顺序：交错排布
    new_col_order = ["task_id"]
    for col in base_cols:
        new_col_order.append(f"{col}_glm52")
        new_col_order.append(f"{col}_jt236b")
        new_col_order.append(f"{col}_jt236_fp8")

    # 两两是否一致标记
    df_merge["is_same_glm_jt236b"] = (
        df_merge["category_glm52"].notna()
        & df_merge["category_jt236b"].notna()
        & (df_merge["category_glm52"] == df_merge["category_jt236b"])
    )
    df_merge["is_same_jt236b_fp8"] = (
        df_merge["category_jt236b"].notna()
        & df_merge["category_jt236_fp8"].notna()
        & (df_merge["category_jt236b"] == df_merge["category_jt236_fp8"])
    )
    df_merge["is_same_glm_fp8"] = (
        df_merge["category_glm52"].notna()
        & df_merge["category_jt236_fp8"].notna()
        & (df_merge["category_glm52"] == df_merge["category_jt236_fp8"])
    )
    new_col_order.extend(["is_same_glm_jt236b", "is_same_jt236b_fp8", "is_same_glm_fp8"])
    df_merge = df_merge[new_col_order]

    # ========== 生成统计汇总表，只统计finished有效任务 ==========
    def get_stats(df_in, model_suffix):
        df_valid = df_in[df_in[f"status_{model_suffix}"] == "finished"]
        cost = df_valid[f"cost_seconds_{model_suffix}"].dropna()
        turn = df_valid[f"agent_turns_{model_suffix}"].dropna()
        return {
            "model": model_suffix,
            "valid_task_count": len(cost),
            "cost_sec_mean": round(cost.mean(),2),
            "cost_sec_max": round(cost.max(),2),
            "cost_sec_min": round(cost.min(),2),
            "agent_turn_mean": round(turn.mean(),2),
            "agent_turn_max": int(turn.max()),
            "agent_turn_min": int(turn.min()),
        }

    stat_list = [
        get_stats(df_merge, "glm52"),
        get_stats(df_merge, "jt236b"),
        get_stats(df_merge, "jt236_fp8")
    ]
    df_stat = pd.DataFrame(stat_list)

    # 写入csv：先写主体对比数据，再写一个空行，再写统计汇总表
    with open(args.out_csv, "w", encoding="utf-8-sig") as f:
        df_merge.to_csv(f, index=False)
        f.write("\n")   # 空行分隔
        df_stat.to_csv(f, index=False)

    # 控制台打印统计
    total = len(df_merge)
    all_three_exist = (
        df_merge["category_glm52"].notna()
        & df_merge["category_jt236b"].notna()
        & df_merge["category_jt236_fp8"].notna()
    )
    count_all_three = all_three_exist.sum()
    same_glm_jt236b = df_merge["is_same_glm_jt236b"].sum()
    same_jt236b_fp8 = df_merge["is_same_jt236b_fp8"].sum()
    same_glm_fp8 = df_merge["is_same_glm_fp8"].sum()

    print(f"输出文件: {args.out_csv}")
    print(f"全部task_id总数: {total}")
    print(f"三份文件都存在的task: {count_all_three}")
    print(f"glm52 vs jt236b 分类一致：{same_glm_jt236b}")
    print(f"jt236b vs jt236_fp8 分类一致：{same_jt236b_fp8}")
    print(f"glm52 vs jt236_fp8 分类一致：{same_glm_fp8}")
    print("\n===== 有效finished任务统计汇总 =====")
    print(df_stat.to_string(index=False))


if __name__ == "__main__":
    main()