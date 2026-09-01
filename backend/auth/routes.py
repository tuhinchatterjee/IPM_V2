"""Plain Flask login/logout routes. The login form is a small self-contained HTML
page (reusing the app palette) so it renders without the Dash layout tree."""

import logging
import time
from urllib.parse import urlsplit

from flask import redirect, request
from flask_login import login_required, login_user, logout_user
from sqlalchemy import func, update

from backend.auth.login import AuthUser
from backend.auth.security import verify_password
from backend.db.engine import get_session
from backend.db.models import User

logger = logging.getLogger(__name__)

# Delay on a failed attempt — cheap brute-force friction at this user scale.
_FAILED_LOGIN_DELAY_S = 0.5


def _safe_next(raw: str | None) -> str:
    """Only allow same-site relative redirect targets (no open redirect)."""
    if not raw:
        return "/"
    parts = urlsplit(raw)
    if parts.scheme or parts.netloc or not raw.startswith("/") or raw.startswith("//"):
        return "/"
    return raw


def _login_page(error: str = "", next_url: str = "/") -> str:
    err_html = f'<div class="err">{error}</div>' if error else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in · CreditProbe Tool</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         font-family:'Inter',-apple-system,'Segoe UI',sans-serif; color:#16232f;
         position:relative; overflow:hidden;
         background:#0a1c2a url('/assets/login-bg.jpg') center center / cover no-repeat; }}
  /* subtle vignette so the card pops and the busy edges recede */
  body::before {{ content:""; position:absolute; inset:0; pointer-events:none;
         background: radial-gradient(circle at 50% 45%, rgba(4,14,22,0) 38%, rgba(4,14,22,0.55) 100%); }}
  .card {{ position:relative; z-index:1; background:#fff; border-radius:14px; padding:36px 34px; width:360px;
          box-shadow:0 20px 60px rgba(0,0,0,0.5); }}
  .brand {{ display:flex; align-items:center; gap:10px; margin-bottom:6px; }}
  .logo {{ width:30px; height:30px; border-radius:8px; background:#16b8a6; color:#052e2a;
          font-weight:800; display:flex; align-items:center; justify-content:center; }}
  h1 {{ font-size:17px; margin:0; font-weight:800; }}
  .sub {{ color:#6c7a8c; font-size:12.5px; margin:4px 0 22px; }}
  label {{ font-size:11px; font-weight:800; letter-spacing:0.5px; color:#93a1b2;
          text-transform:uppercase; display:block; margin-bottom:6px; }}
  input {{ width:100%; padding:11px 13px; border:1px solid #e3e8ef; border-radius:8px;
          font-size:14px; font-family:inherit; margin-bottom:16px; outline:none; }}
  input:focus {{ border-color:#16b8a6; box-shadow:0 0 0 3px rgba(22,184,166,0.14); }}
  button {{ width:100%; padding:11px; background:#16b8a6; color:#052e2a; border:none;
           border-radius:8px; font-weight:800; font-size:14px; cursor:pointer; }}
  button:hover {{ background:#0d9488; }}
  .err {{ background:#fdeceb; color:#c0292e; font-size:12.5px; font-weight:600;
         padding:9px 12px; border-radius:8px; margin-bottom:16px; }}
</style></head><body>
  <form class="card" method="post" action="/login?next={next_url}">
    <div class="brand"><div class="logo">CreditProbe</div><h1>Intelligent Portfolio Manager</h1></div>
    <div class="sub">Sign in to continue</div>
    {err_html}
    <label>Username</label>
    <input name="username" autocomplete="username" autofocus required>
    <label>Password</label>
    <input name="password" type="password" autocomplete="current-password" required>
    <button type="submit">Sign in</button>
  </form>
</body></html>"""


def register_auth_routes(server) -> None:
    @server.route("/login", methods=["GET", "POST"])
    def login():
        next_url = _safe_next(request.args.get("next"))
        if request.method == "GET":
            return _login_page(next_url=next_url)

        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        with get_session() as s:
            row = s.query(User).filter(User.username == username).one_or_none()
            if row is not None and row.is_active and verify_password(row.password_hash, password):
                s.execute(update(User).where(User.id == row.id).values(last_login_at=func.now()))
                user = AuthUser(row)
                login_user(user)
                logger.info("Login OK: user=%s", username)
                return redirect(next_url)

        time.sleep(_FAILED_LOGIN_DELAY_S)
        logger.warning("Login failed: user=%r", username)
        return _login_page("Invalid username or password.", next_url), 401

    @server.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect("/login")
