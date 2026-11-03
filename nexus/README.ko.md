# NEXUS 서버

[English](README.md)

NEXUS 서버는 CORTHEX 프로젝트 허브를 내 주소에 올려, 어느 기기에서든 열 수 있게 합니다. Cloudflare Worker로 돌아가며, `hub.py push`가 보낸 스냅샷을 Cloudflare D1 데이터베이스에 두고 `corthex-nexus`가 내 컴퓨터에서 만드는 것과 같은 페이지를 보여 줍니다. 내 Cloudflare 계정에서 돌고, 누가 열 수 있는지는 Cloudflare Access가 정합니다.

이 폴더는 플러그인이 아닙니다. 이 저장소를 내려받은 사본에서 배포합니다.

## 무엇을 두고 누가 보는가

- **스냅샷만 둡니다.** 프로젝트마다 한 줄에 `hub.py push`가 보낸 스냅샷을 둡니다. ID, 제목, 상태, 점검 결과, 파일 위치, 커밋 ID만 있고, 그 밖의 파일 내용이나 내 컴퓨터의 경로는 없습니다([형식](../plugins/corthex-nexus/skills/corthex-hub/references/snapshot.md)). 같은 프로젝트를 다시 보내면 그 줄을 바꿉니다. 그 밖에는 아무것도 두지 않고, 저장된 글을 로그에 남기지 않습니다.
- **Access가 먼저입니다.** Worker는 Cloudflare Access가 확인한 요청에만 답합니다. 다른 요청은 모두 `403`을 받고 데이터를 보지 못하므로, Access를 설정하기 전에 배포해도 아무것도 보이지 않습니다.
- **주소는 하나입니다.** 내가 정한 주소에서만 열립니다. `workers.dev` 주소나 미리보기 주소가 없고, 정적 자산도 쓰지 않습니다. 정적 자산을 쓰면 Worker가 Access 확인 결과를 받지 못합니다.
- **아무것도 불러오지 않는 페이지입니다.** 페이지는 데이터를 안에 담고 네트워크에서 아무것도 불러오지 않습니다. 해시로 허용한 자기 스크립트만 돌리고, 다른 사이트는 이 페이지를 틀 안에 넣을 수도, 서버에 둔 내용을 바꿀 수도 없습니다.

## 필요한 것

- 도메인을 올려 둔 Cloudflare 계정과 Cloudflare Zero Trust 설정. Zero Trust Free 요금제로 충분하지만, 설정할 때 결제 정보를 넣어야 합니다.
- Node.js 22.13 이상과 이 저장소를 내려받은 사본.
- 스냅샷을 보내는 컴퓨터마다 설치한 `corthex-nexus`.

## 설정

1. 도구 설치: 이 폴더에서 `npm install`을 실행합니다.
2. 내 설정 파일 만들기: `wrangler.jsonc`를 `wrangler.local.jsonc`로 복사합니다. 이 사본은 git이 무시합니다. 사본의 `routes`에 내 계정에 있는 도메인의 주소, 예를 들어 `nexus.example.com`을 적고, 한국어 페이지를 원하면 `NEXUS_LANGUAGE`를 `ko`로 바꿉니다.
3. 배포: `npx wrangler login`을 실행한 뒤 `npm run deploy`를 실행합니다. 첫 배포 때 D1 데이터베이스 `corthex-nexus`가 만들어져 Worker에 연결됩니다. 터미널에서 실행하면 그 ID가 내 설정 파일에도 적히고, 적히지 않아도 다음 배포는 같은 데이터베이스를 씁니다. 이어서 Cloudflare가 주소의 DNS 레코드와 인증서를 더합니다. 예전 서비스 등이 남긴 DNS 레코드가 주소에 이미 있으면 Cloudflare가 그 위에 Worker의 레코드를 만들지 않습니다. 필요하면 그 값을 적어 두고, 대시보드의 내 도메인 **DNS** › **Records**에서 지운 뒤 다시 배포합니다. 다음 단계를 마칠 때까지 주소는 `403`으로 답합니다.
4. Access로 보호하기: Cloudflare 대시보드에서 **Workers & Pages**로 가서 `corthex-nexus`를 고르고, **Access** 탭에서 **Protect this Worker behind Access**를 누릅니다. **All traffic**을 고르고, 로그인할 수 있는 사람을 정한 뒤(나 혼자라면 **Cloudflare account**) **Apply Access**를 누릅니다. **Zero Trust** › **Access controls** › **Applications**에 이 주소의 Access 애플리케이션이 이미 있으면, 그것이 Worker 단위 Access보다 먼저 적용되어 이미 허브를 보호합니다. 그 정책이 원하는 사람만 들이는지 확인하고 이 단계는 건너뜁니다.
5. 확인 전에 애플리케이션을 고정합니다. 로컬 `vars`에서 빈 `ACCESS_AUD` 자리를 지운 뒤 `npx wrangler secret put ACCESS_AUD -c wrangler.local.jsonc`를 실행해 입력 프롬프트에 그 애플리케이션의 **Application Audience (AUD) Tag**를 넣습니다. 로컬 파일의 `vars`에는 `ACCESS_TEAM_DOMAIN`으로 팀 호스트(예: `your-team.cloudflareaccess.com`)를 적고 다시 배포합니다. 시크릿 창에서 열면 Access 로그인이 먼저 나오고 빈 허브 페이지가 나옵니다.
6. `hub.py`용 서비스 토큰 만들기: **Zero Trust** › **Access controls** › **Service credentials** › **Service Tokens**에서 토큰을 만들고 Client ID와 Client Secret을 복사합니다. Secret은 이때 한 번만 보입니다. 그다음 **Zero Trust** › **Access controls** › **Applications**에서 허브를 보호하는 Access 애플리케이션, 곧 4단계에서 만든 것이나 주소에 이미 있던 것을 열고, 동작이 **Service Auth**이고 이 토큰을 포함하는 정책을 더합니다. 같은 Worker에 애플리케이션을 하나 더 만들면 서로 부딪칠 수 있으니, 기존 애플리케이션에 더합니다.
7. 스냅샷을 보내는 컴퓨터마다 `~/.corthex/profile.json`에 주소와 보내도 되는 프로젝트를 적습니다.

   ```json
   { "nexus": { "url": "https://nexus.example.com", "push": ["acme-shop"] } }
   ```

   토큰은 시스템의 비밀값 저장소에서 환경 변수 `CORTHEX_NEXUS_CLIENT_ID`와 `CORTHEX_NEXUS_CLIENT_SECRET`으로 넣고, 저장소 안의 파일에는 절대 적지 않습니다. 그다음 `hub.py push --dry-run`을 실행하고, `hub.py push`를 실행합니다.

