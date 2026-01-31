# Main repo ↔ Tricrawl 협업 가이드 (Upstream/Downstream + Sync PR)

> 목표: **코어는 `tricrawl`에서 개발**하고, **통합은 `main` 레포에서 진행**한다.  
> 코어 변경은 항상 `main` 레포의 `sync/core-to-dashboard` 브랜치로 올려 **PR로만 반영**한다.

---

## 0) 레포/브랜치 정의 (이 문서의 기준)

### 레포 2개
- **`tricrawl` 레포**: 코어(크롤링 프레임워크/파이프라인/DB/공통 모듈) 개발 레포
- **`main` 레포**: 통합(대시보드/데모/발표용) 레포

### `main` 레포의 브랜치 3개(확장 가능)
- **`main`**: 통합 레포의 기본 브랜치(최종 통합 지점)
- **`dashboard`**: 팀장 작업 브랜치(대시보드 중심)
- **`sync/core-to-dashboard`**: `tricrawl`의 코어 변경을 `main` 레포로 보내는 **배송/동기화 브랜치**

> 원칙: `main` 레포의 `main`에는 직접 push하지 않는다. 모든 반영은 PR로 한다.

---

## 1) 로컬 remotes 표준

로컬에서 두 레포를 다루기 위해 remote 이름을 고정한다.

- `origin` = **tricrawl 레포**
- `downstream` = **main 레포**

확인:

```bash
git remote -v
```

설정(최초 1회):

```bash
git remote add downstream https://github.com/Tri-Best-3/darkweb_crawler_main.git
# 이미 있으면 생략 (혹은 git remote set-url downstream ...)
```

---

## 2) 핵심 원칙 (실수 방지 룰 5개)

1. **코어 개발은 항상 `tricrawl:main`에서 한다.**
2. `main` 레포에 코어를 반영할 때는 **반드시 `sync/core-to-dashboard` 브랜치를 사용**한다.
3. PR 생성 직전, `sync/core-to-dashboard`는 항상 **`main` 레포의 최신 `main`을 먼저 포함**해야 한다.
4. `sync/core-to-dashboard`에 코어를 얹을 때는 **`downstream/main` → `origin/main` 순서로 merge**한다.
5. `main` 레포의 `main`에는 **직접 push 금지**(권한이 있어도 금지). PR만.

---

## 3) 일상 루틴 (매번 이대로)

### A) `tricrawl`에서 코어 개발 → 푸시

```bash
# tricrawl 레포

git checkout main

git add .
git commit -m "feat(core): <요약>"

git push origin main
```

### B) `main` 레포로 동기화 브랜치 갱신 → PR

> **중요 순서:** `downstream/main` 먼저 먹고 → `origin/main`을 얹는다.

```bash
# sync 브랜치로 이동

git checkout sync/core-to-dashboard

# 1) 통합 레포(main 레포)의 최신 main을 먼저 반영 (팀장이 밤새 머지했든 뭐든 흡수)

git fetch downstream
git merge downstream/main

# 2) 그 위에 tricrawl 코어 최신을 반영

git fetch origin
git merge origin/main

# 3) main 레포에 푸시 (PR용)

git push downstream sync/core-to-dashboard
```

### C) PR 생성

- 레포: **`main`**
- base: **`main`**
- compare: **`sync/core-to-dashboard`**

권장 PR 제목 예시:
- `Sync(core): <변경 요약>`

PR 본문 템플릿:
- `tricrawl(main)의 코어 변경을 main 레포(main)에 반영합니다.`
- `포함: <핵심 2~4개 bullet>`

---

## 4) 브랜치 운영 권장

### `tricrawl`에서 main 직접 작업은 가능하지만, 다음을 권장
- 큰 작업/리팩토링은 브랜치로:
  - `hhkb/core-db`
  - `hhkb/pipeline-supabase`

### `main` 레포에서는
- `dashboard`는 팀장/프론트 작업
- `sync/core-to-dashboard`는 코어 배송 전용

---

## 5) 트러블슈팅 (자주 터지는 오류별)

### 5.1 PR 화면에서 Ahead/Behind가 뜬다

#### 증상
- PR 비교에서 `X commits behind`가 보임

#### 원인
- `sync/core-to-dashboard`가 `downstream/main` 최신을 아직 포함하지 않음

#### 해결

