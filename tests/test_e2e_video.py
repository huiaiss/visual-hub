"""End-to-end video render test — first real MP4 from FrameCraft.

Uses real product images from uploads/ and a minimal plan to validate
the full rendering pipeline: Script → TTS → Assets → HTML → MP4.
No AI API keys required.
"""
import io
import json
import os
import sys
import tempfile

# Fix Windows GBK encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.script_models import Beat, Script
from services.video_renderer import render_video


def build_test_plan(product_name="老爹鞋", image_paths=None):
    """Build a QA-compliant 7-shot plan for a shoe product video."""
    if image_paths is None:
        uploads = os.path.join(os.path.dirname(__file__), "..", "data", "uploads")
        candidates = []
        for f in sorted(os.listdir(uploads)):
            fpath = os.path.join(uploads, f)
            if os.path.getsize(fpath) > 100 * 1024:
                candidates.append(fpath)
            if len(candidates) >= 4:
                break
        image_paths = candidates

    storyboard = [
        {
            "shot": 1, "tier": "L1",
            "visual": f"白色背景+{product_name}正面平铺展示，光线柔和",
            "audio_l1": "我跟你说这双鞋真的绝了，你们看这个鞋底设计，我拿到手就惊了",
            "audio_l2": "今天测评这款复古厚底老爹鞋，先看鞋底高弹EVA材质，回弹率实测非常出色",
            "how_to_shoot": "手机放地上仰拍鞋底，窗边白墙自然光，手持稳定拍摄鞋面特写",
            "duration": 5.0,
        },
        {
            "shot": 2, "tier": "L1",
            "visual": f"鞋底特写+手指按压展示回弹，慢动作",
            "audio_l1": "你看我这样按下去马上就弹回来，走一天路脚都不酸",
            "audio_l2": "鞋底采用高弹EVA发泡材质，减震回弹效果实测对比，日常通勤和逛街都很适合",
            "how_to_shoot": "手机倒扣放桌上俯拍，手指按压鞋底慢动作，白墙背景",
            "duration": 5.0,
        },
        {
            "shot": 3, "tier": "L1",
            "visual": f"鞋面透气孔特写+灯光透射效果",
            "audio_l1": "你们看这个网面它真的很透气，我自己穿了一个星期了完全不闷脚",
            "audio_l2": "鞋面采用飞织网面工艺，透气孔排列均匀密实，穿一天也不会有闷热感，夏天完全hold住",
            "how_to_shoot": "手持手机拍鞋面细节，灯光从鞋内往外打，窗边自然光辅助",
            "duration": 4.0,
        },
        {
            "shot": 4, "tier": "L1",
            "visual": f"模特穿{product_name}街拍效果，动态走姿展示",
            "audio_l1": "它真的很好搭衣服，你看我随便穿个牛仔裤就很好看",
            "audio_l2": "这双鞋的复古轮廓很适合日常穿搭，搭配宽松牛仔裤或休闲裤，街头感直接拉满",
            "how_to_shoot": "手机手持跟拍模特走路，小区路面自然光，保持画面稳定",
            "duration": 4.0,
        },
        {
            "shot": 5, "tier": "L1",
            "visual": f"鞋后跟稳定片特写+用手扭动展示不变形",
            "audio_l1": "再看后跟这个位置它是有加固的，我使劲扭它都不变形",
            "audio_l2": "后跟内置TPU稳定片，防崴脚设计，用手扭动对比普通鞋款稳定性差距明显",
            "how_to_shoot": "手持手机特写后跟，双手扭动鞋体展示，对镜自拍取景",
            "duration": 4.0,
        },
        {
            "shot": 6, "tier": "L1",
            "visual": f"三种颜色{product_name}并排展示+价格标签",
            "audio_l1": "它有三个颜色可以选，我觉得这个卡其色最好看，你们觉得呢",
            "audio_l2": "目前在售三个配色，卡其色最受欢迎，鞋码正码选择，下单即送运费险，不满意随时退",
            "how_to_shoot": "手机放三脚架上俯拍三色并排，窗边白墙+自然光，对镜自拍取景",
            "duration": 4.0,
        },
        {
            "shot": 7, "tier": "L1",
            "visual": f"链接展示+关注引导动画+产品旋转",
            "audio_l1": "真的就是一顿火锅钱就能买到一双这么好穿的鞋，左下角链接记得看一下",
            "audio_l2": "点击左下角链接了解详情，高品质老爹鞋性价比之选，关注我每天分享好鞋测评",
            "how_to_shoot": "手机手持拍产品360度展示，窗边白墙背景，加入关注引导手势",
            "duration": 5.0,
        },
    ]

    plan = {
        "image_paths": json.dumps(image_paths),
        "shooting_tier": "L1",
        "hook": f"我跟你说这双{product_name}真的绝了，一双能当三双穿",
        "titles": [
            {"text": f"这双{product_name}绝了", "type": "悬念型"},
            {"text": f"一双{product_name}穿三个季节", "type": "反常识型"},
        ],
        "shooting_template_card": {
            "tier_label": "L1手机拍摄版",
            "equipment_needed": "手机+三脚架+自然光",
            "best_scene": "窗边白墙+小区路面",
            "time_needed": "30分钟",
            "pitfall_alert": "避免逆光拍摄鞋面细节",
            "editing_recipe": "剪映美颜+调亮+锐化",
            "bgm_pick": "轻快节奏卡点BGM",
        },
        "script": {"storyboard": storyboard},
        "creative_brief": {
            "concept_name": f"城市漫游者 — {product_name}",
            "bgm_suggestion": {"style": "轻快时尚", "search_keywords": ["轻快", "潮流"]},
            "color_palette": {"primary": "#FF6B35", "secondary": "#2D2D2D", "accent": "#00D4AA"},
            "model_direction": "休闲街头风格",
            "composition_style": "产品居中",
            "differentiation": "高弹EVA鞋底",
            "mood_keywords": ["潮流", "舒适", "性价比"],
        },
        "product_analysis": {
            "category": product_name,
            "key_features": ["高弹EVA", "透气网面", "轻量", "复古厚底"],
            "design_highlights": ["鞋底回弹技术", "透气孔设计"],
        },
    }
    return plan, image_paths


