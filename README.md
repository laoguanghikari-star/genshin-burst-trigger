# 原神 · 元素爆发音效触发（v1.7）

玩原神时，**只有奥黛塔（队伍第 2 槽位）**释放元素爆发时，播放指定 BGM（从「一滴一滴刺痛我的心 …」开始）+ **舞台灯光特效**；其他角色爆发不触发；BGM/灯光播放期间不会重复触发。

## 语音控制（voice）

对着麦克风喊「**原神 启动！**」→ 直接启动游戏（绕过启动器）+ TTS 播报「原神，启动！」。

- **vosk 离线中文关键词识别**（模型随包分发，任何 Windows 表现一致，全本地无网络）
- 内置命令（`config.json` → `voice.commands` 可扩展）：
  - 原神 启动 / 启动原神 → 启动游戏
  - 关闭原神 / 退出原神 → 结束游戏
  - 打开特效 / 关闭特效 → 控制灯光秀
  - 试听音乐 → 播放 BGM + 特效预览
  - 开始检测 / 停止检测 → 控制爆发检测
- GUI 里勾选「语音命令」即开始聆听；「测试麦克风」可检查输入电平

## 灯光特效（fx）

- **真·半透明舞台灯光**：UpdateLayeredWindow 每像素 alpha + 加法混合（光即光，背景永远透出），不再是实心色块
- **固定 3 束探照灯**（红/紫/绿）：光源集中在中段、摆动收窄——中央始终有光，不甩到屏幕边缘
- **顶边/底边频谱跳动波**：音乐播放器风格**细密频率条（48 段、带间隙）**，每段独立跳动 + 鼓点包络脉冲，不平移
- **波浪旁粒子光点**：48 个彩色/白色光点集中在顶/底频谱带附近浮动闪烁
- **雪花粒子**：24 片六角雪花形状光点全屏缓慢飘动
- **左右跳舞 GIF**：`fx.gif` 配置的动画（如 dance27s_full.gif）显示在屏幕左右两侧中间偏上位置（左右对称，距边 30px），与灯光同步循环
- **鼠标完全穿透**（WS_EX_TRANSPARENT），不抢焦点，不影响游戏操作
- 强度可在 GUI 调节；`fx.protected_region` 默认关闭（不影响队伍面板）
- 强度可在 GUI 调节；**队伍面板角标区域自动挖洞**（`fx.protected_region`）
- 独立进程 `fx_server.py`（tkinter 外壳 + Win32 分层窗口），由 `fx_client.py` 命令管道控制
- 注意：窗口不能加 WS_EX_NOACTIVATE / WS_EX_TOOLWINDOW、子窗口不能设 WS_EX_LAYERED（实测会破坏本机 ULW 合成）

## 原理

```
Q 键按下 + 爆发画面识别（奥黛塔元素爆发演示特写）= 触发 BGM + 灯光秀
```

- **爆发画面识别**：Q 按下后 2.5 秒窗口内逐帧评分，比对对象是 `assets/burst_ref.png`（奥黛塔爆发演示参考图）。评分 = 0.25×冰蓝占比 + 0.20×HSV 直方图相关 + 0.55×舞姿模板匹配，再减去**条件扣分**（仅当帧更像七七/桑多涅的负样本模板时）：`0.75 × max(0, 负匹配 - 正匹配)`。连续 2 帧 ≥ 0.55 触发。实测：奥黛塔 0.65-0.89，七七 ≤ 0.40，桑多涅 ≤ 0.40。
- **防叠音/防连按**：BGM 播放期间屏蔽一切新触发 + 20 秒冷却 + Q 键 1 秒防抖（手抖连按 Q 只算一次）。
- 槽位校验（`use_slot_check`）默认关闭（爆发演示会遮挡队伍面板，读数不可靠）。

## 安装

```powershell
cd genshin-burst-trigger
pip install -r requirements.txt
```

## 使用

### 图形化控制台（推荐）

```powershell
python gui.py
```

**奥黛塔冰晶主题**（`theme.py`，纯 tkinter 零依赖）：奥黛塔01 半透明玻璃面板背景（主角透出）、**胶囊圆角按钮 + 圆形滑块 + 圆形勾选**、窗内冰晶渐变标题横幅（❖ 钻石 + ❋ 羽饰）、日志分级着色（触发=绿 / 警告=黄 / 错误=红）。

