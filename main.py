from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import json
import os


@register(
    "gsign",
    "Nova",
    "每日自动群签到插件，支持白名单/黑名单模式",
    "v1.0.0",
)
class GSignPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.scheduler = AsyncIOScheduler()
        self._job_id = "gsign_daily_sign"

    async def initialize(self):
        config_dir = os.path.join("data", "plugins", "gsign")
        os.makedirs(config_dir, exist_ok=True)
        self._config_path = os.path.join(config_dir, "settings.json")
        self._load_config()
        self._setup_scheduler()
        logger.info("[gsign] 插件初始化完成")

    # -------------------------------------------------------------------------
    # 定时任务
    # -------------------------------------------------------------------------
    def _setup_scheduler(self):
        """根据配置重新注册或清除定时任务"""
        if self.scheduler.get_job(self._job_id):
            self.scheduler.remove_job(self._job_id)

        if self.config.get("enabled", False):
            self.scheduler.add_job(
                self._do_sign,
                CronTrigger(hour=0, minute=0),
                id=self._job_id,
                replace_existing=True,
            )
            logger.info("[gsign] 每日凌晨定时签到已启动")
        else:
            logger.info("[gsign] 签到未开启，定时任务未注册")

    async def _do_sign(self):
        """执行每日签到，向符合条件的群发送签到消息"""
        mode = self.config.get("mode", "whitelist")
        whitelist = self.config.get("whitelist", [])
        blacklist = self.config.get("blacklist", [])

        # 获取 bot 所在的所有群
        all_groups = await self._get_all_groups()
        target_groups = []

        for gid in all_groups:
            if mode == "whitelist":
                if gid in whitelist:
                    target_groups.append(gid)
            else:  # blacklist
                if gid not in blacklist:
                    target_groups.append(gid)

        if not target_groups:
            logger.info("[gsign] 本次没有需要签到的群")
            return

        # 获取平台适配器
        platform = self.context.get_platform()

        for gid in target_groups:
            try:
                await platform.call_action("set_group_sign", group_id=gid)
                logger.info(f"[gsign] 群 {gid} 签到完成")
            except Exception as e:
                logger.error(f"[gsign] 群 {gid} 签到失败: {e}")

    async def _get_all_groups(self):
        """获取 bot 所在的所有群 ID"""
        try:
            platform = self.context.get_platform()
            result = await platform.call_action("get_group_list")
            # result 为群信息列表，提取 group_id
            if isinstance(result, list):
                return [str(g.get("group_id", "")) for g in result if g.get("group_id")]
            return []
        except Exception as e:
            logger.error(f"[gsign] 获取群列表失败: {e}")
            return []

    # -------------------------------------------------------------------------
    # 配置读写
    # -------------------------------------------------------------------------
    def _load_config(self):
        if os.path.exists(self._config_path):
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
            except Exception as e:
                logger.error(f"[gsign] 配置文件读取失败: {e}")
                self.config = self._default_config()
        else:
            self.config = self._default_config()
            self._save_config()

    def _save_config(self):
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[gsign] 配置文件保存失败: {e}")

    def _default_config(self):
        return {
            "enabled": False,
            "mode": "whitelist",
            "whitelist": [],
            "blacklist": [],
        }

    # -------------------------------------------------------------------------
    # 指令
    # -------------------------------------------------------------------------
    @filter.command("gsign")
    async def gsign(self, event: AstrMessageEvent):
        """gsign 签到插件主指令，输入 /gsign 查看帮助"""
        msg = event.message_str.strip()
        if not msg:
            yield event.plain_result(self._help_text())
            return

        sub = msg.split()[0]
        if sub == "开关":
            async for r in self._cmd_switch(event, msg):
                yield r
        elif sub == "状态":
            async for r in self._cmd_status(event):
                yield r
        elif sub == "模式":
            async for r in self._cmd_mode(event, msg):
                yield r
        elif sub == "添加群":
            async for r in self._cmd_add_group(event, msg):
                yield r
        elif sub == "移除群":
            async for r in self._cmd_remove_group(event, msg):
                yield r
        else:
            yield event.plain_result(self._help_text())

    @filter.command("gsign开关")
    async def gsign_switch(self, event: AstrMessageEvent):
        msg = event.message_str.strip()
        async for r in self._cmd_switch(event, f"开关 {msg}"):
            yield r

    @filter.command("gsign状态")
    async def gsign_status(self, event: AstrMessageEvent):
        async for r in self._cmd_status(event):
            yield r

    async def _cmd_switch(self, event: AstrMessageEvent, msg: str):
        parts = msg.strip().split()
        if len(parts) < 2:
            yield event.plain_result("用法：/gsign开关 开 | 关")
            return

        val = parts[1]
        if val == "开":
            self.config["enabled"] = True
            self._save_config()
            self._setup_scheduler()
            yield event.plain_result("✅ 每日自动签到已开启，将在凌晨 00:00 执行")
        elif val == "关":
            self.config["enabled"] = False
            self._save_config()
            self._setup_scheduler()
            yield event.plain_result("✅ 每日自动签到已关闭")
        else:
            yield event.plain_result("参数错误，请输入 /gsign开关 开 或 /gsign开关 关")

    async def _cmd_status(self, event: AstrMessageEvent):
        enabled = "开启" if self.config.get("enabled") else "关闭"
        mode = self.config.get("mode", "whitelist")
        mode_text = "白名单" if mode == "whitelist" else "黑名单"
        whitelist = self.config.get("whitelist", [])
        blacklist = self.config.get("blacklist", [])
        list_key = "白名单" if mode == "whitelist" else "黑名单"
        current_list = whitelist if mode == "whitelist" else blacklist

        status = (
            f"📋 gsign 签到状态\n"
            f"━━━━━━━━━━━━━\n"
            f"总开关：{enabled}\n"
            f"运行模式：{mode_text}\n"
            f"━━━━━━━━━━━━━\n"
            f"{list_key}群列表 ({len(current_list)} 个)：\n"
        )
        if current_list:
            for gid in current_list:
                status += f"  - {gid}\n"
        else:
            status += "  （暂无）\n"
        status += "━━━━━━━━━━━━━\n"
        status += "使用 /gsign 查看所有指令"
        yield event.plain_result(status)

    async def _cmd_mode(self, event: AstrMessageEvent, msg: str):
        parts = msg.strip().split()
        if len(parts) < 2:
            yield event.plain_result(
                "当前模式：白名单（仅白名单群号打卡）\n"
                "用法：/gsign模式 白名单 | 黑名单"
            )
            return

        val = parts[1]
        if val == "白名单":
            self.config["mode"] = "whitelist"
            self._save_config()
            yield event.plain_result("✅ 已切换为白名单模式，仅白名单群号会执行签到")
        elif val == "黑名单":
            self.config["mode"] = "blacklist"
            self._save_config()
            yield event.plain_result("✅ 已切换为黑名单模式，除黑名单外所有群都会执行签到")
        else:
            yield event.plain_result("参数错误，请输入 /gsign模式 白名单 或 /gsign模式 黑名单")

    async def _cmd_add_group(self, event: AstrMessageEvent, msg: str):
        parts = msg.strip().split()
        if len(parts) < 2:
            yield event.plain_result("用法：/gsign添加群 <群号>")
            return

        gid = parts[1]
        mode = self.config.get("mode", "whitelist")
        target_list = "whitelist" if mode == "whitelist" else "blacklist"

        if gid in self.config.get(target_list, []):
            yield event.plain_result(f"⚠️ 群号 {gid} 已在列表中，无需重复添加")
            return

        self.config.setdefault(target_list, []).append(gid)
        self._save_config()
        list_name = "白名单" if mode == "whitelist" else "黑名单"
        yield event.plain_result(f"✅ 群号 {gid} 已添加到 {list_name}")

    async def _cmd_remove_group(self, event: AstrMessageEvent, msg: str):
        parts = msg.strip().split()
        if len(parts) < 2:
            yield event.plain_result("用法：/gsign移除群 <群号>")
            return

        gid = parts[1]
        mode = self.config.get("mode", "whitelist")
        target_list = "whitelist" if mode == "whitelist" else "blacklist"

        if gid not in self.config.get(target_list, []):
            list_name = "白名单" if mode == "whitelist" else "黑名单"
            yield event.plain_result(f"⚠️ 群号 {gid} 不在 {list_name}中")
            return

        self.config[target_list].remove(gid)
        self._save_config()
        list_name = "白名单" if mode == "whitelist" else "黑名单"
        yield event.plain_result(f"✅ 群号 {gid} 已从 {list_name}移除")

    def _help_text(self):
        return (
            "📋 gsign 每日自动签到插件\n"
            "━━━━━━━━━━━━━\n"
            "指令列表：\n"
            "  /gsign开关 开|关      - 开启/关闭每日签到\n"
            "  /gsign状态            - 查看当前状态\n"
            "  /gsign模式 白名单|黑名单 - 切换运行模式\n"
            "  /gsign添加群 <群号>   - 将群号加入当前模式列表\n"
            "  /gsign移除群 <群号>   - 从当前模式列表移除群号\n"
            "━━━━━━━━━━━━━\n"
            "📌 模式说明：\n"
            "  白名单：仅列表内群号执行签到\n"
            "  黑名单：除列表内群号外全部执行签到\n"
            "━━━━━━━━━━━━━\n"
            "⏰ 签到时间：每天凌晨 00:00"
        )

    # -------------------------------------------------------------------------
    # WebUI 配置面板支持
    # -------------------------------------------------------------------------
    async def get_config_schema(self):
        return {
            "enabled": {
                "type": "bool",
                "default": False,
                "label": "开启每日签到",
            },
            "mode": {
                "type": "select",
                "options": ["whitelist", "blacklist"],
                "default": "whitelist",
                "label": "运行模式",
            },
            "whitelist": {
                "type": "list",
                "default": [],
                "label": "白名单群号",
            },
            "blacklist": {
                "type": "list",
                "default": [],
                "label": "黑名单群号",
            },
        }

    async def terminate(self):
        self.scheduler.shutdown(wait=False)
        logger.info("[gsign] 插件已卸载，定时任务已清除")
