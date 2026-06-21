import json
import sys
import os
import urllib.request
import urllib.error

BASE_URL = "http://localhost:5000/api"


def api(method, path, body=None):
    url = f"{BASE_URL}{path}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            ct = resp.headers.get("Content-Type", "")
            if "json" in ct:
                return json.loads(resp.read().decode("utf-8"))
            else:
                return {"success": True, "raw": resp.read().decode("utf-8-sig"), "status": resp.status}
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"success": False, "message": str(e), "error": "HTTP_ERROR"}
    except Exception as e:
        return {"success": False, "message": str(e), "error": "CONNECTION_ERROR"}


_pass = 0
_fail = 0


def test(name, cond, detail=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  [OK] PASS  {name}")
        if detail:
            print(f"         {detail}")
    else:
        _fail += 1
        print(f"  [FAIL]  {name}")
        if detail:
            print(f"         {detail}")


def sub(name):
    print()
    print(f"  --- {name} ---")


def verify_dirty_snapshot(snap):
    sub("脏数据隔离 (真实重启后验证)")

    exist_code = snap["exist_code"]
    exist_id = snap["exist_id"]
    exist_version = snap["exist_version"]
    ok1_code = snap["ok1_code"]
    ok2_code = snap["ok2_code"]
    bad_temp_code = snap["bad_temp_code"]
    bad_loc_code = snap["bad_loc_code"]
    allfail_1 = snap["allfail_code_1"]
    allfail_2 = snap["allfail_code_2"]
    batch_code = snap["batch_code"]
    batch_total = snap["batch_total"]
    batch_succ = snap["batch_succ"]
    batch_fail = snap["batch_fail"]
    batch_status = snap["batch_status"]
    allfail_batch_code = snap["allfail_batch_code"]

    r = api("GET", f"/samples/{exist_id}")
    test(f"预存在样本 {exist_code} (id={exist_id}) 仍存在 v={exist_version}",
         r.get("success") and r["data"]["version"] == exist_version and r["data"]["sample_code"] == exist_code,
         f"v={r.get('data',{}).get('version')} code={r.get('data',{}).get('sample_code')}")

    r = api("GET", f"/samples/code/{ok1_code}")
    test(f"成功样本 {ok1_code} 状态 IN_STORAGE v=2",
         r.get("success") and r["data"]["status"] == "IN_STORAGE" and r["data"]["version"] == 2,
         f"status={r.get('data',{}).get('status')} v={r.get('data',{}).get('version')}")

    r = api("GET", f"/samples/code/{ok2_code}")
    test(f"成功样本 {ok2_code} 状态 IN_STORAGE v=2",
         r.get("success") and r["data"]["status"] == "IN_STORAGE" and r["data"]["version"] == 2,
         f"status={r.get('data',{}).get('status')} v={r.get('data',{}).get('version')}")

    r = api("GET", f"/samples/code/{bad_temp_code}")
    test(f"修正前失败样本 {bad_temp_code} 后修正成功登记 IN_STORAGE",
         r.get("success") and r["data"]["status"] == "IN_STORAGE",
         f"status={r.get('data',{}).get('status')}")

    r = api("GET", f"/samples/code/{bad_loc_code}")
    test(f"修正前失败样本 {bad_loc_code} 后修正成功登记 IN_STORAGE",
         r.get("success") and r["data"]["status"] == "IN_STORAGE",
         f"status={r.get('data',{}).get('status')}")

    r = api("GET", f"/samples/code/{allfail_1}")
    test(f"纯失败样本 {allfail_1} 不存在",
         r.get("error") == "SAMPLE_NOT_FOUND",
         f"err={r.get('error')}")

    r = api("GET", f"/samples/code/{allfail_2}")
    test(f"纯失败样本 {allfail_2} 不存在",
         r.get("error") == "SAMPLE_NOT_FOUND",
         f"err={r.get('error')}")

    r = api("GET", f"/import/batches/code/{batch_code}")
    test(f"批次 {batch_code} 状态 {batch_status}",
         (r.get("success")
          and r["data"]["total_count"] == batch_total
          and r["data"]["success_count"] == batch_succ
          and r["data"]["failed_count"] == batch_fail
          and r["data"]["status"] == batch_status),
         f"total={r.get('data',{}).get('total_count')} "
         f"succ={r.get('data',{}).get('success_count')} "
         f"fail={r.get('data',{}).get('failed_count')} "
         f"status={r.get('data',{}).get('status')}")

    r = api("GET", f"/import/batches/code/{allfail_batch_code}")
    test(f"纯失败批次 {allfail_batch_code} 状态 FAILED",
         r.get("success") and r["data"]["status"] == "FAILED" and r["data"]["success_count"] == 0,
         f"status={r.get('data',{}).get('status')} "
         f"succ={r.get('data',{}).get('success_count')} "
         f"fail={r.get('data',{}).get('failed_count')}")

    req = urllib.request.Request(f"{BASE_URL}/samples/export?role=LAB_MANAGER")
    with urllib.request.urlopen(req) as resp:
        csv_txt = resp.read().decode("utf-8-sig")
    test(f"导出 CSV 包含 ok1/ok2 成功样本，不包含 allfail 样本",
         ok1_code in csv_txt and ok2_code in csv_txt
         and allfail_1 not in csv_txt and allfail_2 not in csv_txt,
         f"has_ok1={ok1_code in csv_txt} has_ok2={ok2_code in csv_txt} "
         f"has_allfail1={allfail_1 in csv_txt} has_allfail2={allfail_2 in csv_txt}")


def main():
    health = api("GET", "/health")
    if not health.get("success"):
        print("服务不可用，退出")
        print(f"health={health}")
        return 1

    print("=" * 70)
    print("  真实重启后一致性验证")
    print("=" * 70)
    print()

    dirty_path = "data/dirty_state_snapshot.json"
    dirty_snap = None
    if os.path.exists(dirty_path):
        with open(dirty_path, encoding="utf-8") as f:
            dirty_snap = json.load(f)
        print(f"  [INFO] 加载脏数据测试 snapshot: {dirty_path}")
    else:
        print(f"  [WARN] 脏数据 snapshot 不存在 ({dirty_path})，跳过")

    if dirty_snap:
        verify_dirty_snapshot(dirty_snap)

    print()
    print("=" * 70)
    print("  测试汇总")
    print("=" * 70)
    print(f"  总测试数: {_pass + _fail}")
    print(f"  通过:     {_pass}")
    print(f"  失败:     {_fail}")
    print()
    if _fail == 0:
        print("  ✓ 真实重启后一致性全部通过！")
        return 0
    else:
        print(f"  ✗ 有 {_fail} 个用例失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
