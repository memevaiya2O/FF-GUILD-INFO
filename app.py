import httpx
import time
import re
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify
from datetime import datetime
import asyncio
import data_pb2
import encode_id_clan_pb2

# ===================== CONFIG =====================
app = Flask(__name__)
freefire_version = "OB54"
API_AUTH = "FFxAPI"
API_CONTACT = "https://t.me/FFxAPI"
key = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
iv = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])
jwt_tokens = {}  # Store tokens by region
# =================================================
USERAGENT = "Dalvik/2.1.0 (Linux; Android 11; Mobile)"
# ===================== REGION CONFIG =====================
def get_region_credentials(region):
    r = region.upper()
    if r == "IND":
        return "uid={}&password={}"
    elif r == "BD":
        return "uid={}&password={}"
    elif r in {"BR", "US", "SAC", "NA"}:
        return "uid={}&password={}"
    else:
        return "uid={}&password={}"

# ===================== ENCRYPT UID =====================
def Encrypt_ID(x):
    x = int(x)
    dec = [f'{i:02x}' for i in range(128, 256)]
    xxx = [f'{i:02x}' for i in range(0, 128)]

    parts = []
    while x > 0:
        parts.append(x % 128)
        x //= 128
    while len(parts) < 5:
        parts.append(0)
    parts.reverse()

    return ''.join(dec[parts[i]] if i > 0 else xxx[parts[i]] for i in range(5))

# ===================== AES ENCRYPT =====================
def encrypt_api(plain_text_hex):
    plain_text = bytes.fromhex(plain_text_hex)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.encrypt(pad(plain_text, 16)).hex()

# ===================== EMOTE ID EN/DE =====================
def Encrypt_id_emote(uid):
    result = []
    while uid > 0:
        byte = uid & 0x7F
        uid >>= 7
        if uid > 0:
            byte |= 0x80
        result.append(byte)
    return bytes(result).hex()

def Decrypt_id_emote(uidd):
    bytes_value = bytes.fromhex(uidd)
    r, shift = 0, 0
    for byte in bytes_value:
        r |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return r

# ===================== TIMESTAMP =====================
def convert_timestamp(ts):
    return datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')

# ===================== JWT TOKEN =====================
# ===================== JWT TOKEN =====================
import logging

# Add logging setup for better tracking
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def get_access_token(account):
    try:
        parts = dict(x.split("=") for x in account.split("&"))
        uid = parts.get("uid")
        password = parts.get("password")

        url = f"https://ff-ob54-jwt-api.vercel.app/guest_to_jwt?uid={uid}&password={password}"

        logger.debug(f"Requesting JWT for UID: {uid}, Password: {password}")
        
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url)

        logger.debug(f"API Response Status Code: {r.status_code}")
        if r.status_code != 200:
            logger.error(f"[JWT API FAIL] Status Code: {r.status_code} - Response: {r.text[:100]}")
            return None, None

        data = r.json()
        logger.debug(f"API Response JSON: {data}")

        # Verifique se o jwt_token está na resposta
        jwt_token = data.get("jwt_token")
        access_token = data.get("access_token")

        if not jwt_token:
            logger.error("[JWT API FAIL] Token not found in the response.")
            return None, None

        logger.debug(f"JWT Token retrieved successfully for UID: {uid}")
        return jwt_token, access_token  # Agora retornando tanto o jwt_token quanto o access_token

    except Exception as e:
        logger.error(f"[JWT API ERROR] Exception: {e}")
        return None, None

async def create_jwt(region):
    try:
        accounts = {
            "IND": "uid=6631809990&password=8C24A89B3FB5F3D3D58756651712ED9FFF29F72FF9F2B1D24B55809621D2FA59",
            "BD": "uid=4742455110&password=RIZERx64S9IC",
            "BR": "uid=2222222222&password=xxx",
            "US": "uid=3333333333&password=xxx"
        }

        account = accounts.get(region, accounts["IND"])

        token_val, open_id = await get_access_token(account)

        if not token_val or not open_id:
            logger.error(f"[FAIL ACCESS] {region}")
            return

        jwt_tokens[region] = f"Bearer {token_val}"
        logger.info(f"[OK] JWT READY {region}")

    except Exception as e:
        logger.error(f"[JWT ERROR] {e}")


