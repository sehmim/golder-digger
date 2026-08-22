"""Step 0 gate: prove beat-this and CLAP actually run on this machine."""
import sys, time
import numpy as np
import librosa
import torch

path = sys.argv[1]
dev = "mps" if torch.backends.mps.is_available() else "cpu"
print(f"device: {dev}")

t = time.time()
y, sr = librosa.load(path, sr=22050, mono=True)
print(f"loaded {len(y)/sr:.1f}s @ {sr} in {time.time()-t:.1f}s")

# --- beat-this ---
from beat_this.inference import Audio2Beats
t = time.time()
a2b = Audio2Beats(device=dev)
beats, downbeats = a2b(y, sr)
print(f"beat-this: {len(beats)} beats, {len(downbeats)} downbeats in {time.time()-t:.1f}s")
if len(beats) > 1:
    print(f"  bpm ~ {60/np.median(np.diff(beats)):.1f}")

# --- CLAP ---
from transformers import ClapModel, ClapProcessor
t = time.time()
model = ClapModel.from_pretrained("laion/larger_clap_music_and_speech").to(dev).eval()
proc = ClapProcessor.from_pretrained("laion/larger_clap_music_and_speech")
print(f"clap loaded in {time.time()-t:.1f}s")

y48 = librosa.resample(y, orig_sr=sr, target_sr=48000)[: 48000 * 10]
t = time.time()
with torch.no_grad():
    inp = proc(audio=y48, sampling_rate=48000, return_tensors="pt")
    emb = model.get_audio_features(**{k: v.to(dev) for k, v in inp.items()}).pooler_output
emb = torch.nn.functional.normalize(emb, dim=-1).cpu().numpy()
print(f"clap embed {emb.shape} norm={np.linalg.norm(emb):.3f} in {time.time()-t:.1f}s")
print("SMOKE OK")
