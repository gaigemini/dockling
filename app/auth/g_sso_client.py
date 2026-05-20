import base64
import hashlib
import secrets
import urllib.parse
from typing import Dict, Optional, Tuple


class SimpleSSOClient:
    """
    A simple, single-file OIDC Client for Python applications.
    Requires: httpx
    """

    def __init__(
        self,
        sso_url: str,
        realm: str,
        client_id: str,
        client_secret: str = None
    ) -> None:
        self.sso_url = sso_url.rstrip("/")
        self.realm = realm
        self.client_id = client_id
        self.client_secret = client_secret
        self.verify_ssl = False  # Set to True in production

    def _get_http_client(self):
        """Get HttpClient instance with lazy import to avoid circular dependency"""
        from app.utils.http_client import HttpClient
        return HttpClient(verify_ssl=self.verify_ssl)

    def _generate_pkce(self) -> Tuple[str, str]:
        """Generate Code Verifier and Challenge (S256)"""
        verifier = secrets.token_urlsafe(32)
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        return verifier, challenge

    def get_login_url(self, redirect_uri: str, state: str = None) -> Dict[str, str]:
        """
        Generate the Login URL and PKCE verifier.
        Returns a dict: {'url': str, 'verifier': str, 'state': str}
        Save 'verifier' and 'state' in your user session!
        """
        verifier, challenge = self._generate_pkce()
        if not state:
            state = secrets.token_urlsafe(16)

        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256"
        }

        query_string = urllib.parse.urlencode(params)
        url = f"{self.sso_url}/api/v1/auth/{self.realm}/authorize?{query_string}"

        return {
            "url": url,
            "verifier": verifier,
            "state": state
        }

    async def exchange_code(self, code: str, redirect_uri: str, code_verifier: str) -> Dict:
        """
        Exchange Authorization Code for Tokens.
        """
        token_url = f"{self.sso_url}/api/v1/auth/{self.realm}/token"

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
            "code_verifier": code_verifier
        }

        if self.client_secret:
            data["client_secret"] = self.client_secret

        client = self._get_http_client()
        response = await client.post(token_url, data=data)

        if response.status_code != 200:
            raise Exception(f"Token exchange failed: {response.text}")

        return response.json()

    async def get_user_info(self, access_token: str) -> Dict:
        """
        Fetch User Info using Access Token.
        """
        userinfo_url = f"{self.sso_url}/api/v1/auth/{self.realm}/userinfo"

        headers = {
            "Authorization": f"Bearer {access_token}"
        }

        client = self._get_http_client()
        response = await client.get(userinfo_url, headers=headers)

        if response.status_code != 200:
            raise Exception(f"UserInfo failed: {response.text}")

        return response.json()

    async def refresh_token(self, refresh_token: str) -> Dict:
        """
        Get new Access Token using Refresh Token.
        """
        token_url = f"{self.sso_url}/api/v1/auth/{self.realm}/token"

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id
        }

        if self.client_secret:
            data["client_secret"] = self.client_secret

        client = self._get_http_client()
        response = await client.post(token_url, data=data)

        if response.status_code != 200:
            raise Exception(f"Token refresh failed: {response.text}")

        return response.json()

    def get_logout_url(self, redirect_uri: str = None) -> str:
        """
        Generate Logout URL
        """
        url = f"{self.sso_url}/api/v1/auth/{self.realm}/logout"
        if redirect_uri:
            url += f"?post_logout_redirect_uri={urllib.parse.quote(redirect_uri)}"
        return url

    async def register_user(self, user_data: Dict[str, str]) -> Dict:
        """
        Register a new user in the SSO realm.
        Requires client credentials if the client is confidential.
        """
        register_url = f"{self.sso_url}/api/v1/auth/{self.realm}/register"

        payload = {
            "client_id": self.client_id,
            **user_data
        }

        if self.client_secret:
            payload["client_secret"] = self.client_secret

        client = self._get_http_client()
        response = await client.post(register_url, json=payload)

        if response.status_code != 200:
            raise Exception(f"Registration failed: {response.text}")

        return response.json()

    async def get_m2m_token(self, scope: str = None) -> Dict:
        """
        Get an M2M Access Token using Client Credentials grant.
        Requires client_secret.
        """
        if not self.client_secret:
            raise Exception("client_secret is required for M2M tokens")

        token_url = f"{self.sso_url}/api/v1/auth/{self.realm}/token"

        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }

        if scope:
            data["scope"] = scope

        client = self._get_http_client()
        response = await client.post(token_url, data=data)

        if response.status_code != 200:
            raise Exception(f"M2M Token request failed: {response.text}")

        return response.json()

    async def introspect_token(self, token: str) -> Dict:
        """
        Introspect (validate) an access token.
        Requires client_id and client_secret of the Resource Server.
        Returns a dict e.g. {"active": True, "scope": "...", "client_id": "..."}
        """
        if not self.client_secret:
            raise Exception("client_secret is required to introspect tokens")

        introspect_url = f"{self.sso_url}/api/v1/auth/{self.realm}/introspect"

        data = {
            "token": token,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }

        client = self._get_http_client()
        response = await client.post(introspect_url, data=data)

        if response.status_code != 200:
            raise Exception(f"Token introspection failed: {response.text}")

        return response.json()
