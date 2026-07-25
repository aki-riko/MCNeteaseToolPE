# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""网易 Minecraft 全局清理分类与界面文案。"""

MC_DATA_DIR_NAME = "MinecraftPE_Netease"
MC_DATA_DIR_ENV = "MCNETEASE_MINECRAFT_DATA_DIR"

MC_CLEANUP_ENTRY_DEFINITIONS = (
    {
        "key": "game_logs",
        "name": "游戏调试日志",
        "description": "Minecraft 运行诊断文本；删除后不影响存档，遇到故障时会自动重新生成。",
        "relativeDir": ("logs",),
        "browsePath": ("logs",),
        "patterns": ("*.txt",),
        "recursive": True,
    },
    {
        "key": "mcp_logs",
        "name": "Mod API 日志",
        "description": "网易 Mod API 的当前及轮转日志；仅用于排查脚本问题。",
        "relativeDir": (),
        "browsePath": (),
        "patterns": ("mcp.log", "mcp.log.*"),
        "recursive": False,
    },
    {
        "key": "pack_cache",
        "name": "资源包缓存",
        "description": "网易资源包下载与解析缓存；删除后需要时会自动重新生成。",
        "relativeDir": ("packcache",),
        "browsePath": ("packcache",),
        "patterns": ("*",),
        "recursive": True,
        "removeEmptyDirs": True,
    },
)

MC_CLEANUP_PROTECTED_DEFINITIONS = (
    {
        "key": "worlds_and_packs",
        "name": "世界、组件与皮肤",
        "description": "包含本地世界、行为包、资源包、模板与自定义皮肤；默认保留，清理后无法恢复。",
        "paths": ("minecraftWorlds", "games", "skin_packs", "custom_skins"),
        "browsePath": ("minecraftWorlds",),
    },
    {
        "key": "settings_and_user_state",
        "name": "设置与用户状态",
        "description": "包含画面/按键设置、连接信息、教程与用户状态；默认保留，清理后需要重新配置。",
        "paths": ("minecraftpe", "storge"),
        "browsePath": ("minecraftpe",),
    },
    {
        "key": "resource_indexes",
        "name": "运行资源与索引",
        "description": "包含声音、方块、纹理注册表及运行索引；体积很小，默认保留。",
        "paths": (
            "bootstrapStorage",
            "internalStorage",
            "ClientCache",
            "sound_definitions.json",
            "sounds.json",
            "blocks.json",
            "terrain_texture.json",
            "item_texture.json",
            "_global_variables.json",
            "music_definitions.json",
        ),
        "browsePath": ("ClientCache",),
    },
)

MC_CLEANUP_PROTECTED_COUNTDOWN_SECONDS = 3

MC_CLEANUP_UI_TEXTS = {
    "recommendedTitle": "推荐清理",
    "protectedTitle": "有用数据（默认不清理）",
    "refresh": "重新扫描",
    "scanning": "正在扫描…",
    "clean": "清理",
    "cleanAll": "清理全部",
    "openFolder": "打开文件夹",
    "cleanableBadge": "可清理",
    "protectedBadge": "默认保留",
    "missingRoot": "未找到网易 Minecraft 数据目录",
    "safeSummary": "“清理全部”只删除白名单日志和资源包缓存；有用数据默认不参与，只能逐项确认后清理。正在使用的文件会自动跳过。",
    "confirmTitle": "确认清理",
    "confirmAll": "将删除全部已识别的 Minecraft 日志、Mod API 日志和资源包缓存。此操作不可撤销，但不会删除存档和设置。",
    "confirmSingle": "将删除所选日志或缓存文件。此操作不可撤销，但不会删除存档和设置。",
    "confirmProtected": "将删除“{name}”中的全部已识别数据。此操作不可撤销，确认按钮会在 3 秒后启用。",
    "confirm": "确认清理",
    "cancel": "取消",
    "empty": "暂无可清理内容",
}

MC_CLEANUP_MSG_ROOT_MISSING = "未找到网易 Minecraft 数据目录。"
MC_CLEANUP_MSG_UNKNOWN_TYPE = "未知清理类型：{}"
MC_CLEANUP_MSG_EMPTY = "暂无可清理内容。"
MC_CLEANUP_MSG_CLEANED = "已清理 {} 个文件，释放 {}。"
MC_CLEANUP_MSG_PARTIAL = "已清理 {} 个文件，跳过 {} 个正在使用或无权限的文件。"
MC_CLEANUP_MSG_SKIPPED = "有 {} 个文件正在使用或无权限，已全部跳过。"
MC_CLEANUP_MSG_TASK_FAILED = "Minecraft 清理任务失败，请查看日志。"
MC_CLEANUP_MSG_FOLDER_MISSING = "清理目录不存在：{}"
MC_CLEANUP_MSG_FOLDER_OPENED = "已打开清理目录：{}"
MC_CLEANUP_MSG_FOLDER_OPEN_FAILED = "无法打开清理目录：{}"
