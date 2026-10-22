# 多仓库按需下载

管理指定的公开 GitHub 仓库，按需生成包含 `.git` 的源码压缩包。保留原来的 Hermes 下载功能，支持选择单个、多个或全部项目。使用 GitHub Actions 打包，不执行上游项目的编译或安装脚本。

## 使用

1. 打开本仓库 **Actions → Build repository downloads → Run workflow**。
2. 在 `repositories` 输入配置中的仓库 ID：`hermes-agent`；多个用英文逗号分隔；`all` 下载全部。
3. `ref` 留空使用各仓库配置，也可填写分支或标签覆盖本次所选的所有仓库。
4. 按需开启完整历史、子模块或 LFS，点击 **Run workflow**。
5. 完成后，在运行页面的 **Summary / Artifacts** 下载；每个仓库单独一个下载包，失败的仓库不影响其他仓库完成。

每份下载包含 `<ID>.tar.gz`、`COMMIT.txt`、`SOURCE.json` 和 `SHA256SUMS.txt`。解压后可直接使用 Git；`SOURCE.json` 记录源仓库、分支和本次选项。下载需登录 GitHub，文件保留 **14 天**，过期后重新运行即可。

## 添加、修改和删除仓库

编辑根目录 `repositories.json`，每项的键是唯一的仓库 ID。例如：

```json
{
  "hermes-agent": {"repository": "NousResearch/hermes-agent", "ref": "main"},
  "my-project": {"repository": "OWNER/REPO", "ref": ""}
}
```

把 `OWNER/REPO` 替换为真实的公开仓库。`ref` 省略或留空表示使用上游默认分支。删除配置项即可停止管理该仓库，不影响之前生成的下载文件。ID 仅允许字母、数字、下划线和短横线，最多 64 字符；`all` 是保留字。

使用文本清单而非固定下拉菜单，添加仓库时无需修改工作流。每次最多选择 **256 个仓库**（GitHub matrix 限制），更大的清单可分批指定 ID 运行。同时最多处理 4 个仓库。

## 下载范围

- 默认下载指定分支/标签的最新版本及一层 Git 历史；`full_history` 下载该分支的完整历史，**不会额外拉取全部分支**。
- 默认递归下载子模块。`include_lfs` 默认关闭，此时 LFS 文件保留指针；开启后下载主仓及已下载子模块中可达的 LFS 对象并填充工作目录。
- 打包前检查 Git 对象，打包后检查 Git 元数据并生成 SHA-256 校验文件。Linux 可在下载目录执行 `sha256sum -c SHA256SUMS.txt`，macOS 可执行 `shasum -a 256 -c SHA256SUMS.txt`。
- 只支持公开 GitHub 主仓库；私有子模块、不可访问的上游、大型仓库超过运行时限或存储额度都会导致该任务失败。
- 不包含 GitHub Releases 附件、Issues、PR 或独立 Wiki；本工具也不会自动同步到 Gitee 等国内平台。下载仍通过 GitHub Artifacts，国内速度取决于访问 GitHub 的网络情况。
- 只在手动运行时生成下载；修改清单和代码只触发配置验证及测试。重新运行即可获取上游最新代码。

## 本地检查

仅需 Python 3.9+ 和 Git；下载 LFS 时另需 Git LFS。

```sh
python3 -m unittest discover -s tests -v
python3 scripts/download_repositories.py validate
```
