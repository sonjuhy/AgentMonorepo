# 🚀 노코드/바이브 코딩으로 에이전트 뚝딱 만들기 가이드

오케스트라 에이전트(Orchestra Agent) 생태계에 새로운 에이전트를 추가하기 위해 **복잡한 통신 규약(Redis, HTTP, Heartbeat)을 직접 코딩할 필요는 전혀 없습니다!** 

이 가이드는 AI의 도움을 받아(Vibe Coding) **핵심 비즈니스 로직(파이썬 함수 딱 1개)만 작성**하고, 나머지는 시스템이 알아서 뼈대를 붙여 서비스로 배포하게 만드는 방법을 설명합니다.

---

## 🛠️ 방법 1: `agent-builder` CLI 도구 사용하기 (추천)

가장 빠르고 확실한 방법입니다. 터미널에서 스크립트를 실행하고 질문에 답하기만 하면, 완벽히 작동하는 에이전트 패키지가 생성됩니다.

### 1단계: 아이디어 구상 (Vibe Coding 준비)
AI 챗봇(ChatGPT, Claude 등)에게 다음과 같이 질문하여 핵심 함수 코드를 짜달라고 합니다.

> **나(Prompt):** "파이썬으로 네이버 뉴스의 IT/과학 헤드라인 5개를 스크래핑해서 JSON으로 반환하는 비동기 함수 `run(params)` 하나만 짜줘. `BeautifulSoup`이랑 `httpx` 쓸 거야."

AI가 짜준 아래와 같은 핵심 코드 덩어리만 복사해 둡니다.

```python
# 내 핵심 코드 (예시)
import httpx
from bs4 import BeautifulSoup

async def run(params: dict) -> dict:
    url = "https://news.naver.com/section/105"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
    
    soup = BeautifulSoup(response.text, 'html.parser')
    headlines = [item.text.strip() for item in soup.select('.sa_text_strong')[:5]]
    
    return {
        "status": "COMPLETED",
        "result_data": {"headlines": headlines, "summary": "최신 IT 뉴스 5건입니다."}
    }
```

### 2단계: 빌더 실행하기
터미널을 열고 프로젝트 루트(`Cassiopeia`)에서 다음 명령어를 실행합니다.

```bash
python tools/agent_builder/cli.py create
```

### 3단계: 마법의 프롬프트 입력 (대화형)
화면에 나오는 질문에 차근차근 답합니다.

1. **에이전트 이름:** `it_news` (자동으로 `it_news_agent`가 됩니다)
2. **에이전트 설명 (NLU 프롬프트용 - 아주 중요!):** `"사용자가 IT, 테크, 과학 관련 최신 뉴스나 기사를 요약해달라고 할 때 이 에이전트를 호출하세요."`
3. **수행 가능한 액션(Capabilities):** `get_latest_news`
4. **필요한 파이썬 패키지:** `httpx, beautifulsoup4`
5. **실행 환경 (Permissions):** 외부 웹에 접속해야 하므로 `trusted` 선택 (인터넷 접근 허용)
6. **핵심 코드 입력:** 1단계에서 AI가 짜준 코드를 붙여넣기 합니다!

### 4단계: 끝! 시스템 재시작
빌더가 끝나면 `agents/it_news_agent` 폴더가 생성되고, `docker-compose.yml` 파일까지 알아서 수정됩니다.
이제 도커를 껐다 켜기만 하면 끝입니다.

```bash
docker-compose up -d
```
이제 슬랙에 가서 **"@OrchestraBot 요즘 IT 뉴스 좀 알려줘"** 라고 말해보세요. 방금 만든 에이전트가 응답합니다!

---

## 🌐 방법 2: 외부 URL API로 원격 설치 (노코드)

만약 터미널을 열기도 귀찮거나, 이미 서비스 중인 오케스트라 서버를 재시작하지 않고 실시간으로 에이전트를 추가하고 싶다면 **API 호출 한 방(External URL Install)**으로 끝낼 수 있습니다.

### 1단계: 매니페스트(JSON) 파일 만들기
AI에게 부탁해서 아래와 같은 형식의 JSON 파일을 하나 작성해달라고 합니다. 

```json
{
  "name": "crypto_price",
  "description": "사용자가 비트코인이나 이더리움 같은 암호화폐의 현재 가격을 물어볼 때 호출하세요.",
  "capabilities": ["get_coin_price"],
  "language": "python",
  "packages": ["httpx"],
  "permissions": "trusted",
  "lifecycle_type": "long_running",
  "code": "import httpx\n\nasync def run(params: dict) -> dict:\n    coin = params.get('coin', 'bitcoin')\n    url = f'https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd'\n    async with httpx.AsyncClient() as client:\n        resp = await client.get(url)\n        data = resp.json()\n    \n    return {\n        'status': 'COMPLETED',\n        'result_data': {'price': data.get(coin, {}).get('usd', 'Unknown'), 'summary': f'{coin}의 현재 가격을 조회했습니다.'}\n    }"
}
```

이 파일을 Github Gist나 임의의 웹 서버에 올립니다. (예: `https://my-server.com/crypto_agent.json`)

### 2단계: 오케스트라에게 설치 명령 내리기 (API 호출)
Postman 도구나 터미널(curl)을 이용해 오케스트라의 API를 찌릅니다. 서버 재시작 없이 즉시 빌드되고 오케스트라의 NLU 두뇌에 추가됩니다.

```bash
curl -X POST http://localhost:8001/marketplace/install \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_ADMIN_API_KEY" \
  -d '{
    "item_url": "https://my-server.com/crypto_agent.json",
    "user_id": "admin"
  }'
```

**동작 원리:** 오케스트라가 저 JSON 파일을 읽어옵니다 -> 내부적으로 폴더를 만들고 Docker 이미지를 동적으로 굽습니다(Build) -> 컨테이너를 실행하고 큐에 연결시킵니다 -> NLU 엔진에게 "이제 암호화폐 가격 물어보면 얘한테 시켜!" 라고 똑똑하게 업데이트합니다.

---

## 🛑 주의사항 (이것만 지키세요!)

노코드/바이브 코딩으로 짠 `code` 부분(즉, `run(params)` 함수)은 반드시 다음 2가지를 지켜야 합니다.

1.  **함수 시그니처:** 반드시 비동기 함수 `async def run(params: dict) -> dict:` 형태로 작성해야 합니다.
2.  **리턴 포맷:** 반환하는 딕셔너리는 오케스트라가 이해할 수 있도록 최소한 `status`와 `result_data`를 포함해야 합니다.
    *   **성공 시:** `{"status": "COMPLETED", "result_data": {"자유로운": "데이터", "summary": "슬랙에 보여줄 간단한 요약"}}`
    *   **실패 시:** `{"status": "FAILED", "error": {"code": "MY_ERROR", "message": "왜 실패했는지 이유"}}`