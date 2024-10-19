import os
from datetime import datetime, timedelta
import jwt
from elevenlabs.client import AsyncElevenLabs
from dotenv import load_dotenv
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer
from schemas import UserSchema


load_dotenv()

client = AsyncElevenLabs(api_key=os.getenv("API_KEY_ELEVENLABS"))
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

SECRET_KEY = os.getenv("SECRET_KEY")
TOKEN_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRES_MINUTES = 60
REFRESH_TOKEN_EXPIRES_MINUTES = 60 * 24 * 7


async def get_audio_from_text(text):
    audio = await client.generate(text=text, voice="Brian", model="eleven_multilingual_v2")
    return audio


def hash_password(password):
    return pwd_context.hash(password)


def verify_password_and_update(plain_password: str, hashed_password: str) -> tuple[bool, str]:
    return pwd_context.verify_and_update(plain_password, hashed_password)


def create_token(data: dict[str, str | datetime], token_type: str, exp: datetime):
    data["exp"] = exp
    data["token_type"] = token_type
    return jwt.encode(data, SECRET_KEY, algorithm=TOKEN_ALGORITHM)


def create_tokens_for_user(user: UserSchema):
    token_data = {"id": str(user.id), "username": user.username}

    access_token_expires = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRES_MINUTES)
    access_token = create_token(data=token_data, token_type="access", exp=access_token_expires)

    refresh_token_expires = datetime.utcnow() + timedelta(minutes=REFRESH_TOKEN_EXPIRES_MINUTES)
    refresh_token = create_token(data=token_data, token_type="refresh", exp=refresh_token_expires)

    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}
