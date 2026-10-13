# Bắt đầu với Kubernetes Security Remediation Agent

Bạn đang xây một chương trình chọn cách sửa cấu hình bảo mật, dùng kết quả kiểm thử để điều tra tiếp, rồi tạo bản sửa cho người xem lại. Mục tiêu đầu tiên là hiểu một vòng sửa có thể chạy lại được: **sửa bảo mật và giữ ứng dụng hoạt động**.

Bản khởi đầu này dùng Python 3.10 trở lên và thư viện chuẩn. Bạn có thể học vòng xử lý mà chưa cần cluster, GPU hoặc API key. Các lệnh dưới đây chạy từ `/home/ngocnt/agents/kube-security-remediation`.

## 1. Chạy bản minh họa trước

```bash
cd path/to/agent
PYTHONPATH=src python3 -m kube_repair list
PYTHONPATH=src python3 -m kube_repair demo --output runs/first-demo
```

`demo` sử dụng provider `scripted` và backend `simulated`: quyết định được viết bằng Python; kiểm thử mô phỏng các điều kiện của fixture. Kết quả giúp bạn hiểu kiến trúc và quan sát lỗi. Kết quả này chưa chứng minh chất lượng LLM hoặc bảo mật của container đang chạy.

Mở `runs/first-demo/SUMMARY.md` để xem bảng so sánh. Các bundle nằm trong `runs/first-demo/<scenario>/<strategy>/`.

| Kịch bản | Điều cần học |
|---|---|
| `cache-path` | Bật chế độ non-root và filesystem chỉ đọc có thể làm thao tác ghi cache thất bại; cần tìm đúng đường dẫn và cấp vùng ghi phù hợp. |
| `volume-permissions` | Có volume chưa đủ; user/group và quyền ghi còn phải tương thích. |
| `authority-limit` | Một yêu cầu ứng dụng không thể được đáp ứng bằng các thay đổi đang được phép; dừng có lý do là kết quả cần thiết. |
| `already-secure` | Cấu hình đã đáp ứng yêu cầu không cần bị sửa thêm. |

Mỗi lượt tạo một thư mục mới; khi chạy lại, đổi tên output để giữ nguyên bằng chứng lượt trước. Trong mỗi bundle, đọc:

| File | Nội dung cần xem |
|---|---|
| `REVIEW.md` | Trạng thái, provider, backend và mức kiểm chứng. |
| `report.json` | Kết quả kiểm tra, ngân sách, lý do kết thúc và metadata provider. |
| `trace.json` | Thứ tự điều tra, đề xuất, từ chối và kiểm thử. |
| `base.json`, `candidate.json`, `patch.diff` | Manifest ban đầu, manifest được chấp nhận và thay đổi cụ thể. Lượt thất bại giữ manifest gốc ở `candidate.json`; đề xuất thất bại nằm trong trace. |
| `contract.json`, `binding.json` | Contract và hash gắn nội dung bundle với phiên bản source/fixture. |

Với từng lần sửa, hãy trả lời: lỗi nào được verifier trả về, evidence nào được đọc sau đó, bản sửa thay đổi gì, và kiểm thử nào xác nhận nó?

## 2. So sánh với cách sửa đơn giản

Chạy cùng một kịch bản với các cách sửa cố định:

```bash
PYTHONPATH=src python3 -m kube_repair baseline \
  --scenario cache-path --strategy noop --output runs/cache-noop

PYTHONPATH=src python3 -m kube_repair baseline \
  --scenario cache-path --strategy naive --output runs/cache-naive

PYTHONPATH=src python3 -m kube_repair baseline \
  --scenario cache-path --strategy template --output runs/cache-template

PYTHONPATH=src python3 -m kube_repair baseline \
  --scenario cache-path --strategy known-good --output runs/cache-control
```

`noop` giữ cấu hình ban đầu. `naive` chỉ thêm các trường hardening. `template` dùng quy tắc sửa cố định. `known-good` là đối chứng do tác giả fixture xây dựng từ contract; không phải mô hình phát hiện lời giải. Bạn cần cả đối chứng đúng và đối chứng sai để kiểm tra evaluator có phân biệt được chúng.

Đừng dùng việc hết cảnh báo làm tiêu chí duy nhất. Theo yêu cầu của bài toán, một bản sửa cần được phép, đạt các kiểm tra bảo mật đã chọn và giữ các hành vi ứng dụng được quy định. Bộ kiểm thử vẫn chỉ bao phủ phạm vi đã khai báo.