# ===================== CREATE JWT =====================


async def ensure_token(region):
    region = region.upper()

    if jwt_tokens.get(region):
        return jwt_tokens[region]

    await create_jwt(region)
    return jwt_tokens.get(region)
# ===================== CLAN INFO ROUTE (SYNC) =====================
@app.route('/info2', methods=['GET'])
def get_clan_info222():
    clan_id = request.args.get('id') or request.args.get('clan_id')
    region = request.args.get('region', 'IND').upper()

    # Validate clan_id
    if not clan_id:
        return jsonify({"error": "clan_id is required"}), 400

    try:
        # Fetch the JWT token asynchronously
        token = asyncio.run(ensure_token(region))
    except Exception as e:
        return jsonify({"error": "Token initialization failed", "details": str(e)}), 503

    if not token:
        return jsonify({"error": "JWT not available"}), 503

    try:
        # PROTOBUF: Encode the data
        my_data = encode_id_clan_pb2.MyData()
        my_data.field1 = int(clan_id)
        my_data.field2 = 1

        data_bytes = my_data.SerializeToString()

        # AES Encryption
        cipher = AES.new(key, AES.MODE_CBC, iv)
        encrypted_data = cipher.encrypt(pad(data_bytes, 16))  # Ensure data is padded correctly
        payload = encrypted_data

        # Region URL Mapping
        region_map = {
            "IND": ("https://client.ind.freefiremobile.com/GetClanInfoByClanID", "client.ind.freefiremobile.com"),
            "BD": ("https://clientbp.ggpolarbear.com/GetClanInfoByClanID", "clientbp.ggpolarbear.com"),
            "BR": ("https://client.br.freefiremobile.com/GetClanInfoByClanID", "client.br.freefiremobile.com"),
            "SAC": ("https://client.br.freefiremobile.com/GetClanInfoByClanID", "client.br.freefiremobile.com"),
            "US": ("https://client.na.freefiremobile.com/GetClanInfoByClanID", "client.na.freefiremobile.com"),
            "NA": ("https://client.na.freefiremobile.com/GetClanInfoByClanID", "client.na.freefiremobile.com"),
        }

        url, host = region_map.get(region, region_map["IND"])

        headers = {
            "Expect": "100-continue",
            "Authorization": f"Bearer {token}" if not token.startswith("Bearer ") else token,
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1",
            "ReleaseVersion": freefire_version,
            "Content-Type": "application/octet-stream",
            "User-Agent": "Dalvik/2.1.0 (Linux; Android 11)",
            "Host": host,
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip"
        }

        # Sending request
        with httpx.Client(timeout=20.0) as client:
            response = client.post(url, headers=headers, content=payload)

        # Handle non-200 status codes
        if response.status_code != 200:
            return jsonify({
                "error": f"HTTP {response.status_code}",
                "body": response.text[:200]  # Limit to first 200 characters for brevity
            }), 500

        # PROTOBUF: Decode the response
        resp = data_pb2.response()
        resp.ParseFromString(response.content)

        # Timestamp conversion
        def ts(x):
            try:
                return datetime.fromtimestamp(int(x)).strftime("%Y-%m-%d %H:%M:%S")
            except:
                return None

        # Auto find clan info logic
        def auto_find_clan_info(obj):
            if hasattr(obj, "clanInfo") and obj.clanInfo:
                return obj.clanInfo

            for f in dir(obj):
                try:
                    val = getattr(obj, f)
                    if val and (
                        hasattr(val, "memberNum") or
                        hasattr(val, "capacity") or
                        hasattr(val, "captainBasicInfo")
                    ):
                        return val
                except:
                    pass
            return None

        clan_info = auto_find_clan_info(resp)

        # Default values
        member_num = 0
        capacity = 50
        leader_uid = 0
        members_online = getattr(resp, "members_online", 0)

        # Auto fix clan members and capacity
        if clan_info:
            def pick(fields):
                for f in fields:
                    if hasattr(clan_info, f):
                        v = getattr(clan_info, f)
                        if v is not None:
                            return v
                return 0

            member_num = pick(["memberNum", "memberCount", "members", "currentMembers"])
            capacity = pick(["capacity", "maxMembers", "memberLimit"])

            try:
                member_num = int(member_num or 0)
            except:
                member_num = 0

            try:
                capacity = int(capacity or 50)
            except:
                capacity = 50

            if capacity <= 0:
                capacity = 50

            # Fix for leader
            captain = getattr(clan_info, "captainBasicInfo", None)
            if captain:
                leader_uid = int(getattr(captain, "accountId", 0) or 0)

        # Final response
        return jsonify({
            "clan_id": getattr(resp, "id", clan_id),
            "clan_name": getattr(resp, "special_code", None),
            "created_at": ts(getattr(resp, "timestamp1", 0)),
            "updated_at": ts(getattr(resp, "timestamp2", 0)),
            "last_active": ts(getattr(resp, "last_active", 0)),
            "level": getattr(resp, "rank", None),
            "region": getattr(resp, "region", region),
            "welcome_message": getattr(resp, "welcome_message", None),
            "score": getattr(resp, "score", 0),
            "xp": getattr(resp, "xp", 0),
            "auth": API_AUTH,
            "cnct": API_CONTACT,
            "status": "success",
            "requested_region": region
        })

    except Exception as e:
        return jsonify({
            "error": "Server error",
            "details": str(e)
        }), 500



