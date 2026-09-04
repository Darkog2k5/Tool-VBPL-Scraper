# 🏛️ Tool Cào Dữ Liệu Văn Bản Pháp Luật (vbpl.vn)

Công cụ Python tự động thu thập nội dung toàn văn, thuộc tính và lược đồ quan hệ của các Văn bản Pháp luật từ `vbpl.vn`, xuất ra file Word và JSON có cấu trúc rõ ràng.

## ✨ Tính năng nổi bật

- **Gom nhóm dữ liệu thông minh**: Phân loại theo Loại văn bản → Số hiệu văn bản, tránh hoàn toàn tình trạng ghi đè giữa các văn bản trùng số hiệu nhờ gắn ID định danh duy nhất vào tên thư mục.
  ```
  output/documents/Nghị_định/139_2026_NĐ-CP_123456/
  ```
- **Đóng gói chuẩn cấu trúc**: Bên trong mỗi thư mục văn bản gồm:
  - `noi_dung.docx` — Toàn văn định dạng Word (Times New Roman, cỡ 13).
  - `thuoc_tinh.json` — Thuộc tính: Ngày ban hành, Cơ quan ban hành, Tình trạng hiệu lực...
  - `luoc_do.json` — Sơ đồ văn bản liên quan, thay thế, bổ sung.
  - `muc_luc.json` — Mục lục điều khoản.
- **Tải file thông minh**: Nếu văn bản không có tab Nội dung, tự động tải file đính kèm gốc (Word/PDF) từ tab Tải về.
- **Cơ chế Resume**: Ghi nhớ tiến trình. Nếu bị dừng giữa chừng, lần sau chạy lại sẽ tự bỏ qua các văn bản đã xử lý thành công.
- **Báo cáo lỗi rõ ràng**: Khi chạy xong, nếu có văn bản tải thất bại, tool sẽ in ra danh sách đầy đủ kèm lý do lỗi và ghi vào `output/state/failed_urls.jsonl` để xử lý lại.

---

## 🐳 Yêu cầu môi trường

- **Docker Desktop** đã được cài đặt và đang chạy.
- Không cần cài Python hay bất kỳ thư viện nào trên máy thật.

---

## 🚀 Hướng dẫn sử dụng

### Bước 1: Build image (chỉ làm lần đầu hoặc sau khi có cập nhật code)

```bash
docker compose build
```

### Bước 2: Chạy tool

**Chế độ tương tác (menu hỏi-đáp)** — phù hợp để tải thủ công:

```bash
docker compose run --rm vbpl-crawler
```

Tool sẽ hỏi lần lượt: loại văn bản cần tải, từ khóa, số trang, có tải tất cả không, có tiếp tục từ lần trước không. Trả lời rồi nhấn Enter.

**Chế độ tham số** — phù hợp để tự động hóa hoặc phân công cho các thành viên:

```bash
# Cú pháp chung
docker compose run --rm vbpl-crawler python pipeline.py [tham-so]

# Ví dụ: tải toàn bộ Nghị định
docker compose run --rm vbpl-crawler python pipeline.py --type-id nghi_dinh --all-pages

# Ví dụ: tải toàn bộ Thông tư, giới hạn 200 văn bản
docker compose run --rm vbpl-crawler python pipeline.py --type-id thong_tu --all-pages --limit 200

# Ví dụ: tải một văn bản cụ thể theo URL
docker compose run --rm vbpl-crawler python pipeline.py --url "https://vbpl.vn/van-ban/chi-tiet/..."

# Ví dụ: tải lại từ đầu, bỏ qua cache cũ
docker compose run --rm vbpl-crawler python pipeline.py --type-id nghi_dinh --all-pages --no-resume
```

**Các tham số dòng lệnh:**

| Tham số | Mô tả |
|---|---|
| `--type-id <loai>` | Loại văn bản cần tải (xem danh sách bên dưới) |
| `--all-pages` | Tải tất cả các trang danh sách |
| `--max-pages <n>` | Chỉ tải tối đa n trang danh sách (mặc định: 1) |
| `--limit <n>` | Giới hạn số văn bản xử lý, 0 = không giới hạn |
| `--url <url>` | Tải một văn bản đơn lẻ theo URL chi tiết |
| `--no-resume` | Bỏ qua tiến trình cũ, tải lại từ đầu |

**Danh sách `--type-id` được hỗ trợ:**

| type-id | Loại văn bản |
|---|---|
| `nghi_dinh` | Nghị định |
| `thong_tu` | Thông tư |
| `quyet_dinh` | Quyết định |
| `bo_luat` | Bộ luật |
| `luat` | Luật |
| `phap_lenh` | Pháp lệnh |
| `chi_thi` | Chỉ thị |
| `nghi_quyet` | Nghị quyết |
| *(để trống)* | Tải tất cả các loại |

### Bước 3: Lấy dữ liệu

Dữ liệu được lưu tại `output/documents/` trên máy thật (được mount tự động từ Docker).

Khi hoàn tất, tool in ra tổng kết:
```
Pipeline finished | success=4920 | failed=2
```

Nếu có lỗi, danh sách các văn bản thất bại sẽ được in ra ngay trên màn hình kèm lý do, và ghi vào `output/state/failed_urls.jsonl` để tra cứu sau.

---

## 📁 Cấu trúc thư mục đầu ra

```
output/
├── documents/                          # Dữ liệu văn bản đã tải
│   ├── Nghị_định/
│   │   ├── 139_2026_NĐ-CP_123456/     # Tên thư mục = Số_hiệu_ItemID
│   │   │   ├── noi_dung.docx
│   │   │   ├── thuoc_tinh.json
│   │   │   ├── luoc_do.json
│   │   │   └── muc_luc.json
│   │   └── ...
│   ├── Thông_tư/
│   └── ...
├── list/                               # Cache danh sách từ API (tái sử dụng khi Resume)
├── state/
│   ├── processed_urls.txt              # Item ID đã xử lý thành công
│   └── failed_urls.jsonl              # Item ID thất bại + lý do lỗi
└── logs/
    └── pipeline.log                    # Log chi tiết toàn bộ quá trình
```