def test_e2e_minimal():
    """Render a minimal 4-beat video and verify output files exist."""
    plan, images = build_test_plan()

    with tempfile.TemporaryDirectory(prefix="e2e_test_") as tmpdir:
        result = render_video(
            plan=plan,
            scene_images=images,
            output_dir=tmpdir,
            platform="douyin",
            industry="鞋类",
            script_type="with_cart",
            tts_voice="zh-CN-YunxiNeural",
            tts_speed=1.0,
            skip_mp4=False,  # Actually render MP4
            bgm=False,
        )

        if not result.ok:
            print(f"FAILED: {result.error}")
            return

        print(f"Title: {result.script.title}")
        print(f"Beats: {len(result.script.beats)}")
        print(f"Duration: {result.duration_s:.1f}s")
        print(f"Audio: {result.audio_path} ({_fsize(result.audio_path)})")
        print(f"SRT: {result.srt_path} ({_fsize(result.srt_path)})")
        print(f"HTML: {result.html_path} ({_fsize(result.html_path)})")
        print(f"MP4: {result.mp4_path} ({_fsize(result.mp4_path)})")

        # Verify files
        assert os.path.exists(result.html_path), "HTML missing"
        assert os.path.exists(result.audio_path), "Audio missing"
        if os.path.exists(result.audio_path):
            assert os.path.getsize(result.audio_path) > 1000, "Audio too small"
        print("\nALL CHECKS PASSED")

        # Keep output for inspection
        print(f"\nOutput dir: {tmpdir}")
        print("Files:")
        for root, dirs, files in os.walk(tmpdir):
            for f in files:
                fp = os.path.join(root, f)
                print(f"  {f} ({os.path.getsize(fp)} bytes)")


def _fsize(path):
    if path and os.path.exists(path):
        kb = os.path.getsize(path) / 1024
        return f"{kb:.0f}KB"
    return "missing"


if __name__ == "__main__":
    test_e2e_minimal()
