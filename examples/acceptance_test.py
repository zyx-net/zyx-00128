#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
实验室样本交接系统 - 验收测试脚本（Windows 稳定版）
运行方式: python examples/acceptance_test.py
"""

import json
import sys
import time
import urllib.request
import urllib.error

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "http://localhost:5000/api"
test_count = 0
pass_count = 0
fail_count = 0

_REGRESS_CODE = "TEST-REGRESS-%d" % int(time.time() * 1000)


def header(title):
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def test(name, passed, message=""):
    global test_count, pass_count, fail_count
    test_count += 1
    if passed:
        pass_count += 1
        status = "[OK] PASS"
    else:
        fail_count += 1
        status = "[FAIL]"
    print(f"  {status}  {name}")
    if message:
        print(f"         {message}")


def api_call(method, path, body=None):
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
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"success": False, "message": str(e), "error": "HTTP_ERROR"}
    except Exception as e:
        return {"success": False, "message": str(e), "error": "CONNECTION_ERROR"}


def check_service():
    """检查服务是否启动"""
    try:
        result = api_call("GET", "/health")
        return result.get("success", False)
    except Exception:
        return False


def _mk_code(prefix):
    return "%s-%d" % (prefix, int(time.time() * 1000) % 10000000000)


def _chk(resp, ctx=""):
    if not resp.get("success"):
        print()
        print("  [ERROR] %s" % ctx)
        print("    错误码: %s" % resp.get("error"))
        print("    错误信息: %s" % resp.get("message", ""))
        print("    完整响应: %s" % json.dumps(resp, ensure_ascii=False)[:500])
        sys.exit(1)
    if "data" not in resp:
        print()
        print("  [ERROR] %s - 响应缺少 data 字段" % ctx)
        sys.exit(1)
    return resp["data"]


def main():
    print()
    print("=" * 70)
    print("  实验室样本交接系统 - 验收测试")
    print("=" * 70)
    print()

    if not check_service():
        print("服务未启动! 请先运行: python run.py")
        sys.exit(1)

    print("服务状态: 运行中 [OK]")

    # ========== 验收用例 1: 完整生命周期 ==========
    header("验收用例 1: 完整生命周期（登记→入库→借出→退回→废弃）")
    case1_code = _mk_code("TEST-ACCEPT-1")

    # 1.1 登记样本
    result = api_call("POST", "/samples", {
        "sample_code": case1_code,
        "name": "验收样本-完整生命周期",
        "sample_type": "血液",
        "required_temp_zone": "REFRIGERATED",
        "operator": "验收员",
        "operator_role": "LAB_TECHNICIAN",
        "remark": "自动化验收测试"
    })
    d = _chk(result, "用例1-登记样本")
    sample_id = d["id"]
    sample_version = d["version"]
    test("1.1 登记样本成功", result["success"], f"样本ID: {sample_id}, 版本: {sample_version}")

    # 1.2 状态校验
    test("1.2 状态为 REGISTERED", d["status"] == "REGISTERED",
         f"当前状态: {d['status']}")

    # 1.3 入库（温区匹配）
    result = api_call("POST", f"/samples/{sample_id}/store-in", {
        "location_id": 3,
        "operator": "库管员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": sample_version,
        "reason": "接收入库"
    })
    d = _chk(result, "用例1-入库")
    sample_version = d["version"]
    test("1.3 入库成功（温区匹配）", result["success"], f"新版本: {sample_version}")

    # 1.4 状态校验
    test("1.4 状态变为 IN_STORAGE", d["status"] == "IN_STORAGE",
         f"当前状态: {d['status']}")

    # 1.5 借出
    result = api_call("POST", f"/samples/{sample_id}/borrow", {
        "operator": "实验员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": sample_version,
        "reason": "实验使用",
        "remark": "测试借出"
    })
    d = _chk(result, "用例1-借出")
    sample_version = d["version"]
    test("1.5 借出成功", result["success"], f"新版本: {sample_version}")

    # 1.6 状态校验
    test("1.6 状态变为 BORROWED", d["status"] == "BORROWED",
         f"当前状态: {d['status']}")

    # 1.7 退回
    result = api_call("POST", f"/samples/{sample_id}/return", {
        "location_id": 3,
        "operator": "实验员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": sample_version,
        "reason": "实验完成退回"
    })
    d = _chk(result, "用例1-退回")
    sample_version = d["version"]
    test("1.7 退回成功", result["success"], f"新版本: {sample_version}")

    # 1.8 状态校验
    test("1.8 状态变回 IN_STORAGE", d["status"] == "IN_STORAGE",
         f"当前状态: {d['status']}")

    # 1.9 废弃
    result = api_call("POST", f"/samples/{sample_id}/discard", {
        "operator": "主管",
        "operator_role": "LAB_MANAGER",
        "expected_version": sample_version,
        "reason": "样本过期废弃",
        "remark": "按SOP处理"
    })
    d = _chk(result, "用例1-废弃")
    sample_version = d["version"]
    test("1.9 废弃成功", result["success"], f"最终版本: {sample_version}")

    # 1.10 状态校验
    test("1.10 最终状态为 DISCARDED", d["status"] == "DISCARDED",
         f"最终状态: {d['status']}")

    # 1.11 审计日志数量
    logs_result = api_call("GET", f"/samples/{sample_id}/audit-logs")
    _chk(logs_result, "用例1-查询审计日志")
    test("1.11 审计日志完整（5条记录）", len(logs_result["data"]) == 5,
         f"实际记录数: {len(logs_result['data'])}")

    # 1.12 版本号递增验证
    versions = sorted([log["version"] for log in logs_result["data"]])
    version_correct = versions == [1, 2, 3, 4, 5]
    test("1.12 版本号正确递增", version_correct, f"版本序列: {versions}")

    # ========== 验收用例 2: 温区不匹配 ==========
    header("验收用例 2: 温区不匹配导致操作失败")
    case2_code = _mk_code("TEST-ACCEPT-2")

    # 2.1 登记冷冻样本
    result = api_call("POST", "/samples", {
        "sample_code": case2_code,
        "name": "验收样本-温区测试",
        "sample_type": "血清",
        "required_temp_zone": "FROZEN",
        "operator": "验收员",
        "operator_role": "LAB_TECHNICIAN"
    })
    d = _chk(result, "用例2-登记冷冻样本")
    sample_id2 = d["id"]
    test("2.1 登记冷冻样本成功", result["success"], f"样本ID: {sample_id2}")

    # 2.2 尝试入库到常温库位（应失败）
    result = api_call("POST", f"/samples/{sample_id2}/store-in", {
        "location_id": 1,
        "operator": "库管员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": 1,
        "reason": "测试温区"
    })
    temp_mismatch = (not result["success"]) and (result.get("error") == "TEMP_ZONE_MISMATCH")
    test("2.2 入库常温库位失败（温区不匹配）", temp_mismatch, f"错误码: {result.get('error')}")

    # 2.3 验证错误信息包含温区说明
    has_temp_info = "温区" in result.get("message", "")
    test("2.3 错误信息指出温区规则", has_temp_info,
         f"错误信息: {result.get('message', '')[:60]}...")

    # 2.4 正确入库到冷冻库位
    result = api_call("POST", f"/samples/{sample_id2}/store-in", {
        "location_id": 5,
        "operator": "库管员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": 1,
        "reason": "正常入库"
    })
    d = _chk(result, "用例2-正确入库冷冻库位")
    test("2.4 正确入库冷冻库位成功", result["success"], f"状态: {d['status']}")

    # 2.5 尝试转移到冷藏库位（应失败）
    result = api_call("POST", f"/samples/{sample_id2}/transfer", {
        "to_location_id": 3,
        "operator": "库管员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": 2,
        "reason": "测试转移温区"
    })
    transfer_fail = (not result["success"]) and (result.get("error") == "TEMP_ZONE_MISMATCH")
    test("2.5 转移冷藏库位失败（温区不匹配）", transfer_fail, f"错误码: {result.get('error')}")

    # ========== 验收用例 3: 乐观锁 ==========
    header("验收用例 3: 乐观锁 - 两次基于旧版本更新只能成功一次")
    case3_code = _mk_code("TEST-ACCEPT-3")

    # 3.1 登记常温样本
    result = api_call("POST", "/samples", {
        "sample_code": case3_code,
        "name": "验收样本-乐观锁测试",
        "sample_type": "尿液",
        "required_temp_zone": "AMBIENT",
        "operator": "验收员",
        "operator_role": "LAB_TECHNICIAN"
    })
    d = _chk(result, "用例3-登记样本")
    sample_id3 = d["id"]
    old_version = d["version"]
    test("3.1 登记常温样本成功", result["success"], f"版本: {old_version}")

    # 3.2 入库
    result = api_call("POST", f"/samples/{sample_id3}/store-in", {
        "location_id": 1,
        "operator": "库管员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": 1,
        "reason": "入库"
    })
    d = _chk(result, "用例3-入库")
    base_version = d["version"]
    test(f"3.2 入库成功（版本: {base_version}）", result["success"],
         f"当前版本: {base_version}")

    # 3.3 第一次基于旧版本转移（应该成功）
    result1 = api_call("POST", f"/samples/{sample_id3}/transfer", {
        "to_location_id": 2,
        "operator": "操作员A",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": base_version,
        "reason": "第一次转移"
    })
    d1 = _chk(result1, "用例3-第一次转移")
    test(f"3.3 第一次基于版本{base_version}转移成功", result1["success"],
         f"新版本: {d1['version']}")

    # 3.4 第二次基于同一旧版本转移（应该失败）
    result2 = api_call("POST", f"/samples/{sample_id3}/transfer", {
        "to_location_id": 1,
        "operator": "操作员B",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": base_version,
        "reason": "第二次转移"
    })
    version_conflict = (not result2["success"]) and (result2.get("error") == "VERSION_CONFLICT")
    test(f"3.4 第二次基于版本{base_version}转移失败（版本冲突）", version_conflict,
         f"错误码: {result2.get('error')}")

    # 3.5 验证最终版本号
    final_result = api_call("GET", f"/samples/{sample_id3}")
    d_final = _chk(final_result, "用例3-查询最终版本")
    expected_version = base_version + 1
    test(f"3.5 最终版本号为 {expected_version}",
         d_final["version"] == expected_version,
         f"实际版本: {d_final['version']}")

    # 3.6 审计日志中只有一次转移
    logs_result = api_call("GET", f"/samples/{sample_id3}/audit-logs")
    _chk(logs_result, "用例3-查询审计日志")
    transfer_logs = [log for log in logs_result["data"] if log["action"] == "TRANSFER"]
    test("3.6 审计日志只有1条转移记录", len(transfer_logs) == 1,
         f"转移记录数: {len(transfer_logs)}")

    # ========== 验收用例 4: 数据持久化 ==========
    header("验收用例 4: 数据一致性验证")

    # 4.1 样本1废弃后按编码查询能查到
    sample1_by_code = api_call("GET", f"/samples/code/{case1_code}")
    sample1_found_by_code = sample1_by_code.get("success", False)
    test("4.1 样本1按编码查询能查到（废弃后仍可查）", sample1_found_by_code,
         f"状态: {sample1_by_code.get('data', {}).get('status', 'N/A')}")

    # 4.2 按编码查到的状态是 DISCARDED
    sample1_status_ok = sample1_by_code.get("data", {}).get("status") == "DISCARDED"
    test("4.2 按编码查询状态为 DISCARDED", sample1_status_ok,
         f"状态: {sample1_by_code.get('data', {}).get('status', 'N/A')}")

    # 4.3 审计日志完整
    sample1_logs = api_call("GET", f"/samples/{sample_id}/audit-logs")
    _chk(sample1_logs, "用例4-查询样本1审计日志")
    test("4.3 审计日志完整（5条）",
         len(sample1_logs["data"]) == 5,
         f"日志数量: {len(sample1_logs['data'])}")

    # 4.4 按编码查询状态 vs 审计日志终态 一致
    final_log_status = sample1_logs["data"][-1]["to_status"]
    code_query_status = sample1_by_code.get("data", {}).get("status")
    status_consistent = final_log_status == code_query_status == "DISCARDED"
    test("4.4 按编码查询状态与审计日志终态一致", status_consistent,
         f"编码查询: {code_query_status}, 日志终态: {final_log_status}")

    # 4.5 导出CSV验证
    try:
        req = urllib.request.Request(f"{BASE_URL}/samples/{sample_id}/export-chain?role=LAB_TECHNICIAN")
        with urllib.request.urlopen(req) as resp:
            csv_content = resp.read().decode("utf-8-sig")
        has_csv_data = "样本编号" in csv_content and case1_code in csv_content
        test("4.5 CSV导出功能正常，包含样本编号", has_csv_data, "CSV包含样本编号")
    except Exception as e:
        test("4.5 CSV导出功能正常，包含样本编号", False, str(e))

    # ========== 验收用例 5: 角色权限 ==========
    header("验收用例 5: 角色权限验证")
    case5_code = _mk_code("TEST-ACCEPT-PERM")

    # 5.1 GUEST角色不能登记样本
    result = api_call("POST", "/samples", {
        "sample_code": case5_code,
        "name": "权限测试",
        "required_temp_zone": "AMBIENT",
        "operator": "访客",
        "operator_role": "GUEST"
    })
    perm_denied = (not result["success"]) and (result.get("error") == "PERMISSION_DENIED")
    test("5.1 GUEST角色不能登记样本", perm_denied, f"错误码: {result.get('error')}")

    # 5.2 GUEST角色可以查看
    result = api_call("GET", f"/samples/{sample_id3}")
    _chk(result, "用例5-查看样本")
    test("5.2 GUEST角色可以查看样本", result["success"], "查看成功")

    # 5.3 LAB_TECHNICIAN不能废弃样本
    result = api_call("POST", f"/samples/{sample_id3}/discard", {
        "operator": "实验员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": 3,
        "reason": "测试权限"
    })
    discard_denied = (not result["success"]) and (result.get("error") == "PERMISSION_DENIED")
    test("5.3 LAB_TECHNICIAN不能废弃样本", discard_denied, f"错误码: {result.get('error')}")

    # ========== 验收用例 6: 回归测试 ==========
    header("验收用例 6: 回归测试 - 状态流转与查询一致性")
    case6_code = _REGRESS_CODE

    # 6.1 登记一个新样本，用于回归测试
    result = api_call("POST", "/samples", {
        "sample_code": case6_code,
        "name": "回归测试样本-借出废弃链路",
        "sample_type": "血液",
        "required_temp_zone": "REFRIGERATED",
        "operator": "回归测试员",
        "operator_role": "LAB_TECHNICIAN"
    })
    d = _chk(result, "用例6-登记回归样本")
    reg_sample_id = d["id"]
    reg_sample_code = case6_code
    test("6.1 登记回归测试样本成功", result["success"],
         f"样本ID: {reg_sample_id}, 编号: {reg_sample_code}")

    # 6.2 入库
    result = api_call("POST", f"/samples/{reg_sample_id}/store-in", {
        "location_id": 3,
        "operator": "库管员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": 1,
        "reason": "入库"
    })
    d = _chk(result, "用例6-入库")
    reg_version = d["version"]
    test("6.2 入库成功", result["success"], f"版本: {reg_version}")

    # 6.3 借出
    result = api_call("POST", f"/samples/{reg_sample_id}/borrow", {
        "operator": "实验员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": reg_version,
        "reason": "实验使用"
    })
    d = _chk(result, "用例6-借出")
    reg_version = d["version"]
    borrow_ok = result["success"] and d["status"] == "BORROWED"
    test("6.3 借出成功，状态为 BORROWED", borrow_ok,
         f"状态: {d['status']}, 版本: {reg_version}")

    # 6.4 借出状态下直接废弃 - 应该被拦截
    result = api_call("POST", f"/samples/{reg_sample_id}/discard", {
        "operator": "主管",
        "operator_role": "LAB_MANAGER",
        "expected_version": reg_version,
        "reason": "尝试直接废弃借出样本"
    })
    borrow_discard_blocked = (not result["success"]) and (result.get("error") == "INVALID_STATUS_TRANSITION")
    test("6.4 借出中直接废弃被拦截", borrow_discard_blocked,
         f"错误码: {result.get('error')}, 信息: {result.get('message', '')[:50]}")

    # 6.5 先退回
    result = api_call("POST", f"/samples/{reg_sample_id}/return", {
        "location_id": 3,
        "operator": "实验员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": reg_version,
        "reason": "实验完成退回"
    })
    d = _chk(result, "用例6-退回")
    reg_version = d["version"]
    return_ok = result["success"] and d["status"] == "IN_STORAGE"
    test("6.5 退回成功，状态变回 IN_STORAGE", return_ok,
         f"状态: {d['status']}, 版本: {reg_version}")

    # 6.6 退回后再废弃 - 应该成功
    result = api_call("POST", f"/samples/{reg_sample_id}/discard", {
        "operator": "主管",
        "operator_role": "LAB_MANAGER",
        "expected_version": reg_version,
        "reason": "样本过期废弃"
    })
    d = _chk(result, "用例6-废弃")
    reg_version = d["version"]
    discard_ok = result["success"] and d["status"] == "DISCARDED"
    test("6.6 退回后废弃成功，状态为 DISCARDED", discard_ok,
         f"状态: {d['status']}, 版本: {reg_version}")

    # 6.7 废弃后按编码查询 - 必须能查到
    result_by_code = api_call("GET", f"/samples/code/{reg_sample_code}")
    d_code = _chk(result_by_code, "用例6-按编码查询")
    code_query_ok = result_by_code.get("success", False) and d_code.get("status") == "DISCARDED"
    test("6.7 废弃后按编码查询能查到，状态为 DISCARDED", code_query_ok,
         f"success: {result_by_code.get('success')}, 状态: {d_code.get('status', 'N/A')}")

    # 6.8 按编码查询的版本号与实际一致
    code_version_match = d_code.get("version") == reg_version
    test("6.8 按编码查询的版本号与废弃后的版本一致", code_version_match,
         f"查询版本: {d_code.get('version')}, 实际版本: {reg_version}")

    # 6.9 审计日志条数和状态
    logs_result = api_call("GET", f"/samples/{reg_sample_id}/audit-logs")
    _chk(logs_result, "用例6-查询审计日志")
    logs_ok = len(logs_result["data"]) == 5  # 登记、入库、借出、退回、废弃
    test("6.9 审计日志共5条（登记/入库/借出/退回/废弃）", logs_ok,
         f"实际条数: {len(logs_result['data'])}")

    # 6.10 审计日志最后一条是 DISCARD
    last_log = logs_result["data"][-1]
    last_log_ok = last_log["action"] == "DISCARD" and last_log["to_status"] == "DISCARDED"
    test("6.10 审计日志最后一条是废弃操作", last_log_ok,
         f"最后操作: {last_log.get('action')}, 目标状态: {last_log.get('to_status')}")

    # 6.11 按编码查询状态 vs 审计日志终态 一致
    code_status = result_by_code.get("data", {}).get("status")
    log_final_status = last_log.get("to_status")
    status_consistent = code_status == log_final_status == "DISCARDED"
    test("6.11 按编码查询状态与审计日志终态一致", status_consistent,
         f"编码查询状态: {code_status}, 日志终态: {log_final_status}")

    # 6.12 CSV导出 与 按编码查询 一致
    try:
        req = urllib.request.Request(f"{BASE_URL}/samples/{reg_sample_id}/export-chain?role=LAB_TECHNICIAN")
        with urllib.request.urlopen(req) as resp:
            csv_content = resp.read().decode("utf-8-sig")
        csv_has_sample = reg_sample_code in csv_content
        csv_has_discard = "DISCARD" in csv_content
        csv_ok = csv_has_sample and csv_has_discard
        test("6.12 CSV导出包含样本编号和废弃记录，与查询一致", csv_ok,
             f"包含样本编号: {csv_has_sample}, 包含废弃记录: {csv_has_discard}")
    except Exception as e:
        test("6.12 CSV导出包含样本编号和废弃记录，与查询一致", False, str(e))

    # 6.13 样本列表中也能查到废弃样本
    list_result = api_call("GET", "/samples?page=1&per_page=50")
    in_list = any(s["sample_code"] == reg_sample_code for s in list_result.get("data", []))
    test("6.13 废弃样本仍出现在列表中（状态为已废弃）", in_list,
         f"列表中找到: {in_list}")

    # ========== 汇总 ==========
    print()
    print("=" * 70)
    print("  测试汇总")
    print("=" * 70)
    print()
    print(f"  总测试数: {test_count}")
    print(f"  通过:     {pass_count}")
    print(f"  失败:     {fail_count}")
    print()

    if fail_count == 0:
        print("  ✓ 所有验收用例通过！")
        return 0
    else:
        print(f"  ✗ 有 {fail_count} 个用例失败，请检查！")
        return 1


if __name__ == "__main__":
    sys.exit(main())
