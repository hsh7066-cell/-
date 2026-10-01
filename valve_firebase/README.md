# 밸브 조작 관리 (Firebase 버전)

컴퓨터를 켜 둘 필요 없이, 휴대폰 **LTE/5G 또는 Wi-Fi**로 어디서든 밸브 상태를 실시간 공유합니다.
서버는 구글(Firebase)이 24시간 운영합니다. 10명 규모는 **무료 요금제(Spark)** 안에서 사용 가능합니다.
(무료 요금제는 한도를 넘으면 요금이 나가는 게 아니라 그날 사용만 멈춥니다.)

> ⚠ 설비 정보(밸브 번호·작업 일정)가 외부 클라우드에 저장됩니다. 사용 전 회사 보안 규정을 확인하세요.

---

## 처음 한 번만 하는 설정 (약 30분)

준비물: 구글 계정, **인터넷이 되는 개인 PC** (회사 망분리 PC 말고)

### 1단계. Firebase 프로젝트 만들기
1. https://console.firebase.google.com 접속 → 구글 계정 로그인
2. **[프로젝트 만들기]** → 이름 입력 (예: `valve-manager`) → Google 애널리틱스는 **사용 안함** → 만들기

### 2단계. 로그인 기능 켜기
1. 왼쪽 메뉴 **빌드 → Authentication** → [시작하기]
2. **로그인 방법** 탭 → **이메일/비밀번호** → 첫 번째 스위치 **사용 설정** → 저장
   (이메일 링크는 켜지 않아도 됩니다)

### 3단계. 데이터베이스 만들기
1. 왼쪽 메뉴 **빌드 → Firestore Database** → [데이터베이스 만들기]
2. 위치: **asia-northeast3 (서울)** 선택 (나중에 못 바꿉니다)
3. **프로덕션 모드**로 시작 → 만들기
   (보안 규칙은 4단계 배포 때 `firestore.rules` 파일 내용으로 자동 적용됩니다)

### 4단계. 웹 앱 등록하고 설정값 붙여넣기
1. 왼쪽 위 톱니바퀴 ⚙ → **프로젝트 설정** → 아래쪽 **내 앱** → 웹 아이콘 **`</>`** 클릭
2. 앱 닉네임 입력 (예: `valve-web`) → **Firebase 호스팅도 설정** 체크 → 앱 등록
3. 화면에 나오는 `const firebaseConfig = { ... };` 부분의 값을 복사해서
   이 폴더의 **`public/firebase-config.js`** 에 붙여넣고 저장합니다.
   ```js
   export const firebaseConfig = {
     apiKey: "AIza....",
     authDomain: "valve-manager.firebaseapp.com",
     projectId: "valve-manager",
     storageBucket: "valve-manager.firebasestorage.app",
     messagingSenderId: "1234567890",
     appId: "1:1234567890:web:abcd..."
   };
   ```
   (`export` 가 앞에 있어야 합니다. 이 값은 공개되어도 괜찮습니다.)
4. 화면의 나머지 안내(npm install 등)는 다음 단계에서 하므로 [다음]/[콘솔로 이동]

### 5단계. 배포 (인터넷에 올리기)
1. **Node.js** 설치: https://nodejs.org → **LTS** 버전 다운로드 → 설치 (모두 기본값)
2. Visual Studio(또는 명령 프롬프트)에서 터미널을 열고 순서대로 입력:
   ```
   npm install -g firebase-tools
   firebase login
   ```
   → 브라우저가 열리면 같은 구글 계정으로 로그인/허용
3. 이 폴더(`valve_firebase`)로 이동해서:
   ```
   cd valve_firebase
   firebase use --add
   ```
   → 화살표로 1단계에서 만든 프로젝트 선택 → 별칭은 `default` 입력
4. 배포:
   ```
   firebase deploy
   ```
   마지막에 `Hosting URL: https://valve-manager.web.app` 같은 주소가 나오면 완료입니다.

### 6단계. 관리자 계정 만들기 (바로 하세요)
1. 위 주소로 접속 → 로그인 화면 아래 **"최초 설정: 관리자 계정 만들기"**
2. 관리자 아이디/이름/비밀번호 입력 → 만들기
   (이 상자는 관리자가 한 번 만들어지면 다시 나타나지 않습니다. 배포 직후 바로 만드세요.)

### 7단계. 밸브 목록과 사용자 등록
1. **관리자** 탭 → **밸브 목록 불러오기** → 조작요청 **엑셀(.xlsx)을 그대로** 선택
   → 미리보기(개수, 오타 자동 수정 내역) 확인 → [불러오기]
