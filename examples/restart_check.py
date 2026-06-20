#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""重启后一致性验证 - 针对 REAL-HTTP-VERIFY-001"""

import json
import urllib.request
import urllib.error

BASE = "http://localhost:5000/api"
CODE = "REAL-HTTP-VERIFY-001"


def http(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def main():
    print()
    print("=" * 70)
    print("  重启后一致性验证（样本:", CODE, "）")
    print("=" * 70)
    print()

    # 先找样本 ID
    _, r = http("GET", "/samples/code/" + CODE)
    sample_id = r["data"]["id"]
    status_before = r["data"]["status"]
    version_before = r["data"]["version"]
    print("  按编码查询:")
    print("    状态:", status_before, " 版本:", version_before)

    # 按 ID 查询
    _, r2 = http("GET", "/samples/%d" % sample_id)
    print("  按 ID 查询:")
    print("    状态:", r2["data"]["status"], " 版本:", r2["data"]["version"])

    # 列表
    _, r3 = http("GET", "/samples?page=1&per_page=100")
    in_list = any(s["sample_code"] == CODE for s in r3["data"])
    if in_list:
        s = next(s for s in r3["data"] if s["sample_code"] == CODE)
        print("  列表查询:")
        print("    在列表中: True  状态:", s["status"], " 版本:", s["version"])

    # 审计
    _, r4 = http("GET", "/samples/%d/audit-logs" % sample_id)
    print("  审计日志: %d 条" % len(r4["data"]))
    print("    最后一条:", r4["data"][-1]["action"], "→", r4["data"][-1]["to_status"], " v%d" % r4["data"][-1]["version"])

    # CSV
    req = urllib.request.Request(BASE + "/samples/%d/export-chain?role=LAB_TECHNICIAN" % sample_id)
    with urllib.request.urlopen(req) as resp:
        csv_text = resp.read().decode("utf-8-sig")
    print("  CSV 导出:")
    print("    包含编号:", CODE in csv_text)
    print("    包含废弃:", "DISCARD" in csv_text)

    ok = (
        status_before == r2["data"]["status"] == s["status"] == r4["data"][-1]["to_status"] == "DISCARDED"
        and version_before == r2["data"]["version"] == s["version"] == r4["data"][-1]["version"] == 5
        and len(r4["data"]) == 5
        and "DISCARD" in csv_text
    )

    print()
    print("=" * 70)
    if ok:
        print("  ✓✓✓ 重启后完全一致，所有入口状态/版本/记录均未变！")
    else:
        print("  ✗ 不一致！")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
