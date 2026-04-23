import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from meeting_transcriber import (
    LoopbackRecorder,
    list_loopback_speakers,
    now_str,
    transcribe_with_diarization,
)


class MeetingTranscriberGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("会议记录与转写工具 (Windows)")
        self.root.geometry("760x560")

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.recorder: LoopbackRecorder | None = None
        self.recording = False
        self.current_wav: Path | None = None

        self._build_widgets()
        self._load_devices()
        self._poll_logs()

    def _build_widgets(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        # Device
        ttk.Label(main, text="输出回环设备:").grid(row=0, column=0, sticky="w", pady=4)
        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(main, textvariable=self.device_var, width=70, state="readonly")
        self.device_combo.grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Button(main, text="刷新设备", command=self._load_devices).grid(row=0, column=2, padx=8)

        # Output dir
        ttk.Label(main, text="输出目录:").grid(row=1, column=0, sticky="w", pady=4)
        self.output_dir_var = tk.StringVar(value="outputs")
        ttk.Entry(main, textvariable=self.output_dir_var).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(main, text="浏览", command=self._browse_output_dir).grid(row=1, column=2, padx=8)

        # Model/Language
        ttk.Label(main, text="模型:").grid(row=2, column=0, sticky="w", pady=4)
        self.model_var = tk.StringVar(value="large-v3")
        ttk.Entry(main, textvariable=self.model_var).grid(row=2, column=1, sticky="ew", pady=4)

        ttk.Label(main, text="语言:").grid(row=3, column=0, sticky="w", pady=4)
        self.lang_var = tk.StringVar(value="zh")
        ttk.Entry(main, textvariable=self.lang_var).grid(row=3, column=1, sticky="ew", pady=4)

        # Sample rate/channels
        ttk.Label(main, text="采样率:").grid(row=4, column=0, sticky="w", pady=4)
        self.sr_var = tk.StringVar(value="16000")
        ttk.Entry(main, textvariable=self.sr_var).grid(row=4, column=1, sticky="ew", pady=4)

        ttk.Label(main, text="声道:").grid(row=5, column=0, sticky="w", pady=4)
        self.channels_var = tk.StringVar(value="1")
        ttk.Entry(main, textvariable=self.channels_var).grid(row=5, column=1, sticky="ew", pady=4)

        # Options
        self.diarization_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(main, text="启用说话人区分（需要 HF_TOKEN）", variable=self.diarization_var).grid(
            row=6, column=1, sticky="w", pady=6
        )

        # Controls
        controls = ttk.Frame(main)
        controls.grid(row=7, column=0, columnspan=3, pady=10, sticky="w")
        self.start_btn = ttk.Button(controls, text="开始录音", command=self.start_recording)
        self.start_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(controls, text="停止并转写", command=self.stop_and_transcribe, state="disabled")
        self.stop_btn.pack(side="left", padx=4)

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(main, textvariable=self.status_var).grid(row=8, column=0, columnspan=3, sticky="w", pady=4)

        # Logs
        ttk.Label(main, text="日志:").grid(row=9, column=0, sticky="nw", pady=4)
        self.log_text = tk.Text(main, height=16, wrap="word")
        self.log_text.grid(row=9, column=1, columnspan=2, sticky="nsew")

        main.columnconfigure(1, weight=1)
        main.rowconfigure(9, weight=1)

    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_dir_var.set(path)

    def _log(self, msg: str) -> None:
        self.log_queue.put(msg)

    def _poll_logs(self) -> None:
        while not self.log_queue.empty():
            msg = self.log_queue.get()
            self.log_text.insert("end", f"{msg}\n")
            self.log_text.see("end")
        self.root.after(200, self._poll_logs)

    def _load_devices(self) -> None:
        try:
            speakers = list_loopback_speakers()
            names = [s.name for s in speakers]
            self.device_combo["values"] = names
            if names and not self.device_var.get():
                self.device_var.set(names[0])
            self._log(f"已加载 {len(names)} 个回环设备")
        except Exception as exc:
            messagebox.showerror("设备错误", str(exc))

    def start_recording(self) -> None:
        if self.recording:
            return

        selected_name = self.device_var.get().strip()
        if not selected_name:
            messagebox.showwarning("提示", "请先选择回环设备")
            return

        sample_rate = int(self.sr_var.get())
        channels = int(self.channels_var.get())

        outdir = Path(self.output_dir_var.get())
        outdir.mkdir(parents=True, exist_ok=True)
        self.current_wav = outdir / f"meeting_{now_str()}.wav"

        speakers = list_loopback_speakers()
        speaker = next((s for s in speakers if s.name == selected_name), None)
        if speaker is None:
            messagebox.showerror("设备错误", "设备不存在，请刷新后重试")
            return

        self.recorder = LoopbackRecorder(speaker=speaker, wav_path=self.current_wav, samplerate=sample_rate, channels=channels)
        self.recorder.start()
        self.recording = True

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_var.set(f"录音中: {selected_name}")
        self._log(f"[REC] 开始录音: {self.current_wav}")

        threading.Thread(target=self._update_duration, daemon=True).start()

    def _update_duration(self) -> None:
        while self.recording and self.recorder is not None:
            self.status_var.set(f"录音中... {self.recorder.seconds:.1f}s")
            time.sleep(1)

    def stop_and_transcribe(self) -> None:
        if not self.recording or self.recorder is None:
            return

        self.recording = False
        self.recorder.stop()

        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_var.set("录音结束，开始转写...")
        self._log("[REC] 已停止录音，开始转写")

        threading.Thread(target=self._run_transcription, daemon=True).start()

    def _run_transcription(self) -> None:
        try:
            assert self.current_wav is not None
            outdir = Path(self.output_dir_var.get())
            base = self.current_wav.stem
            txt_path = outdir / f"{base}.txt"
            json_path = outdir / f"{base}.json"

            if self.diarization_var.get() and not os.getenv("HF_TOKEN"):
                self._log("[WARN] 未设置 HF_TOKEN，将跳过说话人区分")

            transcribe_with_diarization(
                wav_path=self.current_wav,
                model_name=self.model_var.get().strip() or "large-v3",
                language=self.lang_var.get().strip() or "zh",
                output_txt=txt_path,
                output_json=json_path,
                enable_diarization=self.diarization_var.get(),
            )
            self._log(f"[DONE] 文本稿: {txt_path}")
            self._log(f"[DONE] 结构化结果: {json_path}")
            self.status_var.set("转写完成")
            messagebox.showinfo("完成", f"转写完成\n{txt_path}\n{json_path}")
        except Exception as exc:
            self._log(f"[ERROR] 转写失败: {exc}")
            self.status_var.set("转写失败")
            messagebox.showerror("转写失败", str(exc))


def main() -> None:
    root = tk.Tk()
    app = MeetingTranscriberGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
