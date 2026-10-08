// QUAN TRỌNG: chạy file này với STACK DÙNG MỘT LẦN `pdf-translate-e2e` từ `e2e/compose.fresh.yml` (image `vi-translate-saas:e2e`,
// DB TRỐNG, MAIL_DEV_LOG=1, cổng 127.0.0.1:18082) — KHÔNG phải stack chạy thử `pdf-translate` (DB đã có người dùng thì không còn
// trình cài đặt /setup). Image e2e chỉ khác ở WORKER_CMD: worker giả `backend/tests/fake_worker.py` thay cho nhân dịch
// thật — từ một số máy chủ endpoint dịch miễn phí của Google trả captcha cho IP egress, và E2E không nên phụ thuộc dịch vụ
// bên thứ ba. Bài test chứng minh các luồng WEB (cài đặt lần đầu, Cài đặt › Hệ thống, đăng ký qua link trong log, upload,
// tiến độ, tải xuống, dựng lại, dịch lại đơn + hàng loạt, tìm, phân trang, xoá hàng loạt, xoá, cách ly giữa user, tài
// khoản, đóng/mở đăng ký, sống qua restart, bố cục 360px) — nhân dịch thật được phủ riêng bởi scripts/smoke.sh.
//
// Khởi động đúng stack (DB trống mỗi lần — `down -v` CHỈ với project pdf-translate-e2e):
//   export $(cat .build/local.env)
//   docker compose -p pdf-translate-e2e -f e2e/compose.fresh.yml down -v
//   docker compose -p pdf-translate-e2e -f e2e/compose.fresh.yml up -d --no-build
//   (cd e2e && npx playwright test)   # SECRET_KEY phải còn trong env: lệnh `docker compose` dưới đây nạp compose.fresh.yml
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { expect, test, type BrowserContext, type Page } from '@playwright/test';

const PROJECT = process.env.E2E_COMPOSE_PROJECT ?? 'pdf-translate-e2e';
const COMPOSE_FILE = process.env.E2E_COMPOSE_FILE ?? 'e2e/compose.fresh.yml';
const ROOT = fileURLToPath(new URL('../..', import.meta.url));
const SAMPLE = fileURLToPath(new URL('../fixtures/sample-2p.pdf', import.meta.url));
const SEED = fileURLToPath(new URL('../seed.py', import.meta.url));
const PASSWORD = 'mat-khau-e2e';
// Marker `rebuildslow` của worker giả: lượt dựng lại / dịch lại ngủ thêm 10 s — đủ lâu để thấy bản cũ vẫn tải được.
const SLOW_STEM = 'bao-cao-rebuildslow';
const SLOW_NAME = `${SLOW_STEM}.pdf`;

const docker = (args: string[], input?: Buffer) =>
  execFileSync('docker', ['compose', '-p', PROJECT, '-f', COMPOSE_FILE, ...args], { cwd: ROOT, encoding: 'utf-8', input });

/** Đường dẫn (kèm token) trong thư gần nhất gửi tới `email` có link `route` — MAIL_DEV_LOG in thư ra log container.
 * Thư gửi sau phản hồi (BackgroundTasks) nên dò lại tới ~10 s; chỉ đọc 2000 dòng cuối để không vượt maxBuffer. */
async function mailPath(email: string, route: '/verify-email' | '/confirm-email'): Promise<string> {
  const escaped = email.replace(/[.+]/g, '\\$&');
  const pattern = new RegExp(`MAIL to=${escaped}[\\s\\S]*?(${route}\\?token=[\\w-]+)`, 'g');
  let found = '';
  await expect.poll(() => {
    const logs = docker(['logs', 'app', '--no-log-prefix', '--tail=2000']);
    const matches = [...logs.matchAll(pattern)];
    found = matches.length ? matches[matches.length - 1][1] : '';
    return found;
  }, { message: `không thấy thư ${route} cho ${email} trong log`, timeout: 10_000 }).not.toBe('');
  return found;
}

async function openAccountMenu(page: Page) {
  await page.getByRole('button', { name: 'Menu tài khoản' }).click();
  await expect(page.getByRole('menu')).toBeVisible();
}

