"""Creates disposable local test members/product/order; never targets AWS."""
import json, uuid, urllib.request, urllib.error, time
from pathlib import Path
BASE = "http://localhost:8080"
def call(path, data=None, token=None, headers=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    if token: h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=None if data is None else json.dumps(data).encode(), headers=h)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)
def main():
    env = dict(line.split("=", 1) for line in (Path(__file__).resolve().parents[1] / ".env.local").read_text(encoding="utf-8-sig").splitlines() if line and not line.startswith("#"))
    admin = call("/member-service/member/doLogin", {"loginId":"admin", "password":env["ADMIN_BOOTSTRAP_PASSWORD"]})["token"]
    boundary = "----msa" + uuid.uuid4().hex
    fields = {"name":"Local smoke product", "category":"TEST", "description":"Smoke test", "price":"1000", "stockQuantity":"5"}
    body = "".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k,v in fields.items()) + f"--{boundary}--\r\n"
    req = urllib.request.Request(BASE + "/product-service/product/create", data=body.encode(), headers={"Authorization":"Bearer "+admin,"Content-Type":"multipart/form-data; boundary="+boundary})
    with urllib.request.urlopen(req, timeout=30) as r: product = json.load(r)
    accounts = []
    for _ in range(2):
        name = "smoke" + uuid.uuid4().hex[:12]
        call("/member-service/member/create", {"name":name,"nickname":name,"loginId":name,"email":name+"@example.test","password":"LocalSmokePass123!"})
        accounts.append(call("/member-service/member/doLogin", {"loginId":name,"password":"LocalSmokePass123!"})["token"])
    key = uuid.uuid4().hex
    data = {"productId":product,"productCount":2}
    order = call("/ordering-service/ordering/create", data, accounts[0], {"Idempotency-Key":key})
    for _ in range(30):
        if order["status"] == "ORDERED": break
        assert order["status"] != "FAILED", "Order failed"
        time.sleep(1)
        order = call("/ordering-service/ordering/"+str(order["id"]), token=accounts[0])
    assert order["status"] == "ORDERED", "Order did not complete"
    repeated = call("/ordering-service/ordering/create", data, accounts[0], {"Idempotency-Key":key})
    assert repeated["id"] == order["id"], "Duplicate order"
    item = call("/product-service/product/"+str(product))
    assert item["stockQuantity"] == 3, "Stock must decrement exactly once"
    try:
        call("/ordering-service/ordering/"+str(order["id"]), token=accounts[1])
        raise AssertionError("Other member could read order")
    except urllib.error.HTTPError as e:
        assert e.code in (403,404), f"Unexpected ownership status {e.code}"
    print("PASS: signup, login, product, order, duplicate request, stock and ownership")
    print("Local test data retained. AWS email delivery is disabled.")
if __name__ == "__main__": main()
