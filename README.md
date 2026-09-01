# 原神 · 元素爆发音效触发（v2.0）

玩原神时的多角色仪式感助手：**识别特定角色元素爆发 → 播放专属 BGM + 全屏特效**，另有通关庆祝、商城 BGM、启动迎接视频等持续监控功能。全部基于**屏幕画面识别**（dxcam 抓帧 + 模板匹配/结构判定），不影响游戏操作（特效窗口鼠标穿透）。

## ✨ 功能总览

| 功能 | 触发条件 | 效果 |
|---|---|---|
| **奥黛塔爆发** | 奥黛塔元素爆发演示画面 | 专属 BGM + 镭射灯光秀（27 秒，BGM 同步淡出） |
| **玛薇卡爆发** | 玛薇卡元素爆发演示画面 | 《灼火之心》BGM（1:56-2:59）+ 火焰爆炸特效（绿幕抠像，3 秒播放一次） |
| **哥伦比娅爆发** | 哥伦比娅元素爆发演示画面（01 帧即触发） | 《白鸽之诗》BGM（2:14-2:58，2 秒淡入 + 结尾淡出） |
| **幽境危战通关** | 通关结算页出现 | Unbelievable! 音效 + 小人走入 + 礼花齐放 + 通关 BGM |
| **商城氪金页** | 进入创世结晶购买页 | 《朋友的酒》循环播放（从 10 秒起），离开商城淡出停止 |
| **启动读条读满** | 启动加载读条到指定进度 | 派蒙迎接视频（绿幕抠像，全屏播放一次） |
| **语音控制** | 喊「原神 启动！」 | 启动游戏 + TTS 播报 |

三个角色识别器互相独立（`fired_kind` 路由），BGM 播放期间不会重复触发（防叠音）。

---

## 🎯 角色爆发识别（detection / mavuika / columbina）

按 Q 键 → 2.5 秒窗口内逐帧评分，各角色独立参考图：

```
score = 0.25×冰蓝占比 + 0.20×HSV直方图相关 + 0.55×姿态模板匹配
        − 负样本条件扣分（仅当帧更像负样本模板时）
```

- **多参考图**：每角色支持多张参考图（列表），分别评分取最大——覆盖爆发演示的不同阶段（如玛薇卡跃起/骑行、哥伦比娅面部特写/天使形态）
- **负样本系统**：七七/桑多涅/茜特菈莉/其他角色爆发/队伍配置页等画面加入负样本，只有帧比正参考更"像"负样本时才扣分（条件扣分），精准压制误触
- **场景自适应基准**：Q 按下瞬间采集场景的冰蓝占比与直方图相关度，`ice/hist` 改为相对增量——**海边、天云峠等大范围蓝色场景**不再抬高分数（实测蓝色场景基准下玛薇卡帧归零，奥黛塔自身 0.647 仍触发）
- **低延迟优化**：模板匹配在 ⅛ 尺度进行（分数与 ¼ 实测偏差 <0.01），三角色识别器合计约 **53ms/帧**；确认窗口期间自动暂停通关/商城/启动监控，爆发采样不被抢帧
- 实测交叉验证（阈值 0.5/0.55，连续 2 帧）：
  - 奥黛塔 0.894 触发；玛薇卡 0.813/0.867 触发；哥伦比娅 0.71~0.85 触发（01 帧即触发）
  - 各角色互不误触（≤0.40），队伍配置页 0.117~0.402 安全

## 🛒 商城 BGM（shop）

持续屏幕监控（非 Q 触发）：识别到**购买创世结晶界面**（中部结晶档位面板）→《朋友的酒》无限循环播放；离开商城（连续 6 次未识别 ≈ 3 秒）→ 1.5 秒淡出停止。

- 参考图 `assets/shop_ref.png`（氪金页中部面板），负样本为月卡/礼包/装扮/兑换四页同区域
- 实测：氪金页 0.723 触发，其他商城页 0.09~0.34 安全

## 🚀 启动派蒙迎接视频（startup）

