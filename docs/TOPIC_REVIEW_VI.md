# Đề tài này có ổn không?

**Có. Đây là một đề tài phù hợp để làm portfolio kỹ thuật và có thể phát triển thành nghiên cứu, nếu bạn giữ phạm vi ban đầu nhỏ và chứng minh bản sửa bằng hành vi thực tế.** Câu hỏi trung tâm đủ cụ thể: “Agent có thể sửa một cấu hình bảo mật mà vẫn giữ ứng dụng làm đúng việc cần làm không?”

Bản starter trong repository này giúp bạn học và kiểm tra kiến trúc. Nó chưa xác nhận lợi ích doanh nghiệp, tính mới học thuật hoặc hiệu quả của LLM. Định hướng đầy đủ nằm trong kế hoạch dài hạn lưu trên workspace local: `/home/ngocnt/outputs/agent-long-term-strategy-2026-10-13/README.md`.

## Ưu điểm

| Ưu điểm | Bạn có thể chứng minh bằng gì |
|---|---|
| Bài toán có xung đột rõ ràng giữa bảo mật và chức năng | Một bản bật non-root/read-only vượt kiểm tra cấu hình nhưng làm ứng dụng không ghi cache được. |
| Có công việc điều tra phù hợp với agent | Chọn evidence cần đọc, diễn giải lỗi runtime, chọn cách sửa tiếp và nhận biết khi thiếu quyền. |
| Phù hợp với nền tảng IT Security | Kiến thức về quyền, threat model, cấu hình và kiểm tra negative behavior được dùng trực tiếp. |
| Cho thấy nhiều năng lực kỹ thuật trong một project | API model, tool có kiểu dữ liệu, policy kiểm soát sửa, test runner, trace và review artifact. |
| Có hướng đánh giá định lượng | So sánh sửa thành công, regression, thay đổi bị chặn, chi phí và thời gian với baseline. |
| Có thể phát triển từng bước | Container hardening trước; RBAC hoặc NetworkPolicy sau khi đã có contract thực thi được. |

Non-root, quyền user/group và filesystem chỉ đọc là các cơ chế khác nhau; cấu hình đúng phải phù hợp với thao tác ứng dụng và storage. [Kubernetes security context](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/) mô tả các cơ chế này.

## Khuyết điểm và cách giảm rủi ro

