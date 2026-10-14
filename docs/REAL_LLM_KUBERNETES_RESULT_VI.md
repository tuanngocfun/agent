# LLM thật đã sửa workload trên Kubernetes thật

[GitHub Actions run #14](https://github.com/tuanngocfun/agent/actions/runs/38528564033) hoàn tất thành công lúc **14:37 ngày 14/10/2026, Asia/Saigon**. Source được chạy là commit [`d770c0e`](https://github.com/tuanngocfun/agent/commit/d770c0efea239754e221606a8f76ff16fcc5aedb), trên nhánh `kube-remediation-demo` của repo riêng `tuanngocfun/agent`.

**Qwen2.5 3B Instruct Q4_K_M thực sự sinh patch; Kubernetes v1.34.0 thực sự chạy ứng dụng và kiểm chứng patch.** Kết quả cuối là `status: repaired`, `accepted: true`, tất cả **14/14 kiểm tra** đạt. Có **1 lần gọi LLM cho agent, 1 candidate và 2 lượt test** (manifest gốc và candidate). Lượt smoke kiểm tra model server được ghi riêng.

## Lỗi đã xảy ra và cách sửa

Ở [workflow #13](https://github.com/tuanngocfun/agent/actions/runs/38502780956), model đã tạo một candidate đạt đủ 14 kiểm tra. Controller vẫn chờ action `finish` từ model. Model gọi thêm 9 lần `test`, rồi giới hạn ngân sách bảo thủ từ chối lần gọi kế tiếp. Vì vậy kết quả cuối vẫn là `accepted: false`. Review Gemini nhận diện đúng vấn đề này; file Claude trong thư mục review đang trống khi được kiểm tra.

Chế độ mới `--stop-on-verified-repair` cho phép **engine kết thúc ngay sau kiểm chứng thành công một proposal hợp lệ đã làm manifest thay đổi**. Engine kiểm tra lại policy và hash của candidate, yêu cầu không có lỗi hạ tầng, rồi ghi `trusted_completion` với `completion_actor: trusted_engine`. Nó không tạo action `finish` giả và không tự điền giá trị repair cho model. Mặc định CLI vẫn dùng `model-finish`; launcher LLM chọn rõ `verified-repair` và lưu policy trong evidence.

Các predicate bảo mật, kiểm thử HTTP/cache, image identity và cleanup được giữ nguyên. Ngân sách vẫn giữ nguyên; action `test` vẫn có sẵn. Giả thuyết thứ tự enum hoặc temperature gây lặp chưa được chứng minh bằng một thí nghiệm riêng.

Lượt mới chạy lại từ đầu ở source mới. Kết quả thất bại của lượt cũ được giữ nguyên, không được đổi thành thành công sau khi sửa controller. Local attempt 013 tương ứng workflow #14; hai bộ số đếm khác nhau.

## Model đã sửa gì

Đọc [patch đầy đủ](../evidence/llm-kubernetes-2026-10-14/reports/kubernetes/results/agent/patch.diff), [candidate](../evidence/llm-kubernetes-2026-10-14/reports/kubernetes/results/agent/candidate.json) và [raw response trong report](../evidence/llm-kubernetes-2026-10-14/reports/kubernetes/results/agent/report.json).

- Đặt `runAsNonRoot: true`, UID/GID `10001`, root filesystem chỉ đọc và `allowPrivilegeEscalation: false`.
- Drop `ALL` capabilities, dùng seccomp `RuntimeDefault`.
- Mount `emptyDir` giới hạn `16Mi` tại `/var/cache/repair-app`; chọn `fsGroup: 2000` để cache ghi được.

Các giá trị trên nằm trong JSON thực tế do Ollama trả về. Audit xác nhận action đó tạo đúng candidate đã kiểm chứng, không có giá trị UID/GID được schema hoặc engine chèn vào. Schema hướng dẫn cấu trúc action và yêu cầu tên các field security; đây là generation có ràng buộc schema.

## Kiểm tra đã quan sát

| Arm | Cấu hình security | HTTP/cache | Runtime security | Chấp nhận |
|---|---|---|---|---|
| No-op | Không đạt | Đạt | Không đạt | Không |
| Hardening chỉ thêm flags | Đạt | Khởi động lỗi cache | Không có probe thành công | Không |
| Known-good do tác giả fixture cung cấp | Đạt | Đạt | Đạt | Có |
| Patch LLM | Đạt | Đạt | Đạt | Có |

Arm hardening thất bại thực tế với `Read-only file system` khi ghi `/var/cache/repair-app/cache-contract.txt`. Patch LLM giữ hành vi HTTP health, kết quả SHA-256 do verifier tính độc lập, cache read-back và cache reuse.

Verifier quan sát PID 1 có UID **10001**, ghi ngoài volume bị từ chối với **errno 30 (EROFS)**, `NoNewPrivs=1`, `CapBnd/CapEff/CapPrm=0`, `Seccomp=2`. UID/GID yêu cầu trong task cũng được audit đối chiếu riêng với candidate; probe không đo process GID. Sáu static checks, image identity, application check, năm runtime security checks và namespace cleanup tạo thành 14 kiểm tra. Các namespace, cluster kind và Ollama container đều được dọn với kết quả thành công trong command records.

## Model, ngân sách và bằng chứng

Model là **Qwen2.5 3B Instruct bản general**, không phải Qwen2.5-Coder. Chạy bằng Ollama **0.6.8**, CPU, 2 threads, context 8192, output tối đa 512 token, temperature 0, decoding `compact-schema`. Metadata thực tế ghi **3,085,938,688 parameters** và Qwen Research License Agreement; [model-pin.json](../evidence/llm-kubernetes-2026-10-14/reports/model-pin.json) giữ license/model metadata nhận từ server.

Lượt agent dùng **2,205 prompt + 197 completion = 2,402 token thực tế**, khác reservation bảo thủ **9,394** trên cap **131,072**. Một lần inference mất khoảng **289 giây**; agent gồm hai lượt test mất khoảng **316 giây**. Thời gian này là quan sát của worker hiện tại.

| Identity | SHA-256 |
|---|---|
| Model manifest | `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b` |
| Weight blob đã tải và kiểm tra | `5ee4f07cdb9beadbbb293e85803c569b01bd37ed059d2715faa7bb405f31caa6` |
| Image app thực tế | `33a542e97364862cb8acc95eb57cb330af93c86fc2909de5c7d7557fc233efe4` |
| Source fingerprint | `a8fb2b5c655e52eaf1b7939b1098b4d7239bcc7cb9a6067b8c8b461e4bff16b0` |
| Archive artifact GitHub | `72a5ae2561aa4dddaf137777abc4bc47bdd578139486b10f705d429801fc5bdf` |

Xem [artifact-info](../evidence/llm-kubernetes-2026-10-14/artifact-info.json), [trace](../evidence/llm-kubernetes-2026-10-14/reports/kubernetes/results/agent/trace.json), [model commands](../evidence/llm-kubernetes-2026-10-14/reports/model-commands.json), [Kubernetes commands](../evidence/llm-kubernetes-2026-10-14/reports/kubernetes/commands.json) và [kết quả audit](../evidence/llm-kubernetes-2026-10-14/audit.json).

Audit chạy lại trên evidence đã lưu: cả bốn bundle có hashes hợp lệ; source/fixture/model pins khớp; request hash được tái tạo chính xác; raw response hash, parsed action, tác động lên candidate và terminal completion khớp. Progress journal vẫn là snapshot không export được; bundle cuối mới chứa kết quả accepted. **139 unit tests** đã đạt trước lượt worker mới.

Artifact GitHub hết hạn sau 7 ngày, nên 41 file report được lưu nguyên byte trong `evidence/`. Không lưu weights, archive ZIP hay cluster credentials trong repo. Audit có thể chạy trên host này mà không cần model hoặc Kubernetes:

```bash
cd /home/ngocnt/agents/kube-security-remediation
mkdir -p runs/evidence-review
PYTHONDONTWRITEBYTECODE=1 python3 \
  evidence/llm-kubernetes-2026-10-14/audit_llm_evidence.py \
  evidence/llm-kubernetes-2026-10-14/reports \
  --output runs/evidence-review/audit.json
```

Để chạy lại workload/model thật, dùng **Re-run all jobs** trên GitHub Actions run đã dẫn ở trên, hoặc [worker guide](GITHUB_KUBERNETES_DEMO.md) trên máy lab có Docker/kind/kubectl. Host hiện tại chưa có môi trường Kubernetes; evidence này đến từ GitHub worker.

## Giới hạn của kết quả

Đây là một fixture tổng hợp với task và schema hướng dẫn rõ. Model sửa đúng ở lần đề xuất đầu tiên, không chọn `inspect` và không phải sửa tiếp theo feedback của một candidate thất bại trong lượt này. Vì vậy demo chứng minh tích hợp LLM thật, repair đúng theo các kiểm tra đã khai báo và completion đáng tin cậy; chưa chứng minh ưu thế của điều tra thích nghi, chống prompt injection, held-out reliability hay khả năng tổng quát sang ứng dụng khác.

`known-good` là oracle; Checkov chưa được chạy. Seccomp mode 2 xác nhận filter hoạt động, không xác thực nội dung profile. Audit tin cậy source, runner và command records; nó kiểm tra consistency/provenance, không phải remote attestation hoặc thực thi lại workload độc lập.

Mốc tiếp theo là nhiều workload độc lập, direct-model/template baselines có năng lực, test được bảo vệ và so sánh ở ngân sách tương đương. [Demo scripted trước đó](REAL_KUBERNETES_RESULT_VI.md) vẫn là bằng chứng riêng về vòng sửa nhiều bước trên Kubernetes.
