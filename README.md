<p align="right"><a href="https://wubing2023.github.io/PaperSpine/v5/"><img src="website/assets/brand/paperspine-mark.svg" width="24" alt="PaperSpine"></a></p>

<p align="center"><a href="https://wubing2023.github.io/PaperSpine/v5/"><img src="website/assets/brand/paperspine-hero.webp" alt="PaperSpine5 · 从零开始，快速完成一篇图文完整的论文"></a></p>

# PaperSpine5

[中文](README.md) · [English](README.en.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Русский](README.ru.md) · [Português](README.pt.md)

[产品页](https://wubing2023.github.io/PaperSpine/v5/) · [GitHub Release](https://github.com/WUBING2023/PaperSpine/releases/tag/v0.4.0-alpha.3)

**PaperSpine5：从零开始，快速完成一篇图文完整的论文。**

PaperSpine5 是一个覆盖论文全流程的 AI Skill。你提供研究方向、已有资料或实验数据，它帮你查文献、梳理论点、搭建大纲、撰写全文、生成科研配图，并完成引用核验、审阅修改和排版，最终交付可编辑的 Word / LaTeX 源文件和 PDF。

从正文到数据图、机制示意图和方法框架图，在同一个任务中完成。通过 `paper-spine` 启动，在网页中选择方案、预览图文、提出修改意见并下载成果。研究材料优先保存在本地，论点、引用和图表均以真实资料与证据为依据。

## 本 fork 的 Claude Skill 修复记录

本 fork 面向在 Claude 中使用 `paper-spine` Skill 的场景，Skill 安装目录为
`~/.claude/skills/paper-spine`。以下记录来自 Windows 上的实际使用问题。

| 问题 | 原因与解决办法 |
| --- | --- |
| `launch --no-open` 报“Keep the local profile separate from installed product files” | 官方安装器将程序放在 profile 下，启动检查却拒绝这个布局。修复为允许该布局，仍拒绝 profile 与程序目录相同或位于程序目录内。 |
| 材料登记报 `materials.read_failed`，提示文件不存在 | 深层暂存路径超过 Windows 默认长度限制。材料扫描、复制、校验、替换和清理接入已有扩展路径支持，补齐长路径解析；保留原存储布局与完整 SHA-256，无需改系统长路径设置。 |
| 外部模板目录已生成稿件、图件和 PDF，工作台仍停在研究阶段 | 保存文件不会自动更新工作台。新增 `host bind-output` 记住同一任务的外部写作目录，`host checkpoint` 按文件清单发布成果、提交真实阶段的里程碑并读回确认；支持复用未变文件和失败后恢复。 |

第三项的命令、JSON 清单及恢复方式见
[工作流说明](src/skill/references/product-v1-workflow.md#external-writing-directories-and-one-command-checkpoints)。
每个实际工作段完成、恢复会话和最终回复前，Claude 应按 Skill 要求同步成果与进度。
修复使用独立测试材料和任务验证，不需要重新登记原论文的 55 个材料文件。

### 自用版本与后续更新

这些修复已进入 fork 源码和 Claude Skill 分发文件。已安装的 Skill 与其 Web 核心仍需一起更新，
才能使用全部修复；仅拉取仓库不会更新本机安装。当前下载链接和默认更新清单仍指向官方套件，
它们不包含本 fork 的自用改动，后续官方自动更新也可能覆盖本地修复。

后续维护应合并上游更新、运行相关回归测试，并构建包含修复的自用完整套件。
发布自用更新清单后，可用更新器的 `--preflight --source <自用更新清单>` 指向该渠道；
渠道建立前，按更新器设置明确关闭自动更新。这里记录更新策略，尚未切换本机更新渠道或重装 Skill。

## 下载

- Windows x64 套件：约 26.5 MB。
- Linux glibc x86_64 套件：约 56.2 MB。
- macOS Apple Silicon 套件：约 40.6 MB。
- macOS Intel x86_64 套件：约 40.5 MB。

所有下载都列在公开发布清单中，并用 SHA-256 校验。完整版本号为 `v0.4.0-alpha.3` 预发布。

<details>
<summary>高级 / 手动安装</summary>

当前发布仅提供四个平台的完整套件。历史约 0.70 MB 的 Skill-only ZIP 不含 Web 核心与运行时，不能用于首次安装或修复缺失套件指针。高级用户可从已验证的完整套件管理 Skill。

</details>

## 安装与旧版本迁移

Windows x64：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Target codex -CleanLegacy
```

macOS / Linux：

```sh
sh ./install.sh --target codex --clean-legacy
```

`-CleanLegacy` 先只读预览，仅在发现旧版冲突时写归档；不删除论文任务数据、宿主设置或未知文件。两个平台安装器都会校验字节数、SHA-256、套件内部完整性和首次启动自检。

## 检查与应用更新

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File .\install.ps1 -CheckOnly
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Target codex
```

```sh
# macOS / Linux
sh ./install.sh --check-only
sh ./install.sh --target codex
```

重新运行安装器会检查版本：有新版时执行可回滚更新，保留任务数据并做启动自检；已是最新版且 Skill 完整时直接继续，不重复下载或覆盖。每次调用 Skill 时检查更新，有新版则自动升级完整套件和更新器；尊重明确关闭自动更新的设置。

## 边界

- 四个平台套件均已通过归档和 SHA-256 校验。Windows x64 已通过本地安装、更新和工作台验证；[发版后原生 CI](https://github.com/WUBING2023/PaperSpine/actions/runs/35944185453) 在 Windows、Linux x86_64、macOS arm64 和 macOS x86_64 均通过旧更新器升级与工作台启动。Linux arm64、musl/Alpine 未声明支持。
- macOS 套件尚未签名或公证，首次运行可能需要用户明确允许。
- 当前为 alpha 预发布，无独立密码学签名。
- 产品发布不授权投稿、上传私有材料、付款或外部联系。
- 支持入口是自愿维护支持，不解锁功能，不读取支付状态。

## 公开仓库结构

- `dist/codex/skills/paper-spine`、`dist/claude/skills/paper-spine`、`dist/openclaw/skills/paper-spine`：宿主投影。
- `dist/claude/commands/paperspine.md`：Claude 命令入口。
- `install.ps1`、`install.sh`：安装边界。
- 关键方法/工具：`writing_rationale_matrix`、`citation_support_bank`、`translation_package`、`artifact_check.py`、`reference_inventory.py`、`citation_bank_check.py`、`latex_guard.py`、`word_guard.py`。

## 开发

`src/` 存放 Skill 源代码，`dist/` 是各宿主的公开投影。公开仓库保留源代码和测试，不保留本地任务、临床数据、缓存或开发运行日志。

MIT License。
