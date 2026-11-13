"""Fixed, offline regression questions. No live model or business data required."""
import unittest
from datetime import date

import assistant_actions
import intent_router


class AssistantAcceptanceTests(unittest.TestCase):
    def test_business_intents_and_followups(self):
        cases=[
            (['2026年10月各地市挂起数量最多的前三名'],'suspension'),
            (['2026年10月合肥挂起主要问题是什么'],'suspension_reason'),
            (['2026年10月哪些地市挂起数量连续两个月增长'],'suspension_growth'),
            (['2026年10月哪个地市黑点解决率最低，和上个月比怎么样'],'ranked_comparison'),
            (['2026年10月各地市黑点解决率和上月相比'],'city_comparison'),
            (['2026年11月2日简述日报内容'],'network_overview'),
            (['2026年10月21日全省5G流量与10月20日相比怎么样'],'daily_comparison'),
            (['2026年10月21日合肥5G流量是多少'],'network_metric'),
        ]
        for questions,expected in cases:
            with self.subTest(questions=questions):
                self.assertEqual(intent_router.route([{'role':'user','content':q} for q in questions])[0],expected)

    def test_analysis_and_alerts_are_prepared_not_sent(self):
        today=date(2026,11,10)
        for question,action in [('生成2026年10月黑点解决率分析报告并发送邮件','open_analysis_report'),
                                ('帮我分析2026年10月全省黑点解决情况，生成一份报告','open_analysis_report'),
                                ('帮我分析2026年10月全省黑点解决情况，对比9月，生成一份带图表的报告','open_analysis_report'),
                                ('准备2026年10月地市告警并发送邮件','open_city_alerts')]:
            with self.subTest(question=question):
                result=assistant_actions.plan(question,today)
                self.assertEqual(result['action']['type'],action)
                self.assertEqual(result['action']['month'],'2026-10')
        self.assertIsNone(assistant_actions.plan('发送月报邮件',today))

