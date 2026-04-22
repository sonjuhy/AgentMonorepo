import os
import httpx
from dotenv import load_dotenv

load_dotenv(encoding="utf-8", override=True)

# .env에 NOTION_DATABASE_ID 대신 NOTION_DB_ID만 있는 경우를 위한 Fallback
if "NOTION_DATABASE_ID" not in os.environ and "NOTION_DB_ID" in os.environ:
    os.environ["NOTION_DATABASE_ID"] = os.environ["NOTION_DB_ID"]

token = os.environ.get("NOTION_TOKEN")
db_id = os.environ.get("NOTION_DATABASE_ID")

headers = {
    "Authorization": f"Bearer {token}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

print(f"Token: {token[:4]}...{token[-4:]}" if token else "No Token")
print(f"DB ID: {db_id}")

try:
    # 1. DB의 프로퍼티 목록(스키마) 조회
    db_url = f"https://api.notion.com/v1/databases/{db_id}"
    resp = httpx.get(db_url, headers=headers)
    resp.raise_for_status()
    db_data = resp.json()
    print("\n--- Properties Schema ---")
    for prop_name, prop_info in db_data.get("properties", {}).items():
        print(f"Name: {prop_name}, Type: {prop_info['type']}")
        if prop_info["type"] == "status":
            options = [opt["name"] for opt in prop_info["status"]["options"]]
            print(f"  Status Options: {options}")

    # 2. 필터 없이 1개만 조회해보기
    query_url = f"https://api.notion.com/v1/databases/{db_id}/query"
    resp2 = httpx.post(query_url, headers=headers, json={"page_size": 1})
    resp2.raise_for_status()
    query_data = resp2.json()
    results = query_data.get("results", [])
    print(f"\n--- Total Items in DB: {len(results)} (showing up to 1) ---")
    if results:
        print("\n--- Example Item ---")
        props = results[0].get("properties", {})
        for k, v in props.items():
            if v["type"] == "status":
                status_name = v["status"]["name"] if v.get("status") else None
                print(f"{k} ({v['type']}): {status_name}")
            elif v["type"] == "title":
                title_val = v["title"][0]["plain_text"] if v["title"] else "Empty"
                print(f"{k} ({v['type']}): {title_val}")
            else:
                print(f"{k} ({v['type']})")
except Exception as e:
    print(f"Error: {e}")
