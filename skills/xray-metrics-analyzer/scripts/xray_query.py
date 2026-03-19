#!/usr/bin/env python3
"""
XRay Prometheus 指标查询与分析工具

通过 XRay OpenAPI 查询 Grafana/Prometheus 底层存储的指标数据，
支持 PQL 查询、统计分析、趋势对比等功能。

文档: https://docs.xiaohongshu.com/doc/6673a390cf03cf4f4d6d4bc15eb4e8ad
"""

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests
except ImportError:
    print("ERROR: 缺少 requests 库，请执行: pip install requests", file=sys.stderr)
    sys.exit(1)

# ============================================================
# 配置
# ============================================================

DEFAULT_BASE_URL = os.environ.get("XRAY_BASE_URL", "http://xray.int.xiaohongshu.com/openapi")
DEFAULT_SOURCE = os.environ.get("XRAY_SOURCE", "")      # 需通过环境变量或 --source 参数提供
DEFAULT_TOKEN = os.environ.get("XRAY_TOKEN", "")         # 需通过环境变量或 --token 参数提供


# ============================================================
# Ticket 生成
# ============================================================

def generate_ticket(source: str, token: str) -> str:
    """生成 XRay API 认证 ticket (base64 编码)"""
    timestamp_ms = int(time.time() * 1000)
    raw = f"{source}&{token}&{timestamp_ms}"
    return base64.b64encode(raw.encode("utf-8")).decode("utf-8")


# ============================================================
# API 客户端
# ============================================================

