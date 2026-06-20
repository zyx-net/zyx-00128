#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""借出→退回→废弃 链路真实接口验证
Windows 环境稳定版：自动生成唯一编号、ASCII 输出、健壮返回检查
"""

import sys
import os
import time
import json
import urllib.request
import urllib.error

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "http://localhost:5000/api"
CODE_PREFIX = "LINK-VERIFY"
SAMPLE_CODE = "%s-%d" % (CODE_PREFIX, int(time.time() * 1000) % 10000000000)


def api(method, path, body=None):
    url = BASE_URL + path
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"success": False, "error": "HTTP_ERROR", "message": str(e)}


def check_success(resp, context=""):
    if not resp.get("success"):
        print()
        print("  [ERROR] %s" % context)
        print("    错误码: %s" % resp.get("error"))
        print("    错误信息: %s" % resp.get("message", ""))
        print("    完整响应: %s" % json.dumps(resp, ensure_ascii=False)[:500])
        sys.exit(1)
    if "data" not in resp:
        print()
        print("  [ERROR] %s - 响应缺少 data 字段" % context)
        print("    完整响应: %s" % json.dumps(resp, ensure_ascii=False)[:500])
        sys.exit(1)


def main():
    print("=" * 60)
    print("  借出 -> 退回 -> 废弃 链路真实接口验证")
    print("=" * 60)
    print("  样本编号:", SAMPLE_CODE)
    print()

    # 1. 登记
    r = api("POST", "/samples", {
        "sample_code": SAMPLE_CODE,
        "name": "链路验证样本",
        "sample_type": "血液",
        "required_temp_zone": "REFRIGERATED",
        "operator": "验证员",
        "operator_role": "LAB_TECHNICIAN"
    })
    check_success(r, "登记样本")
    sid = r["data"]["id"]
    ver = r["data"]["version"]
    status = r["data"]["status"]
    print("[1] 登记样本")
    print("    状态:", status, " 版本:", ver)
    assert status == "REGISTERED" and ver == 1, "登记失败"
    print("    [OK]")

    # 2. 入库
    r = api("POST", "/samples/%d/store-in" % sid, {
        "location_id": 3,
        "operator": "库管员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": ver,
        "reason": "入库"
    })
    check_success(r, "入库")
    ver = r["data"]["version"]
    status = r["data"]["status"]
    loc = r["data"]["location_name"]
    print("[2] 入库到冷藏库位")
    print("    状态:", status, " 版本:", ver, " 库位:", loc)
    assert status == "IN_STORAGE" and ver == 2, "入库失败"
    print("    [OK]")

    # 3. 借出
    r = api("POST", "/samples/%d/borrow" % sid, {
        "operator": "实验员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": ver,
        "reason": "实验使用"
    })
    check_success(r, "借出")
    ver = r["data"]["version"]
    status = r["data"]["status"]
    print("[3] 借出样本")
    print("    状态:", status, " 版本:", ver)
    assert status == "BORROWED" and ver == 3, "借出失败"
    print("    [OK]")

    # 4. 借出状态直接废弃 - 必须被拦截
    r = api("POST", "/samples/%d/discard" % sid, {
        "operator": "主管",
        "operator_role": "LAB_MANAGER",
        "expected_version": ver,
        "reason": "测试直接废弃"
    })
    success = r.get("success", False)
    err = r.get("error")
    msg = r.get("message", "")
    print("[4] 借出状态直接废弃（预期被拦截）")
    print("    success:", success, " error:", err)
    print("    错误信息:", msg[:70])
    assert not success and err == "INVALID_STATUS_TRANSITION", "借出直接废弃应该被拦截！"
    print("    [OK] 正确拦截")

    # 5. 退回
    r = api("POST", "/samples/%d/return" % sid, {
        "location_id": 4,
        "operator": "实验员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": ver,
        "reason": "实验完成退回"
    })
    check_success(r, "退回")
    ver = r["data"]["version"]
    status = r["data"]["status"]
    loc = r["data"]["location_name"]
    print("[5] 退回样本（必须先退回才能废弃）")
    print("    状态:", status, " 版本:", ver, " 库位:", loc)
    assert status == "IN_STORAGE" and ver == 4, "退回失败"
    print("    [OK]")

    # 6. 退回后废弃 - 应该成功
    r = api("POST", "/samples/%d/discard" % sid, {
        "operator": "主管",
        "operator_role": "LAB_MANAGER",
        "expected_version": ver,
        "reason": "样本过期废弃"
    })
    check_success(r, "退回后废弃")
    ver = r["data"]["version"]
    status = r["data"]["status"]
    is_deleted = r["data"].get("is_deleted")
    print("[6] 退回后废弃")
    print("    状态:", status, " 版本:", ver, " is_deleted:", is_deleted)
    assert status == "DISCARDED" and ver == 5, "退回后废弃失败"
    assert is_deleted is False, "is_deleted 应该为 False"
    print("    [OK]")

    # 7. 按编码查询最终状态
    r = api("GET", "/samples/code/" + SAMPLE_CODE)
    check_success(r, "按编码查询")
    success = r.get("success", False)
    status = r.get("data", {}).get("status")
    version = r.get("data", {}).get("version")
    is_deleted = r.get("data", {}).get("is_deleted")
    print("[7] 按编码查询最终状态")
    print("    success:", success)
    print("    状态:", status, " 版本:", version)
    print("    is_deleted:", is_deleted)
    assert success, "废弃后按编码应该能查到！"
    assert status == "DISCARDED", "状态应该是 DISCARDED"
    assert is_deleted is False, "is_deleted 应该是 False"
    print("    [OK]")

    # 8. 审计日志
    r = api("GET", "/samples/%d/audit-logs" % sid)
    check_success(r, "审计日志查询")
    logs = r["data"]
    print("[8] 审计日志（共 %d 条）" % len(logs))
    for l in logs:
        seq = l["sequence"]
        act = l["action"]
        fs = l.get("from_status", "-")
        ts = l.get("to_status", "-")
        v = l["version"]
        op = l["operator"]
        print("    [%d] %-10s %-12s -> %-12s  v%d  %s" % (seq, act, fs, ts, v, op))
    assert len(logs) == 5, "应该有5条审计日志，实际 %d 条" % len(logs)
    assert logs[-1]["action"] == "DISCARD", "最后一条应该是废弃操作"
    print("    [OK]")

    # 9. CSV导出
    req = urllib.request.Request(BASE_URL + "/samples/%d/export-chain?role=LAB_TECHNICIAN" % sid)
    try:
        with urllib.request.urlopen(req) as resp:
            csv = resp.read().decode("utf-8-sig")
    except Exception as e:
        print()
        print("  [ERROR] CSV 导出失败: %s" % e)
        sys.exit(1)
    has_code = SAMPLE_CODE in csv
    has_discard = "DISCARD" in csv
    print("[9] CSV导出")
    print("    包含样本编号:", has_code)
    print("    包含废弃记录:", has_discard)
    assert has_code and has_discard, "CSV导出内容不对"
    print("    [OK]")

    # 一致性校验
    print()
    print("=" * 60)
    print("  三方一致性校验")
    print("=" * 60)

    r_code = api("GET", "/samples/code/" + SAMPLE_CODE)
    check_success(r_code, "二次按编码查询")
    code_status = r_code["data"]["status"]
    log_status = logs[-1]["to_status"]
    csv_has_status = "DISCARDED" in csv or "已废弃" in csv

    print("  按编码查询状态:", code_status)
    print("  审计日志终态:", log_status)
    print("  CSV包含状态:", csv_has_status)

    all_ok = (code_status == log_status == "DISCARDED" and csv_has_status)
    print()
    if all_ok:
        print("  [OK] 三者一致，全部验证通过！")
    else:
        print("  [FAIL] 不一致，请检查")
        sys.exit(1)

    print()
    print("=" * 60)
    print("  结论")
    print("=" * 60)
    print("  1. 借出中直接废弃 -> 被正确拦截（INVALID_STATUS_TRANSITION）")
    print("  2. 退回后再废弃 -> 正常执行")
    print("  3. 废弃后按编码查询 -> 能查到，状态 DISCARDED")
    print("  4. is_deleted 为 False -> 不影响查询")
    print("  5. 编码查询/审计日志/CSV导出 -> 三者一致")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
