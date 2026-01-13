import httpx
import os
import base64
from typing import Optional

DROPBOX_API_URL = "https://api.dropboxapi.com"
DROPBOX_CONTENT_URL = "https://content.dropboxapi.com"

class DropboxService:
    def __init__(self):
        self.access_token = os.getenv("DROPBOX_ACCESS_TOKEN")
        if not self.access_token:
            print("ERROR: DROPBOX_ACCESS_TOKEN not found in environment")
            raise ValueError("DROPBOX_ACCESS_TOKEN not found in environment")
        self.headers = {
            "Authorization": f"Bearer {self.access_token}"
        }
        print(f"DEBUG: Dropbox service initialized, token length: {len(self.access_token)}")

    async def upload_image(self, file_data: bytes, filename: str) -> Optional[str]:
        """Upload image to Dropbox and return shared link"""
        path = None
        try:
            path = f"/recipes/{filename}"
            
            print(f"[DROPBOX] Uploading file {filename} to {path}")
            print(f"[DROPBOX] File size: {len(file_data)} bytes")
            
            # Step 1: Upload file
            upload_headers = {
                "Authorization": f"Bearer {self.access_token}",
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
                
                if upload_response.status_code == 401 or upload_response.status_code == 403:
                    raise ValueError("Dropbox access token is expired or invalid. Please regenerate the token in Dropbox Developer Console.")
                
                if upload_response.status_code != 200:
                    print(f"[DROPBOX] Upload failed with status {upload_response.status_code}")
                    print(f"[DROPBOX] Response: {upload_response.text[:500]}")
                    raise ValueError(f"Dropbox API error: {upload_response.status_code}")
                
                upload_response.raise_for_status()
                print("[DROPBOX] Upload successful")
                
                # Step 2: Create shared link
                link_headers = {
                    "Authorization": f"Bearer {self.access_token}",
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
                
                # Don't raise here - let it fall through to HTTPStatusError handler
                # which has fallback logic for missing sharing.write scope
                link_response.raise_for_status()
                
                result = link_response.json()
                url = result.get("url")
                print(f"[DROPBOX] Shared link created: {url}")
                # Convert to direct raw URL for image display
                direct_url = self._to_direct_url(url)
                print(f"[DROPBOX] Direct URL: {direct_url}")
                return direct_url
        except ValueError:
            raise
        except httpx.HTTPStatusError as e:
            error_text = e.response.text[:500] if e.response else "No response"
            print(f"[DROPBOX] HTTP Error: {e.response.status_code if e.response else 'Unknown'}: {error_text}")
            
            # Handle case where shared link already exists (409)
            if path and e.response and e.response.status_code == 409:
                print("[DROPBOX] Shared link already exists, trying to get existing link...")
                try:
                    existing_url = await self._get_existing_shared_link(path)
                    if existing_url:
                        return existing_url
                except Exception as ex:
                    print(f"[DROPBOX] Could not get existing link: {ex}")
            
            # Handle missing permissions - fall back to temporary link
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
        """Get existing shared link for a file"""
        try:
            async with httpx.AsyncClient() as client:
                list_headers = {
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json"
                }
                # Try to list shared links for this file
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
        """Get a temporary download link (valid for 4 hours)"""
        try:
            async with httpx.AsyncClient() as client:
                link_headers = {
                    "Authorization": f"Bearer {self.access_token}",
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
        """Delete file from Dropbox using URL to extract path"""
        if not image_url:
            return False
        
        # Extract filename from URL (works for both formats)
        # Old format: https://www.dropbox.com/s/[id]/filename?dl=0
        # New format: https://dl.dropboxusercontent.com/scl/fi/[hash]/filename?raw=1
        filename = image_url.split("/")[-1].split("?")[0]
        
        if not filename:
            return False
            
        # Get file metadata to find the path
        try:
            async with httpx.AsyncClient() as client:
                # List files in recipes folder to find matching file
                list_headers = {**self.headers, "Content-Type": "application/json"}
                list_response = await client.post(
                    f"{DROPBOX_API_URL}/2/files/list_folder",
                    headers=list_headers,
                    json={"path": "/recipes"}
                )
                list_response.raise_for_status()
                
                entries = list_response.json().get("entries", [])
                
                for entry in entries:
                    # Use exact match instead of substring
                    if entry["name"] == filename:
                        # Delete the file using path_lower (Dropbox API is case-insensitive)
                        delete_headers = {**self.headers, "Content-Type": "application/json"}
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
        """Convert Dropbox shared URL to direct raw URL for images"""
        if not url:
            return url
        # Replace www.dropbox.com with dl.dropboxusercontent.com for direct download
        if "www.dropbox.com" in url:
            url = url.replace("www.dropbox.com", "dl.dropboxusercontent.com")
        # Ensure raw=1 or dl=1 for direct content access
        if "?" in url:
            if "&dl=0" in url:
                url = url.replace("&dl=0", "&raw=1")
            elif "?dl=0" in url:
                url = url.replace("?dl=0", "?raw=1")
        return url

# Singleton instance
dropbox_service = DropboxService()