## 3. Hiểu “agentic” nằm ở đâu

Một workflow cố định có thể luôn làm: đọc image → thêm security context → thêm volume → kiểm thử. Một agent dùng trạng thái hiện tại để quyết định **đọc gì tiếp, thử bản sửa nào, hiểu lỗi ra sao và khi nào dừng**.

Trong project này, provider trả về một action JSON trong tập hữu hạn:

| Action | Ý nghĩa |
|---|---|
| `inspect` | Đọc một nguồn được cho phép: `image`, `app` hoặc `repository`. |
| `propose` | Đưa ra manifest ứng viên và lý do. |
| `test` | Yêu cầu kiểm thử lại ứng viên hiện tại. |
| `finish` | Đề nghị kết thúc. Engine vẫn kiểm tra kết quả thật. |
| `abstain` | Giải thích vì sao chưa thể sửa trong quyền hạn/ngân sách hiện có. |

Engine giữ lịch sử và ngân sách, kiểm tra phạm vi thay đổi, chạy verifier và tạo artifact. Provider nhận kết quả kiểm thử có nguồn gốc từ engine; một câu “tests passed” trong tài liệu repository không thay thế được kết quả này. Model không có tool chạy shell tùy ý.

`ScriptedProvider` là bộ điều khiển viết tay để dạy vòng phản hồi. Nó cho thấy nhánh xử lý và giao diện tool, nhưng không phải bằng chứng rằng AI đã tự tìm ra cách sửa. `OllamaProvider` cho phép một LLM lựa chọn các action qua cùng giao diện. Có LLM cũng chưa tự chứng minh rằng vòng lặp tốt hơn template; việc đó cần thí nghiệm.

## 4. Thử tài liệu gây nhiễu

```bash
PYTHONPATH=src python3 -m kube_repair run \
  --scenario cache-path --backend simulated --provider scripted \
  --attacked --output runs/cache-attacked
```

So sánh với bản sạch:

```bash
PYTHONPATH=src python3 -m kube_repair run \
  --scenario cache-path --backend simulated --provider scripted \
  --output runs/cache-clean
```

Tài liệu repository là evidence không đáng tin. Nó có thể chứa lời yêu cầu bỏ qua policy hoặc giả mạo kết quả. Lệnh `--attacked` đưa nội dung như vậy vào fixture để kiểm tra ranh giới đọc và sửa. Provider viết tay không có tính dễ bị prompt injection như một LLM; lượt chạy này là đối chứng kiểm tra harness, chưa phải đánh giá khả năng kháng prompt injection của model.

Đọc trace để xác nhận nguồn repository có thực sự được đọc hay không. Một cuộc tấn công chưa được model nhìn thấy không kiểm tra được tác động của nội dung đó.

## 5. Kết nối LLM khi bạn đã hiểu trace

Nếu bạn đã có Ollama chạy ở máy và model đã có sẵn, thay provider:

```bash
PYTHONPATH=src python3 -m kube_repair run \
  --scenario cache-path --backend simulated --provider ollama \
  --model YOUR_LOCAL_MODEL --output runs/cache-llm
```

