# Kronos Financial Forecasting Evaluation Lab

Bộ mã khởi đầu từ các kế hoạch Kronos do Ngọc cung cấp: tải nến công khai,
kiểm tra suy luận Kronos và xác thực tài khoản Binance Spot testnet chỉ đọc.
Nhánh này được tạo từ `main`; dự án Kubernetes nằm ở nhánh
[`kube-remediation-demo`](https://github.com/tuanngocfun/agent/tree/kube-remediation-demo).

## 1. Tải nến công khai

Yêu cầu Python 3.10+. Bước tải nến và kiểm tra testnet dùng thư viện chuẩn,
không cần cài dependencies hoặc dùng API key để tải nến.

```bash
python3 download_candles.py --symbol BTCUSDT --interval 1h --limit 500 --output data/BTCUSDT_1h.csv
```

CSV có bảy cột `timestamps,open,high,low,close,volume,amount`; timestamp là UTC,
`amount` lấy từ quote asset volume của Binance. Script chỉ ghi nến đã đóng,
kiểm tra OHLC, số hữu hạn, timestamp trùng và khoảng trống, và lưu metadata bên cạnh CSV.
Khi giới hạn 1000, kết quả có thể chỉ có 999 nến đã đóng. Lỗi HTTP 451/403 có
thể do hạn chế truy cập của nguồn; không tự chuyển nguồn dữ liệu hoặc bỏ qua lỗi.

## 2. Chạy smoke test Kronos

Tạo môi trường riêng, tải mã upstream và checkout đúng phiên bản đã đối chiếu:

```bash
python3 -m venv .venv
source .venv/bin/activate
git clone https://github.com/shiyu-coder/Kronos.git vendor/Kronos
git -C vendor/Kronos checkout 67b630e67f6a18c9e9be918d9b4337c960db1e9a
python -m pip install -r vendor/Kronos/requirements.txt
python first_forecast.py
```

Lần đầu sẽ tải `NeoQuasar/Kronos-small` và tokenizer từ Hugging Face. Có thể
chỉ định `--device cpu` hoặc `--device cuda:0`. Checkpoint dùng revision mặc định
của Hugging Face; metadata ghi rõ giới hạn này, chưa bảo đảm tái lập tuyệt đối.

Chạy trên CSV vừa tải:

```bash
python first_forecast.py --csv data/BTCUSDT_1h.csv --lookback 256 --horizon 24
```

Đây là kiểm tra phần mềm trên một cửa sổ lịch sử: dùng `lookback` nến trước
`horizon` nến giữ lại. Chỉ timestamps của phần giữ lại được truyền vào mô hình;
giá tương lai không đi vào `predict()`. Script không phát dự báo cho các mốc thời
gian ngoài CSV. CSV mẫu upstream có thể trùng giai đoạn pretraining, nên kết quả
không chứng minh chất lượng ngoài mẫu hoặc lợi nhuận. Đầu ra ở `output/` gồm
CSV dự báo và metadata (revision upstream, hash dữ liệu, seed, sampling, thiết bị).

## 3. Kiểm tra key testnet chỉ đọc

```bash
test -f .env || cp .env.example .env
# Điền key/secret HMAC của Spot testnet vào .env bằng trình soạn thảo.
python3 check_testnet.py --env-file .env
```

Nếu biến đã được export trong shell, chạy `python3 check_testnet.py`.
Script chỉ gọi `GET /api/v3/time` và `GET /api/v3/account` trên host cố định
`testnet.binance.vision`. Đầu ra chỉ gồm trạng thái xác thực và thông tin tóm tắt;
không in key, secret, chữ ký hoặc số dư. Script dành cho key HMAC có secret;
RSA và Ed25519 cần cách ký khác. Không có chức năng gửi lệnh.

`.env` đã có trên máy được giữ nguyên và bị Git bỏ qua. File `.env.example`
chỉ có tên biến rỗng. CSV, output, model, vendor và môi trường Python cũng bị bỏ qua.

## Kiểm tra cục bộ

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile download_candles.py first_forecast.py check_testnet.py
```

Test dùng phản hồi giả lập; không sử dụng key thật, tải weights hoặc đặt lệnh.
Xem [VALIDATION.md](VALIDATION.md) để biết những bước đã thực sự chạy.

## Tài liệu nguồn và bước tiếp theo

- [Kế hoạch ngắn](docs/plans/action-plan.txt)
- [Thảo luận tính khả thi](docs/plans/feasibility.txt)
- [Kế hoạch nghiên cứu gốc](docs/plans/deep-research.txt)
- [HTML minh họa được cung cấp](interactive_visual_im_6689e014fcae1cde.html)

Ba bản `.txt` được trích từ nội dung Word để dễ tìm kiếm và review. Định dạng,
công thức dạng ảnh và hyperlink trong Word không được giữ đầy đủ. Các file Word
gốc vẫn nằm cục bộ. Các tài liệu này là bối cảnh do người dùng cung cấp; các
khẳng định nghiên cứu trong đó chưa được tái thẩm định toàn bộ trong lần tạo nhánh.
Bản thẩm định 10 trang và `check_testnet.py` được nhắc trong hội thoại trước
không có trong các file nhận được; script testnet ở đây được viết mới.

Bước nghiên cứu sau smoke test: thêm baseline giữ nguyên giá đóng cửa, đánh giá
walk-forward, kiểm tra calibration và lưu dự báo trước khi có kết quả thực tế.
Starter này chưa có pipeline đánh giá hoặc fine-tuning. `sample_count > 1`
trong API upstream trả trung bình các mẫu; không được xem đó là nhiều đường mẫu
riêng. Chưa áp dụng hệ số hiệu chuẩn 2,7 hoặc một điểm “confidence chuẩn MCP”.

Nguồn kỹ thuật đã đối chiếu:
[Kronos predictor tại revision cố định](https://github.com/shiyu-coder/Kronos/blob/67b630e67f6a18c9e9be918d9b4337c960db1e9a/model/kronos.py),
[Binance market data](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints),
[Binance signed requests](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/request-security),
[Spot testnet](https://developers.binance.com/docs/binance-spot-api-docs/testnet/general-info).