2. **사용자 등록** → 아이디/이름/부서/임시 비밀번호 → 등록 (10명)
3. 각 사람에게 **주소 + 아이디 + 임시 비밀번호**를 카톡/문자로 전달
   → 첫 로그인 때 본인이 비밀번호를 바꿉니다.

---

## 휴대폰에서 사용

1. 크롬에서 주소(`https://○○○.web.app`) 접속 → 로그인
2. 크롬 메뉴(⋮) → **홈 화면에 추가** → 앱처럼 아이콘으로 실행
   (아이폰: 사파리 → 공유 버튼 → 홈 화면에 추가)

### 조작·검증 절차 (2인 확인)
1. **조작자**: 밸브를 실제로 돌린 뒤 → 목록에서 밸브 선택 → `OPEN 했음`/`CLOSE 했음`
   → "명판 확인", "실제 조작함" 두 칸 체크해야 등록 → **확인대기**(주황)
2. **확인자**(조작자와 다른 사람): 현장에서 보고 `맞음` → **확인완료**(초록)
   / `다름` → **불일치**(빨강, 사유 필수) → 다시 조작
3. 누가 바꾸면 **모든 사람 화면이 즉시** 바뀌고 알림이 뜹니다.
4. 두 사람이 동시에 같은 밸브를 바꾸면 늦은 쪽은 거절되고 최신 상태를 다시 보여줍니다.
5. 지하 등 신호가 없는 곳에서는 마지막 화면은 보이지만 등록은 안 됩니다(빨간 줄 표시).
   신호가 잡히는 곳에서 등록하세요.

### 이 규칙들은 서버에서 강제됩니다
`firestore.rules` 에 의해, 앱을 조작해도 다음은 불가능합니다:
본인이 조작한 밸브를 본인이 확인 / 다른 사람 이름으로 등록 / 이력 수정·삭제 /
관리자의 확인 위조 / 사용중지된 사람의 접속.

---

## 자주 하는 일

| 하고 싶은 일 | 방법 |
|---|---|
| 새 작업 시작 | 관리자 탭 → 새 엑셀 불러오기 (기존 목록은 숨겨지고 이력은 보존) |
| 퇴사/이동자 차단 | 관리자 탭 → 사용자 목록 → 사용중지 (즉시 차단) |
| 비밀번호 분실 | 해당 사용자 사용중지 → 새 아이디(예: `kim2`)로 다시 등록 |
| 이력 보관 | 조작 이력 탭 → 엑셀(CSV) 받기 |
| 밸브 정보 수정 | 관리자가 밸브 선택 → 관리자: 밸브 정보 수정 |
| 화면 수정 후 다시 올리기 | `firebase deploy` |

## 파일 구성

| 파일 | 역할 |
|---|---|
| `public/index.html` | 앱 화면 전체 |
| `public/firebase-config.js` | **내 Firebase 설정값 (4단계에서 붙여넣기)** |
| `public/style.css`, `manifest.json`, `icon.svg` | 화면 디자인, 홈 화면 아이콘 |
| `public/vendor/` | Firebase·엑셀 읽기 라이브러리 (인터넷에서 따로 받지 않도록 포함) |
| `firestore.rules` | 서버 보안 규칙 (2인 확인 등) |
| `firebase.json` | 배포 설정 |
| `tools/` | 개발용 (라이브러리 재생성, 보안 규칙 자동 시험) |

## 무료 한도 (Spark 요금제, 하루 기준 대략)
읽기 5만 건 / 쓰기 2만 건 / 저장 1GB / 호스팅 전송 360MB.
10명이 하루 종일 써도 수천 건 수준입니다. 사용량은 Firebase 콘솔 → **사용량 및 결제**에서 볼 수 있습니다.

## 개발자용 메모
- `public/vendor/firebase.js` 재생성:
  `npm i firebase esbuild && npx esbuild tools/firebase-entry.js --bundle --format=esm --minify --outfile=public/vendor/firebase.js`
- 내 PC 시험: `firebase emulators:start --project demo-valve` → http://localhost:5000
  (localhost 로 열면 자동으로 에뮬레이터에 연결, firebase-config.js 에 아무 값이나 있어야 함)
- 보안 규칙 시험: 에뮬레이터 실행 중 `npm i @firebase/rules-unit-testing firebase && node tools/rules.test.mjs`
