# SoloRecord 文档中心

## 按读者阅读

| 读者 | 文档 | 用途 |
| --- | --- | --- |
| 运维/IT | [human-ops/README.md](human-ops/README.md) | 部署、配置、备份、排障、上线检查 |
| 开发者 | [human-dev/README.md](human-dev/README.md) | 代码结构、API、数据模型、测试、二次开发 |
| 普通使用者 | [user/README.md](user/README.md) | 登录、录音、查看记录、改说话人、导出 |
| 智能体 | [../AGENTS.md](../AGENTS.md)、[agents/README.md](agents/README.md)、[../llms.txt](../llms.txt) | 快速接手、约束、命令、上下文索引 |

## 参考资料

| 文档 | 内容 |
| --- | --- |
| [meeting-app-prd-v2.md](meeting-app-prd-v2.md) | 完整 PRD，文件名沿用原版本名 |
| [deployment.md](deployment.md) | 部署快速参考 |
| [data-storage-and-es.md](data-storage-and-es.md) | 服务端数据保存、APK 重装同步、外部 API、ES/OpenSearch |
| [local-asr-pipeline.md](local-asr-pipeline.md) | 本地 ASR、VAD、说话人分离、音频处理 |
| [synology-bailian-architecture.md](synology-bailian-architecture.md) | 群晖 SSO、百炼/Qwen ASR、安全架构 |
| [open-source-research.md](open-source-research.md) | 开源组件调研和许可证判断 |
| [security-audit.md](security-audit.md) | 安全审计、已知风险和验证记录 |
| [integration-contract.md](integration-contract.md) | 早期接口契约参考 |
| [distribution-mode.md](distribution-mode.md) | 内部分发模式参考 |
| [roadmap.md](roadmap.md) | 后续增强建议 |

## 当前推荐路径

明天部署：

1. 看 [human-ops/README.md](human-ops/README.md)。
2. 配 `server/.env`。
3. 启动服务。
4. 上传 APK。
5. 用测试用户录一段会议，检查转写、纪要、同步和导出。

继续开发：

1. 看 [human-dev/README.md](human-dev/README.md)。
2. 跑 `scripts\run-tests.ps1`。
3. 修改代码。
4. 再跑测试和 Android `assembleDebug`。

让智能体接手：

1. 先读 [../AGENTS.md](../AGENTS.md)。
2. 再读 [../llms.txt](../llms.txt)。
3. 根据任务读取对应人类手册。
