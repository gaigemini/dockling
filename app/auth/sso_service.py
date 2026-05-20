from typing import Dict, Optional

from app.auth.g_sso_client import SimpleSSOClient
from app.models.sso_model import SsoIntrospectResponseModel, SsoTokenResponseModel, SsoUserInfoModel
from config import settings


class SsoService:
    def __init__(self):
        self.client = SimpleSSOClient(
            sso_url=settings.SSO_URL,
            realm=settings.SSO_REALM,
            client_id=settings.SSO_CLIENT_ID,
            client_secret=settings.SSO_CLIENT_SECRET
        )
        self.redirect_uri = f"{settings.SSO_REDIRECT_URI.rstrip('/')}/auth/v1/callback"

    def get_login_url(self, state: Optional[str] = None) -> Dict[str, str]:
        return self.client.get_login_url(redirect_uri=self.redirect_uri, state=state)

    async def exchange_code(self, code: str, code_verifier: str) -> SsoTokenResponseModel:
        tokens = await self.client.exchange_code(
            code=code,
            redirect_uri=self.redirect_uri,
            code_verifier=code_verifier
        )
        return SsoTokenResponseModel(**tokens)

    async def get_user_info(self, access_token: str) -> SsoUserInfoModel:
        user_info = await self.client.get_user_info(access_token)
        return SsoUserInfoModel(**user_info)

    async def refresh_token(self, refresh_token: str) -> SsoTokenResponseModel:
        tokens = await self.client.refresh_token(refresh_token)
        return SsoTokenResponseModel(**tokens)

    def get_logout_url(self, post_logout_redirect_uri: Optional[str] = None) -> str:
        if not post_logout_redirect_uri:
            post_logout_redirect_uri = settings.SSO_REDIRECT_URI
        return self.client.get_logout_url(redirect_uri=post_logout_redirect_uri)

    async def register_user(self, user_data: Dict[str, str]) -> Dict:
        return await self.client.register_user(user_data)

    async def get_m2m_token(self, scope: Optional[str] = None) -> SsoTokenResponseModel:
        """Get an M2M Access Token using Client Credentials grant."""
        tokens = await self.client.get_m2m_token(scope=scope)
        return SsoTokenResponseModel(**tokens)

    async def introspect_token(self, token: str) -> SsoIntrospectResponseModel:
        """Introspect (validate) an access token."""
        result = await self.client.introspect_token(token=token)
        return SsoIntrospectResponseModel(**result)


# Singleton instance
sso_service = SsoService()

