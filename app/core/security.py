import hashlib, hmac, os
from datetime import datetime, timedelta
from jose import jwt
from app.core.config import settings

def hash_password(password: str) -> str:
    salt=os.urandom(16)
    digest=hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310000)
    return salt.hex()+"$"+digest.hex()

def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest=stored.split("$",1)
        actual=hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 310000).hex()
        return hmac.compare_digest(actual,digest)
    except Exception: return False

def make_token(user_id: int, role: str):
    return jwt.encode({"sub":str(user_id),"role":role,"exp":datetime.utcnow()+timedelta(minutes=settings.access_token_minutes)},settings.jwt_secret,algorithm=settings.jwt_algorithm)
