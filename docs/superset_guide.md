# Superset 사용가이드

이 문서는 Superset에 새 대시보드나 차트를 추가할 때 참고하는 가이드입니다.

---

## 1. 시작하기

접속정보는 디코 주요정보 메뉴 확인 

<br></br>

<img width="1667" height="491" alt="image" src="https://github.com/user-attachments/assets/6d8e5ea6-ac6f-4373-bcbd-4badf52e8788" />



- 최종 대시보드는 하나로 통합될 예정
- 차트는 자유롭게 대시보드에 추가할 수 있으니 개별 대시보드 생성 후 작업해도 상관 없음

---

## 2. 대시보드 생성

<img width="135" height="60" alt="image" src="https://github.com/user-attachments/assets/0fc7fb7c-fbbc-4f15-bf8c-3dd58b0bc007" />

- `+ Dashboard` 로 새 대시보드 생성
 <br></br>
 
<img width="265" height="82" alt="image" src="https://github.com/user-attachments/assets/b66eda35-7516-41b4-b346-efc81ba4640e" />

- 대시보드 이름 수정

<br></br>

<img width="653" height="531" alt="image" src="https://github.com/user-attachments/assets/bd443dfe-fa80-453f-aa60-e2d292a2293f" />

- `+ Create a new chart` 로 새 차트(카드) 생성 
---

## 3. 차트 생성

<img width="1096" height="731" alt="image" src="https://github.com/user-attachments/assets/8220c86e-9a1d-4f9f-ae2e-8ae6bc856fba" />

- dataset : `darkweb_leaks` 선택
- 아래 차트 타입은 적절한 타입 선택

<br></br>

<img width="613" height="1108" alt="image" src="https://github.com/user-attachments/assets/a3f7bd2d-f8c3-40c5-bc7a-e94543090e74" />

- 차트 이름 설정 : 어떤 데이터를 정제하고 싶었는지 알아보기 쉽게!
- `X-axis` : 가로축
- `Metrics` : 세로축. 출력할 값 (`COUNT(*)` 을 사용하면 총함)

<img width="289" height="55" alt="image" src="https://github.com/user-attachments/assets/c1cd421b-fa71-40ff-b371-ff7a739b4990" />

- `Filter` : 필터 값. 위와 같은 형태면 `source` 가 `BestCardingWorld` 인 항목 내에서만
- `Create/Update chart` : 값이 변경되면 해당 버튼 눌러줘야 차트 갱신 


<br></br>

<img width="613" height="403" alt="image" src="https://github.com/user-attachments/assets/3812e5a0-ba10-419d-a311-80bffde6310d" />

- `Chart name` : 차트 이름 확인
- `Add to dashboard` : 내가 업로드할 대시보드 확인 
