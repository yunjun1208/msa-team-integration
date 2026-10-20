"""Read-only SES account/identity and Lambda consumer diagnostics; omit addresses/secrets."""
import json
import subprocess

def aws(*args):
    result = subprocess.run(["aws", *args, "--region", "ap-northeast-2", "--output", "json"],
                            capture_output=True, text=True, encoding="utf-8", timeout=45)
    if result.returncode:
        # AWS denial text is useful, but configuration/secret values are never requested.
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)

def main():
    caller = aws("sts", "get-caller-identity")
    if caller["Account"] != "256187519952":
        raise RuntimeError("Wrong AWS account; stopping")
    report = {}
    tasks = {
        "ses_account": lambda: aws("sesv2", "get-account"),
        "ses_identities": lambda: aws("sesv2", "list-email-identities"),
        "consumer_mappings": lambda: aws("lambda", "list-event-source-mappings", "--function-name", "Final-order-email"),
        "queue_counts": lambda: aws("sqs", "get-queue-attributes", "--queue-url",
            "https://sqs.ap-northeast-2.amazonaws.com/256187519952/Final-order-notifications",
            "--attribute-names", "ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"),
    }
    for name, task in tasks.items():
        try:
            value = task()
            if name == "ses_account":
                report[name] = {key: value.get(key) for key in ("ProductionAccessEnabled", "SendingEnabled", "EnforcementStatus", "SendQuota")}
            elif name == "ses_identities":
                report[name] = []
                for index, identity in enumerate(value.get("EmailIdentities", []), 1):
                    item = {"index": index, "type": identity.get("IdentityType"),
                            "sending_enabled": identity.get("SendingEnabled"),
                            "verification": identity.get("VerificationStatus")}
                    if identity.get("IdentityType") == "DOMAIN":
                        detail = aws("sesv2", "get-email-identity", "--email-identity", identity["IdentityName"])
                        item["dkim"] = {k: detail.get("DkimAttributes", {}).get(k) for k in ("SigningEnabled", "Status")}
                    report[name].append(item)
            elif name == "consumer_mappings":
                report[name] = [{k: v.get(k) for k in ("State", "LastProcessingResult")} for v in value.get("EventSourceMappings", [])]
            else:
                report[name] = value.get("Attributes", {})
        except Exception as error:
            report[name] = {"error": str(error)}
    print(json.dumps(report, ensure_ascii=True, indent=2))
    print("READ ONLY: no AWS settings changed, no emails sent.")

if __name__ == "__main__":
    main()
