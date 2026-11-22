from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    app_name: str = "Private Attendance API"
    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 720
    cors_origins: str = "http://localhost:3001,http://127.0.0.1:3001"
    admin_username: str = "admin"
    admin_password: str = "ChangeThisAdminPassword!"
    google_client_id: str = ""
    firebase_credentials_path: str = ""
    app_timezone: str = "Asia/Kolkata"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
settings = Settings()
