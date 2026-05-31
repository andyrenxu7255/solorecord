# SoloRecord UI/UE 设计系统与办公场景验收

## 中文

本文定义 SoloRecord 的界面设计原则、角色场景和验收标准。目标是让公司内部不同办公使用者都能高效完成任务：会议发起人放心录音，参会者快速查证，销售/交付人员拿到可执行待办，管理员稳定配置模型和发布客户端。

## 设计原则

- 清晰优先：所有页面先回答“现在是什么状态、下一步做什么、是否有风险”。
- 工作台优先：Web 不是营销页，而是可反复使用的办公工具，信息密度要适中、层级要稳定。
- 少打扰：会议中不让用户理解 ASR、LLM、token 等技术细节。
- 可扫读：列表、状态、时间线、待办和任务队列都要能一眼判断重点。
- 可恢复：弱网、处理中、失败、待上传都必须给明确提示。
- 证据可追：纪要、待办、转写、音频分段之间保持时间线和来源关系。
- 克制美观：主色用于主要动作和状态，不使用装饰性渐变、浮夸大卡片或单一色块堆叠。

## 角色场景

| 角色 | 核心目标 | UI/UE 要求 |
| --- | --- | --- |
| 会议记录者 | 快速开始录音，确认没有丢音频 | 录音状态明显，分段上传进度可见，弱网有重试 |
| 参会者 | 会后快速找结论和原文 | 会议列表可搜索，详情先看状态、纪要、待办，再看音频和转写 |
| 销售/交付 | 从会议中得到负责人和下一步 | 待办可编辑 owner、task、due、status，导出和外部 API 同步 |
| 管理员 | 配模型、看任务、发客户端 | 配置项分组清晰，密钥不回显，任务失败可重试 |
| 知识平台 Agent | 稳定读取会议证据层 | 外部 API 保留转写、历史、待办和搜索文本 |

## Web 设计落地

- 页面结构从左侧导航 + 右侧工作台组成。
- 会议页新增顶部总览条：全部会议、已完成、处理中、需处理。
- 会议列表使用紧凑卡片，显示标题、创建时间、状态、时长和版本。
- 详情页使用稳定顺序：标题和操作、状态说明、进度、说话人统计、纪要、待办、录音分段、转写时间线、任务日志。
- 操作按钮分组：保存/重新处理和导出分开，减少扫读负担。
- 录音页保留两个任务区：实时录音和文件补传。
- 下载页使用平台切换，不暴露复杂发布细节。
- 管理页保持少量必填，模型、任务、发布三个区块分开。
- 增加 skip link、明确 button type、toast live region，提升键盘和辅助技术可用性。

## Android 设计落地

- 三页签保持不变：录音、记录、登录状态。
- 使用统一的办公色彩、8px 圆角、清晰按钮层级。
- 录音页突出“准备录音/录音中”和本地保存说明。
- 记录详情优先显示纪要、待办、说话人统计，再显示转写。
- 弱网和阶段转写提示写进记录概览，避免用户误以为数据丢失。
- 登录页说明 APK 不含模型或外部系统密钥。

## 验收清单

- Web 会议页在桌面和移动宽度下不发生文字遮挡。
- 会议列表、详情、录音、下载、管理均可键盘点击主要按钮。
- 详情页能在 10 秒内判断会议是否完成、是否有待上传、是否有失败任务。
- 待办编辑后，Web、移动同步、导出和外部 API 都读取同一份数据。
- 录音失败或上传失败时，用户知道下一步是重试、同步还是联系管理员。
- 管理页密钥字段不回显，保存后仅显示“已保存”占位。
- UI 不依赖单一颜色表达状态，文本也说明状态含义。
- 所有真实动态文本经转义后渲染。

## 本轮验证记录

2026-05-30 已完成以下验证：

- Web 多视口真实浏览器检查通过：1440、1024、768、390、320 像素宽度。
- Web 用户路径检查通过：登录、会议工作台、录音、App 下载、系统管理、登录弹窗。
- Web 检查项包括：无横向滚动、无主要控件越界、按钮触控高度不小于基础可点区域。
- 服务端测试通过：`scripts\run-tests.ps1`。
- HTTP 端到端 smoke 通过：`scripts\smoke-e2e.ps1 -BaseUrl http://127.0.0.1:8018 -ExternalToken test-token`。
- Android 构建通过：`assembleDebug`，输出 `app/build/outputs/apk/debug/app-debug.apk`。
- Android 模拟器验证通过：安装 APK、清空应用数据、打开首屏、切换录音/记录/登录状态三页签，无崩溃日志；公开调试包首启不会带内部服务器地址。
- Android 真机麦克风权限弹窗、系统后台保活提示和长时间录音仍需在运维/测试机上复核。
- 公共源码密钥扫描未发现真实 ASR、LLM、LDAP、服务器账号或内部 token。