class XRayClient:
    """XRay OpenAPI 客户端"""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        source: str = DEFAULT_SOURCE,
        token: str = DEFAULT_TOKEN,
    ):
        self.base_url = base_url.rstrip("/")
        self.source = source
        self.token = token

    def _headers(self) -> Dict[str, str]:
        return {
            "xray_ticket": generate_ticket(self.source, self.token),
            "Content-Type": "application/json",
        }

    # ---------- 数据源接口 ----------

    def get_datasource_by_app(self, app: str) -> Dict:
        """根据应用获取 VMS 数据源"""
        url = f"{self.base_url}/application/metric/datasource/get"
        resp = requests.get(url, params={"app": app}, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_datasource_by_service(self, service: str) -> Dict:
        """根据服务获取 VMS 数据源"""
        url = f"{self.base_url}/application/metric/datasource/get/service"
        resp = requests.get(url, params={"service": service}, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def list_datasources(self) -> Dict:
        """获取全部 VMS 数据源列表"""
        url = f"{self.base_url}/application/metric/datasource/list"
        resp = requests.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ---------- PQL 查询接口 ----------

    def query_range(
        self,
        pql: str,
        start: int,
        end: int,
        step: int = 60,
        app: Optional[str] = None,
        datasource: Optional[str] = None,
        metric: Optional[str] = None,
        system: Optional[bool] = None,
        fmt: Optional[bool] = None,
    ) -> Dict:
        """
        通过 PQL 查询指标数据

        Args:
            pql: PromQL 查询表达式
            start: 开始时间（Unix 秒）
            end: 结束时间（Unix 秒）
            step: 步长（秒），默认 60
            app: 应用名（可选，若不填须指定 datasource）
            datasource: VMS 数据源名称（可选）
            metric: 指标名（可选）
            system: 是否系统指标（可选）
            fmt: 是否格式化精度（可选，False 不设置）
        """
        url = f"{self.base_url}/application/metric/data/query_range/v1"
        body: Dict[str, Any] = {
            "pql": pql,
            "start": start,
            "end": end,
            "step": step,
        }
        if app is not None:
            body["app"] = app
        if datasource is not None:
            body["datasource"] = datasource
        if metric is not None:
            body["metric"] = metric
        if system is not None:
            body["system"] = system
        if fmt is not None:
            body["format"] = fmt

        resp = requests.post(url, json=body, headers=self._headers(), timeout=60)
        resp.raise_for_status()
        return resp.json()


# ============================================================
# 数据解析
# ============================================================

def parse_query_result(result: Dict) -> List[Dict]:
    """
    解析 query_range 返回结果，提取时间序列数据。
    
    返回 list of:
      {
        "metric": {...标签...},
        "values": [(timestamp, value), ...],
      }
    """
    series_list = []

    # 支持多种返回结构
    data = result.get("data", result)
    if isinstance(data, dict):
        result_items = data.get("result", [])
    elif isinstance(data, list):
        result_items = data
    else:
        result_items = []

    for item in result_items:
        metric_labels = item.get("metric", {})
        raw_values = item.get("values", [])
        values = []
        for v in raw_values:
            if isinstance(v, (list, tuple)) and len(v) >= 2:
                ts = float(v[0])
                val_str = v[1]
                try:
                    val = float(val_str)
                except (ValueError, TypeError):
                    val = None
                values.append((ts, val))
        series_list.append({"metric": metric_labels, "values": values})

    return series_list


# ============================================================
# 统计分析
# ============================================================

def compute_stats(values: List[Tuple[float, Optional[float]]]) -> Dict[str, Any]:
    """
    计算单条时间序列的统计值

    Returns:
        dict: avg, max, min, p50, p90, p95, p99, count, sum, first, last, 
              start_time, end_time, duration_sec
    """
    nums = [v for _, v in values if v is not None]
    if not nums:
        return {"count": 0, "error": "no valid data points"}

    nums_sorted = sorted(nums)
    n = len(nums_sorted)

    def percentile(pct: float) -> float:
        idx = int(pct / 100.0 * (n - 1))
        return nums_sorted[min(idx, n - 1)]

    timestamps = [ts for ts, v in values if v is not None]
    return {
        "count": n,
        "sum": sum(nums),
        "avg": sum(nums) / n,
        "min": min(nums),
        "max": max(nums),
        "p50": percentile(50),
        "p90": percentile(90),
        "p95": percentile(95),
        "p99": percentile(99),
        "first": nums[0],
        "last": nums[-1],
        "start_time": datetime.fromtimestamp(min(timestamps)).isoformat(),
        "end_time": datetime.fromtimestamp(max(timestamps)).isoformat(),
        "duration_sec": max(timestamps) - min(timestamps),
    }


def format_stats(stats: Dict[str, Any], label: str = "") -> str:
    """将统计结果格式化为可读字符串"""
    if stats.get("error"):
        return f"  {label}: 无有效数据"

    lines = []
    if label:
        lines.append(f"  [{label}]")
    lines.append(f"    数据点数: {stats['count']}")
    lines.append(f"    时间范围: {stats['start_time']} ~ {stats['end_time']} ({stats['duration_sec']:.0f}s)")
    lines.append(f"    平均值:   {stats['avg']:.6g}")
    lines.append(f"    最小值:   {stats['min']:.6g}")
    lines.append(f"    最大值:   {stats['max']:.6g}")
    lines.append(f"    P50:      {stats['p50']:.6g}")
    lines.append(f"    P90:      {stats['p90']:.6g}")
    lines.append(f"    P95:      {stats['p95']:.6g}")
    lines.append(f"    P99:      {stats['p99']:.6g}")
    lines.append(f"    首个值:   {stats['first']:.6g}")
    lines.append(f"    末尾值:   {stats['last']:.6g}")
    return "\n".join(lines)


# ============================================================
# 趋势对比
# ============================================================

def compare_periods(
    client: XRayClient,
    pql: str,
    period1: Tuple[int, int],
    period2: Tuple[int, int],
    step: int = 60,
    app: Optional[str] = None,
    datasource: Optional[str] = None,
) -> str:
    """
    对比两个时间段的指标变化

    Args:
        period1: (start, end) 基准时间段（Unix 秒）
        period2: (start, end) 对比时间段（Unix 秒）

    Returns:
        格式化的对比报告
    """
    result1 = client.query_range(pql, period1[0], period1[1], step=step, app=app, datasource=datasource)
    result2 = client.query_range(pql, period2[0], period2[1], step=step, app=app, datasource=datasource)

    series1 = parse_query_result(result1)
    series2 = parse_query_result(result2)

    lines = []
    lines.append("=" * 60)
    lines.append("指标时间段对比报告")
    lines.append("=" * 60)
    lines.append(f"PQL: {pql}")
    lines.append(f"基准时间段: {datetime.fromtimestamp(period1[0]).isoformat()} ~ {datetime.fromtimestamp(period1[1]).isoformat()}")
    lines.append(f"对比时间段: {datetime.fromtimestamp(period2[0]).isoformat()} ~ {datetime.fromtimestamp(period2[1]).isoformat()}")
    lines.append("")

    # 取第一条序列做统计（多序列场景可扩展）
    stats1 = compute_stats(series1[0]["values"]) if series1 else {"error": "无数据"}
    stats2 = compute_stats(series2[0]["values"]) if series2 else {"error": "无数据"}

    lines.append("--- 基准时间段 ---")
    lines.append(format_stats(stats1))
    lines.append("")
    lines.append("--- 对比时间段 ---")
    lines.append(format_stats(stats2))
    lines.append("")

    if not stats1.get("error") and not stats2.get("error"):
        lines.append("--- 变化分析 ---")
        for key in ["avg", "max", "min", "p50", "p90", "p95", "p99"]:
            v1 = stats1[key]
            v2 = stats2[key]
            if v1 != 0:
                change_pct = (v2 - v1) / abs(v1) * 100
                direction = "↑" if change_pct > 0 else ("↓" if change_pct < 0 else "→")
                lines.append(f"    {key:6s}: {v1:.6g} → {v2:.6g}  ({direction} {abs(change_pct):.2f}%)")
            else:
                lines.append(f"    {key:6s}: {v1:.6g} → {v2:.6g}")

    lines.append("=" * 60)
    return "\n".join(lines)


# ============================================================
# 时间辅助函数
# ============================================================

def parse_time_range(time_range: str) -> Tuple[int, int]:
    """
    解析时间范围字符串

    支持格式:
      - "1h", "30m", "2d", "1w"  → 最近 N 小时/分钟/天/周
      - "2024-01-01T00:00:00,2024-01-02T00:00:00"  → 精确时间范围
      - "1710000000,1710003600"  → Unix 时间戳
    """
    now = int(time.time())

    # 相对时间
    if time_range.endswith("m"):
        minutes = int(time_range[:-1])
        return (now - minutes * 60, now)
    elif time_range.endswith("h"):
        hours = int(time_range[:-1])
        return (now - hours * 3600, now)
    elif time_range.endswith("d"):
        days = int(time_range[:-1])
        return (now - days * 86400, now)
    elif time_range.endswith("w"):
        weeks = int(time_range[:-1])
        return (now - weeks * 7 * 86400, now)

    # 精确时间
    if "," in time_range:
        parts = time_range.split(",", 1)
        try:
            s = int(parts[0])
            e = int(parts[1])
        except ValueError:
            s = int(datetime.fromisoformat(parts[0].strip()).timestamp())
            e = int(datetime.fromisoformat(parts[1].strip()).timestamp())
        return (s, e)

    raise ValueError(f"无法解析时间范围: {time_range}。支持格式: 1h, 30m, 2d, 1w 或 start,end")


def auto_step(start: int, end: int) -> int:
    """根据时间范围自动计算合适的 step"""
    duration = end - start
    if duration <= 3600:        # <= 1h
        return 15
    elif duration <= 21600:     # <= 6h
        return 60
    elif duration <= 86400:     # <= 1d
        return 300
    elif duration <= 604800:    # <= 7d
        return 900
    else:
        return 3600


# ============================================================
# 命令行入口
# ============================================================

def cmd_query(args):
    """执行 PQL 查询"""
    client = XRayClient(
        base_url=args.base_url,
        source=args.source,
        token=args.token,
    )
    start, end = parse_time_range(args.time_range)
    step = args.step or auto_step(start, end)

    print(f"查询: {args.pql}")
    print(f"时间: {datetime.fromtimestamp(start).isoformat()} ~ {datetime.fromtimestamp(end).isoformat()}")
    print(f"步长: {step}s")
    if args.datasource:
        print(f"数据源: {args.datasource}")
    print()

    result = client.query_range(
        pql=args.pql,
        start=start,
        end=end,
        step=step,
        app=args.app,
        datasource=args.datasource,
    )

    if args.raw:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    series = parse_query_result(result)
    if not series:
        print("查询无结果，请检查 PQL 表达式和时间范围。")
        return

    print(f"共 {len(series)} 条时间序列\n")
    for i, s in enumerate(series):
        label_str = ", ".join(f'{k}="{v}"' for k, v in s["metric"].items()) or "(无标签)"
        stats = compute_stats(s["values"])
        print(f"序列 #{i + 1}: {label_str}")
        print(format_stats(stats))
        print()


def cmd_stats(args):
    """查询并输出统计信息（JSON 格式，适合程序消费）"""
    client = XRayClient(
        base_url=args.base_url,
        source=args.source,
        token=args.token,
    )
    start, end = parse_time_range(args.time_range)
    step = args.step or auto_step(start, end)

    result = client.query_range(
        pql=args.pql,
        start=start,
        end=end,
        step=step,
        app=args.app,
        datasource=args.datasource,
    )

    series = parse_query_result(result)
    output = []
    for s in series:
        stats = compute_stats(s["values"])
        output.append({"metric": s["metric"], "stats": stats})

    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))


