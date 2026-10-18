"""
app/routers/auth_router.py
===============================================================================
Lát 3 - Bước 4: Endpoint xác thực. PRODUCT_SPEC Mục 3.2.
Gắn vào app với prefix "/api/auth" (xem app/main.py):

    POST /register   đăng ký -> đăng nhập luôn (Mục 3.2), 201 + TokenResponse + cookie httpOnly
    POST /login      đăng nhập, 200 + TokenResponse + cookie httpOnly
    GET  /me         user hiện tại
    POST /logout     thu hồi token + xóa cookie

Token đi cả trong body (cho client dùng Bearer) lẫn cookie `access_token` (httpOnly, SameSite=Lax).
Header Authorization được ưu tiên hơn cookie (logic ở auth_service.get_current_user / extract_token).

Cấu hình cookie: biến môi trường AUTH_COOKIE_SECURE=1 bật cờ `Secure` (BẮT BUỘC khi triển khai qua HTTPS;
mặc định tắt để chạy được trên http://localhost khi phát triển).
"""
import os

from fastapi import APIRouter, Depends, Request, Response

from app.chat_models import TokenResponse, UserLoginRequest, UserOut, UserRegisterRequest
from app.services import auth_service
from app.services.auth_service import COOKIE_NAME, get_current_user

router = APIRouter()


def _cookie_secure() -> bool:
    return os.environ.get("AUTH_COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes", "on")


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=auth_service.token_ttl_seconds(),  # cùng hạn với token trong DB
        path="/",
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
    )


def _clear_auth_cookie(response: Response) -> None:
    # delete_cookie phải khớp thuộc tính với lúc set thì trình duyệt mới xóa đúng cookie.
    response.delete_cookie(key=COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=_cookie_secure())


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"  # phản hồi chứa token không được cache


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: UserRegisterRequest, response: Response):
    """Đăng ký bằng email + mật khẩu. Trùng email -> 409. Sai định dạng -> 422."""
    result = auth_service.register_and_login(payload.email, payload.password)
    _set_auth_cookie(response, result.access_token)
    _no_store(response)
    return result


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLoginRequest, response: Response):
    """Sai email hoặc mật khẩu -> 401 'email hoặc mật khẩu không đúng' (không phân biệt nguyên nhân)."""
    result = auth_service.authenticate_user(payload.email, payload.password)
    _set_auth_cookie(response, result.access_token)
    _no_store(response)
    return result


@router.get("/me", response_model=UserOut)
def me(current_user: UserOut = Depends(get_current_user)):
    return current_user


@router.post("/logout")
def logout(request: Request, response: Response, current_user: UserOut = Depends(get_current_user)):
    """Thu hồi đúng token đang dùng (header hoặc cookie) và xóa cookie."""
    token = auth_service.extract_token(request.headers.get("authorization"), request.cookies.get(COOKIE_NAME))
    auth_service.revoke_token(token)
    _clear_auth_cookie(response)
    return {"ok": True}
