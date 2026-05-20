from typing import Dict, Optional, Union

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from config import get_request_logger

from .g_sso_client import SimpleSSOClient

# Configuration
SSO_URL = "http://localhost:8000"
REALM = "myrealm"
CLIENT_ID = "client1"  # Ensure this client exists in SSO with redirect_uri http://localhost:8001/callback
CLIENT_SECRET = "secret1"  # If client is confidential

app = FastAPI()

sso = SimpleSSOClient(SSO_URL, REALM, CLIENT_ID, CLIENT_SECRET)
logger = get_request_logger(__name__)


async def get_current_user(request: Request) -> Dict:
    """FastAPI Dependency to get current user matching SSO info."""
    auth_header = request.headers.get("Authorization")
    token = None

    # Check Bearer token first
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]

    # Fallback to cookie
    if not token:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_info = await sso.get_user_info(token)
        return user_info
    except Exception as e:
        logger.error(f"Token validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.get("/api/protected")
async def protected_route(current_user: Dict = Depends(get_current_user)) -> Dict:
    """Example of a protected endpoint using the dependency."""
    return {
        "status": "success",
        "message": f"Hello {current_user.get('name')}, you have access to this protected data.",
        "user_data": current_user
    }


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> Union[str, HTMLResponse]:
    token = request.cookies.get("access_token")
    if token:
        try:
            user = await sso.get_user_info(token)
            return f"""
            <h1>Welcome, {user.get('name')}</h1>
            <pre>{user}</pre>
            <a href="/logout">Logout</a>
            """
        except Exception as e:
            return f"Error: {e} <a href='/logout'>Logout</a>"

    return '<a href="/login">Login with SSO</a> | <a href="/register">Register</a>'


@app.get("/register", response_class=HTMLResponse)
async def register_form(request: Request) -> str:
    return """
    <h1>Register New User</h1>
    <form method="post" action="/register">
        <label>Username:</label><br>
        <input type="text" name="username" required><br>
        <label>Email:</label><br>
        <input type="email" name="email" required><br>
        <label>Password:</label><br>
        <input type="password" name="password" required><br>
        <label>First Name:</label><br>
        <input type="text" name="first_name"><br>
        <label>Last Name:</label><br>
        <input type="text" name="last_name"><br><br>
        <button type="submit">Register</button>
    </form>
    <a href="/">Back</a>
    """


@app.post("/register", response_class=HTMLResponse)
async def register_submit(request: Request) -> str:
    form_data = await request.form()
    user_data = {
        "username": form_data.get("username"),
        "email": form_data.get("email"),
        "password": form_data.get("password"),
        "first_name": form_data.get("first_name"),
        "last_name": form_data.get("last_name")
    }

    try:
        result = await sso.register_user(user_data)
        return f"<h3>Registration Successful!</h3><p>User ID: {result.get('user_id')}</p><a href='/login'>Proceed to Login</a>"
    except Exception as e:
        return f"<h3>Registration Failed</h3><p>{e}</p><a href='/register'>Try Again</a>"


@app.get("/login")
async def login(response: Response) -> RedirectResponse:
    # 1. Generate Auth URL and State/Verifier
    data = sso.get_login_url(redirect_uri="http://localhost:8001/callback")

    # 2. Store verifier in cookie (in production use secure session backend)
    response = RedirectResponse(data["url"])
    response.set_cookie("pkce_verifier", data["verifier"], httponly=True)
    return response


@app.get("/callback")
async def callback(request: Request, code: str) -> Union[str, RedirectResponse]:
    # 3. Retrieve verifier
    verifier = request.cookies.get("pkce_verifier")
    if not verifier:
        return "Error: Missing PKCE verifier"

    try:
        # 4. Exchange Code for Token
        tokens = await sso.exchange_code(code, "http://localhost:8001/callback", verifier)
        logger.info(f"Tokens received for code {code}")

        response = RedirectResponse("/")
        response.set_cookie("access_token", tokens["access_token"], httponly=True)
        response.delete_cookie("pkce_verifier")
        return response

    except Exception as e:
        return f"Callback Error: {e}"


@app.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    # 5. Local Logout
    response = RedirectResponse("/")
    response.delete_cookie("access_token")

    # 6. SSO Logout (Optional)
    sso_logout_url = sso.get_logout_url(redirect_uri="http://localhost:8001")
    response = RedirectResponse(sso_logout_url)
    # Note: Redirecting to SSO logout will clear SSO session too.

    return response


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
