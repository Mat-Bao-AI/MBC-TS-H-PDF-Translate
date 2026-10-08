# Số đo — PDF Translate SaaS

| Mục | Giá trị | Cách đo |
|---|---|---|
| Cỡ image | 2.69 GB disk usage / 764 MB content size | `docker images vi-translate-saas:local` |
| Build image (lần đầu, cold, không cache) | ~27 phút, rc=0 | `setsid nohup docker build …`, mốc thời gian log + rc file |
| Dịch `e2e/fixtures/sample-2p.pdf` (2 trang) | CHƯA ĐO — bị chặn mạng | `scripts/smoke.sh`. Google Translate (`translate.google.com/m`, endpoint duy nhất mà engine `google` dùng) trả 429 + trang captcha cho IP ra Internet dùng chung của máy chủ thử, xác nhận độc lập bằng `curl` từ cả host lẫn container. Thử lại 3 lần thật (không phải giả lập) trải trong ~20 phút, mỗi lần đều bị chặn lại ngay. Đây là giới hạn hạ tầng bên ngoài, không phải lỗi code. |
| Khởi động → `/health` 200 (sau `docker compose restart`) | 1.5s | vòng `curl -sf /health` mỗi 0.2s ngay sau `docker compose -p <project> restart app` |
| Phiên + danh sách tệp sống sót qua restart | Có — `1 error` giữ nguyên (không phải `1 done`, vì bản dịch thật không hoàn tất — xem dòng trên) | `GET /api/files` bằng cookie phiên cũ, trước và sau `docker compose restart app` |
| Trang SPA (`/files/khong-co`) sau restart | `200` | `curl -o /dev/null -w '%{http_code}'` |
| Đĩa trống trước build | 13 GB | `df -h /` trước Step 7 |
| Đĩa trống sau build + fixture | 8.6 GB | `df -h /` sau Step 7–8 |

(Chỉ điền số đo được; mục nào chưa đo ghi `CHƯA ĐO`.)

## 2026-10-07 — pipeline tách + dựng (offline, bảng dịch giả)

Mục đích: định cỡ `ram` / `cpu` cho form Vibe Host. Đo phần nặng CPU/RAM của mọi job (đọc PDF + model layout
onnxruntime `doclayout.onnx` + dựng lại), bằng engine `handoff` của lõi với bảng dịch GIẢ (`"Bản dịch: <nguyên văn>"`).
Thời gian gọi mạng dịch (Gemini / Cloud Translation / Google) KHÔNG nằm trong số đo.

**Cách đo** (image `vi-translate-saas:local`, ID 26a5a3abfd89, mỗi lần là `docker run --rm` mới = khởi động lạnh; phase
đầu tiên của mỗi lần gồm cả việc upstream ghi `doclayout.onnx.optimized` trong HOME):

```
PDFS=<thư mục chứa attn.pdf, gpt4.pdf>   # arXiv 1706.03762 (15 trang, 2,2 MB), arXiv 2303.08774 (100 trang, 5,2 MB)
docker run --rm --network none [--cpuset-cpus=0|0,1|0-3] -v "$PWD/scripts:/work/scripts:ro" -v "$PDFS:/work/pdfs:ro" \
    vi-translate-saas:local python /work/scripts/measure-pipeline.py /work/pdfs/attn.pdf
```

`scripts/measure-pipeline.py`: prepare (hồ sơ font) → split → rebuild → subset, mỗi phase một dòng JSON. RSS = tổng VmRSS của
mọi `/proc/[0-9]*/status` trong container, lấy mẫu mỗi 0,25 s, lấy đỉnh (trang dùng chung bị cộng lặp → số hơi cao).
CPU = `os.times()` gồm tiến trình con.

**Giới hạn CPU:** `--cpus=N` KHÔNG chạy được ở DinD này (`unable to apply cgroup configuration: cannot enter cgroupv2
"/sys/fs/cgroup/docker" with domain controllers -- it is in threaded mode`; `--cpu-quota`/`--cpu-shares` cùng lỗi). Dùng
`--cpuset-cpus` (ghim cứng vào N lõi; hiệu lực thật: cpu/wall ≈ 1,0 với 1 lõi). Cpuset khác quota CFS: quota cho phép đủ
số luồng rồi bóp nghẹt, cpuset chỉ có N lõi vật lý. Container thấy `os.cpu_count()` = 12 trong mọi lần chạy.

| Tài liệu | CPU | split (s) | rebuild (s) | subset (s) | CPU-s (split+rebuild) | RSS đỉnh container |
|---|---|---|---|---|---|---|
| 15 trang | không giới hạn (lần 1) | 28,4 | 29,1 | 1,3 | 282 | 589 MB |
| 15 trang | không giới hạn (lần 2) | 31,1 | 28,8 | 1,2 | 301 | 590 MB |
| 15 trang | 4 lõi | 82,0 | 77,7 | 1,2 | 535 | 591 MB |
| 15 trang | 2 lõi | 137,2 | 130,8 | 1,1 | 501 | 602 MB |
| 15 trang | 1 lõi | 233,7 | 233,8 | 1,2 | 466 | 601 MB |
| 100 trang | không giới hạn | 167,0 | 185,0 | 1,5 | 2172 | 923 MB |
| 100 trang | 2 lõi | 821,2 | 785,7 | 1,5 | 3082 | 922 MB |
| 100 trang | 1 lõi | CHƯA ĐO | CHƯA ĐO | CHƯA ĐO | — | — |

