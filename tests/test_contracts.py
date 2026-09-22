from pytest import CaptureFixture

from scripts.validate_contracts import main


def test_contract_validation_smoke(capsys: CaptureFixture[str]) -> None:
    assert main() == 0

    output = capsys.readouterr().out
    assert "Contract validation passed: 22 valid and 16 invalid cases" in output
