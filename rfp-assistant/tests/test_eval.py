from eval.run_eval import parse_facts, score
from rfp.prompts import NO_ANSWER


def test_parse_facts_with_alternatives():
    assert parse_facts("AES-256|TLS 1.2 OR TLS 1.3") == [["AES-256"], ["TLS 1.2", "TLS 1.3"]]


def test_score_counts_facts_case_insensitively():
    ok, found, total, missing = score("We use aes-256 and TLS 1.3.", "AES-256|TLS 1.2 OR TLS 1.3|SOC 2")
    assert (ok, found, total) == (False, 2, 3) and missing == ["SOC 2"]


def test_score_no_answer_cases():
    assert score(NO_ANSWER, "NO_ANSWER")[0]
    assert not score("Our revenue is $1B.", "NO_ANSWER")[0]


def test_retrieval_only_eval_runs_offline(tmp_path, capsys):
    from eval.run_eval import main

    assert main(["--retrieval-only", "--embedder", "hashing", "--out", str(tmp_path / "r.csv")]) == 0
    assert "contain all expected facts" in capsys.readouterr().out