Ghi chú: `prepare` ~1 s, RSS 136 MB. Trước phase đầu container (python + import) ~46 MB. Cả hai bản dựng ra đủ số trang
(15/15, 100/100), `untranslated` 5 và 31 là đoạn 1 ký tự lõi tự giữ nguyên văn. 15 trang: 151 đoạn/31.216 ký tự; 100
trang: 1268 đoạn/210.636 ký tự. RSS tăng ~4 MB mỗi trang (590 → 923 MB từ 15 → 100 trang). Phase đầu của lần 1 gồm cả
tối ưu model (không tách riêng được: lần 1 và lần 2 chênh trong biên dao động ±3 s). 100 trang ở 1 lõi bỏ qua (quá lâu); ngoại suy theo tỉ lệ 1 lõi/2 lõi của 15 trang (1,74) ≈ 47 phút cho split + rebuild.

Phát hiện: onnxruntime mở theo `os.cpu_count()` (12) chứ không theo số lõi được cấp → khi bị giới hạn, CPU-giây tăng (cpu_ratio
1,9 ở 2 lõi) và thời gian xấp xỉ gấp 4,5 lần (2 lõi) / 7,9 lần (1 lõi) so với không giới hạn, tệ hơn tỉ lệ lõi. Đặt số luồng
onnxruntime theo số lõi cấp phát là việc tối ưu chưa làm (ngoài phạm vi task đo này).

**App (khởi động bình thường, MAX_CONCURRENT_JOBS=1 mặc định):** `docker run` → `/health` 200: 2,7 s. RSS container khi rảnh
sau 30 s: 97 MB. Cỡ image: 2,87 GB (`docker images`).

**Khuyến nghị cho form Vibe Host:**
- `ram`: RSS đỉnh khi có 1 job = app rảnh 97 MB + tiến trình worker (đo độc lập, gồm cả interpreter): 15 trang 97 + 590 = 687 MB;
  100 trang 97 + 923 = 1020 MB. Cộng 25 % đệm: 1020 × 1,25 = 1275 MB → làm tròn lên bước 512 MB = **1536 MB (1,5 GB)**
  (tài liệu ≤ ~15 trang: 687 × 1,25 = 859 MB → 1 GB là đủ). Tài liệu dài hơn 100 trang chưa đo.
- `cpu`: **2**. Tiêu chí ~2× thời gian không giới hạn không đạt ở lõi nào đo được (15 trang: 2 lõi 4,5×, 4 lõi 2,7×, 1 lõi 7,9×); 2 là
  nhỏ nhất trong {1, 2} và còn chạy được: 15 trang ≈ 4,5 phút phần nặng (cộng thời gian mạng), 100 trang ≈ 27 phút ở 2 lõi. 1 lõi:
  15 trang ≈ 7,8 phút, 100 trang ước ~47 phút (ngoại suy, không đo). Muốn tài liệu dài nhanh hơn cần ≥ 4 lõi.

**KHÔNG nằm trong số đo:** thời gian mạng dịch (độ trễ Gemini / Cloud / Google); đường `google_free` chạy inline (cùng phần nặng,
không chạy offline được ở máy chủ thử); OCR; tải đồng thời > 1 job; tài liệu > 100 trang; chạy trên host khác 12 lõi (cpuset ghim
vào lõi 0..N-1 của máy đang bận việc khác, nên số có thể dao động).

## Số đo tham khảo của bản bọc trước (cùng lõi upstream, kiến trúc khác)

Không phải số đo của bản SaaS này: bản bọc trước là lớp web FastAPI mỏng (3 dependency) gọi hàm cấp cao của lõi upstream. Số
này chỉ cho biết cỡ RAM của lõi trên tài liệu dài. Nguồn: đánh giá và số đo của bản bọc trước, ngày 2026-09-04.

- Tài liệu: `grade-7-mathematics.pdf` — sách giáo khoa 288 trang, 22 MB, 247.688 ký tự, 286 trang có chữ, 31 trang có ảnh.
- RAM đỉnh: **1.353 MiB** (worker của lõi dịch). Mã thoát 0, tệp ra 39 MB đủ 288 trang.
- Thời gian: 1.346 giây (≈ 22,4 phút) chạy CLI trực tiếp; 763 giây (≈ 12,7 phút) qua lớp web của bản đó sau khi vá.
- RAM theo số trang (cùng đợt): 7 trang 627 MiB; 90 trang 834 MiB; 170 trang 1.004 MiB; 181 trang 1.038 MiB; 288 trang 1.353 MiB.
- Kết quả kèm theo: 12 đoạn không dịch được (7 hỏng dấu công thức, 5 chữ dịch ra không vừa dòng); 2 trang là ảnh scan, không có OCR.
- Số này không đo bằng `scripts/measure-pipeline.py`; đừng so trực tiếp với các bảng ở trên.
