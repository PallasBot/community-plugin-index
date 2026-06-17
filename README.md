# Pallas-Bot 社区插件索引

Pallas-Bot 控制台 **插件商店 → 社区插件** 的策展列表。Bot 默认拉取本仓 `index.json`；站点可通过 `COMMUNITY_PLUGIN_INDEX_URL` 或本地文件覆盖。

## 索引与插件的关系

| 层级 | 仓库 | 内容 |
| --- | --- | --- |
| **索引（本仓）** | `PallasBot/community-plugin-index` | JSON 元数据：id、名称、git 仓库 URL |
| **插件代码** | 各作者独立仓库 | NoneBot 插件目录，含 `__init__.py` |
| **站点安装目录** | 运行中的 Bot | `local/plugins/<id>/`（git clone） |

Bot **不会**从索引直接下载 zip；WebUI 安装时会 `git clone` 到 `local/plugins/<id>/`。

## 收录要求

1. **开源**：仓库公开可 clone（GitHub / GitLab / Gitee / Codeberg）。
2. **插件 ID**：小写字母开头，仅 `a-z` `0-9` `_`，与目录名一致，全索引唯一。
3. **结构**：标准 NoneBot 插件包，根目录含 `__init__.py`；建议提供 `__plugin_meta__`。
4. **兼容性**：在 `min_pallas_version` 中声明最低 Pallas 版本（当前推荐 `4.0.0`）。
5. **维护**：仓库可正常访问；长期失效条目会被维护者移除。

## 如何提交

1. Fork 本仓。
2. 在 `index.json` 的 `plugins` 数组追加条目（字段见 [`schema/index.schema.json`](schema/index.schema.json)）。
3. 本地校验：`python tools/validate_index.py`
4. 发起 PR（**只需改 `index.json`**；README 插件表由 CI 自动同步），说明插件用途、仓库链接与自测情况。

维护者合并后，已联网的 Bot 会在刷新商店时看到新条目（默认缓存约 30 秒）。

**无需手工改 README 插件表**：同源 PR 与合并到 `main` 后，CI 会运行 `tools/sync_readme.py` 并自动提交表格更新。

## 插件列表

Bot 安装时读取 `index.json`；下表由 CI 根据 JSON **自动生成**，请勿手工改表格。

<!-- PLUGIN_LIST_START -->
| 名称 | ID | 作者 | 说明 |
| --- | --- | --- | --- |
| [牛牛互动](https://github.com/TogetsuDo/pallas-community-plugin-niuniu-interact) | `niuniu_interact` | [@TogetsuDo](https://github.com/TogetsuDo) | 名片点赞、戳一戳回图与群主设置专属头衔。社区插件开发示范。 |
<!-- PLUGIN_LIST_END -->

## 条目示例

```json
{
  "id": "my_plugin",
  "name": "示例插件",
  "description": "一句话说明功能。",
  "repository": "https://github.com/ORG/pallas-plugin-my-plugin.git",
  "ref": "main",
  "author": "作者名",
  "homepage": "https://github.com/ORG/pallas-plugin-my-plugin",
  "tags": ["工具"],
  "min_pallas_version": "4.0.0"
}
```

## 站点覆盖索引

| 方式 | 路径 / 键 | 优先级 |
| --- | --- | --- |
| 环境变量 | `COMMUNITY_PLUGIN_INDEX_URL` | 最高（覆盖默认 URL） |
| 默认远程 | 本仓 `main/index.json` | 联网默认 |
| 本地覆盖 | `data/pallas_config/community_plugin_index.json` | 远程失败或未设 URL 时 |
| 内置兜底 | Bot 主仓 `config/community_plugin_index.json` | 最后 |

私有站点可自建索引仓，在 `pallas.toml` 的 `[env]` 设置 `COMMUNITY_PLUGIN_INDEX_URL` 指向 raw JSON。

## 相关文档

- [Pallas-Bot · 安装插件 · 社区商店](https://github.com/PallasBot/Pallas-Bot/blob/dev/docs/guide/community-plugin-store.md)
- [站点定制 · local/plugins](https://github.com/PallasBot/Pallas-Bot/blob/dev/docs/architecture/site-customization-and-updates.md)
