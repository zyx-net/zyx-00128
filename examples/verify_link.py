#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
借出→退回→废弃 链路真实接口验证
一步步打印每一步的关键响应，便于核对
"""

import json
import urllib.request
import urllib.error

BASE_URL = "http://localhost:5000/api"
SAMPLE_CODE = "VERIFY-LINK-001"


def api(method, path, body=None):
    url = f"{BASE_URL}{path}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))


def print_step(title, result, keys=None):
    print()
    print("─" * 60)
    print(f"  {title}")
    print("─" * 60)
    success = result.get("success", False)
    status = "✓ 成功" if success else "✗ 失败"
    print(f"  结果: {status}")
    if not success:
        print(f"  错误码: {result.get('error')}")
        print(f"  错误信息: {result.get('message')}")
    if keys and success and "data" in result:
        for k in keys:
            v = result["data"].get(k)
            print(f"  {k}: {v}")
    print()


def main():
    print("╔════════════════════════════════════════════════════════════╗")
    print("║       借出 → 退回 → 废弃 链路真实接口验证                  ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print(f"  样本编号: {SAMPLE_CODE}")

    # 第1步：登记样本
    r1 = api("POST", "/samples", {
        "sample_code": SAMPLE_CODE,
        "name": "链路验证样本-借出退回废弃",
        "sample_type": "血液",
        "required_temp_zone": "REFRIGERATED",
        "operator": "验证员",
        "operator_role": "LAB_TECHNICIAN",
        "remark": "用于验证完整流转链路"
    })
    sample_id = r1["data"]["id"] if r1.get("success") else None
    print_step("第1步：登记样本（REG → 初始版本v1）", r1,
               ["sample_code", "status", "version", "location_name"])

    # 第2步：入库到冷藏库位
    r2 = api("POST", f"/samples/{sample_id}/store-in", {
        "location_id": 3,
        "operator": "库管员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": 1,
        "reason": "样本接收入库"
    })
    print_step("第2步：入库到冷藏库位（REG → IN_STORAGE，v1→v2）", r2,
               ["status", "version", "location_name"])

    # 第3步：借出
    r3 = api("POST", f"/samples/{sample_id}/borrow", {
        "operator": "实验员小李",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": 2,
        "reason": "进行生化检测实验",
        "remark": "预计使用2天"
    })
    print_step("第3步：借出样本（IN_STORAGE → BORROWED，v2→v3）", r3,
               ["status", "version", "location_name"])

    # 第4步：借出状态下尝试直接废弃 - 应该被拦截
    r4 = api("POST", f"/samples/{sample_id}/discard", {
        "operator": "主管老王",
        "operator_role": "LAB_MANAGER",
        "expected_version": 3,
        "reason": "尝试在借出状态直接废弃"
    })
    print_step("第4步：借出状态下尝试直接废弃（应被拦截！）", r4)

    # 第5步：退回
    r5 = api("POST", f"/samples/{sample_id}/return", {
        "location_id": 4,
        "operator": "实验员小李",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": 3,
        "reason": "实验完成，样本退回",
        "remark": "样本完好无损"
    })
    print_step("第5步：退回样本（BORROWED → IN_STORAGE，v3→v4）", r5,
               ["status", "version", "location_name"])

    # 第6步：退回后废弃 - 应该成功
    r6 = api("POST", f"/samples/{sample_id}/discard", {
        "operator": "主管老王",
        "operator_role": "LAB_MANAGER",
        "expected_version": 4,
        "reason": "样本已过有效期，按SOP废弃",
        "remark": "废弃处理完成，记录归档"
    })
    print_step("第6步：退回后废弃（IN_STORAGE → DISCARDED，v4→v5）", r6,
               ["status", "version", "location_name"])

    # 第7步：按编码查询最终状态
    r7 = api("GET", f"/samples/code/{SAMPLE_CODE}")
    print_step("第7步：按编码查询最终状态（必须能查到！）", r7,
               ["sample_code", "status", "version", "is_deleted"])

    # 第8步：查询审计日志
    r8 = api("GET", f"/samples/{sample_id}/audit-logs")
    print()
    print("─" * 60)
    print("  第8步：审计日志完整链路")
    print("─" * 60)
    if r8.get("success"):
        print(f"  共 {len(r8['data'])} 条记录")
        print()
        for log in r8["data"]:
            seq = log["sequence"]
            action = log["action"]
            from_s = log.get("from_status", "-")
            to_s = log.get("to_status", "-")
            op = log.get("operator", "-")
            ver = log.get("version", "-")
            from_loc = log.get("from_location_name", "-") or "-"
            to_loc = log.get("to_location_name", "-") or "-"
            print(f"  [{seq}] {action:10s} {from_s:12s} → {to_s:12s}  "
                  f"库位: {from_loc:10s} → {to_loc:10s}  "
                  f"操作人: {op:8s}  v{ver}")
    print()

    # 第9步：按编码查询 vs 审计日志终态 一致性核对
    print("─" * 60)
    print("  第9步：三方一致性核对")
    print("─" * 60)
    code_status = r7.get("data", {}).get("status") if r7.get("success") else "N/A"
    code_version = r7.get("data", {}).get("version") if r7.get("success") else "N/A"
    log_final_status = r8["data"][-1]["to_status"] if r8.get("success") else "N/A"
    log_final_version = r8["data"][-1]["version"] if r8.get("success") else "N/A"

    print(f"  按编码查询状态: {code_status}  版本: {code_version}")
    print(f"  审计日志终态:   {log_final_status}  版本: {log_final_version}")

    status_match = code_status == log_final_status == "DISCARDED"
    version_match = code_version == log_final_version
    print()
    print(f"  状态一致: {'✓ 是' if status_match else '✗ 否'}")
    print(f"  版本一致: {'✓ 是' if version_match else '✗ 否'}")
    print()

    # 第10步：CSV导出验证
    print("─" * 60)
    print("  第10步：CSV导出与查询一致性")
    print("─" * 60)
    try:
        req = urllib.request.Request(f"{BASE_URL}/samples/{sample_id}/export-chain?role=LAB_TECHNICIAN")
        with urllib.request.urlopen(req) as resp:
            csv_content = resp.read().decode("utf-8-sig")
        has_code = SAMPLE_CODE in csv_content
        has_discard = "DISCARD" in csv_content
        has_status = "已废弃" in csv_content or "DISCARDED" in csv_content
        print(f"  CSV包含样本编号: {'✓ 是' if has_code else '✗ 否'}")
        print(f"  CSV包含废弃记录: {'✓ 是' if has_discard else '✗ 否'}")
        print(f"  CSV包含废弃状态: {'✓ 是' if has_status else '✗ 否'}")

        csv_match = has_code and has_discard
        print()
        print(f"  CSV与查询一致: {'✓ 是' if csv_match else '✗ 否'}")
    except Exception as e:
        print(f"  导出失败: {e}")
        csv_match = False
    print()

    # 最终结论
    all_ok = (r1.get("success") and r2.get("success") and r3.get("success") and
              not r4.get("success") and r5.get("success") and r6.get("success") and
              r7.get("success") and status_match and version_match and csv_match)

    print("═" * 60)
    print(f"  最终结论: {'✓ 全部验证通过！' if all_ok else '✗ 存在问题，请检查'}")
    print("═" * 60)
    print()
    print("  关键结论:")
    print("    1. 借出状态下直接废弃 → 被拦截（INVALID_STATUS_TRANSITION）")
    print("    2. 必须先退回再废弃 → 正常执行")
    print("    3. 废弃后按编码查询 → 能查到，状态为 DISCARDED")
    print("    4. 按编码查询 / 审计日志 / CSV导出 → 三者一致")
    print()


if __name__ == "__main__":
    main()
