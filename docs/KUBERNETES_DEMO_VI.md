# Demo LLM chọn bản sửa và kiểm thử trên Kubernetes

Workflow hiện tại dùng **LLM thật qua Ollama để chọn action**, rồi chạy fixture và kiểm thử bảo mật/chức năng trên Kubernetes thật. Source nằm trên nhánh `kube-remediation-demo` của repo riêng [`tuanngocfun/agent`](https://github.com/tuanngocfun/agent).

Launcher chọn **Qwen2.5-3B-Instruct được pin**, với **guided decoding compact-schema** và completion do trusted engine kiểm soát. [Run 38528564033](https://github.com/tuanngocfun/agent/actions/runs/38528564033) đã hoàn tất thành công; artifact tải về đã qua [audit cục bộ](../evidence/llm-kubernetes-2026-10-14/audit.json). Source là `d770c0efea239754e221606a8f76ff16fcc5aedb`, với 139 kiểm thử đầy đủ đã qua.

Model trả về **một proposal, tạo một repair và hai lượt test**: cấu hình ban đầu và candidate. Cả 14 protected checks đều đạt; [report cuối](../evidence/llm-kubernetes-2026-10-14/reports/kubernetes/results/agent/report.json) ghi `accepted: true`, `status: repaired` và actor hoàn tất là `trusted_engine`. Ollama báo 2.205 prompt token cộng 197 completion token, tổng 2.402 cho lần gọi repair. Lượt này không cần inspect hay sửa lại proposal; nó chứng minh một bản sửa có hướng dẫn, chưa phải benchmark về lợi ích của feedback thích nghi. [Bản ghi kết quả](REAL_LLM_KUBERNETES_RESULT_VI.md) liên kết raw response, patch và audit. Kubernetes/Ollama chạy trên worker Actions tạm thời; không khởi động cluster hoặc model service trên workstation ban đầu.

[Lượt scripted đã thành công](https://github.com/tuanngocfun/agent/actions/runs/38408621533) được giữ riêng trong [bản ghi lịch sử](REAL_KUBERNETES_RESULT_VI.md). Lượt model trước đó có candidate pass nhưng kết thúc `accepted: false`; lịch sử phía dưới vẫn ghi đúng thất bại đó.

## Mở job và đọc bằng chứng

Mở [Actions](https://github.com/tuanngocfun/agent/actions), chọn **Real LLM Kubernetes remediation demo** và kiểm tra commit của lượt chạy. Bước cần xem là **Run pinned CPU LLM with protected Kubernetes tests**. Workflow nằm ở [.github/workflows/kubernetes-demo.yml](../.github/workflows/kubernetes-demo.yml).

Để chạy lại đúng commit đã ghi, mở một run hoàn tất rồi chọn **Re-run all jobs**; rerun dùng commit/ref của lượt gốc. Muốn kiểm tra source mới, push lên nhánh `kube-remediation-demo`. Xem [hướng dẫn rerun của GitHub](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs). Workflow hiện nằm trên nhánh demo, còn `main` chỉ có bootstrap. GitHub yêu cầu workflow file nằm trên default branch để dùng `workflow_dispatch`, nên không thể hứa nút **Run workflow** có sẵn với bố cục hiện tại. [Tài liệu GitHub về chạy workflow thủ công](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)

Tải artifact **`real-llm-kubernetes-evidence`**. Artifact được upload cả khi job lỗi, nên hãy kiểm tra nội dung:

1. `summary.json`: launcher LLM có `status: passed` hay lỗi gì?
2. `kubernetes/summary.json`: các control và agent có đạt điều kiện của demo không?
3. `model-pin.json`: đúng model/digest/settings không; before/after có nhất quán và VRAM bằng 0 không?
4. `kubernetes/results/agent/report.json`: `backend: kubernetes`, `runtime_verified: true`, `accepted: true`, provider `ollama`, `uses_llm: true` và model revision được ghi lại.
5. `provider.inference_calls` trong report: đọc `raw_server_response`, `action`, `reported_usage`, hashes và trạng thái của từng lượt suy luận.
6. `trace.json`, `patch.diff`, `REVIEW.md`: nối action do model trả về với evidence đã đọc, proposal, policy và kết quả verifier.

Kết quả test do runner quyết định. Câu “tests passed” trong raw response của model không thay thế được probe Kubernetes. Launcher không chuyển sang bộ sửa viết tay để tạo kết quả thành công.

Engine chỉ cho model thử lại khi adapter tin cậy báo `ProviderError.invalid_action`, trong action budget hiện có. Trace ghi `rejected_provider_output`; observation có nhãn `trusted_protocol` đưa lỗi validation về cho lần gọi sau. Output bị chặn không chạy tool, không đổi manifest, không chạy test và không tính vào candidate-repair budget; ngân sách model-call/action vẫn bị tiêu thụ. Lỗi transport, identity và các lỗi provider khác dừng vòng. Model phải tự sinh action hợp lệ tiếp theo; engine không sửa output hoặc áp dụng bản sửa bằng quy tắc thay model.

Trong lúc job chạy, log Actions hiển thị ngay các dòng stage/counter như `Agent progress: stage=before_model_call ... current_verified_pass=false`; wrapper truyền output này trực tiếp. Nếu lượt bị ngắt trước khi có bundle cuối, đọc `kubernetes/results/agent-progress.json` để xem bằng chứng còn giữ được.

## Model và môi trường của workflow

[llm_kubernetes_demo.py](../scripts/llm_kubernetes_demo.py) chọn Qwen2.5-3B-Instruct tổng quát, `qwen2.5:3b-instruct-q4_K_M`, khoảng 1,93 GB, chạy Ollama `0.6.8` trong image Docker được pin theo digest. Script kiểm tra manifest digest model và SHA256 của layer GGUF đã tải, rồi kiểm tra lại model identity sau vòng sửa. Checkpoint 3B này dùng [Qwen Research License](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct); weights không được đưa vào repository hoặc artifact.

Inference chạy bằng CPU: hai thread, context 8192, temperature 0, tối đa 512 output token và deadline 420 giây cho mỗi lần gọi action. Script kiểm tra `/api/ps` để xác nhận không có VRAM được dùng. Server chỉ mở trên loopback của worker. Model container tự dùng UID:GID của worker, `HOME=/tmp` và cache mount `/tmp/.ollama`; bạn không cần đổi quyền cache bằng tay. Image server, node Kubernetes v1.34.0 và Python base đều có digest cố định trong script. Các lựa chọn này nhằm tái hiện demo, không phải tuyên bố dùng phiên bản mới nhất hoặc model tốt nhất.

Provider hiện dùng **compact-schema**, với system guide 2.273 byte và generation schema 1.745 byte. Schema có ba dạng: inspect, propose bằng `changes`, và test/finish/abstain. Nó ràng buộc envelope action và yêu cầu đủ bảy trường securityContext khi nhóm này xuất hiện; chế độ này không sinh proposal là manifest đầy đủ. Schema cung cấp tên trường và các cấu trúc control/storage được phép, gồm drop ALL và RuntimeDefault. UID/GID vẫn do model sinh dưới dạng integer dương, không có identity đích hoặc defaults được engine chèn vào. Boolean và mount path cũng do model sinh, rồi chịu kiểm tra policy.

Đây là **guided typed decoding**: kết quả phản ánh model cùng phần hướng dẫn protocol, chưa chứng minh khả năng làm đúng chỉ dẫn không bị ràng buộc. Validator Python, policy, backend và cả 14 acceptance checks vẫn giữ nguyên. CLI còn cho chọn `--decoding-mode json|schema|compact-schema`, mặc định `json`; wrapper pin chọn rõ compact-schema và đối chiếu mode thực tế trong report. Chế độ `schema` cũ dùng action schema đầy đủ; JSON mode chỉ ràng buộc cú pháp JSON trước bước validation action.

Guide giải thích rõ: manifest ban đầu và proposal hợp lệ đều tự được kiểm thử; `inspect` chỉ đọc evidence; `test` chạy lại cấu hình hiện tại mà không thay đổi nó. Sau một lỗi có thể tái hiện, agent cần điều tra hoặc đề xuất thay đổi để sửa; gọi `test` nhiều lần không tự áp dụng bản sửa. Task ghi `required_security_controls` với `runAsUser`/`runAsGroup` từ contract—10001 cho fixture này. Names/labels/selectors và identity của workload được bảo vệ; thay process UID/GID theo task được phép. Non-root, root filesystem chỉ đọc, không privilege escalation, drop ALL capabilities và RuntimeDefault seccomp vẫn bắt buộc.

Launcher yêu cầu smoke test sinh câu trả lời ngắn với completion token thực tế trước vòng sửa. Response JSON đơn giản này kiểm tra generation, chưa kiểm tra đầy đủ protocol repair. Warm-up rỗng có thể trả 0 token, nên load model thành công chưa chứng minh inference hoạt động.

Proposal từng phần trong `changes.securityContext` merge các trường model đưa ra vào cấu hình hiện có; trường bị bỏ qua giữ nguyên giá trị. Bật `runAsNonRoot` kiểm tra user đã chọn, không tự chọn UID. Nếu `runAsUser` hiện là 0, model phải ghi rõ `runAsUser` và `runAsGroup` được task cho phép. Engine chỉ áp dụng trường do model viết, không tự thêm các giá trị đích; điều kiện chấp nhận vẫn giữ nguyên.

Context vẫn giữ task, manifest, evidence đã đọc, đầy đủ observation của lần kiểm thử đáng tin mới nhất và feedback từ policy. Bản sao kết quả test mới nhất trong history được thay bằng tham chiếu tới observation đó; các manifest/evidence lặp lại được hash và kết quả test cũ được tóm tắt. Artifact ghi rõ những bước compact này để người xem kiểm tra.

`model-pin.json` ghi manifest digest `357c53fb659c…` và GGUF layer digest `5ee4f07cdb9b…`; giá trị SHA256 đầy đủ nằm trong script và artifact để đối chiếu. Smoke test chỉ kiểm tra model sinh được câu trả lời; nó chưa chứng minh sửa Kubernetes đúng.

Artifact `inference-smoke.json` lưu response của phép thử ngắn với giới hạn 32 token và số completion token thực tế. Nếu phép thử này lỗi, chưa có vòng sửa LLM để đánh giá, dù weights đã được xác minh.

Worker GitHub Actions tải image/weights trong job tạm thời; không dùng shared GPU hoặc model service trên workstation ban đầu. Khi job kết thúc, worker và cache của nó được thu hồi. Nếu bạn chạy launcher trên máy riêng, cache nằm dưới `.tools/ollama-cache-*` và vẫn còn sau khi script dọn container.

Workflow có quyền repository chỉ đọc, job tối đa 40 phút và artifact giữ 7 ngày. Toàn tiến trình agent có giới hạn 1.800 giây; launcher kind bên ngoài có giới hạn 2.100 giây. Các giới hạn này khác với deadline 420 giây của từng action. Timeout vẫn là một lượt thất bại/chưa hoàn tất. Upload chỉ chọn report/bundle; không upload kubeconfig, weights hoặc raw cluster logs. [Hướng dẫn GitHub](GITHUB_KUBERNETES_DEMO.md) mô tả từng file bằng chứng.

## Bằng chứng từng bước khi lượt chưa kết thúc

CLI có tùy chọn `--progress-output PATH` cho một file mới; thư mục cha phải tồn tại. Launcher dùng đường dẫn `kubernetes/results/agent-progress.json`. File snapshot được thay thế atomically và giữ manifest, hash liên quan đến kết quả test, observations, trace, metadata provider với raw responses/actions, counters, snapshot hash và source fingerprint.

Snapshot chỉ giữ dữ liệu đã có ở lần ghi gần nhất. Một lần gọi model còn đang chờ khi timeout bên ngoài kết thúc tiến trình có thể chưa có response để lưu.

Snapshot luôn có `accepted: false`, `exportable: false`, kể cả snapshot ghi sau khi bundle cuối đã được tạo. Vì vậy stage `final_bundle_written` hoặc `current_verified_pass=true` trong log chưa phải bằng chứng cho phép export. Chỉ bundle review cuối có hash binding và trạng thái được engine chấp nhận mới dùng được trong workflow export. Snapshot giúp điều tra một lượt bị ngắt mà không tạo bản sửa được chấp nhận từ dữ liệu chưa hoàn tất.

## Vòng sửa và các đối chứng

[kind_demo.py](../scripts/kind_demo.py) dựng cluster riêng, kubeconfig riêng và xác định imageID thực tế của fixture. Docker config digest và CRI imageID không bị coi là cùng một giá trị. ImageID đã xác nhận được dùng làm pin khi kiểm thử từng ứng viên.

| Arm | Điều demo cần phân biệt |
|---|---|
| `noop` | HTTP/cache hoạt động nhưng các control bảo mật mục tiêu chưa đạt. |
| `naive` | Chỉ thêm hardening: cấu hình đạt, nhưng startup/cache thất bại. |
| `known-good` | Bản sửa đối chứng từ contract; phải giữ hành vi và đạt các probe. |
| `agent` với `ollama` | Model chọn bước điều tra/sửa dựa trên feedback; bản cuối cần qua cùng kiểm thử độc lập. |

Mỗi ứng viên dùng namespace mới. Backend kiểm tra identity/version của Deployment/ReplicaSet/Pod, imageID và UID/owner khi dọn namespace. Probe cố định kiểm tra HTTP health, kết quả SHA-256 độc lập, cache đọc lại/tái sử dụng, UID, root-filesystem write denial, no-new-privileges, capabilities và seccomp filter mode. Cluster do launcher tạo được dọn trước khi launcher báo thành công. [kind quick start](https://kind.sigs.k8s.io/docs/user/quick-start/) mô tả cluster và image loading.

## Dừng sau khi bản sửa được kiểm chứng

CLI và kind launcher có tùy chọn `--stop-on-verified-repair`, mặc định false; wrapper LLM pin bật rõ tùy chọn này. Engine chỉ kết thúc khi đã áp dụng proposal hợp lệ có thay đổi do model viết, verification độc lập mới nhất đạt mọi check, hash của manifest đã test khớp candidate hiện tại, không có lỗi hạ tầng và policy được kiểm tra lại vẫn hợp lệ.

Trace ghi `trusted_completion`, actor `trusted_engine`; report ghi `completion_policy: verified-repair`, `completion_actor: trusted_engine`. Không giả tạo action `finish` của LLM. Model vẫn là tác giả giá trị của bản sửa; engine quyết định hoàn tất theo bằng chứng kiểm thử.

Mặc định `model-finish` vẫn giữ nguyên. Workload đã an toàn từ đầu hoặc không thay đổi vẫn cần provider finish, kể cả khi có flag opt-in. Đây là sửa cách controller kết thúc: action `test`, ngân sách token/action, schema và cả 14 checks không bị đổi. Trace chứng minh model đã retest sau khi candidate pass; chưa chứng minh thứ tự enum là nguyên nhân gây lặp.

Demo hiện dùng Ollama được pin. Quyền Copilot Student của bạn chưa được khởi tạo hoặc gọi trong workflow này.

Backend chỉ nhận diện đúng thông báo kubelet `CreateContainerConfigError` từ chối candidate có `runAsNonRoot: true` và `runAsUser: 0` kiểu integer thành lỗi hành vi khởi động để model sửa tiếp. Các lỗi configuration không nhận diện được, lỗi image và hạ tầng khác vẫn dừng lượt. Nếu kubelet chặn startup trước khi có imageID, kiểm tra image identity/runtime không đạt; record không tuyên bố container đã thực thi hoặc image identity đã được xác minh.

Ở lượt đã audit, LLM đề xuất sửa đúng ngay, không inspect và không sửa lại sau một candidate thất bại. Đối chứng `naive` vẫn cho thấy regression cache; đánh giá ích lợi của feedback cần có thí nghiệm so sánh riêng.

## Chạy lại trên worker có Docker

Chuẩn bị Docker hoạt động và binary `kind`, `kubectl` đúng phiên bản. Launcher LLM phía dưới **tải image và weights**, khởi động model container, tạo cluster tạm thời rồi dọn chúng:

```bash
cd path/to/agent
python3 scripts/llm_kubernetes_demo.py --output runs/my-llm-kubernetes-demo
```

Output phải là thư mục mới. Đọc `summary.json`, `model-pin.json` và `kubernetes/results/agent/report.json` trước khi kết luận. Nếu có lỗi hạ tầng/model, giữ report và sửa điều kiện môi trường; không diễn giải lỗi thành kết quả repair.

Nếu worker đã có Ollama và model sẵn có, bạn có thể dùng launcher Kubernetes riêng. Script này yêu cầu base/node image đã có cục bộ và không tự tải model:

```bash
python3 scripts/kind_demo.py \
  --base-image python@sha256:YOUR_VERIFIED_LOCAL_DIGEST \
  --provider ollama --model YOUR_LOCAL_MODEL \
  --decoding-mode compact-schema \
  --stop-on-verified-repair \
  --endpoint http://localhost:11434 \
  --output runs/my-existing-model-demo
```

Node image mặc định được pin; cần chuẩn bị nó cục bộ trước. Ví dụ chọn compact-schema và verified-repair để khớp wrapper. Nếu bỏ `--decoding-mode`, CLI mặc định JSON mode; bỏ flag dừng thì cần provider finish. Bỏ `--provider ollama` sẽ dùng **`scripted`**, nên phải ghi đúng provider khi báo cáo. `--provider session --exchange-dir PATH` dùng [bridge của phiên assistant](SESSION_AGENT.md); quyết định đến từ tác nhân bên ngoài, không phải một local model tự chạy lại.

Với cluster lab đã có sẵn, backend cần context/kubeconfig và imageID từ bước setup tin cậy. Dùng CLI với `--backend kubernetes --kube-context ... --kubeconfig ... --image ... --expected-image-id ... --provider ollama --model ... --decoding-mode compact-schema --stop-on-verified-repair`; runner cần fixture image tại node và quyền tạo/xóa namespace. Đây là runner lab riêng; `volume-permissions` chưa được backend Kubernetes hỗ trợ.

## Bằng chứng trước đó và phạm vi kết luận

| Lượt/cấu hình đã ghi | Kết quả thực tế |
|---|---|
| [Kubernetes scripted](https://github.com/tuanngocfun/agent/actions/runs/38408621533), commit `44613880014ca56882f0a21e5de461db97941b50` | Runtime repair đạt bằng quy tắc viết tay; tách khỏi bằng chứng LLM. |
| Qwen2.5-Coder: [1.5B](https://github.com/tuanngocfun/agent/actions/runs/38449404110), [3B thiếu UID](https://github.com/tuanngocfun/agent/actions/runs/38456111385), [3B hết repair budget](https://github.com/tuanngocfun/agent/actions/runs/38498086650) | Có response model thật; proposal thiếu control/identity cần thiết và không được chấp nhận. Các lượt CPU/schema sớm hơn cũng bị timeout. |
| [Qwen2.5 tổng quát, JSON mode](https://github.com/tuanngocfun/agent/actions/runs/38500479314) | Mười hai response sai envelope; không có repair, chỉ test ban đầu, 33.961 token báo cáo. Không áp dụng bản sửa. |
| [Qwen2.5 tổng quát, compact-schema](https://github.com/tuanngocfun/agent/actions/runs/38502780956), commit `59e0e9fab8fd51a18065ece5241d2ee15b174693` | Proposal đầu chọn UID/GID 10001, fsGroup 2000 và cấu hình cache; cả 14 checks Kubernetes đạt. Chín action `test` tiếp theo cũng đạt, rồi workflow hết ngân sách và kết thúc `accepted: false`. |

Lượt cuối có **10 lần gọi model hoàn tất, một repair và 11 tests**. Ollama báo 31.575 prompt token cộng 422 completion token, tổng 31.997. Lần gọi thứ 11 bị ngân sách bảo thủ chặn trước khi có thêm inference. Proposal đã pass nằm trong trace; bundle cuối của lượt thất bại giữ base ở `candidate.json`, không được export như repair đã chấp nhận.

Controller fix hiện kết thúc bản sửa đã được kiểm chứng ở lượt mới bằng policy engine có guard rõ ràng. Action `test`, decoder, model pins, ngân sách và cả 14 checks vẫn giữ nguyên; CLI khác vẫn mặc định model-finish. Thay đổi xử lý việc tiếp tục chạy sau khi đã đạt objective. Các suy đoán về thứ tự enum hoặc decoder bias vẫn chưa được chứng minh. Lịch sử đã đổi checkpoint/prompt/ngân sách, nên không phải nghiên cứu so sánh chất lượng model có kiểm soát.

Lượt đã audit thành công vẫn chỉ bao phủ một workload tổng hợp và các probe đã khai báo. Chưa có held-out benchmark, đánh giá prompt injection, bảo đảm production security hoặc bằng chứng agent tốt hơn template. Static checks là checks tích hợp; Checkov chưa được chạy. Seccomp mode 2 chứng minh filter hoạt động, không xác thực toàn bộ nội dung profile.
