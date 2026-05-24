"""Test gatekeeper — QA scoring is in valid range."""

from services.gatekeeper import review, QAReport


def test_review_returns_qa_report():
    """review() should return a QAReport with score 0-100."""
    plan = {
        "titles": [{"text": "测试标题", "type": "身份认同型"}],
        "hook_type": "身份认同型",
        "script": {
            "storyboard": [
                {"shot": 1, "visual": "产品正面展示", "audio_l1": "好鞋推荐！", "tier": "L1", "duration": 3.5},
                {"shot": 2, "visual": "侧面细节", "audio_l1": "看看这个设计", "tier": "L2", "duration": 4.0},
                {"shot": 3, "visual": "上脚效果", "audio_l1": "穿上超舒服", "tier": "L1", "duration": 4.0},
            ]
        },
        "shooting_template_card": {"tier_label": "手机拍摄"},
    }

    report = review(plan, "鞋类")

    assert isinstance(report, QAReport)
    assert 0 <= report.score <= 100
    assert isinstance(report.pass_, bool)
    assert isinstance(report.issues, list)


def test_qa_report_defaults():
    """QAReport dataclass should have expected defaults."""
    report = QAReport(plan_index=1, pass_=True, score=85, dimensions={})

    assert report.score == 85
    assert report.pass_ is True
    assert report.issues == []
    assert report.summary == ""
