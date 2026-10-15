# Việc kỹ thuật còn treo (engine dịch Gemini / Cloud Translation)

Gom từ review từng task + review tổng của kế hoạch engine dịch (kế hoạch nội bộ 2026-10-01, không nằm trong repo)
(2026-10-02). Việc vận hành / chờ quyết định (huỷ job trả phí, AGPL, SMTP,
`/data`…) nằm ở mục "Việc còn treo" của `docs/DEPLOY.md` — không lặp lại ở đây.

## Chế độ nâng cao đợt 1b — khôi phục phiên bản, hồ sơ của từng người, dịch thuần tắt nâng cao (kế hoạch nội bộ 2026-10-15, không nằm trong repo)

- **Khôi phục là một job của runner dùng lại đường dịch lại** (`backend/app/engine/jobs.py`, `_execute` → `_stage_restore` → `_finish_rebuild`):
  không worker, không key, không API; `files.restore_version` đi cùng `retranslate_*` + `rebuild_font` của bản nguồn. Mọi điểm chết giữa
  chừng của dịch lại áp dụng y nguyên (thư mục mồ côi, `_put_back`, `_recover`); thêm hai điểm: chết lúc đang chép vào `rebuild/` (chạy
  lại chép lại; `.tmp` bị `_staging` dọn) và tệp/dòng nguồn mất lúc chạy (job lỗi, tệp về `done` với `rebuild_error`, kho nguyên).
- **Bản nguồn có thể bị tỉa trong chính lượt khôi phục** khi nó là bản cũ nhất vượt "Số bản dịch giữ lại" (khôi phục bản cũ nhất khi kho
  đầy): tỉa chạy trong cùng giao dịch SAU khi bản sao đã là bản hiện tại — đúng thiết kế, không mất dữ liệu; hộp xác nhận nói trước.
  Khôi phục không biết số trang (`done_pages/total_pages` về 0).
- **Bảng đoạn đi theo phiên bản** (`_copy_tables`, bước 3 của `_finish_rebuild`): mỗi bản cũ thêm `segments.jsonl` + meta (vài trăm KB
  tới vài MB với tài liệu dài) × tối đa 9 bản, tức tới 9 × cỡ bảng cho mỗi tệp; cửa sổ giữa "cất bản cũ" và commit dài thêm một lần
  chép. Bản cất trước 1b và bản của Google miễn phí không có bảng (`has_tables=false`): khôi phục chúng xoá bảng của thư mục job → dựng
  lại font kế tiếp dịch lại (UI cảnh báo khi động cơ không phải Google miễn phí).
- **Chết sau commit, trước khi thay bảng** (`_replace_tables`): bảng của bản trước vẫn nằm trong thư mục job; lần dịch lại kế tiếp cất chúng
  dưới bản mới hơn. Khôi phục bản đó rồi dựng lại font sẽ dịch lại (tốn lời gọi API; không bao giờ ra bản dịch sai). Cùng lớp với dịch lại từ trước.
- **`translated_at`** là giờ dịch thật của bản (không đổi khi dựng lại font; `_claim_next` không xoá). `file_versions.finished_at` vẫn
  luôn NULL (giữ cột); bản cất trước 1b có `translated_at` NULL → thanh mốc hiện giờ bị thay kèm "(lúc bị thay)"; tệp đang dựng lại
  font lúc nâng cấp cũng NULL tới lần dịch lại kế.
