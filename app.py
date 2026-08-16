import asyncio
import logging
import os
from datetime import datetime
from typing import Any

import data_pb2
import encode_id_clan_pb2
import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from google.protobuf.json_format import MessageToDict


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="FFxAPI Guild Info API",
    description="Free Fire guild information API powered by FFxAPI.",
    version="1.0.0",
)

FREEFIRE_VERSION = "OB54"
API_AUTH = "FFxAPI"
API_CONTACT = "https://t.me/FFxAPI"
AES_KEY = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
AES_IV = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])

jwt_tokens: dict[str, str] = {}


REGION_ENDPOINTS = {
    "IND": ("https://client.ind.freefiremobile.com/GetClanInfoByClanID", "client.ind.freefiremobile.com"),
    "BD": ("https://clientbp.ggpolarbear.com/GetClanInfoByClanID", "clientbp.ggpolarbear.com"),
    "BR": ("https://client.br.freefiremobile.com/GetClanInfoByClanID", "client.br.freefiremobile.com"),
    "SAC": ("https://client.br.freefiremobile.com/GetClanInfoByClanID", "client.br.freefiremobile.com"),
    "US": ("https://client.na.freefiremobile.com/GetClanInfoByClanID", "client.na.freefiremobile.com"),
    "NA": ("https://client.na.freefiremobile.com/GetClanInfoByClanID", "client.na.freefiremobile.com"),
}

REGION_ACCOUNTS = {
    "IND": "uid=6631809990&password=8C24A89B3FB5F3D3D58756651712ED9FFF29F72FF9F2B1D24B55809621D2FA59",
    "BD": "uid=4742455110&password=RIZERx64S9IC",
    "BR": "uid=2222222222&password=xxx",
    "US": "uid=3333333333&password=xxx",
}


def error_response(message: str, status_code: int, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": message, **extra},
    )


def get_clan_id(id_value: str | None, clan_id: str | None) -> str | None:
    return id_value or clan_id


def get_region(region: str) -> str:
    normalized = region.upper()
    return normalized if normalized in REGION_ENDPOINTS else "IND"


async def get_access_token(account: str) -> tuple[str | None, str | None]:
    try:
        parts = dict(item.split("=", 1) for item in account.split("&"))
        uid = parts.get("uid")
        password = parts.get("password")
        url = "https://ff-ob54-jwt-api.vercel.app/guest_to_jwt"

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, params={"uid": uid, "password": password})

        if response.status_code != 200:
            logger.error("JWT service returned status %s", response.status_code)
            return None, None

        data = response.json()
        jwt_token = data.get("jwt_token")
        access_token = data.get("access_token")
        if not jwt_token:
            logger.error("JWT service response did not include jwt_token")
            return None, None

        return jwt_token, access_token
    except Exception:
        logger.exception("JWT request failed")
        return None, None


async def create_jwt(region: str) -> None:
    account = REGION_ACCOUNTS.get(region, REGION_ACCOUNTS["IND"])
    token_value, open_id = await get_access_token(account)
    if token_value and open_id:
        jwt_tokens[region] = f"Bearer {token_value}"
        logger.info("JWT ready for region %s", region)
    else:
        logger.error("JWT unavailable for region %s", region)


async def ensure_token(region: str) -> str | None:
    if jwt_tokens.get(region):
        return jwt_tokens[region]

    await create_jwt(region)
    return jwt_tokens.get(region)


async def fetch_clan_response(clan_id: str, region: str) -> tuple[Any | None, JSONResponse | None]:
    try:
        numeric_clan_id = int(clan_id)
    except ValueError:
        return None, error_response("clan_id must be numeric", 400)

    try:
        token = await ensure_token(region)
    except Exception as exc:
        return None, error_response("Token initialization failed", 503, details=str(exc))

    if not token:
        return None, error_response("JWT not available", 503)

    try:
        request_data = encode_id_clan_pb2.MyData()
        request_data.field1 = numeric_clan_id
        request_data.field2 = 1
        payload = AES.new(AES_KEY, AES.MODE_CBC, AES_IV).encrypt(
            pad(request_data.SerializeToString(), 16)
        )

        url, host = REGION_ENDPOINTS[region]
        headers = {
            "Expect": "100-continue",
            "Authorization": token if token.startswith("Bearer ") else f"Bearer {token}",
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1",
            "ReleaseVersion": FREEFIRE_VERSION,
            "Content-Type": "application/octet-stream",
            "User-Agent": "Dalvik/2.1.0 (Linux; Android 11)",
            "Host": host,
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, headers=headers, content=payload)

        if response.status_code != 200:
            return None, error_response(
                f"HTTP {response.status_code}",
                502,
                body=response.text[:200],
            )

        decoded = data_pb2.response()
        decoded.ParseFromString(response.content)
        return decoded, None
    except Exception as exc:
        logger.exception("Clan lookup failed")
        return None, error_response("Server error", 500, details=str(exc))


