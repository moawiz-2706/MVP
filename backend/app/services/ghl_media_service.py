"""Calendar photos and videos, stored in the operator's HighLevel Media Storage."""

from __future__ import annotations

import ipaddress
import re
import socket
import uuid
from urllib.parse import urlparse

import httpx

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.models.entities import Operator
from app.services.ghl_client import GHLAPIError, GHLClient

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 4 * 1024 * 1024  # Vercel caps a request body at 4.5 MB
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
VIDEO_TYPES = {"video/mp4", "video/webm", "video/quicktime"}
EXTENSIONS = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
    "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
}


def _public_host(host: str) -> bool:
    """Only fetch from the public internet (no internal or metadata addresses)."""
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
    except OSError:
        return False
    return bool(addresses) and all(ipaddress.ip_address(address).is_global for address in addresses)


def _clean_name(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-.")
    return (stem or "passport-media")[:120]


def media_url(response: dict) -> str:
    url = response.get("url") or (response.get("file") or {}).get("url")
    if not url:
        raise ConflictError("HighLevel stored the file but did not return its link")
    return str(url)


class GHLMediaService:
    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id
        self.client = GHLClient(operator_id, db)

    def _call(self, **kwargs) -> str:
        operator = self.db.get(Operator, self.operator_id)
        if operator is None or not operator.ghl_location_id:
            raise ConflictError("Connect HighLevel before uploading media")
        try:
            return media_url(self.client.upload_media(**kwargs))
        except GHLAPIError as exc:
            if exc.status_code in {401, 403}:
                raise ConflictError(
                    "HighLevel refused the upload. Turn on the medias.write scope for the "
                    "Passport app, then reconnect Passport to HighLevel."
                ) from exc
            raise ConflictError(f"HighLevel could not store the file: {exc}") from exc

    def upload(self, *, filename: str, content: bytes, content_type: str) -> str:
        content_type = (content_type or "").split(";")[0].strip().lower()
        if content_type in IMAGE_TYPES:
            limit = MAX_IMAGE_BYTES
        elif content_type in VIDEO_TYPES:
            limit = MAX_VIDEO_BYTES
        else:
            raise ConflictError("Upload a JPG, PNG, WebP or GIF image, or an MP4, WebM or MOV video")
        if not content:
            raise ConflictError("The file is empty")
        if len(content) > limit:
            raise ConflictError(
                f"The file is larger than {limit // (1024 * 1024)} MB. Upload large videos to "
                "HighLevel Media Storage or YouTube and paste the link instead."
            )
        return self._call(name=_clean_name(filename), content=content, content_type=content_type)

    def import_url(self, url: str) -> str:
        """Download a public image or video link and store a copy in HighLevel.

        The file itself is uploaded, so the photo keeps working even if the
        original site (for example FareHarbor) removes it.
        """
        url = url.strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ConflictError("Use a public https:// link")
        content, content_type = self._download(url)
        stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", parsed.path.rsplit("/", 1)[-1]) or "passport-media"
        return self.upload(
            filename=f"{stem}{EXTENSIONS.get(content_type, '')}", content=content, content_type=content_type
        )

    def _download(self, url: str) -> tuple[bytes, str]:
        current = url
        for _ in range(4):
            parsed = urlparse(current)
            if parsed.scheme != "https" or not parsed.hostname or not _public_host(parsed.hostname):
                raise ConflictError("That link can't be downloaded; use a public https:// image or video link")
            try:
                with httpx.stream("GET", current, timeout=20, follow_redirects=False) as response:
                    if response.is_redirect:
                        current = str(response.url.join(response.headers.get("location", "")))
                        continue
                    if response.status_code != 200:
                        raise ConflictError(f"The link returned HTTP {response.status_code}")
                    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    if content_type not in IMAGE_TYPES | VIDEO_TYPES:
                        raise ConflictError("The link is not a JPG, PNG, WebP, GIF, MP4, WebM or MOV file")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_IMAGE_BYTES:
                            raise ConflictError("The file is larger than 10 MB")
                    return bytes(body), content_type
            except httpx.HTTPError as exc:
                raise ConflictError("The link could not be downloaded") from exc
        raise ConflictError("The link redirects too many times")
