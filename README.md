# Pallas-Bot 社区插件索引

这里是 Pallas-Bot 控制台 **插件商店 → 社区插件** 使用的索引仓。

如果你只是想看看现在有什么社区插件可装，先看下面的 **插件列表**。
如果你想把自己的插件加入商店，再看后面的 **提交你的插件**。

## 插件列表

Bot 安装时读取 `index.json`；下表由 CI 根据 JSON 自动生成，请勿手工改表格。

<!-- PLUGIN_LIST_START -->
| 名称 | ID | 作者 | 说明 |
| --- | --- | --- | --- |
| [牛牛互动](https://github.com/TogetsuDo/pallas-community-plugin-interact) | `interact` | [@TogetsuDo](https://github.com/TogetsuDo) | 名片点赞、戳一戳回图与群主设置专属头衔。社区插件开发示范。 |
<!-- PLUGIN_LIST_END -->

## 这份索引怎么用

这份仓库只保存“商店条目”，不保存插件代码本体。

| 层级 | 实际内容 | 放在哪里 |
| --- | --- | --- |
| 社区插件索引 | 插件名称、说明、仓库地址、最低版本等元数据 | 本仓 `index.json` |
| 插件源码 | 真正的 NoneBot 插件代码 | 各作者自己的仓库 |
| 安装结果 | Bot 拉取后的本地插件目录 | `local/plugins/<id>/` |

控制台安装社区插件时，Bot 会按索引里的仓库地址去拉代码，不会直接从这个仓库下载 zip。

## 提交你的插件

如果你想把自己的插件加入社区插件商店，按这个顺序做：

1. 准备一个公开可访问的插件仓库。
2. 确认插件目录本身可以作为标准 NoneBot 插件加载。
3. Fork 本仓，只修改 `index.json`，把你的条目追加到 `plugins` 数组。
4. 本地运行 `python tools/validate_index.py` 做校验。
5. 发起 PR，说明插件是做什么的、仓库地址是什么、你自己怎么测过。

合并后，控制台刷新社区插件列表时就能看到新条目。README 里的插件表会由 CI 自动同步，你不需要手工改。

## 已收录插件发版后怎么改索引

插件已在 `plugins` 里之后，发新版本请**改已有条目**，不要再追加一条同 `id`：

1. 在插件仓打好 `vX.Y.Z` tag，并保证 `CHANGELOG.md` 已归档。
2. Fork 本仓，只改 `index.json`：把对应 `id` 的 `version` 改成 `X.Y.Z`（无 `v` 前缀），并更新根级 `updated_at`。
3. 运行 `python tools/validate_index.py`。
4. 提 PR，说明升到哪个版本、对应 tag。

商店展示的版本号以本仓 `version` 为准；`ref` 为 `main` 时重装虽可拉到新代码，卡片版本仍须你更新索引。更完整的作者步骤见 [写社区插件并上架 · 发版后同步索引](https://github.com/PallasBot/Pallas-Bot/blob/dev/docs/guide/community-plugin-author.md#步骤-6发版后同步索引)。

## 收录要求

为避免商店里出现装不上、找不到、说明不清的条目，至少满足这些要求：

1. 仓库公开可访问，常见 Git 平台可以正常 clone。
2. 插件 `id` 以小写字母开头，只包含 `a-z`、`0-9`、`_`，并且和目录名一致。
3. 仓库里提供标准插件目录，根目录含 `__init__.py`。
4. `index.json` 里写明 `min_pallas_version`，当前建议从 `4.0.0` 起填。
5. 插件用途要能用一句人话说明清楚，不要只写仓库名或技术名词。
6. 仓库长期失效、无法安装或明显无人维护的条目，后续可能会被移除。

**推荐（非强制）**：维护版本与更新日志，给用户更好的「更新日志」分栏体验：

- 遵循[语义化版本](https://semver.org/lang/zh-CN/)，发布版本打 `vX.Y.Z` git tag，可在条目填可选字段 `version`。
- 仓库根目录维护 `CHANGELOG.md`（[Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式）。商店「更新日志」分栏优先展示它；缺失时只能按 git 提交历史兜底。
- 写法见 [Pallas-Bot · 社区插件开发者指南 · 版本与更新日志](https://github.com/PallasBot/Pallas-Bot/blob/dev/docs/guide/community-plugin-author.md#版本与更新日志)。

**无需手工改 README 插件表**：同源 PR 与合并到 `main` 后，CI 会运行 `tools/sync_readme.py` 并自动提交表格更新。

## 条目示例

```json
{
  "id": "my_plugin",
  "name": "示例插件",
  "description": "一句话说明功能。",
  "repository": "https://github.com/ORG/pallas-plugin-my-plugin.git",
  "ref": "main",
  "version": "0.1.0",
  "author": "作者名",
  "homepage": "https://github.com/ORG/pallas-plugin-my-plugin",
  "tags": ["工具"],
  "min_pallas_version": "4.0.0"
}
```

字段约束见 [`schema/index.schema.json`](schema/index.schema.json)。

## 站点如何覆盖这份索引

如果你在维护自己的站点，也可以不使用默认社区索引，改成自己的私有列表。

| 方式 | 路径 / 键 | 说明 |
| --- | --- | --- |
| 环境变量 | `COMMUNITY_PLUGIN_INDEX_URL` | 最高优先级，直接指定远程 JSON |
| 默认远程 | 本仓 `main/index.json` | 联网时默认使用 |
| 本地覆盖 | `data/pallas_config/community_plugin_index.json` | 远程失败或未设 URL 时使用 |
| 内置兜底 | Bot 主仓 `config/community_plugin_index.json` | 最后的保底列表 |

私有站点可以自建一个索引仓或静态 JSON，再把 `[env]` 里的 `COMMUNITY_PLUGIN_INDEX_URL` 指过去。

## 相关文档

- [Pallas-Bot · 社区插件商店](https://github.com/PallasBot/Pallas-Bot/blob/dev/docs/guide/community-plugin-store.md)
- [站点定制与 `local/plugins`](https://github.com/PallasBot/Pallas-Bot/blob/dev/docs/architecture/site-customization-and-updates.md)
