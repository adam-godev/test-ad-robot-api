from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.integrations.keitaro.client import KeitaroClient


def get_keitaro_client(settings: Settings = Depends(get_settings)) -> KeitaroClient:
    return KeitaroClient(settings)


DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
KeitaroDep = Annotated[KeitaroClient, Depends(get_keitaro_client)]
