# Source Trace

每两天自动获取指定的公开 GitHub 仓库，生成包含 `.git` 的源码下载包。不需要手动运行，也不执行上游项目的编译或安装脚本。

## 已配置项目

| 下载包 ID | 源仓库 | 分支 |
| --- | --- | --- |
| codex | [openai/codex](https://github.com/openai/codex) | main |
| hermes-agent | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | main |
| pi | [earendil-works/pi](https://github.com/earendil-works/pi) | main |
| langgraph | [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | main |
| langchain | [langchain-ai/langchain](https://github.com/langchain-ai/langchain) | master |
| semantic | [microsoft/semantic-kernel](https://github.com/microsoft/semantic-kernel) | main |

Pi 的原地址 `badlogic/pi-mono` 已迁移到上表地址；`semantic` 对应 Microsoft Semantic Kernel。

## 自动更新与下载

- **每两天一次，北京 / 新加坡时间 03:17**，以 2026-10-22 为起点：10 月 22 日、24 日、26 日……。跨月、跨年仍保持隔天，不按月份重置。
- 启用本版本，以及向 `main` 提交仓库清单、打包脚本或本工作流的变更时，也会自动生成一次全部下载包。
- 打开 [Actions](https://github.com/w3ms/source-trace/actions/workflows/source-trace.yml)，进入最近一次成功的 **Source Trace downloads** 运行，在 **Artifacts** 或各任务的 **Summary** 中点击需要的项目下载。
- 每个仓库单独打包，最多同时处理 4 个；一个项目失败不影响其他项目。下载需要登录 GitHub，文件保留 **14 天**。

下载的 ZIP 内包含 `<ID>.tar.gz`、`COMMIT.txt`、`SOURCE.json` 和 `SHA256SUMS.txt`。继续解压 `.tar.gz` 即可获得源码目录，`SOURCE.json` 记录源仓库、分支和提交版本。

GitHub 每天进行一次轻量日期检查，仅在隔天目标日期执行下载。调度可能因 GitHub 负载延迟；公开仓库连续 60 天无仓库活动时，GitHub 可能自动停用定时工作流，届时需在 Actions 中重新启用。官方规则见 [schedule 说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。

## 管理仓库

编辑根目录 `repositories.json` 后提交到 `main` 即可，不需要改动工作流。例如添加：

```json
"my-project": {"repository": "OWNER/REPO", "ref": ""}
```

`OWNER/REPO` 替换为真实的公开仓库；`ref` 留空或省略表示使用上游默认分支。删除配置项即可停止获取该仓库。ID 仅允许字母、数字、下划线和短横线，最多 64 字符；`all` 是保留字。目前自动运行每批最多 **256 个仓库**（GitHub matrix 限制），超过时需要调整为分批工作流。

## 下载范围与选项

- 自动下载指定分支/标签的最新版本及一层 Git 历史，保留 `.git`；默认递归获取子模块。不会额外拉取全部分支，也不包含完整历史。
- 自动任务默认不下载 Git LFS 对象，LFS 文件保留指针。需要完整历史或 LFS 时，可在 `.github/workflows/source-trace.yml` 中把 `FULL_HISTORY` 或 `INCLUDE_LFS` 改为 `'true'`。大仓库需要更多时间和存储空间。
- 打包前检查 Git 对象，打包后检查 Git 元数据并生成 SHA-256 校验文件。Linux 可运行 `sha256sum -c SHA256SUMS.txt`，macOS 可运行 `shasum -a 256 -c SHA256SUMS.txt`。
- 只支持公开 GitHub 主仓库；私有子模块、上游不可访问、运行超时或存储额度不足会导致对应任务失败。
- 不包含 Releases 附件、Issues、PR 或独立 Wiki；不会自动同步到国内平台，下载仍通过 GitHub Artifacts。

## 本地验证

需要 Python 3.9+ 和 Git；启用 LFS 时还需 Git LFS。

```sh
python3 -m unittest discover -s tests -v
python3 scripts/download_repositories.py validate
REPOSITORIES=all python3 scripts/download_repositories.py select
```
