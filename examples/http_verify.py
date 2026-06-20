#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
真实 HTTP 请求完整链路验证（Windows 稳定版）
- 登记 -> 入库 -> 借出 -> 试废弃(被拒) -> 退回 -> 废弃 -> 多入口查询一致性
- 自动生成唯一编号，ASCII 安全输出，健壮返回检查
"""

import sys
import time
import json
import urllib.request
import urllib.error

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://localhost:5000/api"
CODE_PREFIX = "REAL-HTTP"
CODE = "%s-%d" % (CODE_PREFIX, int(time.time() * 1000) % 10000000000)


def http(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {"success": False, "error": "HTTP_ERROR", "message": str(e)}


def header(text):
    print()
    print("=" * 70)
    print("  " + text)
    print("=" * 70)


def step(step_no, title, expected_status=None, expected_error=None, check_fn=None):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            status, resp = fn(*args, **kwargs)
            print()
            print("  [%s] %s" % (step_no, title))
            print("      HTTP状态码:", status)
            print("      success:", resp.get("success"))
            if not resp.get("success"):
                print("      错误码:", resp.get("error"))
                print("      错误信息:", str(resp.get("message", ""))[:80])
            if "data" in resp:
                d = resp["data"]
                if isinstance(d, dict):
                    for k in ("sample_code", "status", "version", "location_name", "is_deleted"):
                        if k in d:
                            print("      %s: %s" % (k, d[k]))

            ok = True
            if expected_status:
                ok = ok and (status == expected_status)
            if expected_error:
                ok = ok and resp.get("error") == expected_error
            if check_fn:
                try:
                    ok = ok and check_fn(resp)
                except Exception as e:
                    print("      检查函数异常: %s" % e)
                    ok = False

            print("      结果: %s" % ("[OK] PASS" if ok else "[FAIL]"))
            if not ok:
                print("      !!! 断言失败，终止")
                print("      完整响应: %s" % json.dumps(resp, ensure_ascii=False)[:800])
                sys.exit(1)
            return status, resp
        return wrapper
    return decorator


def main():
    print()
    print("=" * 70)
    print("  真实 HTTP 请求 - 完整链路验证")
    print("  样本编号: " + CODE)
    print("  API 基地址: " + BASE)
    print("=" * 70)

    # ========== 阶段 0：确认状态机配置 ==========
    header("阶段 0：确认状态机配置已修复")

    @step("0.1", "BORROWED 状态只允许 return，不允许 discard", 200)
    def _():
        return http("GET", "/config/status-flow")
    _, cfg_resp = _()
    borrowed_cfg = cfg_resp["data"]["BORROWED"]
    print("      BORROWED allowed_actions:", borrowed_cfg["allowed_actions"])
    print("      BORROWED allowed_next:", borrowed_cfg["allowed_next"])
    assert "discard" not in borrowed_cfg["allowed_actions"], "配置仍有问题！"
    assert "return" in borrowed_cfg["allowed_actions"], "配置仍有问题！"
    print("      [OK] 配置正确")

    # ========== 阶段 1：登记 -> 入库 -> 借出 ==========
    header("阶段 1：登记 -> 入库 -> 借出")

    @step("1", "登记样本", 201, check_fn=lambda r: r["data"]["status"] == "REGISTERED" and r["data"]["version"] == 1)
    def _():
        return http("POST", "/samples", {
            "sample_code": CODE,
            "name": "真实HTTP完整验证样本",
            "sample_type": "血液",
            "required_temp_zone": "REFRIGERATED",
            "operator": "HTTP测试员",
            "operator_role": "LAB_TECHNICIAN"
        })
    _, r1 = _()
    sample_id = r1["data"]["id"]

    @step("2", "入库到冷藏库位(id=3)", 200, check_fn=lambda r: r["data"]["status"] == "IN_STORAGE" and r["data"]["version"] == 2)
    def _():
        return http("POST", "/samples/%d/store-in" % sample_id, {
            "location_id": 3,
            "operator": "库管员",
            "operator_role": "LAB_TECHNICIAN",
            "expected_version": 1,
            "reason": "接收入库"
        })
    _, r2 = _()

    @step("3", "借出样本", 200, check_fn=lambda r: r["data"]["status"] == "BORROWED" and r["data"]["version"] == 3)
    def _():
        return http("POST", "/samples/%d/borrow" % sample_id, {
            "operator": "实验员小李",
            "operator_role": "LAB_TECHNICIAN",
            "expected_version": 2,
            "reason": "生化检测实验"
        })
    _, r3 = _()

    # ========== 阶段 2：借出态直接废弃 ==========
    header("阶段 2：借出态直接废弃（必须被拦截！）")

    @step("4", "借出态尝试直接废弃 - 预期 INVALID_STATUS_TRANSITION",
          400, expected_error="INVALID_STATUS_TRANSITION")
    def _():
        return http("POST", "/samples/%d/discard" % sample_id, {
            "operator": "主管老王",
            "operator_role": "LAB_MANAGER",
            "expected_version": 3,
            "reason": "尝试直接废弃借出样本"
        })
    _, r4 = _()
    print("      [OK] 借出态废弃已被正确拦截")

    # ========== 阶段 3：先退回，再废弃 ==========
    header("阶段 3：先退回，再废弃")

    @step("5", "退回样本", 200, check_fn=lambda r: r["data"]["status"] == "IN_STORAGE" and r["data"]["version"] == 4)
    def _():
        return http("POST", "/samples/%d/return" % sample_id, {
            "location_id": 4,
            "operator": "实验员小李",
            "operator_role": "LAB_TECHNICIAN",
            "expected_version": 3,
            "reason": "实验完成退回",
            "remark": "样本完好"
        })
    _, r5 = _()

    @step("6", "退回后废弃 - 预期成功", 200,
          check_fn=lambda r: r["data"]["status"] == "DISCARDED" and r["data"]["version"] == 5 and r["data"].get("is_deleted") is False)
    def _():
        return http("POST", "/samples/%d/discard" % sample_id, {
            "operator": "主管老王",
            "operator_role": "LAB_MANAGER",
            "expected_version": 4,
            "reason": "样本过期废弃",
            "remark": "按SOP处理"
        })
    _, r6 = _()
    print("      [OK] 退回后可以正常废弃")
    print("      [OK] is_deleted=False，不影响查询")

    # ========== 阶段 4：多入口查询一致性 ==========
    header("阶段 4：废弃后多入口查询一致性")

    @step("7.1", "按 ID 查询 - 必须能查到，状态 DISCARDED", 200,
          check_fn=lambda r: r["data"]["status"] == "DISCARDED" and r["data"]["version"] == 5)
    def _():
        return http("GET", "/samples/%d" % sample_id)
    _, r_id = _()

    @step("7.2", "按编码查询 - 必须能查到，状态 DISCARDED", 200,
          check_fn=lambda r: r["data"]["status"] == "DISCARDED" and r["data"]["version"] == 5)
    def _():
        return http("GET", "/samples/code/" + CODE)
    _, r_code = _()

    @step("7.3", "列表查询 - 样本在列表中且状态为 DISCARDED", 200,
          check_fn=lambda r: any(s["sample_code"] == CODE and s["status"] == "DISCARDED" for s in r["data"]))
    def _():
        return http("GET", "/samples?page=1&per_page=100")
    _, r_list = _()

    @step("7.4", "审计日志查询 - 共5条，最后一条 DISCARD", 200,
          check_fn=lambda r: len(r["data"]) == 5 and r["data"][-1]["action"] == "DISCARD")
    def _():
        return http("GET", "/samples/%d/audit-logs" % sample_id)
    _, r_logs = _()

    print()
    print("  审计日志完整链路:")
    for l in r_logs["data"]:
        print("    [%d] %-10s %-12s -> %-12s  v%d  %-10s  %s" % (
            l["sequence"], l["action"],
            l.get("from_status", "-"), l.get("to_status", "-"),
            l["version"], l["operator"], l.get("reason", "")
        ))

    # CSV 导出
    print()
    print("  [7.5] CSV 导出验证")
    req = urllib.request.Request(BASE + "/samples/%d/export-chain?role=LAB_TECHNICIAN" % sample_id)
    try:
        with urllib.request.urlopen(req) as resp:
            csv_text = resp.read().decode("utf-8-sig")
        csv_status = resp.status
    except Exception as e:
        print("      [FAIL] CSV 导出异常: %s" % e)
        sys.exit(1)
    has_code = CODE in csv_text
    has_discard = "DISCARD" in csv_text
    has_discarded = "DISCARDED" in csv_text or "已废弃" in csv_text
    print("      HTTP状态码:", csv_status)
    print("      包含样本编号:", has_code)
    print("      包含废弃操作:", has_discard)
    print("      包含废弃状态:", has_discarded)
    csv_ok = has_code and has_discard and csv_status == 200
    print("      结果:", "[OK] PASS" if csv_ok else "[FAIL]")
    if not csv_ok:
        sys.exit(1)

    # ========== 阶段 5：三方一致性最终核对 ==========
    header("阶段 5：三方一致性最终核对")

    id_status = r_id["data"]["status"]
    id_version = r_id["data"]["version"]
    code_status = r_code["data"]["status"]
    code_version = r_code["data"]["version"]
    list_item = next(s for s in r_list["data"] if s["sample_code"] == CODE)
    list_status = list_item["status"]
    list_version = list_item["version"]
    logs_final_status = r_logs["data"][-1]["to_status"]
    logs_final_version = r_logs["data"][-1]["version"]

    print()
    print("  查询入口            状态          版本    一致")
    print("  " + "-" * 62)
    print("  按 ID 查询          %-12s  v%d" % (id_status, id_version))
    print("  按编码查询          %-12s  v%d" % (code_status, code_version))
    print("  列表查询            %-12s  v%d" % (list_status, list_version))
    print("  审计日志终态        %-12s  v%d" % (logs_final_status, logs_final_version))
    print("  CSV 导出包含废弃:   %s" % has_discard)
    print()

    all_ok = (id_status == code_status == list_status == logs_final_status == "DISCARDED"
              and id_version == code_version == list_version == logs_final_version == 5
              and has_code and has_discard)

    if all_ok:
        print("  [OK] 所有查询入口状态和版本完全一致！")
    else:
        print("  [FAIL] 存在不一致，请检查！")
        sys.exit(1)

    # ========== 阶段 6：用户可见结果总结 ==========
    header("阶段 6：用户可见结果总结")
    print()
    print("  1. 借出中样本主管直接废弃 -> 被接口拒绝 (INVALID_STATUS_TRANSITION)")
    print("  2. 必须先退回 -> 才能正常废弃")
    print("  3. 废弃后按编码/按ID/列表 都能查到，状态为 DISCARDED")
    print("  4. 审计日志完整记录 5 步流程，交接链清晰")
    print("  5. CSV 导出包含完整历史，和查询结果一致")
    print()
    print("  " + "=" * 62)
    print("    [OK] 完整链路全部验证通过！")
    print("  " + "=" * 62)
    print()


if __name__ == "__main__":
    main()