async function signUp(page: Page, email: string) {
  await page.goto('/register');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Mật khẩu').fill(PASSWORD);
  await page.getByRole('button', { name: 'Tạo tài khoản' }).click();
  await expect(page.getByText('Kiểm tra hộp thư của bạn')).toBeVisible(); // MAIL_DEV_LOG: vẫn phải xác nhận email
  await page.goto(await mailPath(email, '/verify-email'));
  await expect(page.getByRole('heading', { name: /^Xin chào/ })).toBeVisible();
}

async function signIn(page: Page, email: string) {
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Mật khẩu').fill(PASSWORD);
  await page.getByRole('button', { name: 'Đăng nhập', exact: true }).click();
  await expect(page.getByRole('heading', { name: /^Xin chào/ })).toBeVisible();
}

/** Mọi job đã xếp đều chạy xong: hàng chờ của instance rỗng (`/health` → queue 0 — chỉ đếm tệp CHỜ, không tính tệp
 * đang chạy) VÀ không tệp nào của người dùng này còn `queued` / `running` (≤ 100 tệp — đủ cho bài này). */
async function queueDrained(page: Page, timeout = 120_000) {
  await expect.poll(async () => {
    const waiting = (await (await page.request.get('/health')).json()).queue as number;
    const items = (await (await page.request.get('/api/files?page=1&page_size=100')).json()).items as { status: string }[];
    return waiting + items.filter((item) => item.status === 'queued' || item.status === 'running').length;
  }, { timeout }).toBe(0);
}

/** Ô chọn của Gamut chỉ dành cho trình đọc màn hình (không bấm được bằng chuột): người dùng bấm vào nhãn hiển thị của nó. */
async function tick(page: Page, name: string) {
  const box = page.getByRole('checkbox', { name, exact: true });
  await page.locator(`label[for="${await box.getAttribute('id')}"]`).click();
  await expect(box).toBeChecked();
}

