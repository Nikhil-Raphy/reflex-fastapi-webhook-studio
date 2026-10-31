"""The objects that the API and the UI share in one worker: settings, database, event bus and services."""

from typing import TYPE_CHECKING

from reflex.utils.prerequisites import get_redis

from reflex_fastapi_webhook_studio.bus.memory_bus import MemoryBus
from reflex_fastapi_webhook_studio.bus.redis_bus import RedisBus
from reflex_fastapi_webhook_studio.db.engine import Database
from reflex_fastapi_webhook_studio.log_config import configure_logging
from reflex_fastapi_webhook_studio.services.bins import BinService
from reflex_fastapi_webhook_studio.services.replay import ReplayService
from reflex_fastapi_webhook_studio.services.requests import RequestService
from reflex_fastapi_webhook_studio.services.sweeper import Sweeper
from reflex_fastapi_webhook_studio.settings import get_settings

if TYPE_CHECKING:
    from reflex_fastapi_webhook_studio.bus.base import EventBus

settings = get_settings()
configure_logging(settings.log_level)
database = Database(settings.database_url)
# Reflex's Redis, when REFLEX_REDIS_URL is set, carries events between workers; otherwise one worker needs none.
redis = get_redis()
bus: EventBus = MemoryBus() if redis is None else RedisBus(redis)
bin_service = BinService(database, settings, bus=bus)
request_service = RequestService(database, bus=bus)
replay_service = ReplayService(request_service, settings)
sweeper = Sweeper(database, settings.sweep_interval_s, bus=bus)
