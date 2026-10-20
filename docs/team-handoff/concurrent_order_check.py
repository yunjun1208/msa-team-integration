"""Two distinct QA orders released through one thread barrier; no credential logging."""
import argparse
import concurrent.futures
import getpass
import json
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request
import uuid

BASE = "https://server.aws-cisco.com"
REPORT = Path(__file__).with_name("concurrent-order-result.json")

def request(path, method="GET", data=None, token=None, key=None):
    headers = {"Content-Type": "application/json", "Cache-Control": "no-store"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if key:
        headers["Idempotency-Key"] = key
    req = urllib.request.Request(BASE + path, data=None if data is None else json.dumps(data).encode(),
                                 headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        # Never echo error bodies: a login response could contain private account fields.
        try:
            body = json.load(error)
        except (ValueError, UnicodeError):
            body = {}
        return error.code, body

def stock_snapshot():
    status, rows = request("/product-service/product/list")
    if status != 200 or not isinstance(rows, list):
        raise RuntimeError("Product API unavailable")
    return rows

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--product-id", type=int, default=3)
    args = parser.parse_args()
    rows = stock_snapshot()
    qa = next((p for p in rows if p["id"] == args.product_id), None)
    if not qa or not qa["name"].startswith("QA ") or qa["stockQuantity"] != 1:
        raise RuntimeError("Requires a QA-named product with exactly one stock; no orders sent")
    print(f"PLAN: QA product #{qa['id']}, stock=1, two requests with different keys, one item each.", flush=True)
    if not args.execute:
        print("PLAN ONLY: no login or orders submitted.")
        return
    if REPORT.exists():
        raise RuntimeError("Existing result file found; inspect it before repeating this test")
    login_id = input("Shop login ID: ").strip()
    password = getpass.getpass("Shop password (hidden; not saved): ")
    status, auth = request("/member-service/member/doLogin", "POST", {"loginId": login_id, "password": password})
    del password, login_id
    if status != 200 or not auth.get("token"):
        raise RuntimeError("Login failed; no orders sent")
    token = auth["token"]
    del auth
    status, before_orders = request("/ordering-service/ordering/mine", token=token)
    if status != 200 or not isinstance(before_orders, list):
        raise RuntimeError("Cannot read baseline orders; no orders sent")
    before = {p["id"]: p["stockQuantity"] for p in rows}
    keys = ["qa-race-" + uuid.uuid4().hex for _ in range(2)]
    report = {"product_id": qa["id"], "before_stock": before, "keys": keys,
              "phase": "prepared", "before_order_ids": [o["id"] for o in before_orders]}
    def save():
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    save()  # Preserve request keys before submitting; never repeat an uncertain request with a new key.
    barrier = threading.Barrier(2)
    def submit(key):
        barrier.wait(timeout=10)
        started = time.monotonic_ns()
        code, body = request("/ordering-service/ordering/create", "POST",
                             {"productId": qa["id"], "productCount": 1}, token, key)
        return {"key": key, "started_ns": started, "http": code,
                "id": body.get("id"), "status": body.get("status")}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit, key) for key in keys]
        results = []
        for future in futures:
            try:
                results.append(future.result())
            except Exception as error:
                results.append({"error": type(error).__name__})
    report.update(phase="submitted", requests=results)
    save()
    if len({r.get("id") for r in results if r.get("id")}) != 2:
        raise RuntimeError("Two distinct order IDs not confirmed; inspect report/mine, do not blindly rerun")
    deadline = time.monotonic() + 120
    while True:
        for result in results:
            code, body = request("/ordering-service/ordering/" + str(result["id"]), token=token)
            if code != 200:
                raise RuntimeError("Order read failed; inspect retained report")
            result["status"] = body.get("status")
        if all(r["status"] in ("ORDERED", "FAILED") for r in results):
            break
        if time.monotonic() >= deadline:
            report["phase"] = "pending"
            save()
            raise RuntimeError("Orders still pending after 120s; report retained")
        time.sleep(3)
    after = {p["id"]: p["stockQuantity"] for p in stock_snapshot()}
    winner = next((r for r in results if r["status"] == "ORDERED"), None)
    # Replay the exact successful key to verify idempotency without making a third order.
    replay = None
    if winner:
        code, body = request("/ordering-service/ordering/create", "POST",
                             {"productId": qa["id"], "productCount": 1}, token, winner["key"])
        replay = {"http": code, "id": body.get("id"), "status": body.get("status")}
    code, mine = request("/ordering-service/ordering/mine", token=token)
    new_ids = sorted({o["id"] for o in mine} - set(report["before_order_ids"])) if code == 200 else []
    final = {p["id"]: p["stockQuantity"] for p in stock_snapshot()}
    passed = (sorted(r["status"] for r in results) == ["FAILED", "ORDERED"]
              and after.get(qa["id"]) == final.get(qa["id"]) == 0
              and all(final.get(pid) == stock for pid, stock in before.items() if pid != qa["id"])
              and replay is not None and replay["http"] == 201
              and replay["id"] == winner["id"] and replay["status"] == "ORDERED"
              and new_ids == sorted(r["id"] for r in results))
    report.update(phase="passed" if passed else "failed", requests=results, after_stock=final,
                  replay=replay, new_order_ids=new_ids,
                  client_start_skew_ms=abs(results[0]["started_ns"] - results[1]["started_ns"]) / 1e6)
    save()
    print(json.dumps(report, ensure_ascii=True, indent=2))
    print("PASS: one ORDERED, one FAILED, stock zero, replay same order, other stocks unchanged."
          if passed else "FAIL: inspect the report; no automatic new orders.")
    print("Two client requests share a barrier. This is a two-request race check, not a load benchmark.")
    if not passed:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