def cmd_compare(args):
    """对比两个时间段的指标"""
    client = XRayClient(
        base_url=args.base_url,
        source=args.source,
        token=args.token,
    )
    period1 = parse_time_range(args.period1)
    period2 = parse_time_range(args.period2)
    step = args.step or auto_step(period1[0], period1[1])

    report = compare_periods(
        client=client,
        pql=args.pql,
        period1=period1,
        period2=period2,
        step=step,
        app=args.app,
        datasource=args.datasource,
    )
    print(report)


def cmd_datasource(args):
    """查询数据源"""
    client = XRayClient(
        base_url=args.base_url,
        source=args.source,
        token=args.token,
    )
    if args.app:
        result = client.get_datasource_by_app(args.app)
    elif args.service:
        result = client.get_datasource_by_service(args.service)
    else:
        result = client.list_datasources()

    print(json.dumps(result, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(
        description="XRay Prometheus 指标查询与分析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 查询最近 1 小时的指标
  python xray_query.py query --pql 'rate(http_requests_total[5m])' --time-range 1h --datasource vms-shequ

  # 查询最近 30 分钟并输出原始 JSON
  python xray_query.py query --pql 'up' --time-range 30m --raw --app myapp

  # 输出统计信息（JSON 格式）
  python xray_query.py stats --pql 'node_cpu_seconds_total' --time-range 2h --datasource vms-shequ

  # 对比两个时间段
  python xray_query.py compare --pql 'rate(http_requests_total[5m])' \\
      --period1 '2024-01-01T00:00:00,2024-01-01T12:00:00' \\
      --period2 '2024-01-02T00:00:00,2024-01-02T12:00:00' \\
      --datasource vms-shequ

  # 查询数据源
  python xray_query.py datasource --app myapp
  python xray_query.py datasource --service myservice
  python xray_query.py datasource  # 列出全部
""",
    )

    # 全局参数
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="XRay OpenAPI 基础 URL")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="ticket source 名称")
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="XRay API Token")

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # --- query ---
    p_query = subparsers.add_parser("query", help="执行 PQL 查询并显示统计分析")
    p_query.add_argument("--pql", required=True, help="PromQL 查询表达式")
    p_query.add_argument("--time-range", required=True, help="时间范围 (1h/30m/2d/1w 或 start,end)")
    p_query.add_argument("--step", type=int, default=None, help="步长（秒），默认自动")
    p_query.add_argument("--app", default=None, help="应用名称")
    p_query.add_argument("--datasource", default=None, help="VMS 数据源名称")
    p_query.add_argument("--raw", action="store_true", help="输出原始 JSON 响应")
    p_query.set_defaults(func=cmd_query)

    # --- stats ---
    p_stats = subparsers.add_parser("stats", help="查询指标并输出 JSON 统计信息")
    p_stats.add_argument("--pql", required=True, help="PromQL 查询表达式")
    p_stats.add_argument("--time-range", required=True, help="时间范围")
    p_stats.add_argument("--step", type=int, default=None, help="步长（秒）")
    p_stats.add_argument("--app", default=None, help="应用名称")
    p_stats.add_argument("--datasource", default=None, help="VMS 数据源名称")
    p_stats.set_defaults(func=cmd_stats)

    # --- compare ---
    p_compare = subparsers.add_parser("compare", help="对比两个时间段的指标变化")
    p_compare.add_argument("--pql", required=True, help="PromQL 查询表达式")
    p_compare.add_argument("--period1", required=True, help="基准时间段 (格式同 --time-range)")
    p_compare.add_argument("--period2", required=True, help="对比时间段")
    p_compare.add_argument("--step", type=int, default=None, help="步长（秒）")
    p_compare.add_argument("--app", default=None, help="应用名称")
    p_compare.add_argument("--datasource", default=None, help="VMS 数据源名称")
    p_compare.set_defaults(func=cmd_compare)

    # --- datasource ---
    p_ds = subparsers.add_parser("datasource", help="查询 VMS 数据源")
    p_ds.add_argument("--app", default=None, help="按应用查询")
    p_ds.add_argument("--service", default=None, help="按服务查询")
    p_ds.set_defaults(func=cmd_datasource)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if not args.token:
        print("ERROR: 未提供 XRay API Token。请通过以下方式之一设置:", file=sys.stderr)
        print("  1. 环境变量: export XRAY_TOKEN='your-token'", file=sys.stderr)
        print("  2. 命令行:   --token 'your-token'", file=sys.stderr)
        print("  申请地址: http://xray.devops.xiaohongshu.com/config/token", file=sys.stderr)
        sys.exit(1)

    if not args.source:
        print("ERROR: 未提供 source（调用来源标识）。请通过以下方式之一设置:", file=sys.stderr)
        print("  1. 环境变量: export XRAY_SOURCE='your-app-name'", file=sys.stderr)
        print("  2. 命令行:   --source 'your-app-name'", file=sys.stderr)
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
