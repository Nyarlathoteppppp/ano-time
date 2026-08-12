# AnoTime macOS 受邀体验指南

> 面向受邀体验者。当前是 macOS 开发体验版，不是 App Store 正式版。

## 体验前确认

- Apple Silicon Mac，且系统满足 README 中 Apple Speech / Apple Translation 的版本要求。
- 准备一段英文课程、网页视频或会议音频。
- 体验版不会要求你填写 Groq、Gemini、Cerebras 等供应商 API Key；若安装包要求你提供开发者共享 Key，请停止安装并联系维护者。
- 本地双语记录默认保存到 `~/Documents/Anotime Records`。不要用敏感会议内容测试，除非已获得参与者同意。

## 首次使用

1. 打开 AnoTime，选择 **System Audio**（网页/视频/会议）或 **Microphone**（线下课堂）。
2. 在 macOS 提示时允许“录屏与系统录音”或“麦克风”权限。
3. 选择 **Physical MacBook Notch** 或 **Resizable Glass** 字幕模式。
4. 点击 **Launch Translator**。
5. 播放英文音频，先确认英文原文出现，再确认中文草稿与最终译文出现。

## 系统音频没有反应

打开：

**系统设置 → 隐私与安全性 → 录屏与系统录音**

启用 AnoTime 和体验版随附的音频 helper。修改权限后完全退出 AnoTime 再重新打开。

如果仍无声音：播放视频时，在 **Audio** 页运行音频测试；反馈时只发错误描述和系统版本，不要发送 API Key、完整私人 transcript 或截图中的敏感内容。

## 体验反馈应包含

- Mac 型号、macOS 版本、是否 Apple Silicon。
- 使用的音频来源：System Audio / Microphone / Both。
- 使用场景：课程 / 会议 / 网页视频。
- 是否能看到：英文原文、中文草稿、最终译文。
- 从 Start 到第一条英文、第一条中文的大致秒数。
- 是否出现：卡住、多个窗口、权限循环、全屏不置顶、字幕跳动或崩溃。

不要发送：AnoTime 登录令牌、供应商 API Key、包含私人会议内容的完整日志。

## 体验结束

点击 Stop，确认双语记录已生成。你可以在 Finder 中打开：

```text
~/Documents/Anotime Records
```

若体验版提供云端试用，其剩余额度和时长以服务端显示为准；本地关闭或修改客户端不能延长试用。
