# 解説動画メーカー（Gemini TTS ＋ 図解アニメ）

Gemini TTS で日本語ナレーションを作り、図解アニメとテロップを合わせて縦型（1080×1920）の mp4 にします。
いまの台本は「ブリ（青物）の釣り方」です。台本と図解は `make_video.py` の `SCENES` にあります。

## 使い方

```bash
python3 make_video.py              # 本番生成 → out/buri_short.mp4（キーは環境変数 GEMINI_API_KEY か、ネットワークシークレット）
python3 make_video.py --voice Puck # 声を変える（Kore, Puck, Charon, Aoede など）
python3 make_video.py --preview    # キーなし・無音で映像だけ確認 → out/preview.mp4
```

- 必要なもの: Python 3、Pillow、ffmpeg、日本語フォント
- TTS モデルは、API のモデル一覧から最新のもの（Pro 以外）を自動で選びます。`--model` で固定もできます。
- 作った音声は `out/audio/` に保存され、作り直すときは再利用します（無料枠の回数を節約するため）。
- 無料枠で送った台本は Google の製品改善に使われることがあります。