- **配置表单**：触发快捷键、识别匹配阈值、识别窗口、冷却、音量、抓帧率、BGM 文件（可浏览选择）、详细日志开关、灯光特效开关与强度——全部为**当前识别模式实际生效**的参数；旧版槽位/闪光参数已从界面移除（仍可在 config.json 手动配置 flash 模式）
- **试听 BGM**：一键播放当前 BGM + 灯光特效预览
- **启动/停止检测**：界面内直接开关检测线程，无需命令行
- **状态行**：实时显示画面亮度与识别到的出战槽位
- **运行日志**：完整记录判定过程；勾选「详细日志」后可看到每帧亮度与槽位判定，便于排查触发失败

### 命令行方式

1. **试听**：`python main.py --test`
2. **校准阈值**：`python calibrate.py`（待机 3 秒 → 放爆发按 T 标记 2-3 次 → 写建议阈值到 config.json）
3. **运行**：`python main.py`（游戏需**无边框窗口**模式）

调试：`python main.py --debug` 会打印每帧亮度、出战槽位和判定过程。

## 配置（config.json）

| 字段 | 含义 | 默认 |
|---|---|---|
| hotkey | 触发键 | q |
| target_slot | 目标出战槽位（1-4，奥黛塔=2） | 2 |
| party_panel | 角标检测区域（2K 坐标，x=2480, 槽位中心 y=368/490/611/733） | — |
| active_margin | 出战判定的最小亮度差（仅槽位校验模式） | 20 |
| detection.mode | 检测模式：recognition / flash / both | recognition |
| detection.reference | 爆发参考图（2K 全屏） | assets/burst_ref.png |
| detection.template_roi | 角色模板区域 [x,y,w,h] | [768,288,1024,864] |
| detection.match_threshold | 识别触发阈值 | 0.55 |
| detection.match_frames | 连续命中帧数 | 2 |
| detection.window_seconds | Q 后识别窗口 | 2.5 |
| flash_window_seconds | Q 后等待闪光确认的时间窗 | 1.2 |
| cooldown_seconds | 触发冷却（播放中直接屏蔽，此值为播放结束后的兜底） | 20 |
| capture_fps | 抓帧率 | 30 |
| flash_region | 闪光检测区域 [x,y,w,h] | 屏幕中心 50% |
| audio_file | BGM 文件 | assets/burst_bgm.wav |
| volume | 音量 0-1 | 0.9 |
| fx.enabled | 灯光特效总开关 | true |
| fx.intensity | 灯光强度 0-1 | 0.6 |
| fx.cycle_seconds | 效果轮换周期（秒） | 14 |
| fx.fade_seconds | 结束淡出时长（秒） | 2 |
| fx.fps | 特效帧率 | 30 |
| fx.protected_region | 挖洞区域（队伍面板角标，避免干扰检测） | [2475,344,55,415] |

## 已知限制（v1.5）

- 固定 2K（2560x1440）分辨率；换分辨率需重新标定 party_panel 坐标
- 队伍面板角标坐标假设面板固定在屏幕右缘；若游戏 UI 缩放设置改变需重新标定
- 出战角色判定"未知"时默认不触发（安全优先）
- 游戏需无边框窗口模式；只支持 1 号显示器

## 版权声明

- **BGM**（`assets/burst_bgm.wav`）来自 B 站视频（「一滴一滴刺痛我的心」），版权归原作者所有，仅供个人使用；如遇版权方要求，请替换为你自己的音乐文件（用 `tools/trim.py` 截取即可）
- **游戏截图**（`assets/burst_ref.png`、`neg_*.png`、`gui_bg.png`）为《原神》游戏画面，版权归 miHoYo 所有，仅作识别与界面演示用途
- 代码部分（`main.py` 等）遵循 MIT 协议，可自由修改分发

## 项目结构

```
genshin-burst-trigger/
├── gui.py             # 图形化控制台（推荐入口）
├── main.py            # 主程序（检测 + 触发）
├── calibrate.py       # 校准工具（阈值 + 出战槽位预览）
├── fx_server.py       # 镭射灯光特效进程（透明叠加窗口）
├── fx_client.py       # 特效控制客户端（命令管道）
├── config.json        # 配置
├── tools/trim.py      # 音频截取工具
├── assets/burst_bgm.wav  # BGM（57 秒：从「一滴一滴刺痛我的心」到第一段副歌+伴奏结束）
└── requirements.txt
```