```bash
git checkout sync/core-to-dashboard
git fetch downstream
git merge downstream/main
git push downstream sync/core-to-dashboard
```

그 다음 PR 새로고침.

---

### 5.2 `fatal: refusing to merge unrelated histories`

#### 증상
- `git merge origin/main` 또는 `git merge downstream/main`에서 위 에러

#### 원인
- 두 레포가 **복사로 시작되어 히스토리(부모 커밋)가 연결되지 않은 상태**

#### 해결(초기 1회만)

```bash
git checkout sync/core-to-dashboard
git merge origin/main --allow-unrelated-histories
```

- 충돌이 나면 해결 후 `git commit` 해야 히스토리가 연결됨
- 연결 후에는 보통 이 옵션이 다시 필요 없다

---

### 5.3 충돌이 잔뜩 나고 `both added`가 뜬다

#### 증상
- `.env.example`, `README.md`, `config/*.yaml` 등에서 `CONFLICT (add/add)`

#### 원인
- 서로 다른 히스토리의 레포가 같은 경로/파일명을 동시에 가지고 있어 Git이 선택 불가

#### 원칙
- 팀장이 크롤러(코어)를 건드리지 않는 전제라면:
  - **코어 파일은 `tricrawl` 기준을 채택**하는 편이 가장 안전

#### 빠른 해결(코어를 `tricrawl` 기준으로)

```bash
# merge 중일 때

# 충돌 파일을 tricrawl(theirs)로 채택
git checkout --theirs -- <충돌파일들>

# 해결 표시
git add <충돌파일들>

# merge 커밋
git commit -m "Sync: resolve conflicts using tricrawl as source of truth"
```

> `ours/theirs` 의미: 현재 브랜치가 `sync`이면
> - ours = downstream 쪽
> - theirs = origin(main)에서 온 쪽

---

### 5.4 `Everything up-to-date`가 뜨는데 PR이 비어 보인다

#### 원인
- merge가 실패했거나(충돌 해결 전)
- merge 커밋을 아직 만들지 않아 **브랜치에 새 커밋이 없음**

#### 해결 체크리스트
1) `git status`에 `You have unmerged paths`가 있으면 → 충돌 해결 후 `git commit` 필요
2) `git log --oneline -5`에서 최신 커밋이 실제로 `sync` 브랜치에 생성되었는지 확인

---

### 5.5 실수로 sync 브랜치에서 작업이 꼬였다 (되돌리고 싶다)

#### 1) merge 진행 중이면

```bash
git merge --abort
```

#### 2) 이미 커밋했는데 되돌리고 싶으면

- 안전: 새 브랜치 만들어 수정 후 PR 다시 생성
- 강경: `git reset --hard` (주의)

권장(안전)

```bash
git checkout -b fix/sync-reset
# 필요한 정리 후 push + PR
```

---

## 6) 운영 팁 (팀 커뮤니케이션 최소화)

- 코어 변경 반영은 항상 PR 제목에 `Sync(core)`를 붙인다.
- `main` 레포에서 팀장/프론트 작업이 바쁘면, 코어 PR은 **짧게 자주** 보내는 게 충돌이 덜 난다.
- `main` 레포의 `main`은 PR-only로 보호 설정을 걸면 실수가 줄어든다.

---

## 7) 체크리스트 (PR 올리기 직전 10초)

- [ ] 지금 브랜치가 `sync/core-to-dashboard`인가?
- [ ] `git merge downstream/main`을 먼저 했나?
- [ ] 그 다음 `git merge origin/main`을 했나?
- [ ] `git status`가 clean인가? (unmerged 없음)
- [ ] `git push downstream sync/core-to-dashboard` 했나?
- [ ] PR base가 `main` 레포의 `main`인가?

---

## 8) 부록: 가장 짧은 “배송 스크립트” (복붙용)

```bash
# 1) tricrawl에서
# git checkout main && git add . && git commit -m "feat(core): ..." && git push origin main

# 2) main 레포로 배송

git checkout sync/core-to-dashboard && \
  git fetch downstream && git merge downstream/main && \
  git fetch origin && git merge origin/main && \
  git push downstream sync/core-to-dashboard
```

(Windows PowerShell에서는 `&&`가 환경에 따라 동작이 달라질 수 있으니, 줄 단위 실행 권장)

