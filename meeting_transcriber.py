import argparse
import datetime as dt
import json
import os
import threading
import time
from pathlib import Path
from typing import List, Optional

import numpy as np
import soundcard as sc
import soundfile as sf


def now_str() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def list_loopback_speakers() -> List[sc.Speaker]:
    speakers = sc.all_speakers()
    return [s for s in speakers if s.isloopback]


def choose_speaker(name_hint: Optional[str]) -> sc.Speaker:
    loopbacks = list_loopback_speakers()
    if not loopbacks:
        raise RuntimeError(
            "没有找到可用的 WASAPI 回环设备。请在 Windows 声音设置中启用输出设备。"
        )

    if not name_hint:
        default_name = sc.default_speaker().name.lower()
        for spk in loopbacks:
            if default_name in spk.name.lower() or spk.name.lower() in default_name:
                return spk
        return loopbacks[0]

    hint = name_hint.lower()
    for spk in loopbacks:
        if hint in spk.name.lower():
            return spk

    available = "\n".join([f"- {s.name}" for s in loopbacks])
    raise RuntimeError(f"未找到匹配设备: {name_hint}\n可选回环设备:\n{available}")


class LoopbackRecorder:
    def __init__(self, speaker: sc.Speaker, wav_path: Path, samplerate: int = 16000, channels: int = 1):
        self.speaker = speaker
        self.wav_path = wav_path
        self.samplerate = samplerate
        self.channels = channels
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._frames = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        block_frames = int(self.samplerate * 0.5)
        with self.speaker.recorder(samplerate=self.samplerate, channels=self.channels) as mic:
            with sf.SoundFile(
                self.wav_path,
                mode="w",
                samplerate=self.samplerate,
                channels=self.channels,
                subtype="PCM_16",
            ) as f:
                while not self._stop_evt.is_set():
                    data = mic.record(numframes=block_frames)
                    if data is None or len(data) == 0:
                        continue
                    data = np.clip(data, -1.0, 1.0)
                    f.write(data)
                    self._frames += len(data)

    def stop(self) -> None:
        self._stop_evt.set()
        if self._thread is not None:
            self._thread.join()

    @property
    def seconds(self) -> float:
        return self._frames / float(self.samplerate)


def _format_ts(seconds: float) -> str:
    if seconds is None:
        return "??:??:??"
    ms = int(max(0, seconds) * 1000)
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02}.{ms:03}"


def transcribe_with_diarization(
    wav_path: Path,
    model_name: str,
    language: str,
    output_txt: Path,
    output_json: Path,
    enable_diarization: bool,
) -> None:
    import torch
    import whisperx

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"

    print(f"[INFO] 加载 WhisperX 模型: {model_name} ({device}, {compute_type})")
    model = whisperx.load_model(model_name, device, compute_type=compute_type, language=language)

    print("[INFO] 执行语音识别...")
    audio = whisperx.load_audio(str(wav_path))
    result = model.transcribe(audio, batch_size=8)

    print("[INFO] 对齐中文时间戳...")
    align_model, metadata = whisperx.load_align_model(language_code=language, device=device)
    result = whisperx.align(result["segments"], align_model, metadata, audio, device)

    diarization_result = None
    if enable_diarization:
        hf_token = os.getenv("HF_TOKEN")
        if not hf_token:
            print("[WARN] 未检测到 HF_TOKEN，已跳过说话人分离。")
        else:
            try:
                print("[INFO] 执行说话人分离...")
                diarize_model = whisperx.DiarizationPipeline(use_auth_token=hf_token, device=device)
                diarization_result = diarize_model(audio)
                result = whisperx.assign_word_speakers(diarization_result, result)
            except Exception as exc:
                print(f"[WARN] 说话人分离失败，已回退为普通转写: {exc}")

    lines = []
    for seg in result["segments"]:
        start = _format_ts(seg.get("start"))
        end = _format_ts(seg.get("end"))
        speaker = seg.get("speaker", "SPEAKER_UNKNOWN")
        text = seg.get("text", "").strip()
        lines.append(f"[{start} - {end}] [{speaker}] {text}")

    output_txt.write_text("\n".join(lines), encoding="utf-8")

    payload = {
        "audio_file": str(wav_path),
        "language": language,
        "model": model_name,
        "segments": result["segments"],
        "diarization_enabled": enable_diarization,
        "diarization_available": diarization_result is not None,
    }
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Windows 会议录音 + 中文转写 + 说话人区分")
    p.add_argument("--device-name", default=None, help="回环设备名称关键字（例如 bluetooth/耳机）")
    p.add_argument("--sample-rate", type=int, default=16000)
    p.add_argument("--channels", type=int, default=1)
    p.add_argument("--model", default="large-v3")
    p.add_argument("--language", default="zh")
    p.add_argument("--output-dir", default="outputs")
    p.add_argument("--no-diarization", action="store_true")
    p.add_argument("--list-devices", action="store_true", help="仅列出可用回环设备")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.list_devices:
        print("可用回环设备：")
        for s in list_loopback_speakers():
            print(f"- {s.name}")
        return 0

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    timestamp = now_str()
    wav_path = outdir / f"meeting_{timestamp}.wav"
    txt_path = outdir / f"meeting_{timestamp}.txt"
    json_path = outdir / f"meeting_{timestamp}.json"

    speaker = choose_speaker(args.device_name)
    print(f"[INFO] 使用设备: {speaker.name}")
    print("[INFO] 开始录音，按 Ctrl+C 结束会议并开始转写...")

    recorder = LoopbackRecorder(
        speaker=speaker,
        wav_path=wav_path,
        samplerate=args.sample_rate,
        channels=args.channels,
    )

    recorder.start()
    try:
        while True:
            time.sleep(1)
            print(f"[REC] 已录制 {recorder.seconds:.1f}s", end="\r", flush=True)
    except KeyboardInterrupt:
        print("\n[INFO] 收到停止信号，正在结束录音...")
    finally:
        recorder.stop()

    print(f"[INFO] 录音保存: {wav_path}")
    transcribe_with_diarization(
        wav_path=wav_path,
        model_name=args.model,
        language=args.language,
        output_txt=txt_path,
        output_json=json_path,
        enable_diarization=not args.no_diarization,
    )
    print(f"[DONE] 文本稿: {txt_path}")
    print(f"[DONE] 结构化结果: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
