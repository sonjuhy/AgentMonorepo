
import requests
import json
import time
from datetime import datetime

def run_integration_test():
    base_urls = {
        "communication": "http://127.0.0.1:8000",
        "orchestra": "http://127.0.0.1:8001",
        "archive": "http://127.0.0.1:8002"
    }
    
    report_file = "TEST_RESULTS_LOG.md"
    test_results = []

    print("Checking agents health...")
    health_status = {}
    for name, url in base_urls.items():
        try:
            resp = requests.get(f"{url}/health", timeout=5)
            health_status[name] = "UP" if resp.status_code == 200 else f"DOWN ({resp.status_code})"
        except Exception as e:
            health_status[name] = f"ERROR ({str(e)})"

    # 1. Test Input
    user_input = "내일 오전 10시 주간 회의 내용을 Notion에 '2024-04-15 회의록'으로 저장해줘."
    payload = {
        "content": user_input,
        "user_id": "test_user_01",
        "session_id": f"test_session_{int(time.time())}"
    }

    print(f"Sending task to Orchestra Agent: {user_input}")
    
    test_entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "input": user_input,
        "steps": [],
        "final_result": "FAIL",
        "output": ""
    }

    try:
        # 2. Dispatch Task
        start_time = time.time()
        resp = requests.post(f"{base_urls['orchestra']}/tasks", json=payload, timeout=30)
        dispatch_result = resp.json()
        test_entry["steps"].append({"step": "Orchestra Dispatch", "status": "SUCCESS", "response": dispatch_result})
        
        task_id = dispatch_result.get("task_id")
        
        # 3. Poll for result (Wait up to 90 seconds)
        for i in range(30):
            time.sleep(3)
            status_resp = requests.get(f"{base_urls['orchestra']}/tasks/{task_id}", timeout=5)
            status_data = status_resp.json()
            test_entry["steps"].append({"step": f"Polling Status {i+1}", "status": status_data.get("status"), "data": status_data})
            
            if status_data.get("status") in ["completed", "failed"]:
                test_entry["final_result"] = status_data.get("status").upper()
                test_entry["output"] = json.dumps(status_data.get("result", {}), ensure_ascii=False, indent=2)
                break
        
        elapsed = time.time() - start_time
        test_entry["elapsed_time"] = f"{elapsed:.2f}s"

    except Exception as e:
        test_entry["final_result"] = "ERROR"
        test_entry["output"] = str(e)

    # Write to MD file
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("# 에이전트 통합 테스트 결과 리포트\n\n")
        f.write(f"**테스트 일시**: {test_entry['timestamp']}\n\n")
        
        f.write("## 1. 에이전트 상태\n")
        for name, status in health_status.items():
            f.write(f"- **{name.capitalize()} Agent**: {status}\n")
        f.write("\n")
        
        f.write("## 2. 테스트 시나리오\n")
        f.write(f"- **입력값**: `{test_entry['input']}`\n")
        f.write(f"- **최종 결과**: {test_entry['final_result']}\n")
        if "elapsed_time" in test_entry:
            f.write(f"- **소요 시간**: {test_entry['elapsed_time']}\n")
        f.write("\n")
        
        f.write("## 3. 상세 처리 과정\n")
        f.write("| 단계 | 상태 | 내용 |\n")
        f.write("| :--- | :--- | :--- |\n")
        for step in test_entry["steps"]:
            f.write(f"| {step['step']} | {step['status']} | {json.dumps(step.get('response') or step.get('data'), ensure_ascii=False)} |\n")
        f.write("\n")
        
        f.write("## 4. 최종 출력값\n")
        f.write(f"```json\n{test_entry['output']}\n```\n")

    print(f"Test completed. Results saved to {report_file}")

if __name__ == "__main__":
    run_integration_test()
