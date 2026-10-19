from __future__ import annotations

from app.lifecycle.context import AppContext
from app.lifecycle.task_supervisor import TaskSupervisor
from bot.command_handler import CommandHandler
from core.logger_config import get_logger
from core.message_dispatcher import MessageDispatcher
from music.sdk_voice import SdkVoiceController
from onebot_v11.config import get_onebot_v11_config
from onebot_v11.sdk_integration import OneBotV11Supplement, find_sdk_onebot_v11
from oopz.errors import SensitiveContentError
from oopz.name_resolver import get_resolver
from oopz.sdk_gateway import AsyncOopzGateway
from services.area_invite_inbox import capture_private_area_invites
from services.area_join_notifier import AreaJoinNotifier, start_area_join_notifier

logger = get_logger("AppContext")


class AppContextBuilder:
    @staticmethod
    async def _note_voice_dropped(handler: CommandHandler) -> None:
        note = getattr(handler.infrastructure.music, "note_connection_lost", None)
        if callable(note):
            note()

    @staticmethod
    async def _dispatch_private_command(gateway: AsyncOopzGateway, handler: CommandHandler | None, message: dict) -> None:
        """私信里的播放、进房等命令走和频道一样的处理，回复发回私信。"""
        if handler is None:
            return
        from config import OOPZ_CONFIG
        from core.constants import build_mention
        from domain.routing.private_command import looks_like_private_command

        content = str(message.get("content") or "")
        bot_uid = str(OOPZ_CONFIG.get("person_uid") or "")
        mention = build_mention(bot_uid) if bot_uid else ""
        if not looks_like_private_command(content, mention):
            return
        payload = dict(message)
        payload["private_reply_uid"] = str(message.get("person") or "")
        if not str(payload.get("area") or "").strip():
            payload["area"] = await AppContextBuilder._private_command_area(
                gateway, payload["private_reply_uid"]
            )
        payload["channel"] = str(OOPZ_CONFIG.get("default_channel") or "")
        if not payload["channel"] and payload.get("area"):
            payload["channel"] = await AppContextBuilder._first_text_channel(gateway, payload["area"])
        await handler.handle_message(payload)

    @staticmethod
    async def _first_text_channel(gateway: AsyncOopzGateway, area: str) -> str:
        from web.lobby_rules import is_voice_channel

        try:
            groups = await gateway.get_area_channels(area=area, quiet=True)
        except Exception:
            return ""
        for group in groups or []:
            if not isinstance(group, dict):
                continue
            for channel in group.get("channels") or []:
                if not isinstance(channel, dict):
                    continue
                if is_voice_channel(str(channel.get("type") or "")):
                    continue
                channel_id = str(channel.get("id") or "").strip()
                if channel_id:
                    return channel_id
        return ""

    @staticmethod
    async def _private_command_area(gateway: AsyncOopzGateway, uid: str) -> str:
        from config import OOPZ_CONFIG

        try:
            areas = await gateway.get_joined_areas(quiet=True)
        except Exception:
            areas = []
        for item in areas or []:
            if not isinstance(item, dict):
                continue
            area_id = str(item.get("id") or item.get("area") or "").strip()
            if not area_id or not uid:
                continue
            voice = await gateway.get_voice_channel_for_user(uid, area=area_id)
            if voice:
                return area_id
        return str(OOPZ_CONFIG.get("default_area") or "")

    """在当前事件循环组装 SDK 网关、命令分发和补充服务。"""

    async def build(self, supervisor: TaskSupervisor) -> AppContext:
        dispatcher = MessageDispatcher(workers=4, maxsize=512)
        dispatcher.start()

        # 两个回调在网关创建时就要传入，届时处理器与通知器尚未组装完成；闭包按引用
        # 读取下面的局部变量，因此启动期的事件会命中 None 分支而不是空指针。
        gateway: AsyncOopzGateway | None = None
        handler: CommandHandler | None = None
        notifier: AreaJoinNotifier | None = None

        async def dispatch_chat(message: dict) -> None:
            current = handler
            if current is None:
                logger.warning("命令处理器尚未就绪，忽略一条启动期消息")
                return
            key = f"{message.get('area') or ''}:{message.get('channel') or ''}"

            async def handle() -> None:
                try:
                    await current.handle_message(message)
                except SensitiveContentError:
                    logger.debug("回复被平台风控拦截，已忽略（发送层已记录）")

            dispatcher.submit(key, handle)

        async def dispatch_private_message(message: dict) -> None:
            current = gateway
            if current is None:
                logger.warning("SDK 网关尚未就绪，忽略一条启动期私信")
                return

            async def handle() -> None:
                await capture_private_area_invites(current, message)
                await self._dispatch_private_command(current, handler, message)

            sender_id = str(message.get("person") or "")
            dispatcher.submit(f"__private_invite__:{sender_id}", handle)

        async def dispatch_other_event(event: int, data: dict) -> None:
            current = notifier
            if current is not None:
                dispatcher.submit("__other_events__", current, event, data)

        try:
            gateway = await AsyncOopzGateway.create(
                on_chat_message=dispatch_chat,
                on_private_message=dispatch_private_message,
                on_other_event=dispatch_other_event,
            )
            voice = SdkVoiceController(
                gateway.bot.voice,
                proxy_value=gateway._proxy_value,
                supervisor=supervisor,
            )
            handler = CommandHandler(
                gateway,
                voice_client=voice,
                supervisor=supervisor,
            )
            await get_resolver().bind_gateway(gateway)
            await handler.start()
            gateway.bind_auto_recall_scheduler(
                handler.services.safety.recall_scheduler
            )
            await gateway.start(supervisor)
            await gateway.populate_names()
            register_reconnect = gateway.bot.on("reconnect")
            if callable(register_reconnect):
                register_reconnect(lambda _ctx: self._note_voice_dropped(handler))

            onebot_adapter = find_sdk_onebot_v11(gateway.bot)
            onebot_v11 = (
                OneBotV11Supplement(
                    onebot_adapter,
                    gateway,
                    get_onebot_v11_config(),
                )
                if onebot_adapter is not None
                else None
            )
            if onebot_v11 is not None:
                onebot_v11.start(supervisor)

            async def on_member_change(action: str, area: str, uid: str) -> None:
                if onebot_v11 is not None:
                    await onebot_v11.emit_member_change(action, area, uid)

            notifier = start_area_join_notifier(
                sender=gateway,
                on_member_change=on_member_change,
                supervisor=supervisor,
            )
            return AppContext(
                sender=gateway,
                handler=handler,
                client=gateway,
                notifier_callback=notifier,
                onebot_v11=onebot_v11,
                voice=voice,
                dispatcher=dispatcher,
                supervisor=supervisor,
            )
        except BaseException:
            if handler is not None:
                await handler.infrastructure.plugins.stop(timeout=2.0)
            if gateway is not None:
                await gateway.stop()
            await dispatcher.stop(timeout=2.0)
            raise
