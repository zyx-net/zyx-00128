#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""借出→退回→废弃 链路真实接口验证"""

import json
import urllib.request
import urllib.error

BASE_URL = "http://localhost:5000/api"
SAMPLE_CODE = "LINK-VERIFY-2026-003"


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


def main():
    print("=" * 60)
    print("  借出 → 退回 → 废弃 链路真实接口验证")
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
    sid = r["data"]["id"]
    ver = r["data"]["version"]
    status = r["data"]["status"]
    print("[1] 登记样本")
    print("    状态:", status, " 版本:", ver)
    assert status == "REGISTERED" and ver == 1, "登记失败"

    # 2. 入库
    r = api("POST", "/samples/%d/store-in" % sid, {
        "location_id": 3,
        "operator": "库管员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": ver,
        "reason": "入库"
    })
    ver = r["data"]["version"]
    status = r["data"]["status"]
    loc = r["data"]["location_name"]
    print("[2] 入库到冷藏库位")
    print("    状态:", status, " 版本:", ver, " 库位:", loc)
    assert status == "IN_STORAGE" and ver == 2, "入库失败"

    # 3. 借出
    r = api("POST", "/samples/%d/borrow" % sid, {
        "operator": "实验员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": ver,
        "reason": "实验使用"
    })
    ver = r["data"]["version"]
    status = r["data"]["status"]
    print("[3] 借出样本")
    print("    状态:", status, " 版本:", ver)
    assert status == "BORROWED" and ver == 3, "借出失败"

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
    print("    ✓ 正确拦截")

    # 5. 退回
    r = api("POST", "/samples/%d/return" % sid, {
        "location_id": 4,
        "operator": "实验员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": ver,
        "reason": "实验完成退回"
    })
    ver = r["data"]["version"]
    status = r["data"]["status"]
    loc = r["data"]["location_name"]
    print("[5] 退回样本（必须先退回才能废弃）")
    print("    状态:", status, " 版本:", ver, " 库位:", loc)
    assert status == "IN_STORAGE" and ver == 4, "退回失败"

    # 6. 退回后废弃 - 应该成功
    r = api("POST", "/samples/%d/discard" % sid, {
        "operator": "主管",
        "operator_role": "LAB_MANAGER",
        "expected_version": ver,
        "reason": "样本过期废弃"
    })
    ver = r["data"]["version"]
    status = r["data"]["status"]
    print("[6] 退回后废弃")
    print("    状态:", status, " 版本:", ver)
    assert status == "DISCARDED" and ver == 5, "退回后废弃失败"

    # 7. 按编码查询最终状态
    r = api("GET", "/samples/code/" + SAMPLE_CODE)
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

    # 8. 审计日志
    r = api("GET", "/samples/%d/audit-logs" % sid)
    logs = r["data"]
    print("[8] 审计日志（共 %d 条）" % len(logs))
    for l in logs:
        seq = l["sequence"]
        act = l["action"]
        fs = l.get("from_status", "-")
        ts = l.get("to_status", "-")
        v = l["version"]
        op = l["operator"]
        print("    [%d] %-10s %-12s → %-12s  v%d  %s" % (seq, act, fs, ts, v, op))
    assert len(logs) == 5, "应该有5条审计日志"
    assert logs[-1]["action"] == "DISCARD", "最后一条应该是废弃操作"

    # 9. CSV导出
    req = urllib.request.Request(BASE_URL + "/samples/%d/export-chain?role=LAB_TECHNICIAN" % sid)
    with urllib.request.urlopen(req) as resp:
        csv = resp.read().decode("utf-8-sig")
    has_code = SAMPLE_CODE in csv
    has_discard = "DISCARD" in csv
    print("[9] CSV导出")
    print("    包含样本编号:", has_code)
    print("    包含废弃记录:", has_discard)
    assert has_code and has_discard, "CSV导出内容不对"

    # 一致性校验
    print()
    print("=" * 60)
    print("  三方一致性校验")
    print("=" * 60)

    code_status = api("GET", "/samples/code/" + SAMPLE_CODE)["data"]["status"]
    log_status = logs[-1]["to_status"]
    csv_has_status = "DISCARDED" in csv or "已废弃" in csv

    print("  按编码查询状态:", code_status)
    print("  审计日志终态:", log_status)
    print("  CSV包含状态:", csv_has_status)

    all_ok = (code_status == log_status == "DISCARDED" and csv_has_status)
    print()
    if all_ok:
        print("  ✓ 三者一致，全部验证通过！")
    else:
        print("  ✗ 不一致，请检查")

    print()
    print("=" * 60)
    print("  结论")
    print("=" * 60)
    print("  1. 借出中直接废弃 → 被正确拦截（INVALID_STATUS_TRANSITION）")
    print("  2. 退回后再废弃 → 正常执行")
    print("  3. 废弃后按编码查询 → 能查到，状态 DISCARDED")
    print("  4. is_deleted 为 False → 不影响查询")
    print("  5. 编码查询/审计日志/CSV导出 → 三者一致")
    print("=" * 60)

    return 0 if all_ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
