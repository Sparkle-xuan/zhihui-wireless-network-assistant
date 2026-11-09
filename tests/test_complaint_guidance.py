import unittest
from complaint_guidance import SCENARIOS, guidance


class GuidanceTests(unittest.TestCase):
    def test_scenarios_and_global_greeting(self):
        for key in SCENARIOS:
            self.assertTrue(guidance(key, True)['text'].startswith('尊敬的全球通用户，'))
            self.assertTrue(guidance(key, False)['text'].startswith('您好！'))

    def test_missing_and_invalid_inputs(self):
        with self.assertRaises(ValueError): guidance('unknown')
        with self.assertRaises(ValueError): guidance('first_contact', 'yes')

    def test_long_term_does_not_promise_deadline(self):
        self.assertIn('暂不能向您承诺具体完成时间', guidance('long_term')['text'])


if __name__ == '__main__': unittest.main()