启动加载屏持续监控（非 Q 触发）：**元素图标读条**（灰色图标从左到右逐个亮起）到达指定进度 → 派蒙迎接视频全屏播放一次。

- 触发判定为四重结构条件（纯数值，不依赖模板）：
  1. 整屏纯白 ≥ 90%（拦截一切游戏/菜单画面）
  2. 图标带深色覆盖 ≥ `trigger_ratio`（读条进度）
  3. 图标带深色列簇数 ≥ `min_clusters`（图标行特征；米哈游/原神 logo 只有 1~4 簇）
  4. 图标带上下边缘区域纯白 ≥ 99.5%（竖排大 logo 越界拦截）
- 淡出模拟验证：mihoyo/原神标志界面（含淡出全程）零误触
- 派蒙素材：B 站绿幕素材抠像（`assets/paimon_frames.npz`，241 帧 @24fps，10.14 秒），专属不透明度增益 `fx.paimon_intensity`（默认 1.15，抵消全局灯光强度，派蒙 100% 实心）
- 触发时机由 `startup.trigger_ratio` 控制（当前对应「两个图标亮起」状态，即启动界面04 时刻）

## 🎉 幽境危战通关庆祝（completion）

通关幽境危战结算页出现时自动触发：

- **通关页识别**：持续屏幕监控（参考图 + 失败/选择/载入负样本），边沿触发 + 8 秒冷却
- **胜利特效**：绿幕素材抠像小人从屏幕左右走入，中央礼花齐放（9 朵，金红必带 + 彩池补充，含发射-上升-爆炸完整过程）
- **音效链**：Unbelievable!（1.41s）→ 通关 BGM（18 秒）→ 特效结束时 BGM 同步淡出归零

## 🔊 语音控制（voice）

对着麦克风喊「**原神 启动！**」→ 直接启动游戏 + TTS 播报「原神，启动！」。

- vosk 离线中文关键词识别（模型随包分发，全本地无网络）
- 内置命令（`config.json` → `voice.commands` 可扩展）：原神 启动（含同音字变体）/ 开始 检测 / 停止 检测
- GUI 勾选「语音命令」即开始聆听；「测试麦克风」检查输入电平与识别结果

## 💡 灯光特效（fx）

- **真·半透明舞台灯光**：UpdateLayeredWindow 每像素 alpha + 加法混合（光即光，背景永远透出）
- 3 束探照灯（红/紫/绿）+ 顶/底频谱跳动波 + 波浪旁粒子 + 雪花粒子 + 左右跳舞 GIF
- 特效模式：灯光秀 / 胜利（小人+礼花）/ 火焰爆炸 / 派蒙视频
- 鼠标完全穿透（WS_EX_TRANSPARENT），不抢焦点；独立进程 `fx_server.py`，由 `fx_client.py` 命令管道控制
- 注意：窗口不能加 WS_EX_NOACTIVATE / WS_EX_TOOLWINDOW、子窗口不能设 WS_EX_LAYERED（实测会破坏 ULW 合成）

---

## 安装

```powershell
cd genshin-burst-trigger
pip install -r requirements.txt
```

## 图形化控制台（推荐）

```powershell
python gui.py
```

奥黛塔冰晶主题（纯 tkinter 零依赖）：半透明玻璃面板 + 胶囊圆角按钮 + 圆形滑块，日志分级着色。

- 配置表单：快捷键、阈值、窗口、冷却、音量、抓帧率、BGM、灯光开关与强度
- 测试按钮：**测试通关 / 测试玛薇卡 / 测试派蒙**（一键预览特效，无需进游戏）
- 状态行实时显示亮度与出战槽位；详细日志可看每帧评分

## 命令行方式

```powershell
python main.py            # 正常运行（游戏需无边框窗口模式）
python main.py --test     # 只测试音频播放
python main.py --debug    # 打印每帧评分/判定过程
python fx_server.py --demo fire:3    # 特效演示：火焰爆炸 3 秒
python fx_server.py --demo paimon:10 # 特效演示：派蒙视频 10 秒
```

## 配置（config.json）