@app.route('/info', methods=['GET'])
def get_clan_info():
    clan_id = request.args.get('id') or request.args.get('clan_id')
    region = request.args.get('region', 'IND').upper()

    # Validate clan_id
    if not clan_id:
        return jsonify({"error": "clan_id is required"}), 400

    try:
        # Fetch the JWT token asynchronously
        token = asyncio.run(ensure_token(region))
    except Exception as e:
        return jsonify({"error": "Token initialization failed", "details": str(e)}), 503

    if not token:
        return jsonify({"error": "JWT not available"}), 503

    try:
        # PROTOBUF: Encode the data
        my_data = encode_id_clan_pb2.MyData()
        my_data.field1 = int(clan_id)
        my_data.field2 = 1
        data_bytes = my_data.SerializeToString()

        # AES Encryption
        cipher = AES.new(key, AES.MODE_CBC, iv)
        encrypted_data = cipher.encrypt(pad(data_bytes, 16))
        payload = encrypted_data

        # Region URL Mapping
        region_map = {
            "IND": ("https://client.ind.freefiremobile.com/GetClanInfoByClanID", "client.ind.freefiremobile.com"),
            "BD": ("https://clientbp.ggpolarbear.com/GetClanInfoByClanID", "clientbp.ggpolarbear.com"),
            "BR": ("https://client.br.freefiremobile.com/GetClanInfoByClanID", "client.br.freefiremobile.com"),
            "SAC": ("https://client.br.freefiremobile.com/GetClanInfoByClanID", "client.br.freefiremobile.com"),
            "US": ("https://client.na.freefiremobile.com/GetClanInfoByClanID", "client.na.freefiremobile.com"),
            "NA": ("https://client.na.freefiremobile.com/GetClanInfoByClanID", "client.na.freefiremobile.com"),
        }

        url, host = region_map.get(region, region_map["IND"])

        headers = {
            "Expect": "100-continue",
            "Authorization": f"Bearer {token}" if not token.startswith("Bearer ") else token,
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1",
            "ReleaseVersion": freefire_version,
            "Content-Type": "application/octet-stream",
            "User-Agent": "Dalvik/2.1.0 (Linux; Android 11)",
            "Host": host,
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip"
        }

        # Sending request
        with httpx.Client(timeout=20.0) as client:
            response = client.post(url, headers=headers, content=payload)

        if response.status_code != 200:
            return jsonify({
                "error": f"HTTP {response.status_code}",
                "body": response.text[:200]
            }), 500

        # PROTOBUF: Decode the response
        resp = data_pb2.response()
        resp.ParseFromString(response.content)

        # Convert entire protobuf response to dict
        full_response = MessageToDict(
            resp,
            preserving_proto_field_name=True,
            including_default_value_fields=True
        )

        # Return everything
        return jsonify({
            "status": "success",
            "requested_region": region,
            "auth": API_AUTH,
            "cnct": API_CONTACT,
            "full_response": full_response
        })

    except Exception as e:
        return jsonify({
            "error": "Server error",
            "details": str(e)
        }), 500
        
                        
