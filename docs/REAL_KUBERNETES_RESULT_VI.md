# Demo Kubernetes thật đã chạy thành công

[Workflow run 38408621533](https://github.com/tuanngocfun/agent/actions/runs/38408621533) đã thành công trên repo riêng tư `tuanngocfun/agent`, nhánh `kube-remediation-demo`. Commit được thực thi: `44613880014ca56882f0a21e5de461db97941b50`. Job hoàn tất lúc 20:55 ngày 13/10/2026, Asia/Saigon.

Demo chạy fixture HTTP trên **Kubernetes v1.34.0 trong cluster kind thật**. Provider quyết định là `scripted`, với quy tắc viết tay và feedback từ workload. Không có lượt suy luận LLM trong kết quả này.

## Kết quả quan sát

| Cách sửa | Kiểm tra cấu hình | HTTP/cache | Security runtime | Được chấp nhận |
|---|---|---|---|---|
| No-op | Không đạt | Đạt | Không đạt | Không |
| Chỉ thêm hardening | Đạt | Hỏng khi khởi động | Không có probe thành công | Không |
| Bản đối chứng đúng | Đạt | Đạt | Đạt | Có |
| Vòng sửa có feedback | Đạt | Đạt | Đạt | Có |

Lỗi thực tế của bản hardening đơn giản:

```text
Cache initialization failed: [Errno 30] Read-only file system: '/var/cache/repair-app/cache-contract.txt'
```

Vòng sửa thực hiện **5 quyết định, 2 ứng viên sửa và 3 lượt kiểm thử**: đọc metadata image → đề xuất hardening → nhận lỗi cache và đọc cấu hình app → thêm vùng ghi cache → kết thúc sau khi verifier đạt. Đọc [trace đầy đủ](../evidence/kubernetes-2026-10-13/results/agent/trace.json) và [patch](../evidence/kubernetes-2026-10-13/results/agent/patch.diff).

Bản cuối giữ UID `10001`, filesystem root chỉ đọc, `NoNewPrivs=1`, capabilities effective/permitted/bounding bằng 0 và seccomp filter mode 2. Cache dùng `emptyDir` tại `/var/cache/repair-app` với `fsGroup=10001`. Verifier quan sát HTTP health, kết quả SHA-256 độc lập, cache read-back và lần gọi lại lấy cache; ghi ngoài volume bị từ chối với errno 30.

Tất cả **14 kiểm tra** của bản đối chứng đúng và bản cuối đều đạt, gồm image identity và cleanup namespace. ImageID thực tế được pin trước khi so sánh; nó giống nhau trong cả bốn arm. Mỗi ứng viên có namespace riêng và có ràng buộc UID/owner của workload. Cluster `repair-demo-e2962fea7b39` được tạo và xóa với exit code 0.

## Bằng chứng có thể xem lại

- [Tổng hợp job](../evidence/kubernetes-2026-10-13/summary.json)
- [Report agent và từng probe](../evidence/kubernetes-2026-10-13/results/agent/report.json)
- [Report bản hardening bị lỗi](../evidence/kubernetes-2026-10-13/results/naive/report.json)
- [Pin image/source](../evidence/kubernetes-2026-10-13/image-pin.json)
- [Các lệnh và exit code](../evidence/kubernetes-2026-10-13/commands.json)
- [Kiểm tra integrity độc lập](../evidence/kubernetes-2026-10-13/verified-evidence.json)
- [Metadata artifact và commit](../evidence/kubernetes-2026-10-13/artifact-info.json)

Archive gốc có SHA256 `7361704237d39eeef6cb0db119444b6a392f69664a3caf43e2751a68f687faec`. Cả bốn bundle được kiểm tra lại: payload hashes, review hash, base/candidate/contract hashes và source fingerprint đều hợp lệ. Source fingerprint `df02a9f5baee95c5c0d6ecdb9039a4170428eb9b20c7aad7624f54db06f1f098` khớp mã/fixture được commit và được thực thi.

Bằng chứng lưu trong repo không gồm kubeconfig, private key/certificate hay token; cluster đã được dọn. Artifact GitHub có thời hạn 7 ngày, nên các report được giữ thêm ở thư mục `evidence/`.

## Điều kết quả chứng minh

Một workload tổng hợp đã được harden và giữ được các hành vi đã khai báo trên Kubernetes thật. Việc đạt static checks đơn lẻ không đảm bảo cache hoạt động: đối chứng hardening cho thấy regression thực tế, và bộ kiểm chứng từ chối nó.

Đây chưa phải kết quả LLM, benchmark tổng quát hoặc chứng minh tốt hơn template. `known-good` là oracle control do tác giả fixture cung cấp. Các kiểm tra static là checks tích hợp của lab; Checkov chưa được chạy. Seccomp mode 2 chứng minh filter hoạt động, không xác thực nội dung profile. Phạm vi runtime là fixture tin cậy với các predicate đã ghi.

Với arm thất bại, `candidate.json` giữ manifest gốc để tránh xuất bản sửa chưa đạt. Bản naive được xác định bởi baseline `harden()` tại commit thực thi; report lưu kết quả của bản đó. Không diễn giải `candidate.json` của arm thất bại như một bản sửa được chấp nhận.

Để dùng LLM chọn bước tiếp theo trên cùng runner, xem [runbook Kubernetes](KUBERNETES_DEMO_VI.md). Lượt chạy độc lập cần có model server/API và ghi rõ model/settings/ngân sách trước khi so sánh.
