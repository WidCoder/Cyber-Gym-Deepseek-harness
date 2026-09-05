#!/usr/bin/env python3
"""
compare_reports.py — 对比多轮/多配置评测的 eval_report.md 指标

用法：
    # 直接传多个 report 路径（label 自动取目录名）
    python compare_reports.py \
        /path/to/evalA/data_statistics/eval_report.md \
        /path/to/evalB/data_statistics/eval_report.md

    # 自定义显示名
    python compare_reports.py A.md B.md --labels glm51 dsv4

    # 指定输出文件
    python compare_reports.py A.md B.md --output ./对比报告.md

对比维度：
    1. 总体指标（正确数/准确率/待重跑数等）
    2. 分类概览（各评测类别样本数与占比，附 missing 中超 timeout 数）
    2.5 相同题目对比（读同目录 detail_tasks.csv 取题目交集；--max-cost 按统一耗时预算
        把超预算的 correct 判负而不是剔除题目，适合评测未跑完时或不同 timeout 评测之间
        的公平对比）
    3. 按题目类型正确率（含与首个报告的差值pp）
    4. 效率指标（correct 行与总平均行的耗时/API/压缩/子智能体）
    5. 尾部指标（耗时/API次数的 P90、P95）
    6. 耗时分布（各耗时区间题目数与占比）
    7. PoC提交效率（做对/失败/总平均的提交次数、API次数与token/次提交）
    8. 按题目类型效率（各类型的平均耗时、平均prompt token）
    9. 工具使用（各工具调用次数与占比）
    10. Token 成本（总平均行的各项 token）
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

Table = Tuple[List[str], List[List[str]]]  # (headers, rows)


# ------------------------- md 解析 -------------------------

def parse_md_tables(md_path: Path) -> Dict[str, Table]:
    """把 report.md 按 '## 小节' 拆成 {小节标题: (表头, 行)}。"""
    sections: Dict[str, Table] = {}
    current: Optional[str] = None
    headers: Optional[List[str]] = None
    rows: List[List[str]] = []

    for raw in md_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            if current is not None and headers is not None:
                sections[current] = (headers, rows)
            current = line[3:].strip()
            headers, rows = None, []
        elif line.startswith("|") and current is not None:
            cells = [c.strip() for c in line.strip("|").split("|")]
            # 跳过分隔行 | --- | --- |
            if all(set(c) <= set("-: ") and c for c in cells):
                continue
            if headers is None:
                headers = cells
            else:
                rows.append(cells)

    if current is not None and headers is not None:
        sections[current] = (headers, rows)
    return sections


def find_section(sections: Dict[str, Table], prefix: str) -> Optional[Table]:
    """按前缀找小节（容忍标题细微差异）。"""
    for title, table in sections.items():
        if title.startswith(prefix):
            return table
    return None


def rows_as_dict(table: Table, key_col: int = 0) -> Dict[str, List[str]]:
    _, rows = table
    return {r[key_col]: r for r in rows if len(r) > key_col}


# ------------------------- 数值解析 -------------------------

def parse_num(s: str) -> Optional[float]:
    """解析 '6.67M' '12.81B' '72.58%' '3030.43' 等，'-'/'N/A' 返回 None。"""
    s = (s or "").strip()
    if s in ("-", "", "N/A"):
        return None
    mult = 1.0
    if s.endswith("%"):
        s = s[:-1]
    if s[-1:] in ("K", "M", "B"):
        mult = {"K": 1e3, "M": 1e6, "B": 1e9}[s[-1]]
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def fmt_cell_count_rate(correct: Optional[float], total: Optional[float]) -> str:
    if correct is None or total is None or total == 0:
        return "-"
    return f"{int(correct)}/{int(total)} ({correct / total * 100:.1f}%)"


def build_md_table(rows: List[List[str]], headers: List[str]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for r in rows:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


# ------------------------- 各维度对比表 -------------------------

def cmp_overview(reports: List[Tuple[str, Dict[str, Table]]]) -> Optional[Table]:
    """总体指标：汇总指标小节（指标项/值 两列）。"""
    per_report = []
    for _, secs in reports:
        t = find_section(secs, "汇总指标")
        per_report.append(rows_as_dict(t) if t else {})

    keys: List[str] = []
    for d in per_report:
        for k in d:
            if k not in keys:
                keys.append(k)
    if not keys:
        return None

    headers = ["指标项"] + [name for name, _ in reports]
    rows = []
    for k in keys:
        row = [k]
        for d in per_report:
            cells = d.get(k)
            row.append(cells[1] if cells and len(cells) > 1 else "-")
        rows.append(row)
    return headers, rows


def parse_timeout_from_missing_analysis(md_path: Path) -> Tuple[Optional[int], Optional[int]]:
    """
    从 report.md 同目录的 missing_exit_code_analysis.txt 解析超时情况。
    返回 (超过timeout数, missing总数)，文件不存在返回 (None, None)。
    """
    analysis = md_path.parent / "missing_exit_code_analysis.txt"
    if not analysis.is_file():
        return None, None
    import re as _re
    head = analysis.read_text(encoding="utf-8", errors="ignore")[:2000]
    m_total = _re.search(r"missing总数:\s*(\d+)", head)
    m_over = _re.search(r"超过timeout:\s*(\d+)", head)
    over = int(m_over.group(1)) if m_over else None
    total = int(m_total.group(1)) if m_total else None
    return over, total


def cmp_category(reports: List[Tuple[str, Dict[str, Table]]],
                 report_paths: List[Path]) -> Optional[Table]:
    """分类概览：每类样本数与占比，如 '1030 (68.35%)'；末行附 missing 中超 timeout 数。"""
    per_report = []
    for _, secs in reports:
        t = find_section(secs, "分类概览")
        per_report.append(rows_as_dict(t) if t else {})

    cats: List[str] = []
    for d in per_report:
        for k in d:
            if k not in cats:
                cats.append(k)
    if not cats:
        return None

    headers = ["类别"] + [name for name, _ in reports]
    rows = []
    for cat in cats:
        row = [cat]
        for d in per_report:
            cells = d.get(cat)
            if cells and len(cells) >= 3:
                row.append(f"{cells[1]} ({cells[2]})")
            else:
                row.append("-")
        rows.append(row)

    # 附：missing_exit_code 中超 timeout 数量（来自 missing_exit_code_analysis.txt）
    timeout_row = ["missing中超timeout数"]
    for p in report_paths:
        over, total = parse_timeout_from_missing_analysis(p)
        if over is None or total is None:
            timeout_row.append("-")
        elif total == 0:
            timeout_row.append("0/0")
        else:
            timeout_row.append(f"{over}/{total} ({over / total * 100:.1f}%)")
    rows.append(timeout_row)
    return headers, rows


def cmp_vuln_accuracy(reports: List[Tuple[str, Dict[str, Table]]]) -> Optional[Table]:
    """按题目类型正确率对比，末列为与首个报告的差值（百分点）。"""
    per_report = []
    for _, secs in reports:
        t = find_section(secs, "按题目类型正确率")
        per_report.append(rows_as_dict(t) if t else {})

    types: List[str] = []
    for d in per_report:
        for k in d:
            if k not in types:
                types.append(k)
    if not types:
        return None

    multi = len(reports) > 1
    headers = ["题目类型", "样本数", "占比"] + [name for name, _ in reports]
    if multi:
        headers.append(f"Δpp(vs {reports[0][0]})")

    # 样本数/占比以首个包含该类型的报告为准（各报告题集通常一致）
    first = per_report[0]
    grand_total = None
    if "总计" in first and len(first["总计"]) >= 2:
        grand_total = parse_num(first["总计"][1])

    rows = []
    for vt in types:
        cells0 = first.get(vt)
        cnt = parse_num(cells0[1]) if cells0 and len(cells0) >= 2 else None
        share = f"{cnt / grand_total * 100:.1f}%" if cnt is not None and grand_total else "-"
        row = [vt, str(int(cnt)) if cnt is not None else "-", share]
        rates: List[Optional[float]] = []
        for d in per_report:
            cells = d.get(vt)
            if cells and len(cells) >= 4:
                # cells: [类型, 样本数, 做对数, 做对比例]
                row.append(fmt_cell_count_rate(parse_num(cells[2]), parse_num(cells[1])))
                rates.append(parse_num(cells[3]))
            else:
                row.append("-")
                rates.append(None)
        if multi:
            if rates[0] is not None and any(r is not None for r in rates[1:]):
                best_other = [r for r in rates[1:] if r is not None]
                # 展示与最后一个报告的差值，更贴近“最新vs基线”的读法
                delta = rates[-1] - rates[0] if rates[-1] is not None else None
                row.append(f"{delta:+.1f}" if delta is not None else "-")
            else:
                row.append("-")
        rows.append(row)
    return headers, rows


def _pick_rows(table: Optional[Table], wanted: List[str]) -> Dict[str, List[str]]:
    if not table:
        return {}
    d = rows_as_dict(table)
    return {k: d[k] for k in wanted if k in d}


def cmp_efficiency(reports: List[Tuple[str, Dict[str, Table]]]) -> List[Tuple[str, Table]]:
    """效率指标：correct 行与总平均行各一张表，指标名作为行、报告作为列。"""
    row_keys = ["correct", "总平均"]
    # (显示名, 在效率表中的列名)
    metrics = [
        ("平均耗时(秒)", "平均耗时(秒)"),
        ("耗时中位数(秒)", "耗时中位数(秒)"),
        ("最大耗时(秒)", "最大耗时(秒)"),
        ("平均API次数", "平均API次数"),
        ("API次数中位数", "API次数中位数"),
        ("平均压缩次数", "平均压缩次数"),
        ("压缩总数", "压缩总数"),
        ("平均子智能体次数", "平均子智能体次数"),
        ("子智能体总数", "子智能体总数"),
        ("平均PoC提交次数", "平均PoC提交次数"),
        ("平均工具调用次数", "平均工具调用次数"),
    ]

    per_report = []
    for _, secs in reports:
        t = find_section(secs, "效率指标")
        headers = t[0] if t else []
        picked = _pick_rows(t, row_keys)
        # 转成 {指标显示名: {row_key: 值}}
        m: Dict[str, Dict[str, str]] = {}
        for disp, col in metrics:
            if col in headers:
                idx = headers.index(col)
                m[disp] = {rk: (cells[idx] if len(cells) > idx else "-")
                           for rk, cells in picked.items()}
        per_report.append(m)

    if not any(per_report):
        return []

    result: List[Tuple[str, Table]] = []
    for rk in row_keys:
        headers = ["效率指标"] + [name for name, _ in reports]
        rows = []
        for disp, _ in metrics:
            row = [disp]
            for m in per_report:
                row.append(m.get(disp, {}).get(rk, "-"))
            rows.append(row)
        title = "效率指标对比(做对样本)" if rk == "correct" else "效率指标对比(全部样本总平均)"
        result.append((title, (headers, rows)))
    return result


def cmp_duration_distribution(reports: List[Tuple[str, Dict[str, Table]]]) -> Optional[Table]:
    """耗时分布：行=耗时区间，单元格 '题目数 (占比)'。"""
    per_report = []
    for _, secs in reports:
        t = find_section(secs, "耗时分布")
        per_report.append(rows_as_dict(t) if t else {})

    buckets: List[str] = []
    for d in per_report:
        for k in d:
            if k not in buckets:
                buckets.append(k)
    if not buckets:
        return None

    headers = ["耗时区间"] + [name for name, _ in reports]
    rows = []
    for b in buckets:
        row = [b]
        for d in per_report:
            cells = d.get(b)
            if cells and len(cells) >= 3:
                row.append(f"{cells[1]} ({cells[2]})")
            else:
                row.append("-")
        rows.append(row)
    return headers, rows


_ROW_KEY_TITLES = {
    "correct": "做对样本",
    "失败合计(非correct)": "失败样本",
    "总平均": "全部样本总平均",
}


def _cmp_metric_by_rowkey(reports: List[Tuple[str, Dict[str, Table]]],
                          section_prefix: str, row_keys: List[str],
                          metrics: List[str], row_name: str,
                          title_prefix: str) -> List[Tuple[str, Table]]:
    """通用：某小节的指定行(correct/失败合计/总平均)各出一张表，指标作为行、报告作为列。"""
    per_report = []
    for _, secs in reports:
        t = find_section(secs, section_prefix)
        headers = t[0] if t else []
        picked = _pick_rows(t, row_keys)
        m: Dict[str, Dict[str, str]] = {}
        for col in metrics:
            if col in headers:
                idx = headers.index(col)
                m[col] = {rk: (cells[idx] if len(cells) > idx else "-")
                          for rk, cells in picked.items()}
        per_report.append(m)

    if not any(per_report):
        return []

    result: List[Tuple[str, Table]] = []
    for rk in row_keys:
        headers = [row_name] + [name for name, _ in reports]
        rows = [[col] + [m.get(col, {}).get(rk, "-") for m in per_report]
                for col in metrics]
        result.append((f"{title_prefix}({_ROW_KEY_TITLES.get(rk, rk)})", (headers, rows)))
    return result


def cmp_poc_efficiency(reports: List[Tuple[str, Dict[str, Table]]]) -> List[Tuple[str, Table]]:
    """PoC提交效率：做对/失败/总平均各一张表。"""
    return _cmp_metric_by_rowkey(
        reports, "PoC提交效率",
        ["correct", "失败合计(非correct)", "总平均"],
        ["平均PoC提交次数", "平均API次数/次提交", "平均prompt token/次提交(K/M/B)"],
        "PoC效率指标", "PoC提交效率对比",
    )


def cmp_tail_metrics(reports: List[Tuple[str, Dict[str, Table]]]) -> List[Tuple[str, Table]]:
    """尾部指标(P90/P95)：做对样本与总平均各一张表。"""
    return _cmp_metric_by_rowkey(
        reports, "尾部指标",
        ["correct", "总平均"],
        ["耗时P90(秒)", "耗时P95(秒)", "API次数P90", "API次数P95"],
        "尾部指标", "尾部指标对比",
    )


def cmp_type_efficiency(reports: List[Tuple[str, Dict[str, Table]]]) -> List[Tuple[str, Table]]:
    """按题目类型效率：平均耗时、平均prompt token 各一张表，行=题目类型。"""
    per_report = []
    for _, secs in reports:
        t = find_section(secs, "按题目类型效率")
        per_report.append((t[0] if t else [], rows_as_dict(t) if t else {}))

    types: List[str] = []
    for _, d in per_report:
        for k in d:
            if k not in types:
                types.append(k)
    if not types:
        return []

    result: List[Tuple[str, Table]] = []
    for title, col in (("按题目类型平均耗时对比(秒)", "平均耗时(秒)"),
                       ("按题目类型平均prompt token对比", "平均prompt token(K/M/B)")):
        headers = ["题目类型"] + [name for name, _ in reports]
        rows = []
        for vt in types:
            row = [vt]
            for t_headers, d in per_report:
                cells = d.get(vt)
                if cells and col in t_headers:
                    idx = t_headers.index(col)
                    row.append(cells[idx] if len(cells) > idx else "-")
                else:
                    row.append("-")
            rows.append(row)
        result.append((title, (headers, rows)))
    return result


def cmp_tool_usage(reports: List[Tuple[str, Dict[str, Table]]]) -> Optional[Table]:
    """工具使用：行=工具名（首个报告的顺序优先），单元格 '次数 (占比)'，末行总计。"""
    per_report = []
    for _, secs in reports:
        t = find_section(secs, "工具使用统计")
        per_report.append(rows_as_dict(t) if t else {})

    tools: List[str] = []
    for d in per_report:
        for k in d:
            if k != "总计" and k not in tools:
                tools.append(k)
    if not tools:
        return None

    headers = ["工具名"] + [name for name, _ in reports]
    rows = []
    for tool in tools:
        row = [tool]
        for d in per_report:
            cells = d.get(tool)
            if cells and len(cells) >= 3:
                row.append(f"{cells[1]} ({cells[2]})")
            else:
                row.append("-")
        rows.append(row)

    total_row = ["总计"]
    for d in per_report:
        cells = d.get("总计")
        total_row.append(cells[1] if cells and len(cells) >= 2 else "-")
    rows.append(total_row)
    return headers, rows


# ------------------------- 相同题目对比（读 detail_tasks.csv） -------------------------

CATEGORY_ORDER_FULL = ["correct", "vul_crashed_fix_failed", "vul_not_crashed_fix_failed",
                       "vul_not_crashed", "missing_exit_code"]


def read_detail_csv(detail_path: Path) -> Dict[str, Tuple[str, Optional[float], str, Optional[int]]]:
    """读 detail_tasks.csv → {任务ID: (分类结果, 耗时秒或None, 运行状态, timing状态码或None)}。
    文件不存在返回空 dict。"""
    import csv as _csv
    out: Dict[str, Tuple[str, Optional[float], str, Optional[int]]] = {}
    if not detail_path.is_file():
        return out
    with detail_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = _csv.reader(f)
        headers = next(reader, None)
        if not headers or "任务ID" not in headers or "分类结果" not in headers:
            return out
        i_tid = headers.index("任务ID")
        i_cat = headers.index("分类结果")
        i_cost = headers.index("任务耗时(秒)") if "任务耗时(秒)" in headers else None
        i_status = headers.index("运行状态") if "运行状态" in headers else None
        i_timing = headers.index("timing状态码") if "timing状态码" in headers else None
        for row in reader:
            if len(row) <= max(i_tid, i_cat):
                continue
            tid = row[i_tid].strip()
            if not tid:
                continue
            cost: Optional[float] = None
            if i_cost is not None and len(row) > i_cost and row[i_cost].strip():
                try:
                    cost = float(row[i_cost])
                except ValueError:
                    cost = None
            status = row[i_status].strip() if i_status is not None and len(row) > i_status else ""
            timing_code: Optional[int] = None
            if i_timing is not None and len(row) > i_timing and row[i_timing].strip():
                try:
                    timing_code = int(float(row[i_timing]))
                except ValueError:
                    timing_code = None
            out[tid] = (row[i_cat].strip(), cost, status, timing_code)
    return out


def cmp_common_tasks(report_paths: List[Path], labels: List[str],
                     max_cost: Optional[float],
                     cost_tolerance: float = 300.0) -> List[Tuple[str, Optional[Table]]]:
    """
    相同题目对比：读各报告同目录的 detail_tasks.csv，取题目ID交集
    （两边都必须已跑出分类结果）。
    传入 max_cost 时按统一耗时预算判负（而不是剔除题目）：
    - 某题判 correct 但耗时 > max_cost + cost_tolerance 秒 → 虚拟类别
      "correct超预算判负"，正确率按判负后口径计算——模拟"这次评测若也用
      较小 timeout"的结果，用于不同 timeout 评测之间的公平对比
      （如 eval1 用 15000s、eval2 用 7200s，传 --max-cost 7200）。
    - 某题判 missing_exit_code 但属于超时（耗时 > 预算+容忍，或
      timing状态码=124 被 timeout 杀掉）→ 虚拟类别 "missing超时判负"：
      跑满预算仍无结果是真实失败信号而非中立噪声，"去除missing"表中保留计为失败。
    两边样本集始终一致；耗时缺失的 correct 无法判定，按原样保留。
    cost_tolerance 默认 300s：kill 粒度会让实际结束时间略超 nominal timeout。
    """
    if len(report_paths) < 2:
        return []
    per_report = [read_detail_csv(p.parent / "detail_tasks.csv") for p in report_paths]
    if any(not d for d in per_report):
        missing = [labels[i] for i, d in enumerate(per_report) if not d]
        print(f"[提示] 以下报告缺少 detail_tasks.csv，跳过相同题目对比: {'、'.join(missing)}")
        return []

    common: Set[str] = set(per_report[0])
    for d in per_report[1:]:
        common &= set(d.keys())
    n_intersect = len(common)

    # 两边都必须已跑出分类结果（剔除仍在跑/未跑完的题）
    common = {t for t in common if all(d[t][0] for d in per_report)}
    n_unfinished = n_intersect - len(common)

    over_budget_cat = f"correct超预算判负(>{max_cost:g}s)" if max_cost is not None else None
    missing_timeout_cat = "missing超时判负" if max_cost is not None else None

    def _adj_cat(d: Dict[str, Tuple[str, Optional[float], str, Optional[int]]], t: str) -> str:
        """判负后的类别：correct 超预算耗时 → 判负；missing 超时(耗时超预算
        或 timing状态码=124) → 判负；否则原类别。"""
        cat, cost, _status, timing_code = d[t]
        if max_cost is None:
            return cat
        cost_over = cost is not None and cost > max_cost + cost_tolerance
        if cat == "correct" and cost_over:
            return over_budget_cat
        if cat == "missing_exit_code" and (cost_over or timing_code == 124):
            return missing_timeout_cat
        return cat

    n = len(common)
    note_parts = [f"交集{n_intersect}道"]
    if n_unfinished:
        note_parts.append(f"剔除未完成{n_unfinished}道")
    if max_cost is not None:
        demoted_c = "/".join(
            f"{lab}{sum(1 for t in common if _adj_cat(d, t) == over_budget_cat)}道"
            for lab, d in zip(labels, per_report)
        )
        demoted_m = "/".join(
            f"{lab}{sum(1 for t in common if _adj_cat(d, t) == missing_timeout_cat)}道"
            for lab, d in zip(labels, per_report)
        )
        tol_note = f"+{cost_tolerance:g}s容忍" if cost_tolerance else ""
        note_parts.append(f"correct限耗时≤{max_cost:g}s{tol_note}，超出判负({demoted_c})")
        if any(_adj_cat(d, t) == missing_timeout_cat
               for d in per_report for t in common):
            note_parts.append(f"missing超时判负({demoted_m})")
    note_parts.append(f"参与对比{n}道")
    title = "相同题目对比(" + "，".join(note_parts) + ")"

    multi = len(labels) > 1
    headers = ["类别"] + labels + ([f"Δpp({labels[-1]} vs {labels[0]})"] if multi else [])
    # 判负虚拟类别分别排在 correct / missing_exit_code 之后
    cat_order = list(CATEGORY_ORDER_FULL)
    if over_budget_cat:
        cat_order.insert(1, over_budget_cat)
    if missing_timeout_cat:
        cat_order.insert(cat_order.index("missing_exit_code") + 1, missing_timeout_cat)

    def _build(task_set: Set[str]) -> Table:
        m = len(task_set)
        if m == 0:
            row = ["（无符合条件的相同题目）"] + ["-"] * len(labels) + (["-"] if multi else [])
            return headers, [row]
        cat_set: Set[str] = set()
        for d in per_report:
            for t in task_set:
                cat_set.add(_adj_cat(d, t))
        ordered_cats = [c for c in cat_order if c in cat_set] + \
                       sorted(c for c in cat_set if c not in cat_order)
        rows: List[List[str]] = []
        for cat in ordered_cats:
            row = [cat]
            for d in per_report:
                cnt = sum(1 for t in task_set if _adj_cat(d, t) == cat)
                row.append(f"{cnt} ({cnt / m * 100:.1f}%)")
            if multi:
                row.append("-")
            rows.append(row)
        rows.append(["总计"] + [str(m)] * len(labels) + (["-"] if multi else []))
        rates = []
        for d in per_report:
            c = sum(1 for t in task_set if _adj_cat(d, t) == "correct")
            rates.append(c / m * 100)
        acc_label = "正确率" if max_cost is None else f"正确率(correct限≤{max_cost:g}s)"
        acc_row = [acc_label] + [f"{r:.2f}%" for r in rates]
        if multi:
            acc_row.append(f"{rates[-1] - rates[0]:+.2f}")
        rows.append(acc_row)
        return headers, rows

    result: List[Tuple[str, Optional[Table]]] = [(title, _build(common))]

    # 去除 missing 的对比：剔除判负调整后仍为 missing_exit_code 的题
    # （即非超时的 missing，多为启动失败/基础设施问题等中立噪声；
    #  超时的 missing 已判负，是真实失败信号，保留在本表中计为失败）
    common_nm = {t for t in common
                 if all(_adj_cat(d, t) != "missing_exit_code" for d in per_report)}
    n_missing_excluded = n - len(common_nm)
    if n_missing_excluded > 0:
        budget_note = (f"，correct限耗时≤{max_cost:g}s，超时missing判负保留"
                       if max_cost is not None else "")
        title_nm = (f"相同题目对比(去除missing{budget_note}，剔除{n_missing_excluded}道，"
                    f"参与对比{len(common_nm)}道)")
        result.append((title_nm, _build(common_nm)))
    return result


def cmp_tokens(reports: List[Tuple[str, Dict[str, Table]]]) -> Optional[Table]:
    """Token 成本：总平均行，指标名作为行、报告作为列。"""
    per_report = []
    for _, secs in reports:
        t = find_section(secs, "Token成本")
        if not t:
            per_report.append({})
            continue
        headers, rows = t
        d = rows_as_dict(t)
        total = d.get("总平均")
        m: Dict[str, str] = {}
        if total:
            for i, h in enumerate(headers[1:], start=1):
                m[h] = total[i] if len(total) > i else "-"
        per_report.append(m)

    if not any(per_report):
        return None

    metric_names: List[str] = []
    for m in per_report:
        for k in m:
            if k not in metric_names:
                metric_names.append(k)

    headers = ["Token指标(总平均)"] + [name for name, _ in reports]
    rows = [[k] + [m.get(k, "-") for m in per_report] for k in metric_names]
    return headers, rows


# ------------------------- main -------------------------

def derive_label(md_path: Path) -> str:
    """从路径推导显示名：.../<eval名>/.../data_statistics/eval_report.md → <eval名>。"""
    parts = md_path.parts
    if "data_statistics" in parts:
        idx = parts.index("data_statistics")
        if idx >= 2:
            return parts[idx - 2] + "/" + parts[idx - 1]
        if idx >= 1:
            return parts[idx - 1]
    return md_path.parent.parent.name or md_path.stem


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="对比多个 eval_report.md 的指标")
    parser.add_argument("reports", type=Path, nargs="+", help="多个 eval_report.md 路径")
    parser.add_argument("--labels", nargs="*", default=None, help="各报告显示名，与路径一一对应")
    parser.add_argument("--output", type=Path, default=Path("report_compare.md"),
                        help="输出 markdown 文件（默认 ./report_compare.md）")
    parser.add_argument("--max-cost", type=float, default=None,
                        help="相同题目对比中 correct 的耗时预算（秒，如 7200）：耗时超过"
                             " 预算+容忍 的 correct 判负计入错误（题目不剔除），模拟统一"
                             " timeout 口径。不同 timeout 的评测对比时传较小 timeout 值；"
                             "不传则按原始分类对比")
    parser.add_argument("--max-cost-tolerance", type=float, default=50.0,
                        help="判负容忍秒数，默认 300：kill 粒度会让实际结束时间略超"
                             " nominal timeout，耗时 <= 预算+容忍 的 correct 不判负")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    labels = args.labels or []
    reports: List[Tuple[str, Dict[str, Table]]] = []
    for i, p in enumerate(args.reports):
        p = p.expanduser().resolve()
        if not p.is_file():
            print(f"Error: 文件不存在 {p}", file=sys.stderr)
            return 1
        label = labels[i] if i < len(labels) else derive_label(p)
        reports.append((label, parse_md_tables(p)))

    report_paths = [p.expanduser().resolve() for p in args.reports]
    labels_final = [name for name, _ in reports]
    sections_out: List[Tuple[str, Optional[Table]]] = [
        ("总体指标对比", cmp_overview(reports)),
        ("分类概览对比", cmp_category(reports, report_paths)),
        *cmp_common_tasks(report_paths, labels_final, args.max_cost,
                          args.max_cost_tolerance),
        ("按题目类型正确率对比", cmp_vuln_accuracy(reports)),
        *cmp_efficiency(reports),
        *cmp_tail_metrics(reports),
        ("耗时分布对比", cmp_duration_distribution(reports)),
        *cmp_poc_efficiency(reports),
        *cmp_type_efficiency(reports),
        ("工具使用对比", cmp_tool_usage(reports)),
        ("Token成本对比", cmp_tokens(reports)),
    ]

    md = "# 评测报告对比\n\n"
    md += "对比报告：" + "、".join(name for name, _ in reports) + "\n\n"
    for title, table in sections_out:
        md += f"## {title}\n"
        if table is None:
            md += "（所有报告均缺少该小节，跳过）\n\n"
            print(f"[跳过] {title}: 所有报告均缺少对应小节")
        else:
            headers, rows = table
            md += build_md_table(rows, headers) + "\n\n"
            print(f"\n==== {title} ====")
            print(build_md_table(rows, headers))

    out = args.output.expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"\n对比报告已输出至：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())