@app.route('/', methods=['GET'])
def home():
    if request.args.get('id') or request.args.get('clan_id'):
        return get_clan_info()

    return """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>FFxAPI SYSTEM</title>

<style>
body{
    margin:0;
    font-family: 'Segoe UI', sans-serif;
    background: radial-gradient(circle at top, #0f172a, #020617);
    color:white;
}

/* ⭐ STARS BACKGROUND */
.stars {
    position: fixed;
    width: 100%;
    height: 100%;
    top: 0;
    left: 0;
    z-index: -1;
    overflow: hidden;
    pointer-events: none;
    background: radial-gradient(circle at top, #020617, #000000);
}

/* ⭐ BIG SOFT STARS */
body{
    margin:0;
    font-family:'Segoe UI', sans-serif;
    color:white;
    background:#000;
    overflow:hidden;
}

/* 🌐 CYBER GRID */
body::before{
    content:"";
    position:fixed;
    width:200%;
    height:200%;
    top:-50%;
    left:-50%;
    background:
        linear-gradient(rgba(0,255,255,0.08) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0,255,255,0.08) 1px, transparent 1px);
    background-size:60px 60px;
    animation:gridMove 12s linear infinite;
    z-index:-2;
}

/* 🌈 NEON GLOW WAVES */
body::after{
    content:"";
    position:fixed;
    width:200%;
    height:200%;
    top:-50%;
    left:-50%;
    background: radial-gradient(circle at 20% 30%, rgba(0,255,255,0.18), transparent 40%),
                radial-gradient(circle at 80% 70%, rgba(255,0,255,0.15), transparent 45%),
                radial-gradient(circle at 50% 50%, rgba(0,255,100,0.10), transparent 50%);
    animation:waveMove 18s ease-in-out infinite;
    z-index:-1;
}

/* 🔄 ANIMATIONS */
@keyframes gridMove{
    0%{ transform:translate(0,0); }
    100%{ transform:translate(60px,60px); }
}

@keyframes waveMove{
    0%{ transform:rotate(0deg) scale(1); }
    50%{ transform:rotate(180deg) scale(1.2); }
    100%{ transform:rotate(360deg) scale(1); }
}

/* ⭐ BIG STARS OVER CYBER BACKGROUND */
.stars {
    position: fixed;
    width: 100%;
    height: 100%;
    top: 0;
    left: 0;
    z-index: -1;
    pointer-events: none;
    overflow: hidden;
}

/* BIG SOFT STAR */
.star {
    position: absolute;
    width: 6px;
    height: 6px;
    background: white;
    border-radius: 50%;
    box-shadow: 0 0 20px rgba(255,255,255,0.9);
    opacity: 0.9;
    animation: starFall 10s linear infinite;
}

/* STAR FALL */
@keyframes starFall {
    0% {
        transform: translateY(-20px);
        opacity: 1;
    }
    100% {
        transform: translateY(110vh);
        opacity: 0;
    }
}

/* UI */
.container{
    max-width: 1000px;
    margin:auto;
    padding:40px;
}

h1{
    font-size:40px;
    text-align:center;
    color:#00f5ff;
    text-shadow:0 0 15px #00f5ff;
}

.card{
    background: rgba(255,255,255,0.05);
    border:1px solid rgba(0,255,255,0.2);
    padding:20px;
    margin-top:20px;
    border-radius:15px;
    box-shadow:0 0 20px rgba(0,255,255,0.1);
    backdrop-filter: blur(10px);
}

.badge{
    display:inline-block;
    padding:5px 10px;
    border-radius:8px;
    background:#00f5ff;
    color:#000;
    font-weight:bold;
}

code{
    background:#000;
    padding:6px 10px;
    border-radius:8px;
    color:#00ff88;
    display:inline-block;
}

.grid{
    display:grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap:15px;
}

.glow{
    color:#00ff88;
    text-shadow:0 0 10px #00ff88;
}

.warn{
    color:#ff4d4d;
    text-shadow:0 0 10px #ff4d4d;
}
</style>

</head>

<body>

<!-- 🔊 MUSIC -->
<audio id="bgmusic" loop preload="auto" muted>
    <source src="/static/Mujick.mp3" type="audio/mpeg">
</audio>

<!-- 🎵 BUTTON -->
<button id="musicBtn"
style="
    position:fixed;
    top:15px;
    right:15px;
    z-index:9999;
    padding:10px 14px;
    border:none;
    border-radius:10px;
    background:#00f5ff;
    color:#000;
    font-weight:bold;
    box-shadow:0 0 10px #00f5ff;
    cursor:pointer;
">
▶ Enable Sound
</button>

<script>
const music = document.getElementById("bgmusic");
const btn = document.getElementById("musicBtn");

/* ⚡ TRY AUTO PLAY */
window.addEventListener("load", async () => {
    try {
        await music.play();   // autoplay attempt
        music.muted = false;
        btn.innerHTML = "⏸ Pause Music";
    } catch (e) {
        console.log("Autoplay blocked");
    }
});

/* ⚡ USER CLICK UNMUTE (100% WORKING) */
btn.onclick = async () => {
    try {
        if (music.paused) {
            music.muted = false;
            await music.play();
            btn.innerHTML = "⏸ Pause Music";
        } else {
            music.pause();
            btn.innerHTML = "▶ Play Music";
        }
    } catch (e) {
        alert("Click again (browser policy)");
    }
};
</script>
<!-- ⭐ STAR ANIMATION -->
<div class="stars">
    <div class="star" style="left:5%; animation-duration:7s;"></div>
    <div class="star" style="left:15%; animation-duration:9s;"></div>
    <div class="star" style="left:25%; animation-duration:6s;"></div>
    <div class="star" style="left:35%; animation-duration:8s;"></div>
    <div class="star" style="left:45%; animation-duration:10s;"></div>
    <div class="star" style="left:55%; animation-duration:7s;"></div>
    <div class="star" style="left:65%; animation-duration:9s;"></div>
    <div class="star" style="left:75%; animation-duration:6s;"></div>
    <div class="star" style="left:85%; animation-duration:8s;"></div>
    <div class="star" style="left:95%; animation-duration:7s;"></div>
</div>

<div class="container">

<h1 style="display:flex;align-items:center;justify-content:center;gap:12px;font-size:48px;color:#00f5ff;text-shadow:0 0 20px #00f5ff;">
    <img src="https://freefireadvanceserver.in/wp-content/uploads/2026/01/ff-advanced-Server.webp"
         style="width:55px;height:auto;filter:drop-shadow(0 0 10px #00f5ff);">
    Fꜰ Gᴜʟᴅ Aᴩɪ Sʏꜱᴛᴇᴍ
</h1>

<div class="card">

    <div style="display:flex;align-items:center;gap:10px;">
        <img src="https://cdn-icons-png.flaticon.com/512/5610/5610944.png"
             style="width:20px;height:20px;filter:drop-shadow(0 0 6px #00f5ff);">
        <span style="font-weight:bold;">Sᴛᴀᴛᴜꜱ:</span>

        <span style="
            display:inline-block;
            padding:3px 8px;
            font-size:10px;
            border-radius:6px;
            background:#00f5ff;
            color:#000;
            font-weight:bold;
            box-shadow:0 0 8px #00f5ff;
        ">
            ONLINE
        </span>
    </div>

    <br>

    <div style="display:flex;align-items:center;gap:10px;">
        <img src="https://cdn-icons-png.flaticon.com/512/854/854878.png"
             style="width:20px;height:20px;filter:drop-shadow(0 0 6px #00ff88);">
        <span style="font-weight:bold;">Rᴇɢɪᴏɴ:</span>

        <span style="color:#00ff88; text-shadow:0 0 8px #00ff88;">
            🇮🇳 IND 🇧🇩 BD 🇧🇷 BR 🇺🇸 US 🇳🇦 NA
        </span>
    </div>

</div>
<div class="grid">

<div class="card">
<h2 style="display:flex;align-items:center;gap:10px;color:#ff3b3b;">
    
    <span style="
        font-size:22px;
        color:#ff3b3b;
        text-shadow:0 0 10px #ff3b3b;
    ">
        ✔
    </span>

    Hᴏᴡ Tᴏ Uꜱᴀɢᴇ Aᴩɪ
</h2>
<code>/?id=123456&amp;region=IND</code>
<p>Gᴇᴛ Cʟᴀɴ Dᴀᴛᴀ OB53</p>
</div>

<div class="card">
<h2 style="display:flex;align-items:center;gap:10px;">
    <img src="https://cdn-icons-png.flaticon.com/512/603/603197.png"
         style="width:28px;height:28px;filter:drop-shadow(0 0 8px #00f5ff);">
   Fꜰ Cʟᴀɴ Dᴀᴛᴀ
</h2>
<p style="color:#00ff88; text-shadow:0 0 8px #00ff88;">✔ Cʟᴀɴ Nᴀᴍᴇ</p>
<p style="color:#00ff88; text-shadow:0 0 8px #00ff88;">✔ Cʟᴀɴ Fᴜʟʟ Dᴇᴛᴀɪʟꜱ </p>
<p style="color:#00ff88; text-shadow:0 0 8px #00ff88;">✔ Fꜰ Oꜰꜰɪᴄɪᴀʟ Dᴀᴛᴀ </p>
<p style="color:#00ff88; text-shadow:0 0 8px #00ff88;">✔ Uᴩᴅᴀᴛᴇ Vᴇʀꜱɪᴏɴ OB53</p>
</div>

</div>

<div class="card">
<h2 style="display:flex;align-items:center;gap:10px;color:#ff3b3b;">
    <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28"
         viewBox="0 0 24 24" fill="none"
         style="filter:drop-shadow(0 0 10px #ff3b3b);">
        
        <!-- white circle -->
        <circle cx="12" cy="12" r="10" fill="white"></circle>

        <!-- red question mark -->
        <path d="M9.5 9a2.5 2.5 0 0 1 5 1c0 2-3 2-3 4"
              stroke="#ff3b3b"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"/>

        <!-- red dot -->
        <circle cx="12" cy="17" r="1.2" fill="#ff3b3b"></circle>

    </svg>

    Exᴀᴍᴩʟᴇ Rᴇꜱᴩᴏɴꜱᴇ
</h2>
<pre style="
    background:#0b0000;
    color:#ff3b3b;
    padding:15px;
    border-radius:10px;
    border:1px solid #ff3b3b;
    box-shadow:0 0 15px #ff3b3b;
    overflow:auto;
">
{
  "auth": "FFxAPI",
  "cnct": "https://t.me/FFxAPI",
  "clan_id": 60205231,
  "clan_name": "MGㅤINDIAㅤ",
  "created_at": "2018-02-07 14:12:53",
  "last_active": "2026-03-23 07:50:11",
  "level": 7,
  "region": "IND",
  "requested_region": "IND",
  "score": 19,
  "status": "success",
  "updated_at": "2026-04-05 08:27:15",
  "welcome_message": "To join Msg on insta- @dc_1k4ran_",
  "xp": 202615
}
</pre>
</div>

<div class="card warn" style="display:flex;align-items:center;gap:10px;">

    <img src="https://cdn-icons-png.flaticon.com/512/564/564619.png"
         style="width:22px;height:22px;filter:drop-shadow(0 0 8px #ff4d4d);">

    <span>This API is for testing / educational use only</span>

</div>

</div>

</body>
<div style="
    text-align:center;
    margin-top:40px;
    padding:20px;
">

    <!-- TG BUTTON -->
    <a href="https://t.me/FFxAPI" target="_blank" style="text-decoration:none;">

        <div style="
            display:inline-flex;
            align-items:center;
            gap:10px;
            padding:12px 18px;
            margin:5px;
            border-radius:50px;
            background:linear-gradient(135deg,#0088cc,#00f5ff);
            box-shadow:0 0 15px #00f5ff;
        ">
            <img src="https://cdn-icons-png.flaticon.com/512/2111/2111646.png"
                 width="26" height="26">
            <span style="color:white;font-weight:bold;">Telegram</span>
        </div>

    </a>

</div>
</html>
"""        
# ===================== HEALTH CHECK =====================
@app.route('/health', methods=['GET'])
def health_check():
    regions_status = {}
    for region in ["IND", "BD", "BR", "US", "SAC", "NA"]:
        regions_status[region] = "ready" if region in jwt_tokens and jwt_tokens[region] else "not ready"
    
    return jsonify({
        "status": "running",
        "regions": regions_status,
        "timestamp": datetime.now().isoformat()
    })

# ===================== STARTUP =====================


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
    
