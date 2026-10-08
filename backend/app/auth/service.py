from __future__ import annotations

import hmac
import uuid
from dataclasses import dataclass
from datetime import timedelta

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import utcnow
from ..errors import ApiError
from ..models import EmailToken, User, UserSession
from ..security import hash_password, new_token, token_hash, verify_password
from ..system.store import site_url as resolve_site_url
from .mailer import Mail
from .ratelimit import SlidingWindow

SESSION_TTL = timedelta(days=7)
VERIFY_TTL = timedelta(hours=24)
RESET_TTL = timedelta(hours=1)
NEW_EMAIL_TTL = timedelta(hours=24)
PASSWORD_MIN, PASSWORD_MAX = 8, 128
EMAIL_MAX = 254
LOGIN_WINDOW = 15 * 60
LOGIN_LIMIT_PER_IP_EMAIL = 5  # lần sai / 15 phút cho một cặp IP + email
LOGIN_LIMIT_PER_EMAIL = 20  # lần sai / 15 phút cho một email, bất kể IP (chặn đổi IP liên tục)
REQUEST_LIMIT_PER_IP = 10  # đăng ký + quên mật khẩu + gửi lại thư / 15 phút cho một IP


def normalize_email(raw: str) -> str:
    try:
        return validate_email(raw.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise ApiError(422, "invalid_email") from None


def utf8_encodable(text: str) -> bool:
    """False khi chuỗi có surrogate lẻ (JSON cho phép "\\ud800"): không băm được, không tra / lưu được vào DB."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def check_password(password: str) -> None:
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX or not utf8_encodable(password):
        raise ApiError(422, "invalid_password")


@dataclass(frozen=True)
class Issued:
    """Kết quả đăng ký / gửi lại thư: thư cần gửi (nếu có) và nonce cho cookie verify_nonce —
    nonce chỉ có khi vừa phát một link xác thực mới."""

    mail: Mail | None = None
    nonce: str | None = None


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.login_failures = SlidingWindow(limit=LOGIN_LIMIT_PER_IP_EMAIL, window_seconds=LOGIN_WINDOW)
        self.email_failures = SlidingWindow(limit=LOGIN_LIMIT_PER_EMAIL, window_seconds=LOGIN_WINDOW)
        self.request_throttle = SlidingWindow(limit=REQUEST_LIMIT_PER_IP, window_seconds=LOGIN_WINDOW)
        self.mail_throttle = SlidingWindow(limit=1, window_seconds=60)

    # ---- Đăng ký & xác thực email ------------------------------------------

    def register(self, db: Session, email_raw: str, password: str, *, mail_enabled: bool = True) -> Issued:
        """`mail_enabled=False` (không SMTP, spec 2026-10-05 §5): tài khoản mới coi như đã xác nhận, không phát token,
        không gửi gì — nhưng kết quả trả về vẫn cùng dạng để router đặt cookie mồi y hệt."""
        email = normalize_email(email_raw)
        check_password(password)
        # Luôn băm, kể cả khi email đã có: thời gian phản hồi không lộ email nào đã đăng ký.
        password_hash = hash_password(password)
        user = self._user_by_email(db, email)
        if user is None:
            # Email mới: tạo tài khoản + gửi thư xác thực (không có thư: đã xác nhận ngay).
            user = User(id=uuid.uuid4().hex, email=email, password_hash=password_hash,
                        email_verified_at=None if mail_enabled else utcnow())
            db.add(user)
            try:
                db.flush()
            except IntegrityError:
                # Hai lượt đăng ký cùng email mới chạy song song: lượt kia vừa tạo xong.
                # Coi như email đã có tài khoản thay vì trả 500.
                db.rollback()
                user = self._user_by_email(db, email)
                if user is None:
                    raise
            else:
                issued = Issued()
                if mail_enabled and self._may_mail(email):
                    nonce = new_token()
                    token = self._issue(db, user, "verify", VERIFY_TTL, nonce=nonce)
                    issued = Issued(self._verify_mail(db, user, token), nonce)
                db.commit()
                return issued
        # Email đã có tài khoản: không đổi mật khẩu — tránh kẻ tấn công "đăng ký trước" bằng email
        # nạn nhân rồi giữ mật khẩu của mình. Chưa xác thực thì huỷ luôn mọi link xác thực đang
        # treo: link do lượt đăng ký trước (có thể là kẻ tấn công) sinh ra không còn dùng được.
        if user.email_verified_at is None:
            db.execute(delete(EmailToken).where(
                EmailToken.user_id == user.id, EmailToken.kind == "verify", EmailToken.used_at.is_(None),
            ))
        mail = self._existing_account_mail(db, user) if mail_enabled and self._may_mail(email) else None
        db.commit()
        return Issued(mail)

    def verify_email(self, db: Session, token: str, nonce: str | None) -> tuple[User, bool]:
        """Xác thực email; trả kèm True nếu request đến từ chính trình duyệt đã xin link
        (cookie verify_nonce khớp) — chỉ khi đó mới được tự đăng nhập."""
        row = self._consume(db, token, "verify")
        same_browser = bool(nonce) and row.nonce_hash is not None and hmac.compare_digest(
            row.nonce_hash, self._nonce_hash(nonce),
        )
        user = db.get(User, row.user_id)
        if user.email_verified_at is None:
            user.email_verified_at = utcnow()
        db.commit()
        return user, same_browser

    def resend_verification(self, db: Session, email_raw: str) -> Issued:
        email = self._quiet_email(email_raw)
        user = self._user_by_email(db, email) if email else None
        if user is None or user.email_verified_at is not None or not self._may_mail(email):
            return Issued()
        nonce = new_token()
        mail = self._verify_mail(db, user, self._issue(db, user, "verify", VERIFY_TTL, nonce=nonce))
        db.commit()
        return Issued(mail, nonce)

    # ---- Đăng nhập & phiên ---------------------------------------------------

    def login(self, db: Session, email_raw: str, password: str, client_ip: str) -> User:
        # Cắt độ dài: khoá đếm do người gọi tự đặt, không được giữ chuỗi to tuỳ ý trong RAM.
        email = self._quiet_email(email_raw) or email_raw.strip().lower()[:EMAIL_MAX]
        key = self._start_attempt(email, client_ip)
        if len(password) > PASSWORD_MAX:
            # Không mật khẩu hợp lệ nào dài thế: tính là một lần sai, khỏi tốn CPU băm chuỗi khổng lồ.
            raise ApiError(401, "invalid_credentials")
        # Email có surrogate lẻ không thể nằm trong DB (tra bằng nó là lỗi mã hoá → 500): coi như email lạ — vẫn
        # băm với hash giả bên dưới nên trả lời và thời gian y như mọi email không có tài khoản.
        user = self._user_by_email(db, email) if utf8_encodable(email) else None
        if not verify_password(user.password_hash if user else None, password):
            raise ApiError(401, "invalid_credentials")
        self._attempt_succeeded(key, email)
        if user.email_verified_at is None:
            raise ApiError(403, "email_unverified")
        return user

    def verify_current_password(self, user: User, password: str, client_ip: str) -> None:
        """Ba form tài khoản (đổi mật khẩu / đổi email / xoá tài khoản) dùng CÙNG bộ đếm thử sai với đăng
        nhập: dò mật khẩu qua các form này cũng khoá đăng nhập của cặp IP + email đó, và ngược lại."""
        key = self._start_attempt(user.email, client_ip)
        if len(password) > PASSWORD_MAX or not verify_password(user.password_hash, password):
            raise ApiError(400, "wrong_password")
        self._attempt_succeeded(key, user.email)

    def _start_attempt(self, email: str, client_ip: str) -> str:
        """Ghi một lượt thử mật khẩu TRƯỚC khi kiểm, kiểm-và-ghi trong một lần khoá: nhiều request song song
        không lọt quá trần (trước đây cả loạt cùng qua cửa "chưa bị chặn" rồi mới ghi). Trả khoá `ip|email`."""
        key = f"{client_ip}|{email}"
        if not self.login_failures.attempt(key):
            raise ApiError(429, "too_many_attempts")
        if not self.email_failures.attempt(email):
            self.login_failures.forgive(key)  # chưa hề kiểm mật khẩu: không tính cho cặp IP + email
            raise ApiError(429, "too_many_attempts")
        return key

    def _attempt_succeeded(self, key: str, email: str) -> None:
        """Đúng mật khẩu: lượt vừa ghi không phải lần sai."""
        self.login_failures.reset(key)
        self.email_failures.forgive(email)

    def create_session(self, db: Session, user: User) -> str:
        token = new_token()
        db.add(UserSession(id=self._hash(token), user_id=user.id, expires_at=utcnow() + SESSION_TTL))
        db.commit()
        return token

    def resolve_session(self, db: Session, token: str) -> User | None:
        session = db.get(UserSession, self._hash(token))
        if session is None:
            return None
        if session.expires_at <= utcnow():
            db.delete(session)
            db.commit()
            return None
        return db.get(User, session.user_id)

    def end_session(self, db: Session, token: str) -> None:
        db.execute(delete(UserSession).where(UserSession.id == self._hash(token)))
        db.commit()

    # ---- Quên mật khẩu -------------------------------------------------------

    def forgot_password(self, db: Session, email_raw: str) -> Mail | None:
        email = self._quiet_email(email_raw)
        user = self._user_by_email(db, email) if email else None
        if user is None or not self._may_mail(email):
            return None
        mail = self._reset_mail(db, user, self._issue(db, user, "reset", RESET_TTL))
        db.commit()
        return mail

    def reset_password(self, db: Session, token: str, password: str) -> None:
        check_password(password)  # trước khi tiêu token: gõ mật khẩu yếu không làm hỏng link
        row = self._consume(db, token, "reset")
        user = db.get(User, row.user_id)
        user.password_hash = hash_password(password)
        if user.email_verified_at is None:
            user.email_verified_at = utcnow()  # mở được thư đặt lại = đã chứng minh sở hữu email
        db.execute(delete(UserSession).where(UserSession.user_id == user.id))
        # Chủ sở hữu thật vừa chứng minh quyền kiểm soát email: mọi token xác thực/đặt lại còn
        # treo (kể cả link do kẻ đăng ký trước tạo ra) không còn giá trị gì nữa.
        db.execute(delete(EmailToken).where(
            EmailToken.user_id == user.id, EmailToken.used_at.is_(None),
        ))
        db.commit()

    # ---- Dùng chung với app.auth.account (đổi email / mật khẩu, xoá tài khoản) ----

    def session_id(self, token: str) -> str:
        """Khoá chính của dòng `sessions` ứng với cookie phiên `token`."""
        return self._hash(token)

    def may_mail(self, email: str) -> bool:
        return self._may_mail(email)

    def issue_token(self, db: Session, user: User, kind: str, ttl: timedelta, new_email: str | None = None) -> str:
        return self._issue(db, user, kind, ttl, new_email=new_email)

    def consume_token(self, db: Session, token: str, kind: str) -> EmailToken:
        return self._consume(db, token, kind)

    def user_by_email(self, db: Session, email: str) -> User | None:
        return self._user_by_email(db, email)

    def site_url(self, db: Session) -> str | None:
        """Địa chỉ trang cho MỌI link trong thư — một nguồn (system.store.site_url: env > ghi lúc /setup); None = chưa biết."""
        return resolve_site_url(db, self.settings)[0]

    def link(self, db: Session, path: str, token: str) -> str:
        return self._link(db, path, token)

    # ---- Nội bộ --------------------------------------------------------------

    def _hash(self, token: str) -> str:
        return token_hash(self.settings.secret_key, token)

    def _nonce_hash(self, nonce: str) -> str:
        return token_hash(self.settings.secret_key, f"verify-nonce:{nonce}")  # tách miền với token

    @staticmethod
    def _user_by_email(db: Session, email: str) -> User | None:
        return db.scalar(select(User).where(User.email == email))

    @staticmethod
    def _quiet_email(raw: str) -> str | None:
        try:
            return normalize_email(raw)
        except ApiError:
            return None

    def _may_mail(self, email: str) -> bool:
        if self.mail_throttle.blocked(email):
            return False
        self.mail_throttle.hit(email)
        return True

    def _issue(self, db: Session, user: User, kind: str, ttl: timedelta, nonce: str | None = None,
               new_email: str | None = None) -> str:
        # Mỗi user chỉ một token đang chờ cho mỗi kind: xin link mới là link cũ hết hiệu lực.
        db.execute(delete(EmailToken).where(
            EmailToken.user_id == user.id, EmailToken.kind == kind, EmailToken.used_at.is_(None),
        ))
        token = new_token()
        db.add(EmailToken(
            token_hash=self._hash(token), user_id=user.id, kind=kind, expires_at=utcnow() + ttl,
            nonce_hash=self._nonce_hash(nonce) if nonce else None, new_email=new_email,
        ))
        return token

    def _consume(self, db: Session, token: str, kind: str) -> EmailToken:
        row = db.get(EmailToken, self._hash(token))
        if row is None or row.kind != kind or row.used_at is not None or row.expires_at <= utcnow():
            raise ApiError(400, "invalid_token")
        row.used_at = utcnow()
        return row

    def _base(self, db: Session) -> str:
        base = self.site_url(db)
        if base is None:
            # Người gọi đã qua mail_enabled (đòi biết địa chỉ trang) nên không tới được đây; tới thì đóng an toàn — không
            # bao giờ phát link "None/…" hay link suy từ Host của request.
            raise ApiError(409, "mail_not_configured")
        return base

    def _link(self, db: Session, path: str, token: str) -> str:
        return f"{self._base(db)}{path}?token={token}"

    def _verify_mail(self, db: Session, user: User, token: str) -> Mail:
        return Mail(user.email, "Xác nhận email cho PDF Translate", (
            "Chào bạn,\n\n"
            "Bấm vào liên kết dưới đây để xác nhận email và bắt đầu dùng PDF Translate:\n"
            f"{self._link(db, '/verify-email', token)}\n\n"
            "Liên kết có hiệu lực trong 24 giờ. Nếu bạn không đăng ký, hãy bỏ qua thư này.\n"
        ))

    def _existing_account_mail(self, db: Session, user: User) -> Mail:
        base = self._base(db)
        return Mail(user.email, "Bạn đã có tài khoản PDF Translate", (
            "Chào bạn,\n\n"
            "Ai đó (có thể là bạn) vừa đăng ký PDF Translate bằng email này, nhưng email này đã có tài khoản.\n"
            f"Đăng nhập: {base}/login\n"
            f"Quên mật khẩu: {base}/forgot-password\n\n"
            "Nếu không phải bạn, hãy bỏ qua thư này.\n"
        ))

    def _reset_mail(self, db: Session, user: User, token: str) -> Mail:
        return Mail(user.email, "Đặt lại mật khẩu PDF Translate", (
            "Chào bạn,\n\n"
            "Bấm vào liên kết dưới đây để đặt mật khẩu mới:\n"
            f"{self._link(db, '/reset-password', token)}\n\n"
            "Liên kết có hiệu lực trong 1 giờ và chỉ dùng được một lần. "
            "Nếu bạn không yêu cầu, hãy bỏ qua thư này.\n"
        ))