test('cài đặt lần đầu → hệ thống → đăng ký → dịch (worker giả) → dựng lại → dịch lại đơn + hàng loạt → tìm → phân trang → xoá hàng loạt → xoá → tài khoản → đóng/mở đăng ký → sống qua restart', async ({ page, browser }) => {
  const stamp = Date.now();
  const baseURL = test.info().project.use.baseURL;
  const adminEmail = `admin-${stamp}@example.com`;
  let email = `e2e-${stamp}@example.com`;
  // Font tự lưu trữ: trình duyệt không được gọi origin nào ngoài chính app (không còn codecademy.com cho Apercu/Suisse).
  // Gắn ở mức context cho MỌI context của spec (kể cả của `page`) để mọi trang, kể cả popup, đều được kiểm.
  const appOrigin = new URL(baseURL!).origin;
  const requestedUrls: string[] = [];
  const woff2FromApp: string[] = [];
  const woff2WrongType: string[] = [];
  const watchOrigins = (context: BrowserContext) => {
    context.on('request', (req) => requestedUrls.push(req.url()));
    context.on('response', (res) => {
      if (!/^https?:/.test(res.url())) return;
      const u = new URL(res.url());
      if (u.origin === appOrigin && u.pathname.endsWith('.woff2') && res.status() < 400) {
        // Chromium không ép MIME của phông: nếu không kiểm ở đây thì chỉ test đơn vị chứng minh spa.py trả font/woff2.
        woff2FromApp.push(u.pathname);
        if (res.headers()['content-type'] !== 'font/woff2') woff2WrongType.push(`${u.pathname} → ${res.headers()['content-type']}`);
      }
    });
  };
  watchOrigins(page.context());
  const newWatchedContext = async () => {
    const context = await browser.newContext({ baseURL });
    watchOrigins(context);
    return context;
  };
  const adminContext = await newWatchedContext();
  const admin = await adminContext.newPage();

  await test.step('DB trống: đăng ký bị chặn; mở / là gặp /setup → tạo quản trị viên → bỏ qua SMTP → trang chủ; /setup đóng sau đó', async () => {
    expect(await (await admin.request.get('/api/setup/status')).json()).toEqual(
      { needs_setup: true, setup_token_required: false, registration_open: true, mail_enabled: true });
    const early = await admin.request.post('/api/auth/register', {
      headers: { 'X-Requested-With': 'fetch' }, data: { email: `chen-${stamp}@example.com`, password: PASSWORD },
    });
    expect(early.status()).toBe(409); // không ai chen tạo tài khoản thường trước trình cài đặt
    expect(await early.json()).toEqual({ detail: { code: 'setup_required' } });
    await admin.goto('/');
    await expect(admin).toHaveURL(/\/setup$/);
    await expect(admin.getByText('Bước 1/2 · Tài khoản quản trị')).toBeVisible();
    await expect(admin.getByLabel('Mã cài đặt')).toHaveCount(0); // stack không đặt SETUP_TOKEN
    await admin.getByLabel('Tên hiển thị (tuỳ chọn)').fill('Quản trị E2E');
    await admin.getByLabel('Email').fill(adminEmail);
    await admin.getByLabel('Mật khẩu', { exact: true }).fill(PASSWORD);
    await admin.getByLabel('Nhập lại mật khẩu').fill(PASSWORD);
    await admin.getByRole('button', { name: 'Tạo tài khoản quản trị' }).click();
    await expect(admin.getByText('Bước 2/2 · Gửi thư (SMTP)')).toBeVisible();
    await expect(admin).toHaveURL(/\/setup$/); // bước 2 nằm trong state trang, không đổi route
    await admin.getByRole('button', { name: 'Bỏ qua' }).click();
    await expect(admin.getByRole('heading', { name: 'Xin chào, Quản trị E2E!' })).toBeVisible();
    await expect(admin.getByTestId('smtp-banner')).toHaveCount(0); // MAIL_DEV_LOG=1 tính là đã cấu hình thư
    await admin.goto('/setup');
    await expect(admin).toHaveURL(/\/$/); // đã có người dùng: /setup đóng
    expect((await (await admin.request.get('/api/setup/status')).json()).needs_setup).toBe(false);
  });

  await test.step('quản trị viên: menu avatar → Hệ thống (SMTP chế độ log dev, đăng ký đang mở) rồi đăng xuất', async () => {
    await openAccountMenu(admin);
    await admin.getByRole('menuitem', { name: 'Hệ thống' }).click();
    await expect(admin).toHaveURL(/\/settings\/system$/);
    await expect(admin.getByRole('link', { name: 'Hệ thống' })).toHaveAttribute('aria-current', 'page');
    const smtp = admin.getByRole('region', { name: 'Gửi thư (SMTP)' });
    await expect(smtp.getByText('Chế độ log cho dev (MAIL_DEV_LOG).')).toBeVisible();
    await expect(smtp.getByRole('button', { name: 'Xoá cấu hình, quay về biến môi trường' })).toBeDisabled();
    await expect(admin.getByRole('checkbox', { name: 'Cho phép đăng ký tài khoản mới' })).toBeChecked();
    await openAccountMenu(admin);
    await admin.getByRole('menuitem', { name: 'Đăng xuất' }).click();
    await expect(admin).toHaveURL(/\/login(\?|$)/);
  });

  await signUp(page, email);

  await test.step('người thường: Cài đặt (menu avatar → Dịch thuật) có hai tab, không có Hệ thống; /settings/system về Tài khoản', async () => {
    await openAccountMenu(page);
    await expect(page.getByRole('menuitem', { name: 'Hệ thống' })).toHaveCount(0);
    await page.getByRole('menuitem', { name: 'Cài đặt dịch thuật' }).click();
    await expect(page).toHaveURL(/\/settings\/translation$/);
    await expect(page.getByRole('link', { name: 'Dịch thuật' })).toHaveAttribute('aria-current', 'page');
    await expect(page.getByRole('link', { name: 'Hệ thống' })).toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'Gemini (Google AI Studio)' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Google Cloud Translation' })).toBeVisible();
    await expect(page.getByText('Chưa có key')).toHaveCount(2);
    await expect(page.getByLabel('Dịch thuần')).toBeChecked();
    await expect(page.getByLabel('Dịch bằng AI')).toBeDisabled();
    await expect(page.getByLabel('Font chữ bản dịch')).toHaveValue('auto');
    await page.goto('/settings/system');
    await expect(page).toHaveURL(/\/settings\/account$/);
    await page.goto('/');
  });

  await test.step('tải lên và dịch bằng worker giả (Dịch thuần, không phải nhân dịch thật)', async () => {
    // Vùng kéo thả ở đầu trang chủ: chọn tệp qua ô input của vùng → hộp tải lên mở sẵn tệp đó.
    await expect(page.getByTestId('hero-dropzone')).toContainText('Kéo thả tệp PDF vào đây hoặc chọn từ máy tính');
    await page.getByTestId('hero-file-input').setInputFiles(SAMPLE);
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Đã chọn: sample-2p.pdf')).toBeVisible();
    await expect(dialog.getByLabel('Dịch thuần')).toBeChecked();
    await dialog.getByText('Dịch thuần', { exact: true }).click(); // chọn rõ ràng, như người dùng thật
    await expect(dialog.getByLabel('Google miễn phí')).toBeChecked();
    await expect(dialog.getByLabel('Font chữ bản dịch')).toHaveValue('auto');
    await dialog.getByRole('button', { name: 'Dịch', exact: true }).click();
    await expect(page).toHaveURL(/\/files\/[0-9a-f]{12}$/);
    const translated = page.getByRole('link', { name: 'Tải bản dịch' });
    await expect(translated).toBeVisible({ timeout: 8 * 60 * 1000 });
    const [download] = await Promise.all([page.waitForEvent('download'), translated.click()]);
    expect(download.suggestedFilename()).toBe('sample-2p-vi.pdf');
    expect(readFileSync((await download.path())!).subarray(0, 5).toString()).toBe('%PDF-');
    await expect(page.getByRole('navigation', { name: 'breadcrumbs' }).getByRole('link', { name: 'Tệp của tôi' }))
      .toHaveAttribute('href', '/');
  });

  await test.step('dựng lại với font khác (worker giả): bản dịch cũ còn tải được, font đổi khi xong', async () => {
    const fileId = page.url().split('/').pop()!;
    await page.getByRole('button', { name: 'Dựng lại với font khác' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByLabel('Font chữ bản dịch')).toHaveValue('sans'); // worker giả không báo font → chọn sẵn sans
    await dialog.getByRole('button', { name: 'Dựng lại', exact: true }).click();
    await expect.poll(async () => (await (await page.request.get(`/api/files/${fileId}`)).json()).font,
      { timeout: 60_000 }).toBe('sans');
    await expect(page.getByRole('button', { name: 'Dựng lại với font khác' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Tải bản dịch' })).toBeVisible();
    await expect(page.getByText(/^Không thay được bản dịch/)).toHaveCount(0);
  });

  await test.step('dịch lại một tệp đã xong: bản cũ còn tải được tới khi bản mới xong, rồi bản mới thay vào', async () => {
    await page.goto('/');
    await page.getByTestId('hero-file-input').setInputFiles({ name: SLOW_NAME, mimeType: 'application/pdf', buffer: readFileSync(SAMPLE) });
    const upload = page.getByRole('dialog');
    await expect(upload.getByText(`Đã chọn: ${SLOW_NAME}`)).toBeVisible();
    await upload.getByRole('button', { name: 'Dịch', exact: true }).click();
    await expect(page).toHaveURL(/\/files\/[0-9a-f]{12}$/);
    const fileId = page.url().split('/').pop()!;
    const again = page.getByRole('button', { name: 'Dịch lại', exact: true });
    await expect(again).toBeVisible({ timeout: 60_000 }); // xong lần đầu (worker giả chậm 3 s)
    await again.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText(`Dịch lại ${SLOW_NAME}`)).toBeVisible();
    await expect(dialog.getByText(/^Dịch lại từ đầu gửi tài liệu tới dịch vụ dịch một lần nữa/)).toBeVisible();
    await expect(dialog.getByLabel('Google miễn phí')).toBeChecked(); // chọn sẵn theo chính tệp
    await expect(dialog.getByLabel('Font chữ bản dịch')).toHaveValue('auto');
    await dialog.getByLabel('Dịch sang').selectOption('en');
    await dialog.getByRole('button', { name: 'Dịch lại', exact: true }).click();
    await expect(page.getByText(
      'Đang dịch lại sang Tiếng Anh · Google miễn phí · Tự động (theo bản gốc). Bản dịch hiện tại vẫn xem và tải được.',
    )).toBeVisible();
    const old = page.getByRole('link', { name: 'Tải bản dịch' });
    await expect(old).toBeVisible();
    const [during] = await Promise.all([page.waitForEvent('download'), old.click()]);
    expect(during.suggestedFilename()).toBe(`${SLOW_STEM}-vi.pdf`); // bản cũ, trong lúc lượt dịch lại còn chạy
    await expect(page.getByText(/^Đang dịch lại sang/)).toHaveCount(0, { timeout: 60_000 });
    await expect(page.getByText('Dịch sang Tiếng Anh', { exact: true })).toBeVisible();
    const [after] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'Tải bản dịch' }).click()]);
    expect(after.suggestedFilename()).toBe(`${SLOW_STEM}-en.pdf`);
    const item = await (await page.request.get(`/api/files/${fileId}`)).json();
    expect([item.status, item.language, item.retranslating, item.rebuild_error]).toEqual(['done', 'en', false, '']);
  });

  await test.step('tìm theo tên', async () => {
    await page.goto('/');
    const filter = page.getByLabel('Lọc theo tên');
    await filter.fill('SAMPLE');
    await expect(page.getByRole('link', { name: 'sample-2p.pdf' })).toBeVisible();
    // Lọc áp sau 300 ms (debounce): đợi tệp không khớp biến mất — không thì các bước dưới còn thấy hai dòng.
    await expect(page.getByRole('link', { name: SLOW_NAME })).toHaveCount(0);

    // Bug người dùng báo cáo: tooltip của icon thao tác trong bảng chỉ còn thấy mũi tên — ô TD (overflow: hidden) cắt mất
    // phần thân tip. Floating tip (portal ra ngoài bảng, qua BodyPortal của Gamut) phải hiện đầy đủ và không bị che/clip
    // tại chính điểm giữa của nó. N.b. Gamut gắn `role="tooltip"` cho một span aria-hidden dùng riêng cho tên trợ năng
    // (luôn nằm ngoài khung nhìn) — bong bóng thật khi `placement: 'floating'` là `[data-testid="popover-content-container"]`.
    await page.getByRole('link', { name: 'Tải bản dịch' }).hover();
    const tooltip = page.locator('[data-testid="popover-content-container"]').filter({ hasText: 'Tải bản dịch' });
    await expect(tooltip).toBeVisible();
    const centre = await tooltip.evaluate((el) => {
      const rect = el.getBoundingClientRect();
      return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    });
    const centreIsInsideTooltip = await page.evaluate(({ x, y }) => {
      const el = document.elementFromPoint(x, y);
      return el !== null && el.closest('[data-testid="popover-content-container"]') !== null;
    }, centre);
    expect(centreIsInsideTooltip, 'tâm tooltip phải nằm bên trong chính nó, không bị TD cắt/che').toBe(true);

    await filter.fill('khong-ton-tai');
    await expect(page.getByText('Không có tệp nào khớp “khong-ton-tai”.')).toBeVisible();
  });

  await test.step('phân trang, F5 và nút Back', async () => {
    docker(['exec', '-T', 'app', 'python', '-', email, '25'], readFileSync(SEED));
    await page.goto('/');
    await expect(page.getByRole('link', { name: 'sample-2p.pdf' })).toBeVisible();
    await page.getByRole('button', { name: 'Last Page, Page 2' }).click();
    await expect(page).toHaveURL(/\?page=2$/);
    // 2 tệp thật (mới nhất) + seed 24…07 ở trang 1; trang 2 là seed 06…00.
    await expect(page.getByRole('link', { name: /^seed 0[0-6]\.pdf$/ })).toHaveCount(7);
    await expect(page.getByText('21–27 / 27 tệp')).toBeVisible();
    await page.reload();
    await expect(page.getByRole('link', { name: 'seed 00.pdf' })).toBeVisible();
    await page.goBack();
    await expect(page).toHaveURL(/\/$/);
  });

  await test.step('chọn tất cả 27 tệp → Dịch lại hàng loạt (giữ cài đặt riêng): xếp đúng hạn chờ, báo số bỏ qua', async () => {
    await queueDrained(page); // không còn job nào: bài đếm dưới đây bắt đầu từ 0 tệp chờ
    await page.goto('/');
    await expect(page.getByRole('link', { name: SLOW_NAME })).toBeVisible();
    await tick(page, 'Chọn tất cả tệp trong trang');
    await page.getByRole('button', { name: 'Chọn tất cả 27 tệp' }).click();
    const bar = page.getByRole('group', { name: 'Thao tác với các tệp đã chọn' });
    await expect(bar.getByText('Đã chọn tất cả 27 tệp')).toBeVisible();
    await bar.getByRole('button', { name: 'Dịch lại' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Dịch lại 27 tệp')).toBeVisible();
    await expect(dialog.getByLabel('Giữ cài đặt riêng của từng tệp')).toBeChecked();
    await expect(dialog.getByText(/Các tệp được dịch lần lượt theo hàng chờ\.$/)).toBeVisible();
    await dialog.getByRole('button', { name: 'Dịch lại', exact: true }).click();
    // Mới nhất trước: 2 tệp thật (dịch lại từ đầu, giữ bản cũ) + seed 24 (lỗi → tại chỗ) lấp đủ 3 chỗ; 24 tệp còn lại vượt hạn.
    await expect(page.getByText('Đã xếp hàng 3 tệp. 24 tệp vượt hạn chờ (3 tệp/người) — đợi rồi chọn lại.')).toBeVisible();
    await expect(bar).toHaveCount(0); // xong thì bỏ chọn
    await queueDrained(page);
    const listed = (await (await page.request.get('/api/files?page=1&page_size=20')).json()).items as
      { filename: string; status: string; language: string; retranslating: boolean }[];
    expect(listed.filter((item) => !item.filename.startsWith('seed'))
      .map((item) => [item.filename, item.status, item.language, item.retranslating]))
      .toEqual([[SLOW_NAME, 'done', 'en', false], ['sample-2p.pdf', 'done', 'vi', false]]);
  });

  await test.step('chọn nhiều tệp và xoá hàng loạt', async () => {
    await page.goto('/?q=seed%200');
    for (const name of ['Chọn seed 01.pdf', 'Chọn seed 02.pdf']) await tick(page, name);
    const bar = page.getByRole('group', { name: 'Thao tác với các tệp đã chọn' });
    await expect(bar.getByText('Đã chọn 2 tệp')).toBeVisible();
    await bar.getByRole('button', { name: 'Xoá' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Xoá 2 tệp?')).toBeVisible();
    await dialog.getByRole('button', { name: 'Xoá' }).click();
    await expect(page.getByText('Đã xoá 2 tệp.')).toBeVisible();
    await expect(page.getByRole('link', { name: 'seed 01.pdf' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'seed 02.pdf' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'seed 03.pdf' })).toBeVisible();
  });

  await test.step('xoá có xác nhận', async () => {
    await page.goto('/?q=seed%2000');
    await page.getByRole('button', { name: 'Xoá' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Xoá' }).click();
    await expect(page.getByText('Không có tệp nào khớp “seed 00”.')).toBeVisible();
  });

  await test.step('người khác không thấy tệp của mình', async () => {
    const context = await newWatchedContext();
    const other = await context.newPage();
    await signUp(other, `e2e-khac-${stamp}@example.com`);
    await expect(other.getByText('Chưa có tệp nào')).toBeVisible();
    await context.close();
  });

  await test.step('menu avatar → Tài khoản: đổi tên hiển thị, lời chào đổi theo', async () => {
    await page.goto('/');
    await openAccountMenu(page);
    await page.getByRole('menuitem', { name: 'Tài khoản' }).click();
    await expect(page).toHaveURL(/\/settings\/account$/);
    await page.getByRole('textbox', { name: 'Tên hiển thị' }).fill('Người Thử E2E');
    await page.getByRole('region', { name: 'Tên hiển thị' }).getByRole('button', { name: 'Lưu' }).click();
    await expect(page.getByText('Đã lưu tên hiển thị.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Menu tài khoản' })).toHaveText('N');
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Xin chào, Người Thử E2E!' })).toBeVisible();
  });

  await test.step('đổi email qua link trong thư (log) rồi dùng email mới từ đây', async () => {
    const newEmail = `e2e-moi-${stamp}@example.com`;
    await page.goto('/settings/account');
    const card = page.getByRole('region', { name: 'Đổi email' });
    await card.getByLabel('Email mới').fill(newEmail);
    await card.getByLabel('Mật khẩu hiện tại').fill(PASSWORD);
    await card.getByRole('button', { name: 'Gửi link xác nhận' }).click();
    await expect(card.getByText(`Đã gửi liên kết xác nhận tới ${newEmail}.`, { exact: false })).toBeVisible();
    await page.goto(await mailPath(newEmail, '/confirm-email'));
    await expect(page.getByText(`Email đã đổi thành ${newEmail}.`)).toBeVisible();
    email = newEmail;
  });

  await test.step('đăng xuất rồi đăng nhập lại bằng email (mới) + mật khẩu', async () => {
    await page.goto('/');
    await openAccountMenu(page);
    await page.getByRole('menuitem', { name: 'Đăng xuất' }).click();
    await expect(page).toHaveURL(/\/login(\?|$)/);
    await page.goto('/');
    await expect(page).toHaveURL(/\/login(\?|$)/); // phiên đã bị huỷ thật, không chỉ ẩn giao diện
    await signIn(page, email);
    await expect(page.getByRole('link', { name: 'sample-2p.pdf' })).toBeVisible();
  });

  await test.step('quản trị viên tắt đăng ký → /register báo đóng, đăng nhập không còn "Tạo tài khoản" → bật lại', async () => {
    await signIn(admin, adminEmail);
    await openAccountMenu(admin);
    await admin.getByRole('menuitem', { name: 'Hệ thống' }).click();
    const card = admin.getByRole('region', { name: 'Đăng ký & hàng chờ' });
    const toggle = card.getByRole('checkbox', { name: 'Cho phép đăng ký tài khoản mới' });
    await expect(toggle).toBeChecked();
    await card.getByText('Cho phép đăng ký tài khoản mới', { exact: true }).click(); // nhãn của Toggle (input ẩn)
    await expect(toggle).not.toBeChecked();
    await card.getByRole('button', { name: 'Lưu', exact: true }).click();
    await expect(card.getByText('Đã lưu.')).toBeVisible();

    const guestContext = await newWatchedContext();
    const guest = await guestContext.newPage();
    await guest.goto('/register');
    await expect(guest.getByRole('heading', { name: 'Đăng ký đang tạm đóng' })).toBeVisible();
    await expect(guest.getByLabel('Email')).toHaveCount(0);
    await guest.goto('/login');
    await expect(guest.getByRole('button', { name: 'Đăng nhập', exact: true })).toBeVisible();
    await expect(guest.getByRole('link', { name: 'Tạo tài khoản' })).toHaveCount(0);
    const refused = await guest.request.post('/api/auth/register', {
      headers: { 'X-Requested-With': 'fetch' }, data: { email: `e2e-dong-${stamp}@example.com`, password: PASSWORD },
    });
    expect(refused.status()).toBe(403);
    expect(await refused.json()).toEqual({ detail: { code: 'registration_closed' } });

    await card.getByText('Cho phép đăng ký tài khoản mới', { exact: true }).click();
    await expect(toggle).toBeChecked();
    await card.getByRole('button', { name: 'Lưu', exact: true }).click();
    await expect(card.getByText('Đã lưu.')).toBeVisible();
    await guest.goto('/register'); // tải lại trang: trạng thái instance nạp lại cùng `me`
    await expect(guest.getByRole('button', { name: 'Tạo tài khoản' })).toBeVisible();
    await guestContext.close();
  });

  await test.step('container restart: vẫn đăng nhập, danh sách còn nguyên', async () => {
    docker(['restart', 'app']);
    await expect.poll(async () => {
      try {
        return (await page.request.get('/health')).status();
      } catch {
        return 0;
      }
    }, { timeout: 90_000 }).toBe(200);
    await page.goto('/');
    await expect(page.getByRole('link', { name: 'sample-2p.pdf' })).toBeVisible();
  });

  await test.step('không tràn ngang ở 360px, chụp ảnh để duyệt', async () => {
    for (const [name, width] of [['mobile', 360], ['desktop', 1280]] as const) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto('/');
      await expect(page.getByRole('link', { name: 'sample-2p.pdf' })).toBeVisible();
      await page.screenshot({ path: `test-results/home-${name}.png`, fullPage: true });
      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      expect(scrollWidth, `trang tràn ngang ở ${width}px`).toBeLessThanOrEqual(width);
    }
  });

  await test.step('trình duyệt chỉ gọi origin của app và đã tải ít nhất một .woff2 từ đó', async () => {
    const foreign = requestedUrls.filter((u) => /^https?:/.test(u) && new URL(u).origin !== appOrigin);
    expect(foreign, 'request tới origin lạ').toEqual([]);
    expect(woff2FromApp.length, 'không có .woff2 nào tải từ app').toBeGreaterThan(0);
    expect(woff2WrongType, '.woff2 từ app phải có Content-Type font/woff2').toEqual([]);
  });

  await adminContext.close();
});
