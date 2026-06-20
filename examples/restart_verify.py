#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
验证进程重启后数据一致性
"""

import json
import urllib.request
import sys

BASE_URL = "http://localhost:5000/api"


def api_get(path):
    with urllib.request.urlopen(f"{BASE_URL}{path}") as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "check"

    if action == "save":
        sample1 = api_get("/samples/1")
        logs1 = api_get("/samples/1/audit-logs")
        sample2 = api_get("/samples/2")
        sample3 = api_get("/samples/3")

        state = {
            "sample1": sample1,
            "sample1_logs": logs1,
            "sample2": sample2,
            "sample3": sample3
        }

        with open("data/restart_check.json", "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

        print("已保存当前状态到 data/restart_check.json")
        print(f"  样本1: 状态={sample1['data']['status']}, 版本={sample1['data']['version']}")
        print(f"  样本2: 状态={sample2['data']['status']}, 版本={sample2['data']['version']}")
        print(f"  样本3: 状态={sample3['data']['status']}, 版本={sample3['data']['version']}")

    elif action == "verify":
        with open("data/restart_check.json", "r", encoding="utf-8") as f:
            before = json.load(f)

        sample1 = api_get("/samples/1")
        logs1 = api_get("/samples/1/audit-logs")
        sample2 = api_get("/samples/2")
        sample3 = api_get("/samples/3")

        print("=" * 60)
        print("  数据一致性验证")
        print("=" * 60)

        # 验证样本1
        s1_ok = (sample1["data"]["status"] == before["sample1"]["data"]["status"] and
                 sample1["data"]["version"] == before["sample1"]["data"]["version"] and
                 len(logs1["data"]) == len(before["sample1_logs"]["data"]))
        print(f"\n样本1 (ID=1): {'✓ 一致' if s1_ok else '✗ 不一致'}")
        print(f"  状态: 重启前={before['sample1']['data']['status']}, 重启后={sample1['data']['status']}")
        print(f"  版本: 重启前={before['sample1']['data']['version']}, 重启后={sample1['data']['version']}")
        print(f"  审计日志数: 重启前={len(before['sample1_logs']['data'])}, 重启后={len(logs1['data'])}")

        # 验证样本2
        s2_ok = (sample2["data"]["status"] == before["sample2"]["data"]["status"] and
                 sample2["data"]["version"] == before["sample2"]["data"]["version"])
        print(f"\n样本2 (ID=2): {'✓ 一致' if s2_ok else '✗ 不一致'}")
        print(f"  状态: 重启前={before['sample2']['data']['status']}, 重启后={sample2['data']['status']}")
        print(f"  版本: 重启前={before['sample2']['data']['version']}, 重启后={sample2['data']['version']}")

        # 验证样本3
        s3_ok = (sample3["data"]["status"] == before["sample3"]["data"]["status"] and
                 sample3["data"]["version"] == before["sample3"]["data"]["version"])
        print(f"\n样本3 (ID=3): {'✓ 一致' if s3_ok else '✗ 不一致'}")
        print(f"  状态: 重启前={before['sample3']['data']['status']}, 重启后={sample3['data']['status']}")
        print(f"  版本: 重启前={before['sample3']['data']['version']}, 重启后={sample3['data']['version']}")

        # CSV 导出验证
        print("\nCSV 导出验证:")
        try:
            req = urllib.request.Request(f"{BASE_URL}/samples/1/export-chain?role=LAB_TECHNICIAN")
            with urllib.request.urlopen(req) as resp:
                csv_content = resp.read().decode("utf-8-sig")
            has_data = "TEST-ACCEPT-001" in csv_content and "REGISTER" in csv_content
            print(f"  样本1交接链CSV: {'✓ 正常' if has_data else '✗ 异常'}")
            print(f"  CSV 包含样本编号和登记记录: {has_data}")
        except Exception as e:
            print(f"  导出失败: {e}")
            has_data = False

        all_ok = s1_ok and s2_ok and s3_ok and has_data
        print("\n" + "=" * 60)
        if all_ok:
            print("  ✓ 所有数据验证通过！进程重启后数据一致。")
            return 0
        else:
            print("  ✗ 部分数据不一致，请检查！")
            return 1


if __name__ == "__main__":
    sys.exit(main())
