import os, random, subprocess, asyncio
from flask import Flask, request, send_file, jsonify
import edge_tts

app = Flask(__name__)

SEARCH_QUERIES = [
    "ytsearch15:GTA 5 insane stunt fail clip",
    "ytsearch15:GTA online funny moments fail clip",
    "ytsearch15:GTA 5 thug life stunt clip"
]

async def make_tts(text, out_path):
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
    await communicate.save(out_path)

@app.route("/render", methods=["POST"])
def render_short():
    try:
        data = request.get_json(force=True)
        voiceover_text = data.get("voiceover_text", "Watch this insane GTA stunt!")

        for f in ["raw.mp4", "voice.mp3", "final.mp4"]:
            if os.path.exists(f):
                os.remove(f)

        query = random.choice(SEARCH_QUERIES)
        idx = random.randint(1, 15)
        subprocess.run([
            "yt-dlp",
            "--playlist-items", str(idx),
            "--match-filter", "duration < 60",
            "-f", "best[ext=mp4][height<=1080]/best[ext=mp4]/best",
            "-o", "raw.mp4",
            query
        ], check=True)

        asyncio.run(make_tts(voiceover_text, "voice.mp3"))

        vf = (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:10[bg];"
            "[0:v]scale=1080:-2[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,eq=contrast=1.05:saturation=1.1[outv]"
        )
        cmd = [
            "ffmpeg", "-y", "-i", "raw.mp4", "-i", "voice.mp3",
            "-filter_complex", vf,
            "-map", "[outv]", "-map", "1:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-c:a", "aac", "-shortest", "-t", "58", "final.mp4"
        ]
        subprocess.run(cmd, check=True)
        return send_file("final.mp4", mimetype="video/mp4")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
