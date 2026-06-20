#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
完整链路 + 重启一致性验证
用法：
  python examples/full_verify.py save   # 保存验证后状态
  python examples/full_verify.py check  # 重启后验证一致性
  python examples/full_verify.py        # 跑完整链路并验证
"""

import json
import sys
import os
import urllib.request
import urllib.error

BASE_URL = "http://localhost:5000/api"
SAMPLE_CODE = "FULL-VERIFY-2026-001"
STATE_FILE = "data/full_verify_state.json"


def api(method, path, body=None):
    url = BASE_URL + path
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))


def run_full_chain():
    """跑完整链路：登记→入库→借出→试废弃被拒→退回→废弃→查询验证"""
    print()
    print("=" * 70)
    print("  阶段 1：完整链路执行")
    print("=" * 70)
    print("  样本编号:", SAMPLE_CODE)

    results = {}

    # 1. 登记
    r = api("POST", "/samples", {
        "sample_code": SAMPLE_CODE,
        "name": "完整验证样本-链路+重启",
        "sample_type": "血液",
        "required_temp_zone": "REFRIGERATED",
        "operator": "验证员",
        "operator_role": "LAB_TECHNICIAN",
        "remark": "用于完整验证"
    })
    sid = r["data"]["id"]
    results["sample_id"] = sid
    print()
    print("  [1] 登记样本")
    print("      状态:", r["data"]["status"], " 版本:", r["data"]["version"])
    assert r["data"]["status"] == "REGISTERED" and r["data"]["version"] == 1
    print("      ✓ 通过")

    # 2. 入库
    r = api("POST", "/samples/%d/store-in" % sid, {
        "location_id": 3,
        "operator": "库管员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": 1,
        "reason": "接收入库"
    })
    print()
    print("  [2] 入库到冷藏库位")
    print("      状态:", r["data"]["status"], " 版本:", r["data"]["version"])
    print("      库位:", r["data"]["location_name"])
    assert r["data"]["status"] == "IN_STORAGE" and r["data"]["version"] == 2
    print("      ✓ 通过")

    # 3. 借出
    r = api("POST", "/samples/%d/borrow" % sid, {
        "operator": "实验员小李",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": 2,
        "reason": "生化检测实验",
        "remark": "预计2天"
    })
    print()
    print("  [3] 借出样本")
    print("      状态:", r["data"]["status"], " 版本:", r["data"]["version"])
    assert r["data"]["status"] == "BORROWED" and r["data"]["version"] == 3
    print("      ✓ 通过")

    # 4. 借出状态直接废弃 - 必须被拦截
    r = api("POST", "/samples/%d/discard" % sid, {
        "operator": "主管老王",
        "operator_role": "LAB_MANAGER",
        "expected_version": 3,
        "reason": "尝试直接废弃借出样本"
    })
    print()
    print("  [4] 借出状态下尝试直接废弃（预期被拦截）")
    print("      success:", r.get("success"))
    print("      错误码:", r.get("error"))
    print("      错误信息:", r.get("message", "")[:70])
    blocked = (not r["success"]) and (r.get("error") == "INVALID_STATUS_TRANSITION")
    assert blocked, "借出状态下直接废弃应该被拦截！"
    results["borrow_discard_blocked"] = True
    print("      ✓ 正确拦截")

    # 5. 退回
    r = api("POST", "/samples/%d/return" % sid, {
        "location_id": 4,
        "operator": "实验员小李",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": 3,
        "reason": "实验完成退回",
        "remark": "样本完好"
    })
    print()
    print("  [5] 退回样本（必须先退回才能废弃）")
    print("      状态:", r["data"]["status"], " 版本:", r["data"]["version"])
    print("      库位:", r["data"]["location_name"])
    assert r["data"]["status"] == "IN_STORAGE" and r["data"]["version"] == 4
    print("      ✓ 通过")

    # 6. 退回后废弃
    r = api("POST", "/samples/%d/discard" % sid, {
        "operator": "主管老王",
        "operator_role": "LAB_MANAGER",
        "expected_version": 4,
        "reason": "样本已过有效期，按SOP废弃",
        "remark": "废弃处理完成"
    })
    print()
    print("  [6] 退回后废弃")
    print("      状态:", r["data"]["status"], " 版本:", r["data"]["version"])
    print("      is_deleted:", r["data"]["is_deleted"])
    assert r["data"]["status"] == "DISCARDED" and r["data"]["version"] == 5
    assert r["data"]["is_deleted"] is False, "is_deleted 应该为 False"
    print("      ✓ 通过")

    # 7. 按编码查询
    r = api("GET", "/samples/code/" + SAMPLE_CODE)
    print()
    print("  [7] 按编码查询最终状态")
    print("      success:", r.get("success"))
    print("      状态:", r.get("data", {}).get("status"))
    print("      版本:", r.get("data", {}).get("version"))
    assert r["success"], "废弃后按编码应该能查到"
    assert r["data"]["status"] == "DISCARDED"
    assert r["data"]["version"] == 5
    results["code_query_status"] = r["data"]["status"]
    results["code_query_version"] = r["data"]["version"]
    print("      ✓ 通过")

    # 8. 列表查询
    r = api("GET", "/samples?page=1&per_page=100")
    in_list = any(s["sample_code"] == SAMPLE_CODE for s in r["data"])
    print()
    print("  [8] 列表查询")
    print("      在列表中:", in_list)
    if in_list:
        s = next(s for s in r["data"] if s["sample_code"] == SAMPLE_CODE)
        print("      状态:", s["status"])
        assert s["status"] == "DISCARDED"
    assert in_list, "废弃样本应该在列表中可见"
    print("      ✓ 通过")

    # 9. 审计日志
    r = api("GET", "/samples/%d/audit-logs" % sid)
    logs = r["data"]
    print()
    print("  [9] 审计日志（共 %d 条）" % len(logs))
    for l in logs:
        print("      [%d] %-10s %-12s → %-12s  v%d  %s" % (
            l["sequence"], l["action"],
            l.get("from_status", "-"), l.get("to_status", "-"),
            l["version"], l["operator"]
        ))
    assert len(logs) == 5, "应该有5条审计日志"
    assert logs[-1]["action"] == "DISCARD"
    assert logs[-1]["to_status"] == "DISCARDED"
    results["audit_log_count"] = len(logs)
    results["audit_final_status"] = logs[-1]["to_status"]
    results["audit_final_version"] = logs[-1]["version"]
    print("      ✓ 通过")

    # 10. CSV导出
    req = urllib.request.Request(BASE_URL + "/samples/%d/export-chain?role=LAB_TECHNICIAN" % sid)
    with urllib.request.urlopen(req) as resp:
        csv = resp.read().decode("utf-8-sig")
    has_code = SAMPLE_CODE in csv
    has_discard = "DISCARD" in csv
    has_discarded_status = "DISCARDED" in csv or "已废弃" in csv
    print()
    print("  [10] CSV 导出")
    print("       包含样本编号:", has_code)
    print("       包含废弃操作:", has_discard)
    print("       包含废弃状态:", has_discarded_status)
    assert has_code and has_discard, "CSV 导出内容不对"
    results["csv_has_code"] = has_code
    results["csv_has_discard"] = has_discard
    print("       ✓ 通过")

    # 11. 三方一致性
    print()
    print("=" * 70)
    print("  阶段 2：三方一致性校验")
    print("=" * 70)
    print()

    code_status = results["code_query_status"]
    log_status = results["audit_final_status"]
    csv_ok = results["csv_has_discard"] and results["csv_has_code"]

    print("  按编码查询状态:", code_status)
    print("  审计日志终态:", log_status)
    print("  CSV 包含废弃:", csv_ok)
    print()

    all_consistent = (code_status == log_status == "DISCARDED" and csv_ok)
    print("  三者一致:", "✓ 是" if all_consistent else "✗ 否")
    assert all_consistent, "三者不一致！"
    print()
    print("  ✓ 三方一致性校验通过")

    return results


def save_state(results):
    """保存验证结果，用于重启后比对"""
    # 再额外取一次完整的样本详情，确保保存的是最终状态
    sid = results["sample_id"]
    detail = api("GET", "/samples/%d" % sid)
    logs = api("GET", "/samples/%d/audit-logs" % sid)

    state = {
        "sample_id": sid,
        "sample_code": SAMPLE_CODE,
        "detail": detail["data"],
        "logs": logs["data"],
        "results": results
    }

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 70)
    print("  阶段 3：状态已保存")
    print("=" * 70)
    print("  保存到:", STATE_FILE)
    print("  样本编号:", SAMPLE_CODE)
    print("  样本ID:", sid)
    print("  当前状态:", detail["data"]["status"])
    print("  当前版本:", detail["data"]["version"])
    print("  审计日志:", len(logs["data"]), "条")
    print()


def check_after_restart():
    """重启后验证一致性"""
    if not os.path.exists(STATE_FILE):
        print("错误: 状态文件不存在，请先运行 save")
        return 1

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        before = json.load(f)

    sid = before["sample_id"]
    code = before["sample_code"]

    print()
    print("=" * 70)
    print("  重启后一致性验证")
    print("=" * 70)
    print("  样本编号:", code)
    print("  样本ID:", sid)
    print()

    # 1. 按ID查询
    r1 = api("GET", "/samples/%d" % sid)
    detail_after = r1["data"]
    detail_before = before["detail"]

    print("  [1] 按 ID 查询")
    print("      重启前状态:", detail_before["status"], " 版本:", detail_before["version"])
    print("      重启后状态:", detail_after["status"], " 版本:", detail_after["version"])
    status_ok = detail_before["status"] == detail_after["status"]
    version_ok = detail_before["version"] == detail_after["version"]
    print("      状态一致:", "✓ 是" if status_ok else "✗ 否")
    print("      版本一致:", "✓ 是" if version_ok else "✗ 否")
    assert status_ok and version_ok, "按ID查询不一致"
    print("      ✓ 通过")

    # 2. 按编码查询
    r2 = api("GET", "/samples/code/" + code)
    assert r2["success"], "按编码查询失败"
    code_detail = r2["data"]
    print()
    print("  [2] 按编码查询")
    print("      能查到:", r2["success"])
    print("      状态:", code_detail["status"], " 版本:", code_detail["version"])
    code_match = code_detail["status"] == detail_before["status"]
    code_ver_match = code_detail["version"] == detail_before["version"]
    print("      状态一致:", "✓ 是" if code_match else "✗ 否")
    print("      版本一致:", "✓ 是" if code_ver_match else "✗ 否")
    assert code_match and code_ver_match, "按编码查询不一致"
    print("      ✓ 通过")

    # 3. 审计日志
    r3 = api("GET", "/samples/%d/audit-logs" % sid)
    logs_after = r3["data"]
    logs_before = before["logs"]
    print()
    print("  [3] 审计日志")
    print("      重启前条数:", len(logs_before))
    print("      重启后条数:", len(logs_after))
    log_count_ok = len(logs_before) == len(logs_after)
    print("      条数一致:", "✓ 是" if log_count_ok else "✗ 否")

    last_before = logs_before[-1]
    last_after = logs_after[-1]
    last_ok = (last_before["action"] == last_after["action"] and
               last_before["to_status"] == last_after["to_status"] and
               last_before["version"] == last_after["version"])
    print("      最后一条一致:", "✓ 是" if last_ok else "✗ 否")
    print("        操作:", last_after["action"], " 状态:", last_after["to_status"], " 版本:", last_after["version"])
    assert log_count_ok and last_ok, "审计日志不一致"
    print("      ✓ 通过")

    # 4. CSV导出
    req = urllib.request.Request(BASE_URL + "/samples/%d/export-chain?role=LAB_TECHNICIAN" % sid)
    with urllib.request.urlopen(req) as resp:
        csv_after = resp.read().decode("utf-8-sig")
    has_code = code in csv_after
    has_discard = "DISCARD" in csv_after
    print()
    print("  [4] CSV 导出")
    print("      包含样本编号:", has_code)
    print("      包含废弃操作:", has_discard)
    assert has_code and has_discard, "CSV 导出不对"
    print("      ✓ 通过")

    # 5. 列表查询
    r5 = api("GET", "/samples?page=1&per_page=100")
    in_list = any(s["sample_code"] == code for s in r5["data"])
    print()
    print("  [5] 列表查询")
    print("      在列表中:", in_list)
    assert in_list, "列表中找不到"
    print("      ✓ 通过")

    # 总结
    print()
    print("=" * 70)
    print("  重启后验证结论")
    print("=" * 70)
    print()
    print("  ✓ 按 ID 查询一致")
    print("  ✓ 按编码查询一致")
    print("  ✓ 审计日志一致")
    print("  ✓ CSV 导出一致")
    print("  ✓ 列表查询一致")
    print()
    print("  ✓✓✓ 全部通过，进程重启后数据完全一致！")
    print("=" * 70)
    print()

    return 0


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "full"

    if action == "save":
        results = run_full_chain()
        save_state(results)
        return 0
    elif action == "check":
        return check_after_restart()
    else:
        results = run_full_chain()
        save_state(results)
        print()
        print("💡 提示：现在可以重启服务，然后运行 python examples/full_verify.py check 验证重启后一致性")
        print()
        return 0


if __name__ == "__main__":
    sys.exit(main())