| Khuyết điểm | Cách xử lý trong project |
|---|---|
| Kubernetes có nhiều kiến thức phụ; bạn dễ dành hết thời gian vào hạ tầng | Chỉ bắt đầu với một Deployment, một container, non-root và vùng ghi cache. Dùng Docker để học runtime trước khi thêm cluster. |
| Nhiều lỗi đơn giản được template giải rẻ hơn LLM | Giữ template mạnh làm đối chứng. Nếu template giải gần hết, đơn giản hóa sản phẩm hoặc thêm tình huống điều tra thực tế. |
| “Scan → sửa → PR” đã là hướng phổ biến | Đặt đóng góp ở tính đúng của bản sửa, ích lợi của feedback và đánh giá bằng executable contract. Kế hoạch cũ đã tổng hợp related work; vẫn cần rà soát lại trước khi tuyên bố tính mới. |
| Test không đầy đủ có thể chấp nhận bản sửa làm mất chức năng | Định nghĩa thao tác ứng dụng cần giữ, kiểm tra nhiều đường đi, có biến thể giữ kín và đối chứng sai. Health endpoint đơn lẻ chưa đủ. |
| Scanner không phải toàn bộ chân lý bảo mật | Giữ cấu hình evaluator cố định và kiểm tra runtime. Checkov có cơ chế suppress/skip; mất cảnh báo không tự xác nhận bản sửa đúng. [Checkov suppression](https://www.checkov.io/2.Basics/Suppressing%20and%20Skipping%20Policies.html) |
| Lab mô phỏng dễ cho kết quả đẹp nhưng không phản ánh runtime | Gắn nhãn `simulated`, ghi `runtime_verified` và tiếp tục sang fixture thật. Docker cũng chưa thay thế kiểm chứng Kubernetes. |
| Tài liệu/log trong repository có thể chứa prompt injection | Đánh dấu nguồn evidence, giới hạn tool/quyền, để engine chạy test; chấm tác động thực sự thay vì chỉ xem model có lặp lại câu độc hại không. |
| Chưa có reviewer thường xuyên | Công bố lab có thể tái hiện khi đã sẵn sàng, rồi xin góp ý về case và patch cụ thể. Giá trị người dùng hiện là giả thuyết. |
| Dễ mở phạm vi quá nhanh | Trì hoãn Terraform, compliance tổng quát, nhiều agent và huấn luyện model đến khi lỗi đo được chỉ ra nhu cầu. |

Bạn nên coi các rủi ro trên là tiêu chí ra quyết định. Ví dụ, nếu bổ sung feedback không cải thiện kết quả ở ngân sách tương đương, hãy báo cáo điều đó và tìm xem contract thiếu gì hoặc template đã đủ tốt.

## Agent cần thiết khi nào?

Agent hợp lý khi bước tiếp theo phụ thuộc vào điều vừa quan sát. Lỗi filesystem chỉ đọc có thể dẫn tới đọc cấu hình cache; lỗi permission có thể dẫn tới kiểm tra user/group; ứng dụng bắt buộc chạy root có thể buộc dừng trong phạm vi hiện tại. Một chuỗi cố định luôn đọc mọi nguồn và thử cùng bản sửa cần được xem là baseline đáng so sánh.

Trong starter, provider viết tay minh họa những nhánh này. Provider Ollama cho model chọn action, còn policy/engine giữ quyền thực thi. Đây là một giao diện agent có giới hạn. Framework orchestration và số lượng model không phải tiêu chí xác định đóng góp.

## Điều còn thiếu để thành nghiên cứu

Một câu hỏi phù hợp là: **Ở ngân sách tương đương, feedback kiểm thử đáng tin có giúp agent sửa bảo mật mà giữ chức năng tốt hơn template và model một lượt, kể cả khi evidence thiếu hoặc độc hại không?** Đây là giả thuyết cần kiểm chứng.

Bạn còn cần:

1. **Workload đủ đa dạng:** nhiều ứng dụng/lịch sử task độc lập; ghi rõ fixture tổng hợp và case chuyển thể từ project thực tế. Bốn scenario starter không phải benchmark xác nhận tổng quát.
2. **Evaluator được bảo vệ:** contract và test không cho agent sửa; control đúng/sai; kiểm tra parser failure, bỏ resource và làm yếu policy. Test runtime cần quan sát cơ chế thật.
3. **Baseline cạnh tranh:** template, model một lượt, chuỗi tool cố định và agent thích nghi. Giữ model, input, quyền và ngân sách nhất quán.
4. **Ablation:** có/không feedback; có/không bảo vệ provenance nếu worker đủ cô lập. Phân biệt ích lợi của lựa chọn bước tiếp theo với việc đơn giản cho model nhiều lượt hơn.
5. **Chia dữ liệu trước khi tối ưu:** các phiên bản, biến thể và attack của cùng workload nằm cùng nhóm. Không điều chỉnh prompt theo kết quả held-out.
6. **Đo cả ích lợi và lỗi:** sửa thành công với chức năng giữ nguyên, regression, tác động trái quyền, abstention phù hợp, chi phí và thời gian. Số lần policy chặn đề xuất cũng cần tách khỏi số tác động trái quyền đã thực thi.
7. **Lặp lại và phân tích độ bất định:** báo số workload độc lập, seed, phiên bản model/runtime và ngân sách. Nhiều biến thể của một ứng dụng không tạo ra nhiều ứng dụng độc lập.
8. **Traces và đánh giá bên ngoài:** người khác chạy lại được case và nhận xét tính hợp lý của patch. Đừng ghi thành tích CV hoặc tỷ lệ thành công khi chưa có phép đo tương ứng.

Khoảng 4–6 tháng trong kế hoạch cũ là ước tính lập kế hoạch. Bạn có thể kết thúc sớm hơn với một portfolio nhỏ có kiểm chứng tốt, hoặc cần lâu hơn nếu mục tiêu là kết luận nghiên cứu đáng tin.

## Các mốc nên hoàn thành

| Mốc | Khi nào nên sang bước tiếp |
|---|---|
| Hiểu starter | Bạn tự giải thích được một bản sửa đúng, một regression và một lần dừng vì thiếu quyền. |
| Fixture container thật | Positive/negative probes quan sát UID, ghi cache và giới hạn filesystem thật; lỗi hạ tầng không bị biến thành “pass”. |
| Một LLM hoạt động | Action có cấu trúc, lỗi model được ghi lại, trace đủ để giải thích quyết định và chi phí. |
| Pilot đa dạng | Template, model một lượt và agent được so sánh trên cùng task; một số case thực sự cần điều tra. |
| Kubernetes lab | Manifest được chạy ở worker dùng riêng, có reset/cleanup và kiểm tra những ngữ nghĩa khác với Docker. |
| Nghiên cứu nhỏ | Split được khóa, baseline/ablation rõ ràng, kết quả gồm cả failure và limitations. |

Để bắt đầu ngay, đọc [START_HERE_VI.md](START_HERE_VI.md) và chạy demo. Mục tiêu của buổi đầu là hiểu cách một kết quả test dẫn tới quyết định sửa tiếp, rồi tự kiểm tra được lý do bản sửa cuối cùng được chấp nhận.
