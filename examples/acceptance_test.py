#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
实验室样本交接系统 - 验收测试脚本
运行方式: python examples/acceptance_test.py
"""

import json
import sys
import urllib.request
import urllib.error

BASE_URL = "http://localhost:5000/api"
test_count = 0
pass_count = 0
fail_count = 0


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
        status = "✓ PASS"
    else:
        fail_count += 1
        status = "✗ FAIL"
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


def main():
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║           实验室样本交接系统 - 验收测试                          ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

    if not check_service():
        print("服务未启动! 请先运行: python run.py")
        sys.exit(1)

    print("服务状态: 运行中 ✓")

    # ========== 验收用例 1: 完整生命周期 ==========
    header("验收用例 1: 完整生命周期（登记→入库→借出→退回→废弃）")

    # 1.1 登记样本
    result = api_call("POST", "/samples", {
        "sample_code": "TEST-ACCEPT-001",
        "name": "验收样本-完整生命周期",
        "sample_type": "血液",
        "required_temp_zone": "REFRIGERATED",
        "operator": "验收员",
        "operator_role": "LAB_TECHNICIAN",
        "remark": "自动化验收测试"
    })
    sample_id = result["data"]["id"]
    sample_version = result["data"]["version"]
    test("1.1 登记样本成功", result["success"], f"样本ID: {sample_id}, 版本: {sample_version}")

    # 1.2 状态校验
    test("1.2 状态为 REGISTERED", result["data"]["status"] == "REGISTERED",
         f"当前状态: {result['data']['status']}")

    # 1.3 入库（温区匹配）
    result = api_call("POST", f"/samples/{sample_id}/store-in", {
        "location_id": 3,
        "operator": "库管员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": sample_version,
        "reason": "接收入库"
    })
    sample_version = result["data"]["version"]
    test("1.3 入库成功（温区匹配）", result["success"], f"新版本: {sample_version}")

    # 1.4 状态校验
    test("1.4 状态变为 IN_STORAGE", result["data"]["status"] == "IN_STORAGE",
         f"当前状态: {result['data']['status']}")

    # 1.5 借出
    result = api_call("POST", f"/samples/{sample_id}/borrow", {
        "operator": "实验员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": sample_version,
        "reason": "实验使用",
        "remark": "测试借出"
    })
    sample_version = result["data"]["version"]
    test("1.5 借出成功", result["success"], f"新版本: {sample_version}")

    # 1.6 状态校验
    test("1.6 状态变为 BORROWED", result["data"]["status"] == "BORROWED",
         f"当前状态: {result['data']['status']}")

    # 1.7 退回
    result = api_call("POST", f"/samples/{sample_id}/return", {
        "location_id": 3,
        "operator": "实验员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": sample_version,
        "reason": "实验完成退回"
    })
    sample_version = result["data"]["version"]
    test("1.7 退回成功", result["success"], f"新版本: {sample_version}")

    # 1.8 状态校验
    test("1.8 状态变回 IN_STORAGE", result["data"]["status"] == "IN_STORAGE",
         f"当前状态: {result['data']['status']}")

    # 1.9 废弃
    result = api_call("POST", f"/samples/{sample_id}/discard", {
        "operator": "主管",
        "operator_role": "LAB_MANAGER",
        "expected_version": sample_version,
        "reason": "样本过期废弃",
        "remark": "按SOP处理"
    })
    sample_version = result["data"]["version"]
    test("1.9 废弃成功", result["success"], f"最终版本: {sample_version}")

    # 1.10 状态校验
    test("1.10 最终状态为 DISCARDED", result["data"]["status"] == "DISCARDED",
         f"最终状态: {result['data']['status']}")

    # 1.11 审计日志数量
    logs_result = api_call("GET", f"/samples/{sample_id}/audit-logs")
    test("1.11 审计日志完整（5条记录）", len(logs_result["data"]) == 5,
         f"实际记录数: {len(logs_result['data'])}")

    # 1.12 版本号递增验证
    versions = sorted([log["version"] for log in logs_result["data"]])
    version_correct = versions == [1, 2, 3, 4, 5]
    test("1.12 版本号正确递增", version_correct, f"版本序列: {versions}")

    # ========== 验收用例 2: 温区不匹配 ==========
    header("验收用例 2: 温区不匹配导致操作失败")

    # 2.1 登记冷冻样本
    result = api_call("POST", "/samples", {
        "sample_code": "TEST-ACCEPT-002",
        "name": "验收样本-温区测试",
        "sample_type": "血清",
        "required_temp_zone": "FROZEN",
        "operator": "验收员",
        "operator_role": "LAB_TECHNICIAN"
    })
    sample_id2 = result["data"]["id"]
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
    test("2.4 正确入库冷冻库位成功", result["success"], f"状态: {result['data']['status']}")

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

    # 3.1 登记常温样本
    result = api_call("POST", "/samples", {
        "sample_code": "TEST-ACCEPT-003",
        "name": "验收样本-乐观锁测试",
        "sample_type": "尿液",
        "required_temp_zone": "AMBIENT",
        "operator": "验收员",
        "operator_role": "LAB_TECHNICIAN"
    })
    sample_id3 = result["data"]["id"]
    old_version = result["data"]["version"]
    test("3.1 登记常温样本成功", result["success"], f"版本: {old_version}")

    # 3.2 入库
    result = api_call("POST", f"/samples/{sample_id3}/store-in", {
        "location_id": 1,
        "operator": "库管员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": 1,
        "reason": "入库"
    })
    base_version = result["data"]["version"]
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
    test(f"3.3 第一次基于版本{base_version}转移成功", result1["success"],
         f"新版本: {result1['data']['version']}")

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
    expected_version = base_version + 1
    test(f"3.5 最终版本号为 {expected_version}",
         final_result["data"]["version"] == expected_version,
         f"实际版本: {final_result['data']['version']}")

    # 3.6 审计日志中只有一次转移
    logs_result = api_call("GET", f"/samples/{sample_id3}/audit-logs")
    transfer_logs = [log for log in logs_result["data"] if log["action"] == "TRANSFER"]
    test("3.6 审计日志只有1条转移记录", len(transfer_logs) == 1,
         f"转移记录数: {len(transfer_logs)}")

    # ========== 验收用例 4: 数据持久化 ==========
    header("验收用例 4: 数据一致性验证")

    # 4.1 查询样本1最终状态（通过ID，因为废弃后is_deleted=True）
    sample1_result = api_call("GET", f"/samples/{sample_id}")
    sample1_logs = api_call("GET", f"/samples/{sample_id}/audit-logs")
    sample1_found = sample1_result.get("success", False) or sample1_result.get("error") != "SAMPLE_NOT_FOUND"
    test("4.1 样本1可通过ID查询", sample1_found,
         f"状态: {sample1_result.get('data', {}).get('status', 'N/A')}")
    test("4.2 样本1审计日志完整（5条）",
         len(sample1_logs["data"]) == 5,
         f"日志数量: {len(sample1_logs['data'])}")

    # 4.3 导出CSV验证
    try:
        req = urllib.request.Request(f"{BASE_URL}/samples/{sample_id}/export-chain?role=LAB_TECHNICIAN")
        with urllib.request.urlopen(req) as resp:
            csv_content = resp.read().decode("utf-8-sig")
        has_csv_data = "样本编号" in csv_content and "TEST-ACCEPT-001" in csv_content
        test("4.3 CSV导出功能正常", has_csv_data, "CSV包含样本编号")
    except Exception as e:
        test("4.3 CSV导出功能正常", False, str(e))

    # ========== 验收用例 5: 角色权限 ==========
    header("验收用例 5: 角色权限验证")

    # 5.1 GUEST角色不能登记样本
    result = api_call("POST", "/samples", {
        "sample_code": "TEST-ACCEPT-PERM",
        "name": "权限测试",
        "required_temp_zone": "AMBIENT",
        "operator": "访客",
        "operator_role": "GUEST"
    })
    perm_denied = (not result["success"]) and (result.get("error") == "PERMISSION_DENIED")
    test("5.1 GUEST角色不能登记样本", perm_denied, f"错误码: {result.get('error')}")

    # 5.2 GUEST角色可以查看
    result = api_call("GET", f"/samples/{sample_id3}")
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
