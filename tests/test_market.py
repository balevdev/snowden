"""Test market client utilities."""
from snowden.market import classify_category


class TestClassifyCategory:
    def test_politics_us(self):
        assert classify_category("Will Trump win the election?") == "politics_us"
        assert classify_category("Will Biden run?") == "politics_us"

    def test_crypto(self):
        assert classify_category("Will Bitcoin hit 100k?") == "crypto"
        assert classify_category("Ethereum price above 5000?") == "crypto"

    def test_finance(self):
        assert classify_category("Will the Fed cut rates?") == "finance"

    def test_sports(self):
        assert classify_category("Will team win the NBA championship?") == "sports"

    def test_legal(self):
        assert classify_category("Supreme Court ruling on case?") == "legal"

    def test_politics_intl(self):
        assert classify_category("Will NATO expand?") == "politics_intl"

    def test_other(self):
        assert classify_category("Will aliens visit Earth?") == "other"

    def test_combined_question_and_title(self):
        result = classify_category("Who will win?", title="2024 Presidential Election")
        assert result == "politics_us"

    def test_case_insensitivity(self):
        assert classify_category("BITCOIN price prediction") == "crypto"
        assert classify_category("SUPREME COURT ruling") == "legal"

    def test_unmatched_returns_other(self):
        assert classify_category("Will the weather be nice?") == "other"
        assert classify_category("") == "other"
