#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""重启后一致性验证（Windows 稳定版）
用法：
  步骤1：python examples/restart_check.py save   # 保存当前状态
  步骤2：重启服务
  步骤3：python examples/restart_check.py check  # 验证一致性
"""

import sys
import os
import time
import json
import urllib.request
import urllib.error

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://localhost:5000/api"
STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "restart_check_state.json")


def http(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {"success": False, "error": "HTTP_ERROR", "message": str(e)}


def save_state():
    """创建样本并跑完整链路，保存状态"""
    CODE = "RESTART-CHK-%d" % int(time.time() * 1000)
    print()
    print("=" * 70)
    print("  重启验证 - 阶段 1：跑完整链路并保存状态")
    print("  样本编号: " + CODE)
    print("=" * 70)
    print()

    # 1. 登记
    s, r = http("POST", "/samples", {
        "sample_code": CODE,
        "name": "重启验证样本",
        "sample_type": "血液",
        "required_temp_zone": "REFRIGERATED",
        "operator": "重启测试",
        "operator_role": "LAB_TECHNICIAN"
    })
    if not r.get("success"):
        print("[FAIL] 登记失败: %s - %s" % (r.get("error"), r.get("message")))
        sys.exit(1)
    sid = r["data"]["id"]
    print("  [1] 登记: OK  id=%d" % sid)

    # 2. 入库
    s, r = http("POST", "/samples/%d/store-in" % sid, {
        "location_id": 3,
        "operator": "库管员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": 1,
        "reason": "入库"
    })
    assert r.get("success"), "入库失败"
    print("  [2] 入库: OK")

    # 3. 借出
    s, r = http("POST", "/samples/%d/borrow" % sid, {
        "operator": "实验员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": 2,
        "reason": "实验"
    })
    assert r.get("success"), "借出失败"
    print("  [3] 借出: OK")

    # 4. 退回
    s, r = http("POST", "/samples/%d/return" % sid, {
        "location_id": 4,
        "operator": "实验员",
        "operator_role": "LAB_TECHNICIAN",
        "expected_version": 3,
        "reason": "退回"
    })
    assert r.get("success"), "退回失败"
    print("  [4] 退回: OK")

    # 5. 废弃
    s, r = http("POST", "/samples/%d/discard" % sid, {
        "operator": "主管",
        "operator_role": "LAB_MANAGER",
        "expected_version": 4,
        "reason": "过期废弃"
    })
    assert r.get("success"), "废弃失败"
    print("  [5] 废弃: OK")

    # 6. 查询各入口状态
    s, r_code = http("GET", "/samples/code/" + CODE)
    s, r_id = http("GET", "/samples/%d" % sid)
    s, r_logs = http("GET", "/samples/%d/audit-logs" % sid)
    s, r_list = http("GET", "/samples?page=1&per_page=100")

    req = urllib.request.Request(BASE + "/samples/%d/export-chain?role=LAB_TECHNICIAN" % sid)
    with urllib.request.urlopen(req) as resp:
        csv_text = resp.read().decode("utf-8-sig")

    # 保存状态
    state = {
        "sample_id": sid,
        "sample_code": CODE,
        "code_query": r_code["data"],
        "id_query": r_id["data"],
        "audit_logs": r_logs["data"],
        "csv_has_code": CODE in csv_text,
        "csv_has_discard": "DISCARD" in csv_text,
        "in_list": any(s["sample_code"] == CODE for s in r_list["data"])
    }

    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    print()
    print("  状态已保存到: %s" % STATE_FILE)
    print("  样本编号: %s" % CODE)
    print("  状态: %s  版本: %d" % (r_code["data"]["status"], r_code["data"]["version"]))
    print("  审计日志: %d 条" % len(r_logs["data"]))
    print()
    print("  [OK] 阶段 1 完成，请重启服务后运行: python examples/restart_check.py check")
    print()


def check_state():
    """重启后验证一致性"""
    if not os.path.exists(STATE_FILE):
        print("[FAIL] 状态文件不存在: %s" % STATE_FILE)
        print("       请先运行: python examples/restart_check.py save")
        sys.exit(1)

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        before = json.load(f)

    sid = before["sample_id"]
    CODE = before["sample_code"]

    print()
    print("=" * 70)
    print("  重启验证 - 阶段 2：重启后一致性检查")
    print("  样本编号: " + CODE)
    print("  样本 ID: " + str(sid))
    print("=" * 70)
    print()

    # 查询各入口
    s, r_code = http("GET", "/samples/code/" + CODE)
    s, r_id = http("GET", "/samples/%d" % sid)
    s, r_logs = http("GET", "/samples/%d/audit-logs" % sid)
    s, r_list = http("GET", "/samples?page=1&per_page=100")

    req = urllib.request.Request(BASE + "/samples/%d/export-chain?role=LAB_TECHNICIAN" % sid)
    with urllib.request.urlopen(req) as resp:
        csv_text = resp.read().decode("utf-8-sig")

    all_ok = True

    def check(name, expr, actual, expected):
        nonlocal all_ok
        ok = expr
        print("  [%-25s] 重启前: %-20s  重启后: %-20s  %s" % (
            name, str(expected)[:20], str(actual)[:20],
            "[OK]" if ok else "[FAIL]"
        ))
        if not ok:
            all_ok = False

    check("按编码查询-状态",
          r_code.get("data", {}).get("status") == before["code_query"]["status"],
          r_code.get("data", {}).get("status"), before["code_query"]["status"])
    check("按编码查询-版本",
          r_code.get("data", {}).get("version") == before["code_query"]["version"],
          r_code.get("data", {}).get("version"), before["code_query"]["version"])

    check("按ID查询-状态",
          r_id.get("data", {}).get("status") == before["id_query"]["status"],
          r_id.get("data", {}).get("status"), before["id_query"]["status"])
    check("按ID查询-版本",
          r_id.get("data", {}).get("version") == before["id_query"]["version"],
          r_id.get("data", {}).get("version"), before["id_query"]["version"])

    check("审计日志条数",
          len(r_logs.get("data", [])) == len(before["audit_logs"]),
          len(r_logs.get("data", [])), len(before["audit_logs"]))

    last_before = before["audit_logs"][-1]
    last_after = r_logs.get("data", [])[-1] if r_logs.get("data") else {}
    check("审计最后一条-操作",
          last_after.get("action") == last_before["action"],
          last_after.get("action"), last_before["action"])
    check("审计最后一条-状态",
          last_after.get("to_status") == last_before["to_status"],
          last_after.get("to_status"), last_before["to_status"])
    check("审计最后一条-版本",
          last_after.get("version") == last_before["version"],
          last_after.get("version"), last_before["version"])

    in_list_now = any(s["sample_code"] == CODE for s in r_list.get("data", []))
    check("列表中存在", in_list_now == before["in_list"], in_list_now, before["in_list"])

    csv_has_code_now = CODE in csv_text
    csv_has_discard_now = "DISCARD" in csv_text
    check("CSV含样本编号", csv_has_code_now == before["csv_has_code"], csv_has_code_now, before["csv_has_code"])
    check("CSV含废弃操作", csv_has_discard_now == before["csv_has_discard"], csv_has_discard_now, before["csv_has_discard"])

    print()
    print("=" * 70)
    if all_ok:
        print("  [OK] 重启后所有查询入口完全一致！")
    else:
        print("  [FAIL] 存在不一致项，请检查！")
        sys.exit(1)
    print("=" * 70)
    print()


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "save"
    if action == "save":
        save_state()
    elif action == "check":
        check_state()
    else:
        print("用法:")
        print("  python examples/restart_check.py save   # 保存状态")
        print("  python examples/restart_check.py check  # 重启后验证")
        sys.exit(1)


if __name__ == "__main__":
    main()
