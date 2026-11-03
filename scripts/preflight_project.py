"""Project-specific preflight checks, loaded by scripts/preflight.py.

Everything here is optional. Fill these in when the project talks to an
external service, for example:

    REQUIRED_SETTINGS = ["PARTNER_API_URL", "PARTNER_API_KEY"]
    BASE_URL_SETTINGS = ["PARTNER_API_URL"]

    def run(pf, args):
        base, key = pf.setting("PARTNER_API_URL"), pf.setting("PARTNER_API_KEY")
        pf.section(f"Partner API @ {base}")
        status, body = pf.http_json(f"{base}/health", headers={"X-API-Key": key})
        (pf.ok if status == 200 else pf.fail)(f"/health -> {status}")
"""

REQUIRED_SETTINGS: list[str] = []
BASE_URL_SETTINGS: list[str] = []