## English

# SoloRecord UI/UE Design System And Office Acceptance

This document defines the interface principles, role scenarios, and acceptance criteria for SoloRecord. The goal is to make everyday office workflows efficient for meeting recorders, attendees, sales or delivery teams, administrators, and enterprise knowledge agents.

## Principles

- Clarity first: every screen should show the current state, next action, and risk.
- Workbench first: the Web app is an operational tool, not a landing page.
- Low interruption: users should not need to understand ASR, LLM, token, or LDAP details during meetings.
- Scannable layout: lists, states, timelines, action items, and job queues should be easy to read quickly.
- Recoverable flows: weak network, processing, failure, and pending upload states must be explicit.
- Evidence traceability: summaries, action items, transcript rows, and audio segments remain connected.
- Restrained visual design: primary color is reserved for main actions and state, avoiding decorative gradients or oversized cards.

## Role Scenarios

| Role | Goal | UI/UE Requirement |
| --- | --- | --- |
| Meeting recorder | Start recording quickly and trust audio is safe | Clear recording state, segment progress, weak-network retry |
| Attendee | Find decisions and transcript evidence | Searchable list, detail-first summary/action/timeline layout |
| Sales or delivery | Get accountable next steps | Editable owner, task, due date, and status |
| Administrator | Configure providers and publish clients | Grouped config, hidden secrets, retryable jobs |
| Knowledge agent | Read stable meeting evidence | External API includes transcript, history, actions, and search text |

## Web Implementation

- Left navigation plus right workbench structure.
- Meeting overview strip for total, ready, processing, and attention-needed records.
- Compact meeting cards with title, created time, status, duration, and version.
- Detail order: title/actions, status, progress, speaker stats, summary, actions, audio segments, transcript, jobs.
- Save/process actions are separated from export actions.
- Recorder page keeps live recording and file upload as two clear tasks.
- Download page uses platform tabs.
- Admin page separates providers, jobs, and release publishing.
- Skip link, explicit button types, and live toast status improve accessibility.

## Android Implementation

- Keep the three-tab structure: Recording, Records, Login Status.
- Use consistent office colors, 8px corners, and clear button hierarchy.
- Recording screen emphasizes ready/recording state and local-save safety.
- Record detail shows summary, actions, speaker stats, then transcript.
- Weak-network and partial-transcript hints are visible in record overview.
- Login page states that APKs do not contain model or external-system secrets.

## Acceptance Checklist

- Web layout does not overlap text on desktop or mobile widths.
- Meetings, details, recording, downloads, and admin primary actions are keyboard-accessible.
- A user can identify meeting completion, pending upload, or failed jobs within 10 seconds.
- Edited action items are reflected in Web, mobile sync, exports, and external APIs.
- Upload or processing failures tell users whether to retry, sync, or contact an administrator.
- Admin secret fields never echo raw values.
- State is conveyed by text as well as color.
- Dynamic text is escaped before rendering.

## Current Verification Record

The following checks passed on 2026-05-30:

- Web browser validation across 1440, 1024, 768, 390, and 320 pixel viewport widths.
- Web user flow validation for sign-in, meeting workspace, recording, app downloads, administration, and the sign-in dialog.
- Web layout checks covered horizontal scrolling, visible element overflow, and minimum practical button hit height.
- Server tests passed: `scripts\run-tests.ps1`.
- HTTP end-to-end smoke passed: `scripts\smoke-e2e.ps1 -BaseUrl http://127.0.0.1:8018 -ExternalToken test-token`.
- Android build passed: `assembleDebug`, producing `app/build/outputs/apk/debug/app-debug.apk`.
- Android emulator validation passed: APK install, app-data clear, first launch, Recording/Records/Login tab switching, and no crash logs; the public debug build starts without an internal server URL.
- Android physical-device checks for microphone permission prompts, background recording notices, and long-running recording still need confirmation on an operations or QA device.
- Public-source secret scan found no real ASR, LLM, LDAP, server account, or internal token values.
