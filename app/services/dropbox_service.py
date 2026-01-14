import httpx
import os
import time
from typing import Optional

DROPBOX_API_URL = "https://api.dropboxapi.com"
DROPBOX_CONTENT_URL = "https://content.dropboxapi.com"
DROPBOX_OAUTH_URL = "https://api.dropboxapi.com/oauth2/token"
DROPBOX_UPLOAD_FOLDER = os.getenv("DROPBOX_UPLOAD_FOLDER") or "/recipes"

class DropboxTokenManager:
    def __init__(self):
        self.app_key = os.getenv("DROPBOX_APP_KEY")
        self.app_secret = os.getenv("DROPBOX_APP_SECRET")
        self.refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

        if not self.app_key:
            print("ERROR: DROPBOX_APP_KEY not found in environment")
            raise ValueError("DROPBOX_APP_KEY not found in environment")
        if not self.app_secret:
            print("ERROR: DROPBOX_APP_SECRET not found in environment")
            raise ValueError("DROPBOX_APP_SECRET not found in environment")
        if not self.refresh_token:
            print("ERROR: DROPBOX_REFRESH_TOKEN not found in environment")
            raise ValueError("DROPBOX_REFRESH_TOKEN not found in environment")

    async def get_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token
        await self._refresh_token()
        return self._access_token  # type: ignore[return-value]

    async def _refresh_token(self) -> None:
        print("[DROPBOX] Refreshing access token...")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    DROPBOX_OAUTH_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self.refresh_token,
                        "client_id": self.app_key,
                        "client_secret": self.app_secret
                    }
                )
                if response.status_code != 200:
                    print(f"[DROPBOX] Token refresh failed: {response.status_code} - {response.text}")
                    raise ValueError(f"Failed to refresh Dropbox token: {response.status_code}")

                data = response.json()
                self._access_token = data["access_token"]
                expires_in = data.get("expires_in", 14400)
                self._token_expires_at = time.time() + expires_in
                print(f"[DROPBOX] Token refreshed successfully, expires in {expires_in}s")
        except Exception as e:
            print(f"[DROPBOX] Error refreshing token: {e}")
            raise

    def clear_cache(self) -> None:
        self._access_token = None
        self._token_expires_at = 0

token_manager = DropboxTokenManager()

