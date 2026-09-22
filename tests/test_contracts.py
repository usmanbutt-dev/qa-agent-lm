from pytest import CaptureFixture

from scripts.validate_contracts import main


def test_contract_validation_smoke(capsys: CaptureFixture[str]) -> None:
    assert main() == 0

    output = capsys.readouterr().out
    assert "Contract validation passed: 17 valid and 10 invalid cases" in output