| 块 | 字段 | 含义 | 默认 |
|---|---|---|---|
| 全局 | hotkey / cooldown_seconds / capture_fps / volume | 触发键 / 冷却 / 抓帧率 / 音量 | q / 20 / 30 / 0.5 |
| detection | reference / template_roi / match_threshold / match_frames / window_seconds | 奥黛塔参考图 / 模板区域 / 阈值 / 连续帧 / 窗口 | burst_ref.png / [768,288,1024,864] / 0.55 / 2 / 2.5 |
| detection | negative_templates / neg_penalty | 负样本列表 / 扣分强度 | 七七/桑多涅/玛薇卡/茜特菈莉/哥伦比娅/队伍配置页 / 1.0 |
| mavuika | reference / match_threshold / audio_file / volume / fx_duration | 玛薇卡参考图(2张) / 阈值 / BGM / 音量 / 火焰特效时长 | 0.5 / mavuika_bgm.wav / 0.7 / 3.0 |
| columbina | reference / match_threshold / audio_file / fx_duration | 哥伦比娅参考图(6张) / 阈值 / BGM / 特效时长(待定) | 0.5 / columbina_bgm.wav / 4.0 |
| completion | enabled / reference / match_threshold / sound_file / bgm_file / fx_duration / bgm_fade_delay_seconds | 通关庆祝配置 | 0.45 / unbelievable.wav / victory_bgm.wav / 14 / 0 |
| shop | enabled / reference / match_threshold / check_interval / stop_misses / audio_file / fade_seconds | 商城氪金页监控 | 0.5 / 0.5s / 6 次 / shop_bgm.mp3 / 1.5s |
| startup | enabled / icon_roi / trigger_ratio / release_ratio / min_clusters / margin_white / check_interval / paimon_duration | 启动读条监控（触发时机） | [900,660,850,130] / 0.035 / 0.02 / 2 / 0.995 / 0.3s / 10.0 |
| fx | enabled / intensity / fade_seconds / burst_duration / fire_frames / paimon_frames / paimon_intensity / victory_frames | 特效配置 | 0.87 / 2 / 27 / 火焰与派蒙帧序列 / 1.15 |
| voice | enabled / model_path / game_path / tts / commands | 语音控制 | vosk 模型 / YuanShen.exe / true |

## 已知限制

- 固定 2K（2560x1440）分辨率；换分辨率需重新标定
- 游戏需无边框窗口模式；只支持 1 号显示器
- BGM 播放期间屏蔽新触发（防叠音）；触发冷却 20 秒
- 爆发识别依赖 Q 键（识别窗口 2.5 秒）

## 版权声明

- **BGM**：`burst_bgm.wav`（B站「一滴一滴刺痛我的心」）、`mavuika_bgm.wav`（《灼火之心》1:56-2:59）、`columbina_bgm.wav`（《白鸽之诗》2:14-2:58）、`victory_bgm.wav`、`shop_bgm.mp3`（《朋友的酒》）均来自网络公开音源，版权归原作者/miHoYo 所有，仅供个人使用；如遇版权方要求请替换
- **游戏截图**（`burst_ref.png`、`neg_*.png`、参考图等）为《原神》游戏画面，版权归 miHoYo
- 代码遵循 MIT 协议，可自由修改分发

## 项目结构

```
genshin-burst-trigger/
├── gui.py             # 图形化控制台（推荐入口，含测试按钮）
├── main.py            # 主程序（三角色识别 + 通关/商城/启动监控）
├── calibrate.py       # 校准工具
├── fx_server.py       # 特效进程（灯光秀/胜利/火焰/派蒙，透明叠加窗口）
├── fx_client.py       # 特效控制客户端（命令管道）
├── theme.py           # GUI 冰晶主题（纯 tkinter）
├── voice.py           # 语音控制（vosk 离线识别）
├── config.json        # 全部配置
├── tools/trim.py          # 音频截取工具
├── tools/process_victory.py  # 绿幕抠像 → 帧序列工具
├── assets/            # BGM、参考图、负样本、帧序列（npz）
└── requirements.txt
```
