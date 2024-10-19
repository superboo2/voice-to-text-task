import asyncio
from typing import Annotated
import jwt

from fastapi import FastAPI, Response, HTTPException, Request, status, Depends
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm

from helpers import (
    get_audio_from_text,
    hash_password,
    create_tokens_for_user,
    SECRET_KEY,
    TOKEN_ALGORITHM,
    verify_password_and_update,
    oauth2_scheme,
)
from schemas import (
    UserRegisterSchema,
    UserSchema,
    UserProfileSchema,
    RecordCreateSchema,
)

app = FastAPI()

# fake db
users = []
records = []
current_user_id = 0  # pylint: disable=C0103
user_semaphores = {}


async def authenticate_user(username: str, password: str) -> UserSchema:
    user = next((user for user in users if user.username == username), None)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid username or password")

    verification_result = verify_password_and_update(password, user.hashed_password)
    if not verification_result[0]:
        raise HTTPException(status_code=400, detail="Invalid username or password")

    if verification_result[1] is not None:
        user.hashed_password = verification_result[1]
        await user.save(update_fields=("hashed_password",))

    return user


async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserSchema:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[TOKEN_ALGORITHM])
        user_id = int(payload.get("id"))
        user = next((user for user in users if user.id == user_id), None)
    except jwt.exceptions.InvalidTokenError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from err

    return user


async def get_user_semaphore(user_id: int):
    if user_id not in user_semaphores:
        user_semaphores[user_id] = asyncio.Semaphore(3)
    return user_semaphores[user_id]


@app.middleware("http")
async def limit_concurrent_requests(request: Request, call_next):
    if request.method == "POST" and request.url.path in ["/concurrent-requests", "/records"]:

        bearer_token = request.headers.get("authorization")
        user_id = None
        if bearer_token:
            token = bearer_token.replace("Bearer ", "")
            payload = jwt.decode(token, SECRET_KEY, algorithms=[TOKEN_ALGORITHM])
            user_id = payload.get("id")

        if not user_id:
            return Response(status_code=status.HTTP_401_UNAUTHORIZED)

        if user_id not in user_semaphores:
            user_semaphores[user_id] = asyncio.Semaphore(3)

        semaphore = user_semaphores[user_id]

        async with semaphore:
            response = await call_next(request)

        return response

    return await call_next(request)


@app.post("/register", status_code=status.HTTP_201_CREATED)
async def create_user(user_schema: UserRegisterSchema):
    if any(user_schema.username == user.username for user in users):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already exists")

    global current_user_id  # pylint: disable=W0603
    current_user_id += 1

    user = UserSchema(
        id=current_user_id,
        username=user_schema.username,
        hashed_password=hash_password(user_schema.password.get_secret_value()),
        credits=10,
    )
    users.append(user)

    return Response(status_code=status.HTTP_201_CREATED)


@app.post("/login", status_code=status.HTTP_200_OK)
async def generate_tokens(form_data: OAuth2PasswordRequestForm = Depends()):
    username = form_data.username
    password = form_data.password
    user = await authenticate_user(username=username, password=password)
    return create_tokens_for_user(user)


@app.get("/user", response_model=UserProfileSchema)  # information about credits
async def get_profile(user: Annotated[UserSchema, Depends(get_current_user)]):
    return user


@app.post("/records")
async def create_record(record_data: RecordCreateSchema, user: Annotated[UserSchema, Depends(get_current_user)]):
    words = record_data.text.split(" ")
    word_count = len(words)

    if word_count > user.credits:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"You have not enough credits. Your credits: {user.credits}, the cost is {word_count} credits.",
        )

    user.credits -= word_count
    audio = await get_audio_from_text(record_data.text)

    return StreamingResponse(
        content=audio, media_type="audio/mpeg", headers={"Content-Disposition": "attachment; filename=record.mp3"}
    )


# This endpoint is only for testing limit_concurrent_requests
# I don't want to waste credits from ElevenLabs with /records endpoint.
@app.post("/concurrent-requests")
async def create_three_sec_request(_: Annotated[UserSchema, Depends(get_current_user)]):
    await asyncio.sleep(3)
    return Response(status_code=200)
