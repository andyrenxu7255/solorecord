# SoloRecord HarmonyOS 客户端

## 中文

这是 HarmonyOS 6 / OpenHarmony Stage 模型的 Web 外壳工程。它承载服务器端 SoloRecord Web 体验，不在端侧保存 ASR、LLM、LDAP、SSO、Hermes 或 ES 密钥。

当前 Windows 环境没有 DevEco Studio、hvigor 或 ohpm，因此无法在本机生成签名 HAP。运维团队可在 HarmonyOS 构建机上完成签名和打包。

### 构建步骤

1. 安装 DevEco Studio，并安装 HarmonyOS 6 对应 SDK。
2. 打开 `clients/harmony/SoloRecord`。
3. 将 `entry/src/main/ets/pages/Index.ets` 中 `DEFAULT_SERVER_URL` 改成正式 HTTPS 地址。
4. 配置公司签名证书。
5. 执行 DevEco Studio Build，生成 HAP。
6. 在 SoloRecord Web 管理页选择 `HarmonyOS HAP` 上传发布包。

### 体验说明

HarmonyOS 端与 Web/Windows/macOS 共用同一套界面。录音能力依赖系统 Web 组件和麦克风权限；如企业策略限制 Web 录音，可先使用文件补传或 Android App 采集。

## English

This is the HarmonyOS 6 / OpenHarmony Stage-model Web shell. It hosts the
server-side SoloRecord Web experience and embeds no ASR, LLM, LDAP, SSO, Hermes,
ES, or external secrets.

Signed HAP generation requires DevEco Studio, the HarmonyOS 6 SDK, and company
signing certificates. Update `DEFAULT_SERVER_URL`, build the HAP, then publish it
from the SoloRecord Web admin page.
