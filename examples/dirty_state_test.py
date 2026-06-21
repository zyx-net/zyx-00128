import json
import sys
import os
import urllib.request
import urllib.error

BASE_URL = "http://localhost:5000/api"
_TS = ""


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


def main():
    global _TS

    health = api("GET", "/health")
    if not health.get("success"):
        print("服务不可用，退出")
        return 1

    print("=" * 70)
    print("  脏数据与失败重跑 回归测试")
    print("=" * 70)
    print()
    print("  目标:")
    print("    1) 温区不匹配 / 库位不存在 的行 样本绝不落库 (sample_code 查不到)")
    print("    2) 失败行的 ImportRecord.sample_id = None (不关联脏数据)")
    print("    3) 失败行不污染已存在样本的版本号")
    print("    4) 失败清单 CSV 可以安全重跑 (不会修改已有样本)")
    print("    5) 批次状态正确 (COMPLETED/PARTIAL_FAILED/FAILED 三态)")
    print("    6) 服务重启后以上状态全部保持一致")
    print()

    _TS = str(int(__import__("time").time() * 1000))[-6:]

    # ============================================================
    # 准备 1 条已存在的样本，后续用它验证版本不被失败行污染
    # ============================================================
    sub("0. 准备 1 条已存在样本 (用于验证版本不被污染)")
    exist_code = f"DIRTY-EXIST-{_TS}"
    r = api("POST", "/samples", {
        "sample_code": exist_code,
        "name": "预先存在样本",
        "sample_type": "血液",
        "required_temp_zone": "REFRIGERATED",
        "operator": "A",
        "operator_role": "LAB_TECHNICIAN",
    })
    assert r.get("success"), r
    v_before = r["data"]["version"]
    test(f"预登记样本 v={v_before}", v_before == 1, f"version={v_before}")
    exist_id = r["data"]["id"]

    # ============================================================
    # 构造脏数据批次：4 条记录，其中 2 条成功 2 条失败
    # ============================================================
    sub("1. 构造 2 成功 + 2 失败 批次 (温区不匹配 + 库位不存在)")
    c_ok1 = f"DIRTY-OK1-{_TS}"
    c_ok2 = f"DIRTY-OK2-{_TS}"
    c_bad_temp = f"DIRTY-TEMP-{_TS}"   # REFRIGERATED 样本配 AMB-001 (常温库位)
    c_bad_loc = f"DIRTY-LOC-{_TS}"     # 库位 NO-SUCH-LOC-999 不存在

    csv_lines = [
        "sample_code,name,sample_type,required_temp_zone,location_code",
        f"{c_ok1},合法样本1,血液,REFRIGERATED,REF-001",
        f"{c_ok2},合法样本2,组织,FROZEN,FRZ-001",
        f"{c_bad_temp},温区错配样本,血液,REFRIGERATED,AMB-001",
        f"{c_bad_loc},库位不存在样本,血液,REFRIGERATED,NO-SUCH-LOC-999",
    ]
    csv_content = "\n".join(csv_lines)
    batch_code = f"DIRTY-TEST-{_TS}"

    r = api("POST", "/samples/import/csv", {
        "csv_content": csv_content,
        "operator": "脏数据测试员",
        "operator_role": "LAB_TECHNICIAN",
        "import_mode": "REGISTER_OR_UPDATE",
        "strategy": "FAIL_ON_DUPLICATE",
        "batch_code": batch_code,
    })
    assert r.get("success"), r
    batch = r["data"]["batch"]
    records = r["data"]["records"]
    test("批次 total=4 succ=2 fail=2",
         batch["total_count"] == 4 and batch["success_count"] == 2 and batch["failed_count"] == 2,
         f"total={batch['total_count']} succ={batch['success_count']} fail={batch['failed_count']}")
    test("批次状态 = PARTIAL_FAILED (有成功有失败)",
         batch["status"] == "PARTIAL_FAILED", f"status={batch['status']}")

    by_code = {r_["sample_code"]: r_ for r_ in records}

    test(f"{c_ok1} SUCCESS + 已入库 IN_STORAGE",
         by_code[c_ok1]["result"] == "SUCCESS" and by_code[c_ok1]["action"] == "REGISTER+STORE_IN",
         f"result={by_code[c_ok1]['result']} action={by_code[c_ok1]['action']}")
    test(f"{c_ok2} SUCCESS + 已入库 IN_STORAGE",
         by_code[c_ok2]["result"] == "SUCCESS" and by_code[c_ok2]["action"] == "REGISTER+STORE_IN",
         f"result={by_code[c_ok2]['result']} action={by_code[c_ok2]['action']}")
    test(f"{c_bad_temp} FAILED + TEMP_ZONE_MISMATCH",
         by_code[c_bad_temp]["result"] == "FAILED" and by_code[c_bad_temp]["error_code"] == "TEMP_ZONE_MISMATCH",
         f"code={by_code[c_bad_temp]['error_code']} msg={by_code[c_bad_temp].get('error_message','')[:60]}")
    test(f"{c_bad_loc} FAILED + LOCATION_NOT_FOUND",
         by_code[c_bad_loc]["result"] == "FAILED" and by_code[c_bad_loc]["error_code"] == "LOCATION_NOT_FOUND",
         f"code={by_code[c_bad_loc]['error_code']} msg={by_code[c_bad_loc].get('error_message','')[:60]}")

    # 失败行 ImportRecord.sample_id 必须是 null
    test(f"{c_bad_temp} 的 sample_id 为 null (不关联脏样本)",
         by_code[c_bad_temp].get("sample_id") is None, f"sample_id={by_code[c_bad_temp].get('sample_id')}")
    test(f"{c_bad_loc} 的 sample_id 为 null (不关联脏样本)",
         by_code[c_bad_loc].get("sample_id") is None, f"sample_id={by_code[c_bad_loc].get('sample_id')}")

    # ============================================================
    # 验证失败行样本没被写入 DB
    # ============================================================
    sub("2. 验证失败行样本没被写入 DB (按编号查不到)")
    r_temp = api("GET", f"/samples/code/{c_bad_temp}")
    test(f"温区不匹配的 {c_bad_temp} 查不到",
         r_temp.get("error") == "SAMPLE_NOT_FOUND",
         f"success={r_temp.get('success')} err={r_temp.get('error')}")
    r_loc = api("GET", f"/samples/code/{c_bad_loc}")
    test(f"库位不存在的 {c_bad_loc} 查不到",
         r_loc.get("error") == "SAMPLE_NOT_FOUND",
         f"success={r_loc.get('success')} err={r_loc.get('error')}")

    # 成功行样本能正常查到
    r_ok1 = api("GET", f"/samples/code/{c_ok1}")
    test(f"成功行 {c_ok1} 正常 IN_STORAGE v=2",
         r_ok1.get("success") and r_ok1["data"]["status"] == "IN_STORAGE" and r_ok1["data"]["version"] == 2,
         f"status={r_ok1.get('data',{}).get('status')} v={r_ok1.get('data',{}).get('version')}")

    # ============================================================
    # 验证预存在样本的版本号没被失败行污染
    # ============================================================
    sub("3. 验证预存在样本版本没被污染")
    r_exist = api("GET", f"/samples/{exist_id}")
    v_after = r_exist["data"]["version"]
    test(f"预存在样本版本保持 v={v_before}", v_after == v_before,
         f"before_v={v_before} after_v={v_after}")

    # ============================================================
    # 下载错误清单 CSV，然后用 REGISTER 模式重跑（不做更新），
    # 先手工修正错误（改温区匹配 + 换成合法库位），再重跑
    # ============================================================
    sub("4. 失败清单 CSV 可以安全复跑 (修正错误后重跑)")
    batch_id = batch["id"]
    req = urllib.request.Request(f"{BASE_URL}/import/batches/{batch_id}/errors/csv")
    with urllib.request.urlopen(req) as resp:
        csv_err = resp.read().decode("utf-8-sig")
    test("错误 CSV 包含 2 条失败行 + error_code/error_message 列",
         "error_code" in csv_err and c_bad_temp in csv_err and c_bad_loc in csv_err,
         f"包含 c_bad_temp={c_bad_temp in csv_err} c_bad_loc={c_bad_loc in csv_err}")

    # 模拟用户修正 CSV：c_bad_temp 温区改 AMBIENT 用 AMB-001；c_bad_loc 换 REF-002
    csv_fixed = (
        "sample_code,name,sample_type,required_temp_zone,location_code,error_code,error_message\n"
        f"{c_bad_temp},温区错配样本-修正,血液,AMBIENT,AMB-001,,\n"
        f"{c_bad_loc},库位不存在样本-修正,血液,REFRIGERATED,REF-002,,\n"
    )
    batch_code2 = f"DIRTY-RETRY-{_TS}"
    r2 = api("POST", "/samples/import/csv", {
        "csv_content": csv_fixed,
        "operator": "修正后重跑员",
        "operator_role": "LAB_TECHNICIAN",
        "import_mode": "REGISTER",
        "strategy": "FAIL_ON_DUPLICATE",
        "batch_code": batch_code2,
    })
    assert r2.get("success"), r2
    b2 = r2["data"]["batch"]
    test("修正后重跑 succ=2 fail=0 total=2",
         b2["total_count"] == 2 and b2["success_count"] == 2 and b2["failed_count"] == 0,
         f"total={b2['total_count']} succ={b2['success_count']} fail={b2['failed_count']}")
    test("修正后批次状态 = COMPLETED (全成功)",
         b2["status"] == "COMPLETED", f"status={b2['status']}")

    # 现在两条失败行修正后都应该登记成功了
    r_fix1 = api("GET", f"/samples/code/{c_bad_temp}")
    test(f"修正后的 {c_bad_temp} 已登记入库 IN_STORAGE",
         r_fix1.get("success") and r_fix1["data"]["status"] == "IN_STORAGE",
         f"success={r_fix1.get('success')} status={r_fix1.get('data',{}).get('status')}")
    r_fix2 = api("GET", f"/samples/code/{c_bad_loc}")
    test(f"修正后的 {c_bad_loc} 已登记入库 IN_STORAGE",
         r_fix2.get("success") and r_fix2["data"]["status"] == "IN_STORAGE",
         f"success={r_fix2.get('success')} status={r_fix2.get('data',{}).get('status')}")

    # 版本号还是原始的（之前失败时没污染）
    test(f"{c_bad_temp} 版本=2 (登记 v1 + 入库 v2，未被失败污染)",
         r_fix1.get("success") and r_fix1["data"]["version"] == 2,
         f"v={r_fix1.get('data',{}).get('version')}")

    # ============================================================
    # 测试纯失败批次 (0 成功) 状态 = FAILED
    # ============================================================
    sub("5. 纯失败批次状态 = FAILED")
    c_all_fail1 = f"ALLFAIL-1-{_TS}"
    c_all_fail2 = f"ALLFAIL-2-{_TS}"
    csv_all_fail = (
        "sample_code,name,sample_type,required_temp_zone,location_code\n"
        f"{c_all_fail1},,血液,REFRIGERATED,REF-001\n"
        f"{c_all_fail2},测试,血液,INVALID_TZ,REF-001\n"
    )
    r3 = api("POST", "/samples/import/csv", {
        "csv_content": csv_all_fail,
        "operator": "全失败测试员",
        "operator_role": "LAB_TECHNICIAN",
        "batch_code": f"ALLFAIL-BATCH-{_TS}",
    })
    assert r3.get("success"), r3
    b3 = r3["data"]["batch"]
    test("纯失败批次 succ=0 fail=2",
         b3["success_count"] == 0 and b3["failed_count"] == 2,
         f"succ={b3['success_count']} fail={b3['failed_count']}")
    test("纯失败批次状态 = FAILED", b3["status"] == "FAILED", f"status={b3['status']}")

    # 失败样本不在 DB
    r_af1 = api("GET", f"/samples/code/{c_all_fail1}")
    test(f"纯失败样本 {c_all_fail1} 不在 DB",
         r_af1.get("error") == "SAMPLE_NOT_FOUND", f"err={r_af1.get('error')}")

    # ============================================================
    # 全部失败后重试 batch 的 retry 接口 (应返回 NO_RETRYABLE_RECORDS
    # 因为 MISSING_REQUIRED_FIELD 和 INVALID_TEMP_ZONE 都是 non_retryable)
    # ============================================================
    sub("6. 不可重试错误不会被 retry 接口选中")
    r4 = api("POST", f"/import/batches/{b3['id']}/retry", {
        "operator": "重试员",
        "operator_role": "LAB_TECHNICIAN",
    })
    test("全为不可重试错误时 retry 返回 NO_RETRYABLE_RECORDS",
         (not r4.get("success")) and r4.get("error") == "NO_RETRYABLE_RECORDS",
         f"err={r4.get('error')}")

    # ============================================================
    # 汇总
    # ============================================================
    print()
    print("=" * 70)
    print("  测试汇总")
    print("=" * 70)
    print(f"  总测试数: {_pass + _fail}")
    print(f"  通过:     {_pass}")
    print(f"  失败:     {_fail}")
    print()

    # 写入重启验证 snapshot (真实重启后跑 restart_verify.py)
    snap = {
        "exist_code": exist_code,
        "exist_id": exist_id,
        "exist_version": v_before,
        "ok1_code": c_ok1,
        "ok2_code": c_ok2,
        "bad_temp_code": c_bad_temp,
        "bad_loc_code": c_bad_loc,
        "fixed_temp_code": c_bad_temp,
        "fixed_loc_code": c_bad_loc,
        "allfail_code_1": c_all_fail1,
        "allfail_code_2": c_all_fail2,
        "batch_id": batch_id,
        "batch_code": batch_code,
        "batch_total": batch["total_count"],
        "batch_succ": batch["success_count"],
        "batch_fail": batch["failed_count"],
        "batch_status": batch["status"],
        "allfail_batch_code": f"ALLFAIL-BATCH-{_TS}",
    }
    snap_path = "data/dirty_state_snapshot.json"
    os.makedirs("data", exist_ok=True)
    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)
    print(f"  [INFO] 脏数据验证 snapshot 写入: {snap_path}")
    print(f"         真实重启后运行: python examples/restart_verify.py")
    print()

    if _fail == 0:
        print("  ✓ 所有脏数据隔离 & 失败重跑测试通过！")
        return 0
    else:
        print(f"  ✗ 有 {_fail} 个用例失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
