# Windows 会议录音 + 中文转写工具

这个项目提供了一个可在 **Windows** 上运行的会议记录程序，适用于：

- 飞书会议
- 腾讯会议
- 蓝牙耳机（系统输出回环录音）

核心能力：

1. 录制会议系统音频（WASAPI Loopback）
2. 中文语音识别（WhisperX）
3. 说话人区分（Speaker Diarization，需 HuggingFace Token）
4. 生成文本稿（`.txt`）和结构化 JSON（`.json`）

---

## 1. 环境准备（Windows）

建议 Python 3.10 - 3.11。

先进入项目目录（非常重要）：

```powershell
cd 你的项目路径\codex_project_1
```

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -U pip
pip install -r requirements.txt
```

如果你遇到报错：`Could not open requirements file`，通常是因为不在项目目录。也可以直接运行我们提供的安装脚本（自动切换到脚本目录）：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_windows.ps1
```

> `torch` 在 Windows 上可能需要按你的 CUDA/CPU 环境单独安装。

例如 CPU 版：

```powershell
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

---

## 2. 查看可用音频回环设备

```powershell
python meeting_transcriber.py --list-devices
```

如果你使用蓝牙耳机，一般会看到带有耳机名称的回环设备（例如包含 `Bluetooth`、耳机品牌名等）。

---

## 3. 开始会议录音 + 转写

### 方式 A：图形界面（推荐）

```powershell
python meeting_gui.py
```

GUI 支持：

- 下拉选择回环设备
- 开始录音 / 停止并转写按钮
- 输出目录选择
- 模型、语言、采样率、声道配置
- 日志窗口实时查看状态

### 方式 B：命令行

```powershell
python meeting_transcriber.py --device-name "Bluetooth"
```

参数说明：

- `--device-name`：设备名关键字（建议填蓝牙耳机名称关键词）
- `--model`：WhisperX 模型，默认 `large-v3`
- `--language`：默认 `zh`
- `--output-dir`：输出目录，默认 `outputs`
- `--no-diarization`：关闭说话人分离（仅转写）

运行后：

1. 程序持续录音
2. 按 `Ctrl + C` 结束会议
3. 自动执行转写和说话人区分

输出文件（在 `outputs/`）：

- `meeting_时间戳.wav`：原始录音
- `meeting_时间戳.txt`：可读会议纪要文本
- `meeting_时间戳.json`：结构化转写结果

---

## 4. 启用说话人区分（推荐）

WhisperX 的 diarization 依赖 HuggingFace 访问令牌。

在 PowerShell 中设置：

```powershell
$env:HF_TOKEN="你的_huggingface_token"
```

若未设置，程序会自动跳过说话人分离，仅输出普通转写。

---

## 5. 飞书会议/腾讯会议建议

- Windows 声音设置中，将飞书/腾讯会议输出设备固定到你的蓝牙耳机。
- 在会议软件中关闭“自动切换设备”可减少丢音。
- 尽量保证单设备输出，避免同时外放 + 耳机导致回环设备不一致。

---

## 6. 打包为 Windows EXE（双击运行）

安装 pyinstaller：

```powershell
pip install pyinstaller
```

打包 GUI 版本：

```powershell
pyinstaller --noconfirm --onefile --windowed --name MeetingTranscriberGUI meeting_gui.py
```

打包后可执行文件在：

```text
dist\MeetingTranscriberGUI.exe
```

> 首次打包较慢是正常现象。若你需要附带图标，可额外加 `--icon your.ico`。
