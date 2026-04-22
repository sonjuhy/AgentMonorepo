
import requests
import redis
import json
import time

def run_diagnostics():
    orchestra_url = "http://127.0.0.1:8001"
    redis_url = "redis://127.0.0.1:6379"
    r = redis.from_url(redis_url, decode_responses=True)

    print("=== 1. Orchestra Agent Registered Agents ===")
    try:
        resp = requests.get(f"{orchestra_url}/agents")
        print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Failed to fetch agents: {e}")

    print("\n=== 2. Redis Health Keys ===")
    health_keys = r.keys("agent:*:health")
    for key in health_keys:
        val = r.hgetall(key)
        print(f"Key: {key} -> {val}")

    print("\n=== 3. Recent Tasks in Redis ===")
    # orchestra_agent:state_manager uses "tasks:{task_id}" or similar
    task_keys = r.keys("task:*")
    if not task_keys:
        # Try different pattern if not found
        task_keys = r.keys("*task*")
    
    for key in task_keys[:5]: # Show latest 5
        try:
            val = r.get(key)
            print(f"Key: {key} -> {val}")
        except:
            # Might be a hash
            try:
                val = r.hgetall(key)
                print(f"Key (Hash): {key} -> {val}")
            except:
                pass

    print("\n=== 4. Testing Manual Result Injection ===")
    # Get the last task_id if possible
    last_task_id = None
    for key in task_keys:
        if "task:" in key:
            last_task_id = key.split("task:")[1]
            break
    
    if last_task_id:
        print(f"Injecting mock success result for task_id: {last_task_id}")
        payload = {
            "task_id": last_task_id,
            "agent": "archive_agent",
            "status": "completed",
            "result_data": {"message": "DIAGNOSTIC MOCK SUCCESS", "url": "http://notion.so/mock_page"},
            "error": None
        }
        try:
            resp = requests.post(f"{orchestra_url}/results", json=payload)
            print(f"Orchestra Response: {resp.status_code} - {resp.text}")
            
            # Check status again
            time.sleep(1)
            status_resp = requests.get(f"{orchestra_url}/tasks/{last_task_id}")
            print(f"Task Status after Injection: {status_resp.json().get('status')}")
        except Exception as e:
            print(f"Failed to inject result: {e}")
    else:
        print("No task_id found to inject results.")

if __name__ == "__main__":
    run_diagnostics()