class DropboxService:
    def __init__(self):
        self.headers = {}

    async def _get_headers(self) -> dict:
        access_token = await token_manager.get_access_token()
        return {
            "Authorization": f"Bearer {access_token}"
        }

    async def upload_image(self, file_data: bytes, filename: str) -> Optional[str]:
        path = None
        try:
            path = f"{DROPBOX_UPLOAD_FOLDER}/{filename}"
            headers = await self._get_headers()

            print(f"[DROPBOX] Uploading file {filename} to {path}")
            print(f"[DROPBOX] File size: {len(file_data)} bytes")

            upload_headers = {
                **headers,
                "Dropbox-API-Arg": f'{{"path": "{path}", "mode": "add"}}',
                "Content-Type": "application/octet-stream"
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                print("[DROPBOX] Uploading to Dropbox API...")
                upload_response = await client.post(
                    f"{DROPBOX_CONTENT_URL}/2/files/upload",
                    headers=upload_headers,
                    content=file_data
                )
                print(f"[DROPBOX] Upload response status: {upload_response.status_code}")

                if upload_response.status_code == 401:
                    print("[DROPBOX] Token expired, clearing cache and retrying...")
                    token_manager.clear_cache()
                    headers = await self._get_headers()
                    upload_headers["Authorization"] = headers["Authorization"]
                    upload_response = await client.post(
                        f"{DROPBOX_CONTENT_URL}/2/files/upload",
                        headers=upload_headers,
                        content=file_data
                    )
                    print(f"[DROPBOX] Retry upload response status: {upload_response.status_code}")

                if upload_response.status_code == 401 or upload_response.status_code == 403:
                    raise ValueError("Dropbox access token is expired or invalid. Please regenerate the token in Dropbox Developer Console.")

                if upload_response.status_code != 200:
                    print(f"[DROPBOX] Upload failed with status {upload_response.status_code}")
                    print(f"[DROPBOX] Response: {upload_response.text[:500]}")
                    raise ValueError(f"Dropbox API error: {upload_response.status_code}")

                upload_response.raise_for_status()
                print("[DROPBOX] Upload successful")

                link_headers = {
                    **headers,
                    "Content-Type": "application/json"
                }
                link_data = {
                    "path": path,
                    "settings": {
                        "requested_visibility": "public",
                        "allow_download": True
                    }
                }

                print("[DROPBOX] Creating shared link...")
                link_response = await client.post(
                    f"{DROPBOX_API_URL}/2/sharing/create_shared_link_with_settings",
                    headers=link_headers,
                    json=link_data
                )
                print(f"[DROPBOX] Link response status: {link_response.status_code}")

                if link_response.status_code == 401:
                    print("[DROPBOX] Token expired during link creation, clearing cache and retrying...")
                    token_manager.clear_cache()
                    headers = await self._get_headers()
                    link_headers["Authorization"] = headers["Authorization"]
                    link_response = await client.post(
                        f"{DROPBOX_API_URL}/2/sharing/create_shared_link_with_settings",
                        headers=link_headers,
                        json=link_data
                    )
                    print(f"[DROPBOX] Retry link response status: {link_response.status_code}")

                link_response.raise_for_status()

                result = link_response.json()
                url = result.get("url")
                print(f"[DROPBOX] Shared link created: {url}")
                direct_url = self._to_direct_url(url)
                print(f"[DROPBOX] Direct URL: {direct_url}")
                return direct_url
        except httpx.HTTPStatusError as e:
            error_text = e.response.text[:500] if e.response else "No response"
            print(f"[DROPBOX] HTTP Error: {e.response.status_code if e.response else 'Unknown'}: {error_text}")

            if path and e.response and e.response.status_code == 409:
                print("[DROPBOX] Shared link already exists, trying to get existing link...")
                try:
                    existing_url = await self._get_existing_shared_link(path)
                    if existing_url:
                        return existing_url
                except Exception as ex:
                    print(f"[DROPBOX] Could not get existing link: {ex}")

            if path and e.response and e.response.status_code == 400 and "sharing.write" in error_text:
                print("[DROPBOX] Missing sharing.write scope, falling back to temporary link...")
                try:
                    temp_url = await self._get_temporary_link(path)
                    if temp_url:
                        return temp_url
                except Exception as ex:
                    print(f"[DROPBOX] Could not get temporary link: {ex}")
                    raise ValueError("Dropbox API error: Cannot create shared link and temporary link fallback also failed")

            raise ValueError(f"Dropbox API error: {e.response.status_code}")
        except Exception as e:
            print(f"[DROPBOX] Error uploading to Dropbox: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            raise

    async def _get_existing_shared_link(self, path: str) -> Optional[str]:
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient() as client:
                list_headers = {
                    **headers,
                    "Content-Type": "application/json"
                }
                response = await client.post(
                    f"{DROPBOX_API_URL}/2/sharing/list_shared_links",
                    headers=list_headers,
                    json={"path": path, "direct_only": True}
                )
                response.raise_for_status()
                data = response.json()
                links = data.get("links", [])
                if links:
                    url = links[0].get("url")
                    if url:
                        return self._to_direct_url(url)
        except Exception as e:
            print(f"[DROPBOX] Error getting existing shared link: {e}")
        return None

    async def _get_temporary_link(self, path: str) -> Optional[str]:
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient() as client:
                link_headers = {
                    **headers,
                    "Content-Type": "application/json"
                }
                link_data = {"path": path}

                print("[DROPBOX] Getting temporary link...")
                response = await client.post(
                    f"{DROPBOX_API_URL}/2/files/get_temporary_link",
                    headers=link_headers,
                    json=link_data
                )
                print(f"[DROPBOX] Temporary link response status: {response.status_code}")

                if response.status_code != 200:
                    print(f"[DROPBOX] Temporary link failed: {response.text[:500]}")
                    return None

                result = response.json()
                temp_url = result.get("link")
                print(f"[DROPBOX] Temporary link obtained: {temp_url}")

                if temp_url:
                    direct_url = self._to_direct_url(temp_url)
                    print(f"[DROPBOX] Direct URL: {direct_url}")
                    return direct_url

                return temp_url
        except Exception as e:
            print(f"[DROPBOX] Error getting temporary link: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def delete_image(self, image_url: str) -> bool:
        if not image_url:
            return False

        filename = image_url.split("/")[-1].split("?")[0]

        if not filename:
            return False

        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient() as client:
                list_headers = {**headers, "Content-Type": "application/json"}
                list_response = await client.post(
                    f"{DROPBOX_API_URL}/2/files/list_folder",
                    headers=list_headers,
                    json={"path": DROPBOX_UPLOAD_FOLDER}
                )
                list_response.raise_for_status()

                entries = list_response.json().get("entries", [])

                for entry in entries:
                    if entry["name"] == filename:
                        delete_headers = {**headers, "Content-Type": "application/json"}
                        delete_response = await client.post(
                            f"{DROPBOX_API_URL}/2/files/delete_v2",
                            headers=delete_headers,
                            json={"path": entry["path_lower"]}
                        )
                        delete_response.raise_for_status()
                        return True
        except Exception as e:
            print(f"Error deleting from Dropbox: {e}")
            return False

        return False

    def _to_direct_url(self, url: str) -> str:
        if not url:
            return url
        if "www.dropbox.com" in url:
            url = url.replace("www.dropbox.com", "dl.dropboxusercontent.com")
        if "?" in url:
            if "&dl=0" in url:
                url = url.replace("&dl=0", "&raw=1")
            elif "?dl=0" in url:
                url = url.replace("?dl=0", "?raw=1")
        return url

dropbox_service = DropboxService()
