from pydantic import BaseModel, Field, SecretStr


class UserRegisterSchema(BaseModel):
    username: str
    password: SecretStr


class UserSchema(BaseModel):
    id: int
    username: str
    credits: int = Field(0, ge=0)
    hashed_password: str


class UserProfileSchema(BaseModel):
    username: str
    credits: int = Field(0, ge=0)


class RecordCreateSchema(BaseModel):
    text: str