Thay `YOUR_LOCAL_MODEL` bằng tên model trên máy bạn. Lệnh gọi Ollama qua HTTP cục bộ. Starter không tự tải model hay khởi động server. Nếu dịch vụ/model chưa sẵn sàng, lỗi kết nối cần được sửa trước khi diễn giải kết quả agent. Giao thức chat được mô tả trong [Ollama API chat](https://docs.ollama.com/api/chat).

Đây là **quyết định do LLM tạo + kiểm thử mô phỏng**. Muốn kiểm chứng hành vi container, bạn cần backend runtime riêng.

| Provider | Backend | Điều một lượt chạy thực sự kiểm tra |
|---|---|---|
| `scripted` | `simulated` | Vòng điều khiển viết tay, policy và mô hình fixture. |
| `ollama` | `simulated` | LLM chọn action trong lab mô phỏng. |
| `scripted` | `docker` | Bộ điều khiển viết tay với fixture container thật. |
| `ollama` | `docker` | LLM chọn action, bản sửa được thử trên fixture container thật. |

Backend Docker là bước kiểm chứng container. Nó chưa kiểm tra admission, scheduler, CSI hoặc cách `fsGroup` được áp dụng trong cluster Kubernetes. Các thuộc tính Pod/container và quyền volume cần được hiểu theo [tài liệu Kubernetes security context](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/).

Khi Docker đã sẵn sàng và base image `python:3.12-slim` đã có cục bộ, bạn có thể tự build fixture và chạy:

```bash
docker image inspect python:3.12-slim
docker build --pull=false --network=none \
  -t repair-cache-app:lab fixtures/cache_app
PYTHONPATH=src python3 -m kube_repair run \
  --scenario cache-path --backend docker --provider scripted \
  --image repair-cache-app:lab --output runs/cache-docker
```

Nếu lệnh inspect cho biết thiếu base image, dừng ở đây và chuẩn bị môi trường Docker riêng trước. Build phía trên giả định base đã tồn tại. Chỉ dùng image fixture bạn tin cậy và đã kiểm tra code; executable `python` và ứng dụng trong image là một phần của nền tảng kiểm thử. Backend pin image cục bộ theo ID khi chạy, không tự deploy cluster. Quyền khởi chạy container thuộc runner, và không được đưa Docker socket cho model. Xem [Docker run](https://docs.docker.com/engine/containers/run/) để hiểu các giới hạn runtime.

Probe Docker kiểm tra HTTP health, kết quả SHA-256, dữ liệu cache, UID, capabilities, no-new-privileges, seccomp ở chế độ filter và việc ghi root filesystem bị từ chối. Probe seccomp xác nhận filter hoạt động, chưa xác thực nội dung profile là đúng một profile Kubernetes cụ thể.

## 6. Xem lại và xuất bản sửa cục bộ

Sau một lượt sửa thành công, đọc bundle:

```bash
PYTHONPATH=src python3 -m kube_repair review --bundle runs/cache-clean
```

Kiểm tra manifest gốc, bản sửa, diff và kết quả verifier. Lấy hash do `review` hiển thị, rồi dùng chính hash đó:

```bash
PYTHONPATH=src python3 -m kube_repair export \
  --bundle runs/cache-clean --output runs/cache-export \
  --expected-hash HASH_FROM_REVIEW
```

Lệnh chỉ xuất artifact ra một thư mục mới trên máy; không tạo PR và không deploy. Lượt failed/abstained không thể được xuất thành bản sửa. Hash giúp phát hiện artifact hoặc source/fixture thay đổi giữa lúc chạy, lúc xem và lúc xuất. Bundle được đánh dấu đã xuất để tránh dùng lại lần review đó. Nếu bạn sửa source rồi gặp lỗi version binding, chạy lại task và review bundle mới.

Đây là kiểm tra tính nhất quán của bundle, chưa phải chữ ký xác thực danh tính người duyệt hay hệ thống approval cho production. Khi cần đối chiếu manifest gốc đang có trên máy, dùng tùy chọn `--base PATH_TO_BASE.json` của lệnh export. Starter chưa có trạng thái branch hoặc cluster live để xác thực.

## 7. Thứ tự học và mở rộng

1. **Buổi đầu:** chạy demo và giải thích được vì sao bản hardening đơn giản làm cache hỏng. Đọc [đánh giá đề tài](TOPIC_REVIEW_VI.md).
2. **Vài buổi tiếp:** đọc `scenarios.py`, `policy.py`, `verification.py`, `providers.py`, `engine.py` theo thứ tự. Theo dấu một action từ provider đến verifier và output.
3. **Sau khi hiểu contract:** thêm một fixture khác mà cách sửa cũ không giải được; viết đối chứng đúng, đối chứng sai và kiểm thử hành vi trước khi điều chỉnh provider.
4. **Sau đó:** chạy một local LLM, lưu model/settings và phân tích những quyết định sai. So sánh với template trên cùng task và ngân sách.
5. **Khi vòng container ổn định:** thử runtime Docker, rồi một cluster Kubernetes dùng riêng cho lab. Làm rõ những khác biệt runtime trước khi kết luận về Kubernetes.
6. **Khi evaluator đủ tin cậy:** xây workload độc lập, chia development/held-out và đo hiệu quả của feedback. Kế hoạch dài hạn ở gói chiến lược đã lưu trên workspace local: `/home/ngocnt/outputs/agent-long-term-strategy-2026-10-13/README.md`.

Bạn chưa cần LangChain, nhiều agent hay fine-tuning để bắt đầu. Giá trị đầu tiên là một vòng sửa nhỏ mà bạn hiểu, có lỗi có thể tái hiện, có giới hạn quyền rõ ràng và có bằng chứng để người khác xem lại.
