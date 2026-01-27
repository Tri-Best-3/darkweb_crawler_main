# TriCrawl 데이터 분석 및 시각화 가이드

Supabase(PostgreSQL)에 수집된 데이터를 활용하여 대시보드를 구성하거나 분석 작업 시 필요한 정보입니다.

## 1. 데이터베이스 연결

- **Supabase**: https://supabase.com > 가입 후 초대 요청주세요.
- **Table**: `darkweb_leaks`

### 주요 필드 설명 (Schema)

| 필드명 | 타입 | 설명 | 예시 |
|--------|------|------|------|
| `dedup_id` | `text` (PK) | 게시물 고유 ID | `a1b2c3d4...` |
| `source` | `text` | 출처 (스파이더 이름) | `DarkNetArmy`, `Abyss` |
| `site_type` | `text` | 사이트 유형 | `Forum`, `Ransomware` |
| `category` | `text` | 게시판 또는 분류 | `Leaked Databases`, `General` |
| `title` | `text` | 게시글 제목 | `Samsung Employee DB Leaked` |
| `author` | `text` | 작성자 | `HackerOne` |
| `risk_level` | `text` | 위험도 | `CRITICAL`, `HIGH`, `LOW` |
| `matched_keywords` | `text[]` | 매칭된 키워드 배열 | `['samsung', 'leak']` |
| `posted_at` | `timestamp` | 원본 글 작성 시간 | `2024-03-01 T12:00:00+00:00` |
| `crawled_at` | `timestamp` | 수집된 시간 | `2024-03-01 T12:05:00+00:00` |
| `url` | `text` | 원본 링크 (.onion) | `http://Example.onion/...` |

## 2. 개발자 연동 가이드 (Data Fetching)

대시보드(Web/App) 개발 시 데이터를 가져오는 방법입니다.

### JavaScript/TypeScript(Supabase Client)

```javascript
import { createClient } from '@supabase/supabase-js'

const supabase = createClient('https://xxx.supabase.co', 'public-anon-key')

// 1. 전체 목록 조회 (최신순)
const { data, error } = await supabase
  .from('darkweb_leaks')
  .select('*')
  .order('posted_at', { ascending: false })
  .limit(100)

// 2. 검색 및 필터링 (키워드 검색)
const { data: searchResults } = await supabase
  .from('darkweb_leaks')
  .select('title, risk_level, url')
  .textSearch('title', 'database') // Full-text search
  .eq('risk_level', 'CRITICAL')
```

### REST API(cURL)

```bash
# API URL 및 Key는 프로젝트 설정에서 확인
curl 'https://xxx.supabase.co/rest/v1/darkweb_leaks?select=*&limit=10' \
-H "apikey: SUPABASE_KEY" \
-H "Authorization: Bearer SUPABASE_KEY"
```

### Python(Pandas/Supabase Client)

```python
import os
import pandas as pd
from supabase import create_client

# 1. 연결
url = "https://your-project.supabase.co"
key = "your-anon-key"
supabase = create_client(url, key)

# 2. 데이터 가져오기 (전체 선택)
response = supabase.table("darkweb_leaks").select("*").execute()
df = pd.DataFrame(response.data)

# 3. 데이터 전처리 예시
df['posted_at'] = pd.to_datetime(df['posted_at'])
print(f"📊 총 데이터 수: {len(df)}건")
print(df['risk_level'].value_counts())
```

## 3. SQL 쿼리 예시(BI Tool용)

Grafana, Tableau 등에서 직접 쿼리할 때 사용

### 일별 유출 건수
```sql
SELECT 
  DATE_TRUNC('day', posted_at) as date,
  COUNT(*) as leak_count
FROM darkweb_leaks
WHERE posted_at >= NOW() - INTERVAL '30 days' -- 최근 30일
GROUP BY date
ORDER BY date DESC;
```

### 위험도별 분포
```sql
SELECT 
  risk_level, 
  COUNT(*) as count
FROM darkweb_leaks
GROUP BY risk_level;
```

### 가장 많이 탐지된 키워드
```sql
SELECT 
  keyword, 
  COUNT(*) as freq
FROM darkweb_leaks, UNNEST(matched_keywords) as keyword
GROUP BY keyword
ORDER BY freq DESC
LIMIT 10;
```