def timestamp(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OverflowError):
        return None


def find_clan_info(response: Any) -> Any | None:
    clan_info = getattr(response, "clanInfo", None)
    if clan_info:
        return clan_info

    for field_name in dir(response):
        try:
            value = getattr(response, field_name)
            if value and (
                hasattr(value, "memberNum")
                or hasattr(value, "capacity")
                or hasattr(value, "captainBasicInfo")
            ):
                return value
        except Exception:
            continue
    return None


def info2_payload(response: Any, clan_id: str, region: str) -> dict[str, Any]:
    clan_info = find_clan_info(response)
    member_num = 0
    capacity = 50

    if clan_info:
        def pick(fields: list[str]) -> Any:
            for field_name in fields:
                if hasattr(clan_info, field_name):
                    value = getattr(clan_info, field_name)
                    if value is not None:
                        return value
            return 0

        try:
            member_num = int(pick(["memberNum", "memberCount", "members", "currentMembers"]) or 0)
        except (TypeError, ValueError):
            member_num = 0

        try:
            capacity = int(pick(["capacity", "maxMembers", "memberLimit"]) or 50)
        except (TypeError, ValueError):
            capacity = 50

        if capacity <= 0:
            capacity = 50

    return {
        "clan_id": getattr(response, "id", clan_id),
        "clan_name": getattr(response, "special_code", None),
        "created_at": timestamp(getattr(response, "timestamp1", 0)),
        "updated_at": timestamp(getattr(response, "timestamp2", 0)),
        "last_active": timestamp(getattr(response, "last_active", 0)),
        "level": getattr(response, "rank", None),
        "region": getattr(response, "region", region),
        "welcome_message": getattr(response, "welcome_message", None),
        "score": getattr(response, "score", 0),
        "xp": getattr(response, "xp", 0),
        "member_num": member_num,
        "capacity": capacity,
        "auth": API_AUTH,
        "cnct": API_CONTACT,
        "status": "success",
        "requested_region": region,
    }


def full_response_payload(response: Any, region: str) -> dict[str, Any]:
    try:
        full_response = MessageToDict(
            response,
            preserving_proto_field_name=True,
            including_default_value_fields=True,
        )
    except TypeError:
        full_response = MessageToDict(
            response,
            preserving_proto_field_name=True,
            always_print_fields_with_no_presence=True,
        )

    return {
        "status": "success",
        "requested_region": region,
        "auth": API_AUTH,
        "cnct": API_CONTACT,
        "full_response": full_response,
    }


async def clan_info_response(
    id_value: str | None,
    clan_id_value: str | None,
    region_value: str,
    detailed: bool,
) -> JSONResponse | dict[str, Any]:
    requested_id = get_clan_id(id_value, clan_id_value)
    if not requested_id:
        return error_response("clan_id is required", 400)

    region = get_region(region_value)
    response, error = await fetch_clan_response(requested_id, region)
    if error:
        return error

    if detailed:
        return full_response_payload(response, region)
    return info2_payload(response, requested_id, region)


@app.get("/", response_model=None)
async def root(
    id: str | None = None,
    clan_id: str | None = None,
    region: str = "IND",
) -> JSONResponse | dict[str, Any]:
    if not get_clan_id(id, clan_id):
        return {
            "auth": API_AUTH,
            "cnct": API_CONTACT,
            "status": "running",
            "endpoint": "/?id={}&region=",
            "docs": "/docs",
        }
    return await clan_info_response(id, clan_id, region, detailed=True)


@app.get("/info", response_model=None)
async def get_clan_info(
    id: str | None = None,
    clan_id: str | None = None,
    region: str = "IND",
) -> JSONResponse | dict[str, Any]:
    return await clan_info_response(id, clan_id, region, detailed=True)


@app.get("/info2", response_model=None)
async def get_clan_info2(
    id: str | None = None,
    clan_id: str | None = None,
    region: str = "IND",
) -> JSONResponse | dict[str, Any]:
    return await clan_info_response(id, clan_id, region, detailed=False)


@app.get("/health")
async def health_check() -> dict[str, Any]:
    return {
        "status": "running",
        "regions": {
            region: "ready" if jwt_tokens.get(region) else "not ready"
            for region in ["IND", "BD", "BR", "US", "SAC", "NA"]
        },
        "timestamp": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
    )