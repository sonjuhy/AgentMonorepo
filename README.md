# AgentMonorepo 🤖

`AgentMonorepo`는 다양한 목적의 AI 에이전트를 모듈화하여 관리하기 위한 모노리포(Monorepo) 프로젝트입니다. 이 레포지토리는 여러 에이전트(기획, 슬랙 연동 등)가 통합된 환경에서 동작할 수 있도록 설계되었으며, 에이전트 운영을 보조하는 필수 스킬(지침) 세트를 포함하고 있습니다.

## 📂 프로젝트 구조

```text
AgentMonorepo/
├── .agent/
│   └── skills/                  # 에이전트가 동작할 때 참조하는 핵심 스킬(지침서) 목록
│       ├── ephemeral-docker-ops
│       ├── monorepo-cicd-router
│       ├── notion-schema-expert
│       └── python-strict-typing
├── agents/                      # 개별 에이전트 모듈
│   ├── planning_agent/          # 기획 및 태스크 관리를 담당하는 에이전트
│   └── slack_agent/             # 슬랙(Slack) 연동 및 알림을 담당하는 에이전트
├── .github/                     # GitHub Actions CI/CD 워크플로 목록
└── README.md
```

## 🛠 주요 에이전트 및 스킬 소개

### Agents (에이전트)
- **Planning Agent (`agents/planning_agent`)**
  - 시스템이나 프로젝트의 기획 및 태스크 분배 등을 처리합니다.
- **Slack Agent (`agents/slack_agent`)**
  - 메신저(Slack)를 통해 사용자와 소통하고 결과를 보고하는 허브 역할을 수행합니다.

### Skills (스킬 / 지침)
`.agent/skills`에 정의된 파일들은 에이전트가 코드를 작성하거나 시스템을 다룰 때 지켜야 하는 엄격한 룰셋입니다.
1. **`python-strict-typing`**: Python 3.12+ 구문(PEP 695)을 활용한 엄격한 타입 힌팅 프레임워크 준수 가이드.
2. **`notion-schema-expert`**: Notion API 통신 시 딕셔너리의 깊은 파싱 오류를 방지하기 위한 구조 가이드.
3. **`ephemeral-docker-ops`**: 단발성 및 가벼운 Docker 컨테이너 실행에 대한 제어 지침.
4. **`monorepo-cicd-router`**: 모노리포 환경에서의 CI/CD 라우팅 및 배포 제어 가이드.

## 🚀 시작하기

이 프로젝트는 에이전트 구동에 최적화된 프레임워크를 기반으로 합니다. 컨트리뷰션 또는 커밋 시 반드시 `.gitmessage.txt`에 정의된 **이모지 커밋 컨벤션**을 따르시길 바랍니다.

### 커밋 컨벤션 (예시)
- `✨ feat`: 새로운 기능 추가
- `🐛 fix`: 버그 수정
- `📝 docs`: 문서 수정
- `♻️ refactor`: 코드 리팩토링
- `🔧 chore`: 빌드 업무, 기타 세팅

---

*이 문서는 작성 규칙에 따라 자동으로 생성 및 관리됩니다.*