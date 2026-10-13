# Demo bắt buộc chạy Kubernetes

**Demo Kubernetes thật đã thành công:** [run 38408621533](https://github.com/tuanngocfun/agent/actions/runs/38408621533) chạy source commit `4461388` trên nhánh `kube-remediation-demo` của repo riêng `tuanngocfun/agent`. Artifact đã được tải xuống và kiểm tra; `summary.json` có `status: passed`, backend `kubernetes`, provider `scripted` và version server **v1.34.0**. Host ban đầu thiếu runtime; job dùng worker GitHub Actions để dựng cluster `kind`.

Xem [kết quả thực tế](REAL_KUBERNETES_RESULT_VI.md) và mở run phía trên để tải artifact `kubernetes-remediation-evidence`. Đọc `summary.json` và các file `REVIEW.md`, `report.json`, `trace.json`, `patch.diff`. Artifact được giữ 7 ngày; bản đã tải nằm trên workstation gốc, không nằm trong source Git. Xem thêm [hướng dẫn đọc job và bằng chứng](GITHUB_KUBERNETES_DEMO.md).

## Đường chạy trên GitHub Actions

File [.github/workflows/kubernetes-demo.yml](../.github/workflows/kubernetes-demo.yml) dùng một worker Ubuntu tạm thời có Docker. Workflow hỗ trợ gọi thủ công và push trên nhánh `kube-remediation-demo` theo bộ lọc trong YAML. Publish source đã khởi chạy job đầu tiên; không cần merge vào `main`. Source đầy đủ nằm trên nhánh demo; README ban đầu trên `main` chỉ giúp bootstrap repo trống.

Workflow cài `kind v0.30.0` và `kubectl v1.34.0` bằng checksum từ nguồn chính thức, dùng node image Kubernetes 1.34.0 được pin theo digest của [kind release](https://github.com/kubernetes-sigs/kind/releases/tag/v0.30.0). Đây là phiên bản cố định cho demo, không phải tuyên bố dùng bản mới nhất.

Worker tải image Python chính thức, ghi lại digest thực tế rồi dùng digest đó để build fixture. Lượt chạy tiếp theo muốn tái hiện đúng base image cần dùng digest trong `image-pin.json`; tag `python:3.12-slim` có thể thay đổi giữa các job. Image ứng dụng có tag riêng cho lượt chạy, được load vào cluster. Backend kiểm tra imageID thực tế của Pod với pin do bước setup tin cậy lấy được; không đánh đồng Docker config digest với OCI/CRI digest.

Demo thực hiện:

1. Dựng cluster `kind` riêng và kubeconfig riêng.
2. Chạy một fixture đã harden để xác định runtime image ID.
3. Chạy no-op: ứng dụng hoạt động nhưng thiếu các control mục tiêu.
4. Chạy hardening đơn giản: kiểm tra cấu hình đạt nhưng cache phải thất bại.
5. Chạy bản sửa đối chứng đúng.
6. Chạy vòng agent với feedback từ Kubernetes.
7. Kiểm tra kết quả đối chứng, lưu report/trace/patch và dọn cluster.

Mỗi ứng viên dùng namespace mới. Runner kiểm tra UID/owner của namespace trước khi xóa; xác thực Deployment/ReplicaSet/Pod và version trong lượt kiểm chứng. Probe cố định kiểm tra HTTP, kết quả SHA-256, cache, UID, quyền ghi root filesystem, no-new-privileges, capabilities và seccomp. Runner không cho model truyền shell command hoặc chỉnh evaluator.

Namespace và kubeconfig không dùng cấu hình global. Artifact upload chỉ gồm các report được chọn; kubeconfig và cluster logs không được upload. Worker có giới hạn job 20 phút. Workflow hiện dùng **provider viết tay `scripted` với runtime Kubernetes thật**; kết quả chưa phải thí nghiệm LLM. [kind quick start](https://kind.sigs.k8s.io/docs/user/quick-start/) mô tả cách dựng cluster và load image.

## Chạy trên máy có Docker

Chuẩn bị Docker hoạt động, các binary đúng phiên bản và hai image đã có cục bộ. Script không tự tải image hoặc đổi quyền host:

```bash
cd path/to/agent
python3 scripts/kind_demo.py \
  --base-image python@sha256:YOUR_VERIFIED_LOCAL_DIGEST \
  --output runs/my-kubernetes-demo
```

Node image mặc định đã được pin. Nếu image chưa có cục bộ, preflight dừng trước khi tạo cluster; chuẩn bị worker rồi chạy lại. Thư mục output phải mới. Xem `summary.json`, `image-pin.json`, `commands.json` và các bundle trong `results/`.

Để LLM chọn action, dùng `--provider ollama --model YOUR_MODEL` khi worker đã có Ollama chạy và model sẵn có. Script không tự khởi động server hoặc tải weights. `--provider session --exchange-dir PATH` dùng [bridge của phiên assistant](SESSION_AGENT.md); cần một tác nhân bên ngoài trả lời mỗi request, không tự chạy độc lập.

## Cluster lab đã có sẵn

Backend luôn cần context rõ ràng và imageID từ bước setup tin cậy:

```bash
PYTHONPATH=src python3 -m kube_repair run \
  --scenario cache-path --backend kubernetes \
  --kube-context YOUR_LAB_CONTEXT --kubeconfig /path/to/lab-config \
  --image YOUR_PRELOADED_FIXTURE_TAG \
  --expected-image-id YOUR_OBSERVED_CRI_SHA256_ID \
  --provider scripted --output runs/existing-lab-demo
```

Cluster phải có fixture image đã được load ở node và quyền tạo/xóa namespace cho runner. Đây là runner cho lab riêng; không tự chọn cluster production. `volume-permissions` chưa được hỗ trợ trong backend Kubernetes vì fixture cần setup volume permission thực tế riêng.

## Trạng thái bằng chứng

Lượt đã xác nhận cho kịch bản `cache-path`:

| Cách sửa | Kết quả trên Kubernetes thật |
|---|---|
| Không sửa (`noop`) | Ứng dụng/cache hoạt động; thiếu các control bảo mật mục tiêu. |
| Chỉ bật hardening (`naive`) | Cấu hình đạt; ứng dụng lỗi ghi cache vì filesystem chỉ đọc. |
| Đối chứng đúng (`known-good`) | Qua các kiểm tra đã khai báo. |
| Vòng `scripted` | Sửa thành công sau 2 ứng viên, 3 lượt test, 5 action; khoảng 39 giây. |

Ứng viên cuối chạy UID 10001; ghi root filesystem bị từ chối bằng `EROFS`; `NoNewPrivs=1`; capabilities bằng 0; seccomp ở filter mode 2. Kiểm tra HTTP, kết quả SHA-256, cache đọc lại/tái sử dụng, image ID và cleanup namespace đều qua.

Đây là một fixture tổng hợp được thử trên Kubernetes thật. Kết quả chưa chứng minh LLM tự chọn bản sửa hoặc hiệu quả trên benchmark; các phần đó cần một lượt riêng dùng `ollama` hoặc bridge `session` cùng bằng chứng quyết định và bộ workload độc lập.