- **Gieo hồ sơ mẫu có tác dụng phụ trong GET** (`GET /api/settings`, `GET /api/profiles` — một lần cho người đang bật chế độ mà chưa gieo):
  gieo hỏng → log, danh sách như chưa gieo, không 500. Người có 16+ hồ sơ riêng lúc bật: gieo dừng ở 20 (mẫu thiếu tạo lại bằng "Khôi
  phục 5 mẫu gốc" khi có chỗ). Tạo hồ sơ đồng thời với "Khôi phục 5 mẫu gốc" có thể vượt 20 khoảng 1 dòng. Tham chiếu `preset:<slug>`
  cũ (snapshot, request) ánh xạ sang dòng gieo tới khi người dùng xoá dòng đó → rơi về "hồ sơ đã mất" (hành vi đợt 1).
- **Dịch thuần ⇒ tắt Chế độ nâng cao** áp cả khi xoá key Gemini đang là mặc định và khi Google gỡ model cuối: tab Hồ sơ dịch biến mất,
  hồ sơ / hồ sơ mặc định / snapshot giữ nguyên; lưu lại key không tự bật. Cần BA duyệt một câu nhắc trong hộp xoá key.
- **Trang Phiên bản** tự dựng thanh mốc bằng nút (Gamut không có Stepper/Timeline); hai iframe PDF + bảng 14 dòng × 3 cột trên điện thoại
  khá dài (xếp dọc dưới 1024px). So sánh chỉ PDF + cấu hình, không so từng đoạn văn.
- **Chưa verify:** E2E (không build image mới cho đợt này); khôi phục với tệp thật trên demo; dịch thật bằng key Gemini với hồ sơ / khôi phục
  (test chỉ dùng transport và worker giả, như đợt 1).
- **Chờ BA duyệt câu chữ** (khoá mới hoặc đổi trong `frontend/src/i18n/vi.json`): `detail.versionsButton`, `detail.currentConfig`,
  `detail.restoredFrom`, `detail.config.note` (đổi câu), `restore.*`, `versions.*`, `profiles.fromPreset`, `profiles.restorePresets*`,
  `profiles.restoredPresets`, `profiles.saveInto`, `profiles.savedInto`, `profiles.saveAsNew`, `profiles.create`, `profiles.intro` (đổi:
  câu cũ sai sau khi gieo mẫu), `profiles.empty` (đổi: như trên), `settings.advance.unsaved`, `settings.advance.plainTurnsOff`,
  `settings.advance.editProfile`, `settings.advance.newProfile`, `settings.key.deleteTurnsOffAdvance`,
  `error.not_restorable`, `error.presets_no_room` (gieo / "Khôi phục 5 mẫu gốc" không đủ chỗ); thông báo chung "Đã lưu hồ sơ." (`profiles.saved`) nay cũng hiện sau khi tạo hồ sơ từ hộp tải lên / dịch lại;
  thông điệp job `RESTORE_SOURCE_MISSING_MESSAGE` (`backend/app/engine/jobs.py`).
  Đã gỡ: `detail.version.title/view/download`, `upload.advanced.aiOnly/needKey`, `profiles.title.presets`.

## Chế độ nâng cao đợt 1 — hồ sơ dịch, snapshot, phiên bản (kế hoạch nội bộ 2026-10-14, không nằm trong repo)

- **Thay bản dịch nay có ba bước đổi tên + một giao dịch** (`backend/app/engine/jobs.py`, `_finish_rebuild` → `_commit_swap`): bản cũ
  → `rebuild/.previous` → `versions/<vid>/` rồi mới commit `file_versions` + `files`. Chết giữa "cất vào kho" và commit → thư mục
  `versions/<vid>/` không có dòng DB (mồ côi); lần chạy lại (`_recover` → `_staging(known_versions)`) trả bản cũ về nếu thư mục job
  thiếu nó, không thì xoá. Chết sau commit, trước `rmtree` thư mục đã tỉa → thư mục mồ côi tới lần dựng lại / dịch lại kế tiếp của
  CHÍNH tệp đó (vài MB treo). Khe "cùng tên tệp" của dựng lại (mục dưới) không xấu hơn.
- **Khe "cùng tên tệp" của dịch lại có thể gắn nhầm cấu hình cho một phiên bản** (khe cỡ mili-giây). Dịch lại giữ nguyên tên bản
  dịch (cùng ngôn ngữ: `<gốc>-<ngôn ngữ>.pdf`) mà tiến trình chết sau bước 2 (bản mới đã vào thư mục job) và trước commit: thư mục
  job đã có tệp đúng tên, nên bước cứu thư mục mồ côi (`_rescue_orphan_versions`) xoá `versions/<vid>/` — tức là xoá bản cũ THẬT
  (chết trước bước 3 thì bản cũ ở `rebuild/.previous` và cũng bị xoá theo `rebuild/`). Lần chạy lại coi bản dịch của lượt bị chết
  là "bản hiện tại" và cất nó vào kho với cấu hình CŨ (`files.config` / ngôn ngữ / engine / model chưa đổi vì chưa commit). Khối
  Phiên bản khi đó có thể giải thích sai vì sao hai bản dịch khác nhau: bảng "Cấu hình" ghi cấu hình cũ cho một bản thực ra dịch
  theo cấu hình mới. Sửa đúng cần cùng cờ "đã thay chưa" trong DB như khe của dựng lại.
- **`file_versions.finished_at` luôn NULL** (giữ cột); từ đợt 1b giờ dịch của bản là `translated_at` (xem mục trên). `_claim_next` đặt `finished_at=None` khi nhận job nên lúc thay bản không còn giờ xong
  của bản cũ. Giữ cột cho đợt 3 (xuất lại PDF ghi giờ).
- **Chỉ dẫn văn phong dài làm Gemini trả JSON hỏng thường hơn** → lô chia đôi đệ quy không có tiến độ (mục "Nên làm trước khi thử key
  thật" bên dưới) → dễ chạm `JOB_STALL_MINUTES`. Vì vậy yêu cầu riêng ≤ 1000, ngữ cảnh ≤ 2000 ký tự; chưa sửa thuật toán chia lô.
- `terms=translate_with_original` / `abbreviations=expand` làm đoạn dài hơn → chữ co lại hoặc tràn khung trong PDF (upstream tự xử) —
  chưa đo với tài liệu thật.
- "Nhất quán thuật ngữ" ở đợt 1 chỉ dựa vào chỉ dẫn chung; mỗi lô 40 đoạn / 8000 ký tự không thấy lô khác → có thể lệch giữa các lô.
  Từ điển (đợt 2) mới giải quyết thật. Gemini 3.x chạy temperature mặc định: hai lần cùng cấu hình vẫn khác chút — bảng "Cấu hình" chỉ
  giải thích phần do cấu hình (UI ghi rõ).
- Dịch lại tệp `error` tại chỗ với chỉ dẫn khác → meta khác → bỏ bảng đoạn đã trả tiền (đúng ý: đoạn đó dịch theo chỉ dẫn cũ). Dịch lại
  tệp `done` vốn luôn dịch từ đầu, không đổi.
- Hàng loạt đổi sang động cơ thuần → snapshot của lượt đó NULL (bản cũ vẫn mang snapshot trong `file_versions`); hàng loạt KHÔNG nhận
  hồ sơ (mỗi tệp giữ hồ sơ/ngữ cảnh riêng).
- Hạ "Số bản dịch giữ lại" không giải phóng đĩa ngay: tỉa ở lần dịch lại thành công kế tiếp của từng tệp. Tới 10 PDF/tệp.
- `GET /api/files/{id}` thêm một truy vấn `file_versions` + một `stat()` mỗi bản khi poll 2 s ở trang chi tiết — không ở danh sách.
- **Chưa verify:** dịch thật bằng key Gemini với hồ sơ/ngữ cảnh (test chỉ dùng transport giả); E2E chưa chạy cho đợt này (xem
  `docs/TEST_LOG.md`).
- Giao diện (nhỏ): chiều cao khung chờ của trang Cài đặt › Dịch thuật (`SKELETON_MODE_HEIGHT`) chưa đo lại sau khi thêm công tắc và
  ô chọn hồ sơ mặc định.
- **Chờ BA duyệt câu chữ:** `settings.advance.*`, `settings.tab.profiles`, `profiles.*` (nhãn 9 trường và từng giá trị, tên 5 hồ sơ mẫu +
  `custom_instructions` của mẫu nằm ở `backend/app/profiles/presets.py`), `upload.advanced.*`, `retranslate.bulkKeepsConfig`,
  `file.version`, `detail.version.*` (đợt 1b đã gỡ `title`/`view`/`download` cùng khối Phiên bản cũ; `label`/`current`/`missing`/`basic`
  còn dùng), `detail.config.*`, `system.versions.*`, `system.registration.title` (đổi), `error.advance_mode_off`,
  `error.style_requires_ai`, `error.profile_not_found`, `error.invalid_style`, `error.invalid_profile`, `error.too_many_profiles`,
  `error.preset_readonly`, `error.invalid_max_versions`, `error.version_not_found`; câu tiếng Anh trong `backend/app/profiles/prompt.py`
  (prompt engineering, không phải wording UI nhưng BA nên biết). Lưu ý thêm cho BA: (1) đã bỏ ở đợt 1b — mục "Nâng cao" không còn hiện với động cơ thuần;
  (2) nút "Đặt về mặc định" của thẻ Hệ thống nay đặt lại cả giới hạn hàng đợi lẫn số bản dịch giữ lại (nhãn có thể cần BA chỉnh).

## Cài đặt lần đầu, Cài đặt › Hệ thống, Dịch lại (kế hoạch nội bộ 2026-10-05, không nằm trong repo)

- **Dịch lại thất bại làm mất các đoạn đã dịch của chính lượt đó** (quyết định (7) của kế hoạch). Worker lỗi / đứng /
  quá giờ / thiếu key / lỗi nội bộ → thư mục `rebuild/` bị xoá như dựng lại thất bại: bản cũ + bảng đoạn cũ nguyên vẹn,
  nhưng các đoạn của lựa chọn MỚI đã dịch (đã trả tiền với Gemini / Cloud) mất — bấm "Dịch lại" lần nữa là trả tiền lại
  từ đầu. Khác lượt dịch đầu (bảng ở thư mục job được giữ cho "Dịch lại" sau lỗi). Restart giữa chừng thì giữ
  (`_staging(keep_job_tables=False)` giữ `rebuild/segments.jsonl` + `segments.meta.json` cho lượt chạy lại).
- **Khe hẹp "cùng tên tệp" nay cũng gặp ở dịch lại cùng ngôn ngữ.** Khe đã biết của dựng lại (mục dưới: tiến trình chết
  sau `os.replace` chuyển bản mới vào nhưng trước khi DB commit, bản mới trùng tên bản cũ) xảy ra cả với một lượt dịch
  lại giữ nguyên ngôn ngữ (tên `<gốc>-<ngôn ngữ>.pdf` không đổi): lần chạy lại xoá `rebuild/.previous`; nếu lần đó cũng
  lỗi thì nhãn ngôn ngữ / engine / model cũ đi với bản dịch mới. Chỉ khi tiến trình chết / lỗi I/O đúng giữa hai thao tác.
- **Một luồng dịch, không xoay vòng giữa người dùng** (spec §13): nâng hạn chờ (Cài đặt › Hệ thống) + một người dịch lại
  hàng loạt → người khác đợi hết lượt của người đó. Lượt dịch lại xếp theo `created_at` của tệp nên chen trước tệp mới
  hơn đang chờ (như dựng lại).
- **Không có thư thì lộ email nào đã đăng ký.** Khi chưa cấu hình SMTP, đăng ký trả cùng một phản hồi cho email mới và
  email đã có, nhưng tài khoản mới dùng ngay: đăng ký rồi đăng nhập bằng mật khẩu vừa đặt — được = email còn trống,
  không được = email đã có người dùng. Cố hữu của chế độ không thư; app công khai nên cấu hình SMTP.
- **Không có thư thì chiếm được email của người khác.** Đăng ký bằng địa chỉ của người khác cùng mật khẩu tự đặt là có
  ngay một tài khoản ĐÃ xác nhận (không có thư nào để chứng minh mình giữ hộp thư). Chủ thật của địa chỉ: đăng ký nhận
  202 mà không đăng nhập được, "Quên mật khẩu" trả 409 `mail_not_configured` — chỉ lấy lại được bằng "Quên mật khẩu" sau
  khi instance có SMTP. Cố hữu của spec §5; app công khai nên cấu hình SMTP hoặc đóng đăng ký (Cài đặt › Hệ thống).
- **Chứng chỉ TLS của SMTP luôn được kiểm** (`ssl.create_default_context()`, cả STARTTLS lẫn SSL/TLS): máy chủ SMTP
  dùng chứng chỉ tự ký / CA nội bộ lỗi `SSLCertVerificationError` — chưa có tuỳ chọn tin chứng chỉ riêng.
- **Lưu SMTP trong Cài đặt rồi thì `SMTP_PASSWORD` env không còn tác dụng**: form điền sẵn từ env, lưu với ô mật khẩu
  trống là chép mật khẩu env (mã hoá) vào DB; đổi env sau đó không áp dụng cho tới khi "Xoá cấu hình, quay về biến môi
  trường".
- Hàng loạt "Giữ cài đặt riêng của từng tệp" không kiểm key từng tệp: tệp Gemini / Cloud mà key đã xoá → job lỗi "Chưa có
  API key…" (tệp đã xong: giữ bản cũ, lý do ở `rebuild_error`).
- SMTP nhập sai mà không bấm "Gửi thư thử" → thư rơi vào log; `mail_enabled` là true nên đăng ký mới đòi xác nhận mà không
  ai nhận được thư (chưa có dải "lỗi gửi thư gần nhất" — chỉ log).
- Tài khoản chưa xác nhận từ thời còn SMTP, SMTP sau đó bị gỡ → kẹt tới khi có SMTP lại (spec §5, không nới).
- Quản trị viên sau khi nâng 0005 là người tạo tài khoản sớm nhất; không có API / trang chuyển quyền (spec §15).
- `rebuild_error` dùng chung cho dựng lại và dịch lại (không có cột phân biệt) → trang chi tiết một câu chung "Không thay
  được bản dịch: …".
- Hộp "Dịch lại" khoá nút xác nhận bằng `disabled` đưa qua `confirmCta` của `Dialog` Gamut (kiểu không khai, Dialog trải
  cả object lên `FillButton`) — test `keeps Dịch lại locked until the settings are known…` đỏ nếu nâng Gamut làm mất hành vi này.
- `_check_pending` đọc `instance_settings` mỗi lần tải lên / dựng lại / dịch lại (một truy vấn nhỏ) — không đáng kể.
- **Chờ BA duyệt câu chữ:** khoá mới `setup.*`, `system.*`, `retranslate.*`, `register.closed*` / `register.ready*`,
  `mail.notConfigured`, `shell.system`, `shell.smtpBanner*`, `settings.tab.system`, `action.retranslate*`, `error.setup_required`,
  `error.setup_done`, `error.invalid_setup_token`, `error.admin_required`, `error.registration_closed`,
  `error.mail_not_configured`, `error.invalid_smtp`, `error.smtp_failed`, `error.invalid_limit`, `error.last_admin`,
  `error.not_retranslatable`; nội dung mới của `rebuild.failed`; thư thử "Thư thử từ PDF Translate".

## Bố cục, tài khoản và font bản dịch (kế hoạch nội bộ 2026-10-02, không nằm trong repo)

- **Subset font (§2.6 của spec) — thí nghiệm ĐẠT, đã đưa vào worker.** `Document.subset_fonts()` của PyMuPDF trên
  hai bản dựng Liberation Sans / Serif: text từng trang trước/sau giống hệt, pixel giống hệt. Nhỏ hơn ~35% ở thí
  nghiệm lúc viết plan (1.022.745 → 665.101 B và 1.007.772 → 645.102 B) và ~43% ở lần kiểm trong image của Task 8
  (`font-render-check.py`: 871.312 → 496.090 B và 853.489 → 486.970 B). Worker vẫn kiểm lại cho TỪNG tệp: chỉ thay khi
  text giống hệt và tệp nhỏ hơn; không đạt thì giữ bản chưa subset và ghi một dòng `font_subset skipped=…` /
  `font_subset failed=…` vào `worker-stderr.log` — thấy dòng `text_changed` thường xuyên nghĩa là PyMuPDF đổi cách
  subset, cần xem lại. Tài liệu ≥ 200 trang bỏ qua subset (không có dòng tiến độ trong lúc subset, dễ chạm
  `JOB_STALL_MINUTES`).
- **Lỗi hồ sơ font để lại đúng một dòng stderr** `font_profile code=<mã> detail=<chi tiết>` (vd
  `import:ModuleNotFoundError:pdf2zh.high_level`, `hook:BASE14_STYLE_FONTS:missing`, `files:sans:BoldItalic`,
  `error:<Class>`) trong `worker-stderr.log` (dựng lại lỗi: `rebuild-stderr.log`) — nơi đầu tiên cần xem khi job lỗi
  `font_profile_unsupported` / `font_files_missing`.
- **Nâng pin upstream phải chạy `scripts/font-render-check.py` trong image** (lệnh ở `docs/DEPLOY.md`, mục "Font bản dịch"): kiểm tra
  hook chỉ thấy tên/kiểu còn đó, không thấy upstream ngừng gọi các hàm đã gán đè; chỉ dựng thật mới lộ ra.
- **Dựng lại thất bại giữ bản dịch cũ** (tải được, `rebuild_error` giữ thông điệp) và giữ các đoạn đã dịch trả tiền
  trong `segments.jsonl`.
- **Gỡ model Gemini bị Google gỡ:** job lỗi `model_unavailable` → model bị bỏ khỏi danh sách của key; nếu là mặc định
  thì về Flash-Lite / model đầu tiên còn lại / Google miễn phí, thông điệp lỗi của job nói rõ mặc định mới. Tệp đã
  có giữ `files.model` cũ; hộp "Dịch lại" chọn sẵn model mặc định khi model của tệp không còn trong danh sách của key,
  nên dịch lại không lỗi lại vì model cũ. Lưu lại key nạp lại danh sách từ Google: model còn được liệt kê sẽ quay lại, job lỗi kế tiếp lại gỡ.
- **"Dựng lại" với Google miễn phí = dịch lại từ đầu** (gọi Google miễn phí lần nữa, chậm hơn); Gemini / Cloud dùng
  lại `segments.jsonl` — chỉ gọi API cho các đoạn lần trước không dịch được (nếu có).
- Khung PDF bản dịch tải lại một lần lúc runner nhận job dựng lại (`finished_at` về NULL đổi `&v=`) — vô hại, vẫn là
  bản cũ.
- `email_tokens.kind` là String(10): `new_email` vừa khít; kind kế tiếp phải ≤ 10 ký tự hoặc nới cột.
- Tên hiển thị bị từ chối khi chứa ký tự điều khiển, định dạng vô hình, surrogate lẻ hoặc dấu phân cách dòng/đoạn Unicode (`Cc`, `Cf`, `Cs`, `Zl`, `Zp`) hoặc dài hơn 50 ký tự. Emoji đơn (kể cả màu da, cờ quốc gia) và chữ ngoài BMP vẫn nhận; emoji ghép bằng ZWJ (U+200D, vd 👨‍👩‍👧, 🏳️‍🌈) và cờ dạng tag (vd 🏴󠁧󠁢󠁥󠁮󠁧󠁿) **bị từ chối** vì U+200D / ký tự tag thuộc `Cf` — đã chuyển BA quyết có nới hay không.
- Bộ đếm thử mật khẩu (đăng nhập + đổi mật khẩu / đổi email / xoá tài khoản) nằm trong RAM: mất khi restart (như cũ).
- **Chờ BA duyệt câu chữ:** các khoá mới trong `frontend/src/i18n/vi.json` (`account.*`, `confirmEmail.*`, `font.*`,
  `rebuild.*`, `settings.tab*`, `shell.accountMenu`, `shell.translationSettings`, `login.deleted`, `error.wrong_password`,
  `error.invalid_display_name`, `error.same_email`, `error.email_taken`, `error.unsupported_font`,
  `error.not_rebuildable`), 3 mẫu thư trong `backend/app/auth/account.py`, 2 câu lỗi font trong
  `backend/app/engine/fonts.py`, câu nối "Đã gỡ model…" trong `backend/app/engine/jobs.py`.
  Thông điệp lỗi dựng lại / dịch lại nay đi qua câu chung "Không thay được bản dịch: … Vẫn giữ bản dịch trước."; lý do
  bên trong vẫn là câu của job dịch ("bấm Dịch lại" — tệp `done` nay có nút này) — BA duyệt.
- **Dựng lại — các khe hẹp còn lại** (`backend/app/engine/jobs.py`, chỉ xảy ra khi tiến trình chết / lỗi I/O đúng
  giữa hai thao tác): chết sau khi đã chuyển bản mới vào nhưng trước khi ghi DB (cùng tên tệp) → lần chạy lại xoá
  `rebuild/.previous`, nếu lần chạy lại cũng lỗi thì nhãn font cũ đi với bản dựng mới; `_put_back` unlink lỗi thì bỏ
  qua bước khôi phục; `_restore_tables` vẫn bỏ bảng bị cắt giữa một ký tự UTF-8 / có U+2028 trong bản dịch. Sửa đúng
  cần biết swap đã commit hay chưa (một cờ trong DB) — đừng "luôn khôi phục .previous".
- Hai lượt dựng lại của hai tệp khác nhau bấm cùng lúc có thể cùng lọt qua giới hạn hàng chờ (như tải lên); job dựng
  lại xếp theo `created_at` của tệp nên chen lên trước các tệp mới hơn đang chờ.
- `verify_nonce` giả được đặt ở mọi phản hồi 202 của đăng ký / gửi lại thư (chống dò email): lượt gửi lại bị chặn
  60 s thay nonce thật của trình duyệt → bấm link đầu tiên vẫn xác thực nhưng không tự đăng nhập. `resend-verification`
  còn lệch thời gian nhỏ giữa email chưa xác thực và còn lại (đã giới hạn 10 lần / 15 phút / IP).
- Hộp tải lên cuộn phần nội dung bằng selector `[data-testid="modal-content"]` nội bộ của Gamut — test đơn vị sẽ đỏ
  nếu nâng Gamut làm mất test id đó.
- Xoá tài khoản đúng lúc một lượt tải lên khác đang ghi tệp: trả 401 + dọn thư mục job, nhưng có thể còn thư mục
  `users/<id>/` rỗng; mọi `IntegrityError` lúc tạo tệp đều thành 401 (nguyên nhân thật duy nhất hiện nay là user đã bị xoá).
- Menu avatar: bấm ra ngoài (vd vào ô tìm kiếm) đóng menu rồi kéo focus về avatar (spec yêu cầu trả focus).
- Stack demo trên máy chủ thử: ngày 2026-10-06 Docker-in-Docker của máy bị xoá khi khởi động lại → mất volume dữ liệu
  (tài khoản demo cũ, user của E2E cũ, mọi tệp) cùng mọi tag image. Demo chạy lại trên CSDL trống ở `0005`, dữ liệu để ở
  một bind mount ngoài git (sống qua khởi động lại); từ bản 2026-10-05 E2E chạy trên stack dùng một lần, không thêm user vào
  CSDL demo nữa. Bài học cho người vận hành: dữ liệu phải ở ổ bền ngoài vòng đời của Docker (`docs/DEPLOY.md`, "Ổ lưu trữ bền
  cho `/data`").

## Nên làm trước khi thử key thật với tài liệu dài

- **Lô bị chia đôi đệ quy không có tiến độ** (`backend/app/providers/client.py`, `translate_chunk`): lô 40 đoạn
  mà model trả sai ở mọi cấp → ~79 request nối tiếp, không dòng tiến độ nào → có thể vượt `JOB_STALL_MINUTES`
  (chắc chắn với 3.1 Pro). Kết quả lô con không vào `segments.jsonl` nên "Dịch lại" trả tiền lại cả lô.
  Hướng sửa: tiến độ theo lô con, giới hạn số lần chia / độ sâu, đưa bảng lô con qua `on_batch`.

## Minor

- `ProviderError.diagnostic()` thay key bằng `***` SAU khi đã lọc ký tự + cắt 80 ký tự → key dài > 80 ký tự hoặc
  có ký tự ngoài `[A-Za-z0-9_.:@/-]`, nếu Google có lặp lại, sẽ lọt một phần. Key Google thật (39 ký tự) không
  bị. Sửa: thay key trên giá trị thô trước khi lọc.
- Lỗi không phải `ProviderError` trong vòng dịch (vd `OSError` khi ghi `segments.jsonl` lúc đĩa đầy) không gọi
  `gate.stop()` → các lô đang chạy vẫn chạy hết (vẫn tính tiền) rồi job mới lỗi. Sửa: `except BaseException:
  gate.stop(); raise`.
- Hộp tải lên: nút "Dịch" bị khoá suốt lúc `GET /api/settings` treo (`apiFetch` không có timeout).
- Key Cloud hợp lệ nhưng đã hết hạn mức ngày không lưu được (502 `provider_unavailable`) tới khi hạn mức reset.
- 403 không có `reason` nhận diện được (vd "API key was reported as leaked") → `provider_rejected`; có thể thêm
  lưới theo tiền tố message như với "API key not valid".
- Thay key có thể để `default_model` nằm ngoài danh sách model mới (khi dịch thì tự rơi về model mặc định).
- `requests.Session` dùng chung giữa user/thread (Google API không đặt cookie nên hiện vô hại).
- `assert row is not None` sau khi đọc lại vì `IntegrityError` (lưu key lần đầu) sẽ thành 500 nếu sau này thêm
  ràng buộc khác.
- Che key trong log là `str.replace` thuần (bản key đã biến đổi / một phần không bị che); chưa có test riêng
  cho nhánh lọt key qua đuôi stderr với key thật.
- `verify_key` ném `ValueError` trần với provider lạ (nơi gọi đã kiểm provider).
- Chưa có test vector cố định khoá định dạng mã hoá key (AES-GCM) lưu trong DB.
- Chưa có test trực tiếp cho thẻ key Google Cloud ở trang Cài đặt.
- Gemini 3.x chạy ở temperature mặc định của Google (1.0, đúng khuyến nghị cho 3.x) — độ ổn định bản dịch chưa
  kiểm bằng key thật.
- `segments.jsonl` giữ lại cả sau job lỗi (để "Dịch lại" không trả tiền lại) → văn bản tài liệu nằm trên đĩa
  tới khi xoá tệp.
- Image `vi-translate-saas:local` đã dựng đầy đủ lại từ `Dockerfile` ngày 2026-10-06 (commit `93e5212`, sau khi Docker-in-Docker của
  máy chủ thử bị xoá); các lần chỉ đổi mã sau đó dựng một lớp mỏng lên trên (`docs/TEST_LOG.md`). Từ 2026-10-07 `Dockerfile` chạy bằng
  user thường uid 10001 nhưng bản đó mới được kiểm qua bản dựng mỏng tương đương — chưa dựng đầy đủ (đĩa không đủ,
  xem "Việc còn treo" trong `docs/DEPLOY.md`).

## Đóng gói Vibe Host (2026-10-07)

- **onnxruntime mở số luồng theo `os.cpu_count()` (12 ở máy đo), không theo số lõi được cấp.** Dưới giới hạn 2 lõi, CPU-giây
  tăng ×1,9 (282 → 501 CPU-s cho 15 trang; `docs/MEASUREMENTS.md` 2026-10-07). Việc tiếp theo: giới hạn số luồng intra-op
  theo số lõi được cấp, trong tiến trình con của worker (cùng cơ chế móc như phần ghi đè phông; không sửa upstream).
  Mức giảm kỳ vọng: CHƯA ĐO.
- **`--cpus` / hạn mức CFS chưa kiểm được**: Docker-in-Docker của máy chủ thử (cgroup v2 ở chế độ threaded) từ chối `--cpus`,
  `--cpu-quota`, `--cpu-shares`; số đo dùng `--cpuset-cpus`. Cách nền tảng áp hạn mức CPU lên container: CHƯA ĐO.
- **Cuộc đua đã thấy một lần trong log E2E**: `FileNotFoundError` trên `/data/users/<u>/<f>/worker-stderr.log` khi một tệp bị
  xoá đúng lúc job của nó bắt đầu (xoá tệp / job so với lúc runner khởi động). Test vẫn qua (báo cáo task C). Cần một ticket backend.
- **`Dockerfile` đầy đủ chưa dựng lại từ sau khi đổi sang user thường** (thiếu đĩa) — chỉ kiểm bản dựng mỏng tương đương
  (chi tiết ở mục "Image `vi-translate-saas:local`" phía trên và "Việc còn treo" của `docs/DEPLOY.md`).
- **Câu chữ cần BA duyệt**: khi đã cấu hình SMTP nhưng chưa biết địa chỉ trang, dải báo, thẻ đổi email và trang quên mật khẩu vẫn
  ghi "chưa cấu hình SMTP" (khoá `shell.smtpBanner`, `account.email.noMail`, `mail.notConfigured`, `error.mail_not_configured`).
- Chiều cao khung chờ (skeleton) của thẻ SMTP đặt 620 px — chưa đo.

## Chờ BA duyệt câu chữ

- Câu báo lỗi mới của worker (`ERROR_MESSAGES` trong `backend/app/engine/handoff_worker.py`) và các khoá
  `error.*`, `status.runningStep`, `settings.key.switchedToAi` trong `frontend/src/i18n/vi.json` — bản nháp.
- Ghi chú quyền riêng tư (Google có thể dùng nội dung ở gói miễn phí) mới có ở thẻ Gemini, chưa có ở thẻ Cloud.
