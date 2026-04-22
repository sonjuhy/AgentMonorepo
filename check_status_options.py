"""DB에서 현황 컬럼의 status 옵션 이름을 hex로 출력"""

import os

import httpx
from dotenv import load_dotenv

load_dotenv(encoding="utf-8", override=True)

if "NOTION_DATABASE_ID" not in os.environ and "NOTION_DB_ID" in os.environ:
    os.environ["NOTION_DATABASE_ID"] = os.environ["NOTION_DB_ID"]

token = os.environ["NOTION_TOKEN"]
db_id = os.environ["NOTION_DATABASE_ID"]
headers = {
    "Authorization": f"Bearer {token}",
    "Notion-Version": "2022-06-28",
}

resp = httpx.get(f"https://api.notion.com/v1/databases/{db_id}", headers=headers)
resp.raise_for_status()

props = resp.json()["properties"]
for prop_key in props:
    print(f"prop_key repr: {repr(prop_key)}")

status_key = next((k for k, v in props.items() if v["type"] == "status"), None)
print(f"\n=== Found status key: {repr(status_key)} ===")

if status_key:
    status_prop = props[status_key]["status"]
    options = status_prop.get("options", [])
    print(f"\nOptions (total={len(options)}):")
    for opt in options:
        name = opt["name"]
        hex_bytes = name.encode("utf-8").hex()
        print(f"  repr={repr(name)}  utf8_hex={hex_bytes}")