0.2에서는 `ACCESS_AUD`와 `ACCESS_TEAM_DOMAIN`이 필수입니다. audience 태그는 쉼표로 나눠 여러 개를 넣을 수 있습니다. Worker는 `ctx.access`를 확인한 뒤 설정한 팀의 공개 키로 헤더 토큰의 RS256 서명·발급자·audience·만료를 검증합니다. 설정이 빠지면 접근을 허용하지 않습니다. 쓴 쪽의 종류만 남기며 사람이나 서비스 신원은 보관하지 않습니다.

대시보드 메뉴 이름은 2026년 10월 Cloudflare 문서를 따랐습니다: [Workers용 Cloudflare Access](https://developers.cloudflare.com/workers/configuration/cloudflare-access/), [Custom Domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/), [서비스 토큰](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/), [Zero Trust 설정](https://developers.cloudflare.com/cloudflare-one/setup/).

## 쓰기

- `hub.py push`는 `nexus.push`의 프로젝트를 보냅니다. 프로젝트 이름을 주면 그것만 보냅니다. 서버는 프로젝트마다 더 새 스냅샷을 둡니다. 저장된 것보다 먼저 만든 스냅샷은 거절하니, 다시 만들어 보내세요.
- `hub.py remove <프로젝트>`는 서버에서 프로젝트를 지웁니다. `nexus.push`에서 프로젝트를 빼면 그 뒤로 보내지 않을 뿐, 서버에 둔 것은 남습니다.
- 로그인한 상태에서 `/api/snapshots`를 열면 서버에 둔 목록이 보입니다.

## 한도

- 스냅샷 하나는 1MiB까지(`hub.py`는 1MB 아래로 만듭니다), 프로젝트는 30개까지입니다. 10분 넘게 미래 시각이 적힌 스냅샷은 거절합니다. 그 스냅샷을 만든 컴퓨터의 시계를 확인하세요.
- Workers Free 요금제에서는 요청 하나에 CPU 시간 10ms를 씁니다. 항목 92개인 실제 프로젝트 크기, 약 40KB의 스냅샷은 Node로 로컬에서 재 보니 검사에 1ms가 안 걸렸고, 1MB에 가까운 것은 약 15ms가 걸려 한도를 넘을 수 있습니다.
- D1 무료 요금제에는 하루에 읽고 쓰는 행 수 한도가 있지만, 개인 허브는 그보다 훨씬 적게 씁니다. 현재 한도는 Cloudflare의 [Workers 한도](https://developers.cloudflare.com/workers/platform/limits/)와 [D1 한도](https://developers.cloudflare.com/d1/platform/limits/)에서 확인하세요.

## 이 컴퓨터에서 먼저 해 보기

- `npm test`는 메모리 안의 데이터베이스로 서버 검사를 Node 자체 테스트 도구로 돌립니다.
- 로컬 HTTP 대역은 `node test/serve.js`로 실행합니다. 가상 토큰에 서명하고 메모리 SQLite를 쓰며, 출력한 `127.0.0.1` 주소로 허브를 연결할 수 있습니다. `npm run dev`는 서명된 Access 토큰을 만들지 않습니다. 0.2에서 `ctx.access`의 audience 대역만으로 인증되지 않습니다. Workers 실행 환경은 별도 Access·D1·서비스 토큰을 갖춘 개발 Worker에서 확인합니다.

## 갱신과 제거

- 갱신하려면 저장소를 받아 온 뒤 `wrangler.jsonc`를 내 사본과 비교하고, `npm install`과 `npm run deploy`를 실행합니다.
- 없애려면 `npx wrangler delete -c wrangler.local.jsonc`로 Worker를, `npx wrangler d1 delete corthex-nexus`로 데이터베이스와 스냅샷을 지웁니다. 그다음 **Zero Trust** › **Access controls**에서 Access 애플리케이션과 서비스 토큰을 지웁니다.
