import pytest
from data_linter.validation import load_and_validate_config
from jsonschema.exceptions import ValidationError
import json


@pytest.mark.parametrize(
    "test_input, expected",
    [
        ("example_config_fail_bucket.yaml", "pattern"),
        ("example_config_fail_table.yaml", "required"),
    ],
)
def test_load_and_validate_config_fail(test_input, expected):
    try:
        _ = load_and_validate_config(path="tests/data/inputs", file_name=test_input)
    except ValidationError as e:
        assert e.validator == expected


def test_load_and_validate_config_pass():
    with open("tests/data/expected/expected_pass.json", "r") as f:
        expected_pass = json.load(f)
    c = load_and_validate_config(
        path="tests/data/inputs", file_name="example_config_pass.yaml"
    )
    assert c == expected_pass
